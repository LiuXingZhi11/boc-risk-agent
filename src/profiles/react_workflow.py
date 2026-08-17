"""LangChain 驱动的单领域受控 ReAct 企业画像调查。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage
from langchain_core.tools import BaseTool

from src.config.settings import get_settings
from src.evidence.models import EvidenceUnit
from src.evidence.service import EvidenceQueryService
from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig, REQUEST_TIMEOUT_SECONDS
from src.prompts import render_prompt_section
from .extraction import (
    PROFILE_DOMAINS,
    PROFILE_DOMAIN_PURPOSES,
    extract_profile_candidates,
    filter_domain_candidates,
    build_relation_repair_messages,
)
from .react_models import (
    ReactDomainResult,
    ReactLimits,
    ReactProfileRun,
    ReactToolSession,
)
from .react_tools import create_react_tools


REACT_SUPPORTED_DOMAINS = PROFILE_DOMAINS


def build_deepseek_chat_model(config: GenerationConfig) -> BaseChatModel:
    """从现有运行配置创建官方 ChatDeepSeek 模型。"""
    from langchain_deepseek import ChatDeepSeek

    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": settings.api_key,
        "base_url": config.base_url or settings.base_url,
        "max_tokens": config.max_tokens,
        "max_retries": config.max_retries,
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }
    if config.mode == "thinking":
        kwargs["reasoning_effort"] = config.reasoning_effort
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    else:
        kwargs["temperature"] = config.temperature
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatDeepSeek(**kwargs)


def build_react_system_prompt(
    *,
    case_id: str,
    domain: str,
    query: str,
    limits: ReactLimits,
) -> str:
    """构造单领域证据调查提示词，并注入当前运行参数。"""
    if domain not in PROFILE_DOMAINS:
        raise ValueError(f"调查领域非法：{domain!r}")
    return render_prompt_section(
        "data/企业画像数据规则.md",
        "ReAct证据调查",
        {
            "case_id": case_id,
            "domain": domain,
            "domain_purpose": PROFILE_DOMAIN_PURPOSES[domain],
            "query_or_none": query or "无",
            "max_model_calls": limits.max_model_calls,
            "max_search_calls": limits.max_search_calls,
            "max_read_calls": limits.max_read_calls,
            "max_read_units": limits.max_read_units,
        },
    )


def build_recovery_system_prompt(
    *,
    case_id: str,
    domain: str,
    requests: list[dict[str, Any]],
    limits: ReactLimits,
) -> str:
    """构造候选被拒绝后的定向补查提示词。"""
    return render_prompt_section(
        "data/企业画像数据规则.md",
        "ReAct被拒候选补查",
        {
            "case_id": case_id,
            "domain": domain,
            "domain_purpose": PROFILE_DOMAIN_PURPOSES[domain],
            "recovery_requests_json": json.dumps(requests, ensure_ascii=False, indent=2),
            "max_model_calls": limits.max_model_calls,
            "max_search_calls": limits.max_search_calls,
            "max_read_calls": limits.max_read_calls,
            "max_read_units": limits.max_read_units,
        },
    )

def build_react_agent(
    *,
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    limits: ReactLimits,
) -> Any:
    """创建具有运行级模型和工具调用上限的 LangChain Agent。"""
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(
                run_limit=limits.max_model_calls,
                exit_behavior="end",
            ),
            ToolCallLimitMiddleware(
                tool_name="search_evidence",
                run_limit=limits.max_search_calls,
                exit_behavior="continue",
            ),
            ToolCallLimitMiddleware(
                tool_name="read_evidence",
                run_limit=limits.max_read_calls,
                exit_behavior="continue",
            ),
        ],
    )


class ControlledReactProfileWorkflow:
    """运行当前企业的单领域受控 ReAct 调查。"""

    def __init__(
        self,
        evidence_service: EvidenceQueryService,
        *,
        model_factory: Callable[[GenerationConfig], BaseChatModel] = build_deepseek_chat_model,
        agent_factory: Callable[..., Any] = build_react_agent,
        extractor: Callable[..., dict[str, Any]] = extract_profile_candidates,
    ) -> None:
        self.evidence_service = evidence_service
        self.model_factory = model_factory
        self.agent_factory = agent_factory
        self.extractor = extractor

    def run_current_domain(
        self,
        *,
        case_id: str,
        domain: str,
        config: GenerationConfig | None = None,
        react_config: GenerationConfig | None = None,
        extraction_config: GenerationConfig | None = None,
        query: str = "",
        limits: ReactLimits = ReactLimits(),
        guide_text: str = "",
    ) -> ReactProfileRun:
        if domain not in REACT_SUPPORTED_DOMAINS:
            raise ValueError(
                f"受控 ReAct 不支持领域：{domain}。"
            )
        if config is not None:
            react_config = react_config or config
            extraction_config = extraction_config or config
        if react_config is None or extraction_config is None:
            raise ValueError("必须提供 react_config 和 extraction_config。")
        session = ReactToolSession(
            case_id=case_id,
            domain=domain,
            evidence_service=self.evidence_service,
            limits=limits,
        )
        model = self.model_factory(react_config)
        tools = create_react_tools(session)
        system_prompt = build_react_system_prompt(
            case_id=case_id,
            domain=domain,
            query=query,
            limits=limits,
        )
        agent = self.agent_factory(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            limits=limits,
        )
        state = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"调查当前企业的{PROFILE_DOMAIN_PURPOSES[domain]}。"
                            f"补充要求：{query or '无'}"
                        ),
                    }
                ]
            }
        )
        api_meta = collect_agent_api_meta(state.get("messages", []))
        for record in api_meta:
            record["stage"] = "react_evidence_discovery"
        if not session.read_units:
            status = (
                "limit_reached"
                if state.get("run_model_call_count", 0) >= limits.max_model_calls
                else "no_evidence"
            )
            return build_react_profile_run(
                session=session,
                status=status,
                candidates=None,
                api_meta=api_meta,
            )
        extracted = self.extractor(
            tuple(session.read_units.values()),
            domain=domain,
            profile_type="current",
            config=extraction_config,
            guide_text=guide_text,
        )
        candidates = dict(extracted)
        extraction_meta = candidates.pop("api_meta", None)
        if extraction_meta:
            api_meta.append(extraction_meta)

        recovery_requests = build_recovery_requests(candidates)
        remaining_read_units = max(
            limits.max_total_read_units - len(session.read_units),
            0,
        )
        recovery_read_units = min(
            limits.max_recovery_read_units,
            remaining_read_units,
        )
        if (
            recovery_requests
            and limits.max_recovery_rounds > 0
            and recovery_read_units > 0
        ):
            initial_evidence_unit_ids = frozenset(session.read_units)
            recovery_limits = ReactLimits(
                max_model_calls=limits.max_recovery_model_calls,
                max_search_calls=limits.max_recovery_search_calls,
                max_read_calls=limits.max_recovery_read_calls,
                max_read_units=recovery_read_units,
                max_catalog_items=limits.max_catalog_items,
            )
            recovery_session = ReactToolSession(
                case_id=case_id,
                domain=domain,
                evidence_service=self.evidence_service,
                limits=recovery_limits,
                phase="react_evidence_recovery",
            )
            recovery_model = self.model_factory(react_config)
            recovery_agent = self.agent_factory(
                model=recovery_model,
                tools=create_react_tools(recovery_session),
                system_prompt=build_recovery_system_prompt(
                    case_id=case_id,
                    domain=domain,
                    requests=recovery_requests,
                    limits=recovery_limits,
                ),
                limits=recovery_limits,
            )
            recovery_state = recovery_agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "请为以下失败候选寻找补充证据："
                                f"{json.dumps(recovery_requests, ensure_ascii=False)}"
                            ),
                        }
                    ]
                }
            )
            recovery_meta = collect_agent_api_meta(
                recovery_state.get("messages", [])
            )
            for record in recovery_meta:
                record["stage"] = "react_evidence_recovery"
            api_meta.extend(recovery_meta)
            session.discovered_units.update(recovery_session.discovered_units)
            session.catalog_items.update(recovery_session.catalog_items)
            session.read_units.update(recovery_session.read_units)
            session.trace.extend(recovery_session.trace)

            if recovery_session.read_units:
                recovery_extracted = self.extractor(
                    tuple(session.read_units.values()),
                    domain=domain,
                    profile_type="current",
                    config=extraction_config,
                    guide_text=guide_text,
                    focus_instructions=build_recovery_focus(recovery_requests),
                )
                recovery_extracted = restore_recovery_relation_types(
                    recovery_extracted,
                    recovery_requests,
                )
                relation_requests = [
                    request
                    for request in recovery_requests
                    if request.get("kind") == "profile_relations"
                ]
                if relation_requests and limits.max_relation_repair_calls > 0:
                    repair_call_count = 0
                    for request in relation_requests:
                        repair_units = select_relation_repair_evidence(
                            (
                                unit
                                for unit in recovery_session.read_units.values()
                                if unit.evidence_unit_id not in initial_evidence_unit_ids
                            ),
                            request,
                        )
                        if not repair_units:
                            continue
                        repair_result = call_deepseek(
                            build_relation_repair_messages(
                                repair_units,
                                requests=[request],
                                domain=domain,
                            ),
                            extraction_config,
                        )
                        repair_meta = dict(repair_result.pop("api_meta", {}) or {})
                        repair_meta["stage"] = "profile_relation_repair"
                        decisions = repair_result.get("relation_decisions", [])
                        repaired_relations = build_repaired_relations(
                            decisions,
                            [request],
                        )
                        repair_data = {
                            "profile_items": [
                                *candidates.get("profile_items", []),
                                *recovery_extracted.get("profile_items", []),
                            ],
                            "profile_relations": repaired_relations,
                            "information_gaps": [],
                            "conflicts": [],
                            "unmapped_items": [],
                        }
                        repaired = filter_domain_candidates(
                            repair_data,
                            evidence_unit_ids=tuple(session.read_units),
                            domain=domain,
                            profile_type="current",
                            evidence_contents={
                                unit.evidence_unit_id: unit.content
                                for unit in session.read_units.values()
                            },
                        )
                        repair_meta["relation_decision"] = summarize_relation_repair_decision(
                            decisions,
                            request,
                            repaired,
                        )
                        api_meta.append(repair_meta)
                        recovery_extracted = merge_relation_repair_candidates(
                            recovery_extracted,
                            repaired,
                        )
                        repair_call_count += 1
                        if repair_call_count >= limits.max_relation_repair_calls:
                            break
                recovery_extraction_meta = recovery_extracted.pop("api_meta", None)
                if recovery_extraction_meta:
                    recovery_extraction_meta = dict(recovery_extraction_meta)
                    recovery_extraction_meta["stage"] = "profile_extraction_recovery"
                    api_meta.append(recovery_extraction_meta)
                candidates = merge_recovery_candidates(
                    candidates,
                    recovery_extracted,
                    evidence_unit_ids=tuple(session.read_units),
                    evidence_contents={
                        unit.evidence_unit_id: unit.content
                        for unit in session.read_units.values()
                    },
                    domain=domain,
                )
        status = "pending_review" if has_reviewable_candidates(candidates) else "no_valid_candidates"
        return build_react_profile_run(
            session=session,
            status=status,
            candidates=candidates,
            api_meta=api_meta,
        )


_RECOVERY_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "technology.source": ("自研", "研发", "开发"),
    "team.key_person": ("核心技术人员", "关键人员", "姓名"),
    "team.education_structure": ("学历", "教育背景"),
    "team.professional_background": ("职业经历", "任职经历"),
    "enterprise.main_business": ("主营业务", "主要产品", "产品矩阵"),
    "product.name": ("产品型号", "产品"),
    "product.commercialization_stage": ("商业化", "销售", "量产", "交付"),
}

_RECOVERY_RELATION_TERMS: dict[str, tuple[str, ...]] = {
    "develops": ("自研", "研发", "开发"),
    "sells_to": ("销售", "客户", "收入"),
    "purchases_from": ("采购", "供应商", "采购内容"),
    "controls": ("实际控制人", "控股股东", "控制关系"),
}

_RELATION_ENDPOINT_TYPES_BY_FIELD = {
    "enterprise.legal_name": "Enterprise",
    "team.key_person": "Person",
    "technology.name": "Technology",
    "intellectual_property.name": "IntellectualProperty",
    "product.name": "ProductService",
    "risk.matter": "LegalRiskMatter",
}


def build_recovery_requests(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    """把候选拒绝记录转换为可执行的补充检索要求。"""
    item_values = {
        item.get("item_id"): item.get("value")
        for item in candidates.get("profile_items", [])
        if isinstance(item, dict) and item.get("item_id")
    }
    item_types = {
        item.get("item_id"): _RELATION_ENDPOINT_TYPES_BY_FIELD[item.get("field_id")]
        for item in candidates.get("profile_items", [])
        if isinstance(item, dict)
        and item.get("item_id")
        and item.get("field_id") in _RELATION_ENDPOINT_TYPES_BY_FIELD
    }
    requests: list[dict[str, Any]] = []
    for rejection in candidates.get("rejected_candidates", []):
        if rejection.get("kind") not in {"profile_items", "profile_relations"}:
            continue
        candidate = rejection.get("candidate") or rejection.get("value")
        if not isinstance(candidate, dict):
            continue
        kind = rejection["kind"]
        if kind == "profile_items":
            field_or_relation = candidate.get("field_id", "")
            subject = str(candidate.get("subject") or "")
            object_name = str(candidate.get("value") or "")
            terms = list(_RECOVERY_FIELD_TERMS.get(field_or_relation, ()))
        else:
            field_or_relation = candidate.get("relation_type", "")
            subject = _relation_endpoint_name(candidate.get("source_id"), item_values)
            object_name = _relation_endpoint_name(candidate.get("target_id"), item_values)
            terms = list(_RECOVERY_RELATION_TERMS.get(field_or_relation, ()))
        search_terms = _unique_recovery_terms(
            [subject, object_name, *terms]
        )
        requests.append(
            {
                "kind": kind,
                "field_or_relation": field_or_relation,
                "subject": subject,
                "object": object_name,
                "reason": rejection.get("reason", "证据不足"),
                "search_terms": search_terms,
                "candidate_id": candidate.get("item_id") or candidate.get("relation_id"),
                **(
                    {
                        "source_id": candidate.get("source_id"),
                        "target_id": candidate.get("target_id"),
                        "source_type": candidate.get("source_type")
                        or _relation_endpoint_type(candidate.get("source_id"), item_types),
                        "target_type": candidate.get("target_type")
                        or _relation_endpoint_type(candidate.get("target_id"), item_types),
                        "information_status": candidate.get("information_status"),
                        "content_role": candidate.get("content_role"),
                    }
                    if kind == "profile_relations"
                    else {}
                ),
            }
        )
    return requests


def build_recovery_focus(requests: list[dict[str, Any]]) -> str:
    return (
        "本轮只处理以下失败候选，并使用补充证据逐条重新判断。关系候选必须沿用请求中的"
        " candidate_id、source_id 和 target_id；证据明确支持时按原 ID 回填，不能重新命名"
        "主体或对象。必须判断关系谓词对主体和对象的实际作用范围，并逐字提供直接支持该关系的"
        "连续 evidence_quote，不得使用省略号或自行概括。若补充证据仍不直接支持，"
        "不要强行生成候选：\n"
        + json.dumps(requests, ensure_ascii=False, indent=2)
    )


def restore_recovery_relation_types(
    candidates: dict[str, Any],
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """用原请求中的端点类型修复补充轮的结构性缺字段。"""
    request_by_id = {
        request.get("candidate_id"): request
        for request in requests
        if request.get("candidate_id")
    }
    normalized = dict(candidates)
    relations = list(candidates.get("profile_relations", []))
    unresolved: list[dict[str, Any]] = []
    for rejection in candidates.get("rejected_candidates", []):
        if rejection.get("kind") != "profile_relations":
            unresolved.append(rejection)
            continue
        candidate = rejection.get("candidate")
        request = request_by_id.get(rejection.get("candidate_id"))
        if not isinstance(candidate, dict) or request is None:
            unresolved.append(rejection)
            continue
        restored = dict(candidate)
        missing_type = False
        for key in ("source_type", "target_type"):
            if not restored.get(key) and request.get(key):
                restored[key] = request[key]
                missing_type = True
        if missing_type and restored.get("source_type") and restored.get("target_type"):
            relations.append(restored)
        else:
            unresolved.append(rejection)
    normalized["profile_relations"] = relations
    normalized["rejected_candidates"] = unresolved
    return normalized


def build_repaired_relations(
    decisions: Any,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把窄调用的关系支持判定转换为原候选关系。"""
    request_by_id = {
        request.get("candidate_id"): request
        for request in requests
        if request.get("candidate_id")
    }
    if not isinstance(decisions, list):
        return []
    relations: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("supported") is not True:
            continue
        request = request_by_id.get(decision.get("candidate_id"))
        if request is None:
            continue
        relations.append(
            {
                "relation_id": request["candidate_id"],
                "relation_type": request["field_or_relation"],
                "source_id": request.get("source_id"),
                "source_type": request.get("source_type"),
                "target_id": request.get("target_id"),
                "target_type": request.get("target_type"),
                "information_status": request.get("information_status") or "claimed",
                "content_role": request.get("content_role") or "enterprise_claim",
                "evidence_unit_ids": decision.get("evidence_unit_ids", []),
                "evidence_quotes": normalize_relation_decision_quotes(decision),
                "_relation_scope_verified": True,
            }
        )
    return relations


def normalize_relation_decision_quotes(decision: dict[str, Any]) -> Any:
    """把单证据判定的字符串摘录包装为标准证据对象。"""
    evidence_unit_ids = decision.get("evidence_unit_ids", [])
    evidence_quotes = decision.get("evidence_quotes", [])
    if (
        isinstance(evidence_unit_ids, list)
        and len(evidence_unit_ids) == 1
        and isinstance(evidence_quotes, list)
        and all(isinstance(quote, str) for quote in evidence_quotes)
    ):
        return [
            {
                "evidence_unit_id": evidence_unit_ids[0],
                "excerpt": quote,
            }
            for quote in evidence_quotes
        ]
    return evidence_quotes


def select_relation_repair_evidence(
    evidence_units: Iterable[EvidenceUnit],
    request: dict[str, Any],
) -> tuple[EvidenceUnit, ...]:
    """选择补查正文中直接出现关系目标名称的证据。"""
    target_name = "".join(str(request.get("object") or "").casefold().split())
    return tuple(
        unit
        for unit in evidence_units
        if target_name
        and target_name in "".join(unit.content.casefold().split())
    )


def summarize_relation_repair_decision(
    decisions: Any,
    request: dict[str, Any],
    repaired: dict[str, Any],
) -> dict[str, Any]:
    """记录模型支持判定及 Python 过滤结果。"""
    candidate_id = request.get("candidate_id")
    decision = next(
        (
            item
            for item in decisions
            if isinstance(item, dict) and item.get("candidate_id") == candidate_id
        ),
        None,
    ) if isinstance(decisions, list) else None
    accepted = any(
        relation.get("relation_id") == candidate_id
        for relation in repaired.get("profile_relations", [])
    )
    rejection_reason = next(
        (
            item.get("reason", "")
            for item in repaired.get("rejected_candidates", [])
            if item.get("candidate_id") == candidate_id
        ),
        "",
    )
    supported = decision.get("supported") if decision else None
    if accepted:
        result = "accepted"
    elif supported is True:
        result = "filter_rejected"
    else:
        result = "model_unsupported"
    return {
        "candidate_id": candidate_id,
        "supported": supported,
        "evidence_unit_ids": decision.get("evidence_unit_ids", []) if decision else [],
        "result": result,
        "filter_reason": rejection_reason,
    }


def merge_relation_repair_candidates(
    recovery: dict[str, Any],
    repaired: dict[str, Any],
) -> dict[str, Any]:
    """合并窄范围关系修复结果，并移除已修复关系的旧拒绝记录。"""
    repaired_relations = list(repaired.get("profile_relations", []))
    normalized = dict(recovery)
    normalized["profile_relations"] = [
        *recovery.get("profile_relations", []),
        *repaired_relations,
    ]
    unresolved = []
    for rejection in recovery.get("rejected_candidates", []):
        if any(
            _rejection_matches_relation(rejection, relation)
            for relation in repaired_relations
        ):
            continue
        unresolved.append(rejection)
    known = {
        (item.get("kind"), item.get("candidate_id"))
        for item in unresolved
    }
    for rejection in repaired.get("rejected_candidates", []):
        key = (rejection.get("kind"), rejection.get("candidate_id"))
        if key not in known:
            unresolved.append(rejection)
            known.add(key)
    normalized["rejected_candidates"] = unresolved
    return normalized


def _rejection_matches_relation(
    rejection: dict[str, Any],
    relation: dict[str, Any],
) -> bool:
    candidate = rejection.get("candidate")
    if not isinstance(candidate, dict):
        return False
    return (
        rejection.get("candidate_id") == relation.get("relation_id")
        or (
            candidate.get("relation_type") == relation.get("relation_type")
            and _strip_recovery_prefix(candidate.get("source_id"))
            == _strip_recovery_prefix(relation.get("source_id"))
            and _strip_recovery_prefix(candidate.get("target_id"))
            == _strip_recovery_prefix(relation.get("target_id"))
        )
    )


def merge_recovery_candidates(
    first: dict[str, Any],
    recovery: dict[str, Any],
    *,
    evidence_unit_ids: Iterable[str],
    evidence_contents: dict[str, str],
    domain: str,
) -> dict[str, Any]:
    """合并首轮候选和补查候选，并以完整证据重新过滤。"""
    recovery_prefixed = _prefix_recovery_candidate_ids(recovery)
    recovered_items = list(recovery_prefixed.get("profile_items", []))
    recovered_relations = list(recovery_prefixed.get("profile_relations", []))
    first_failed_items = [
        candidate
        for candidate in _rejected_candidate_values(first, "profile_items")
        if not _has_recovery_match(candidate, recovered_items, kind="profile_items")
    ]
    first_failed_relations = [
        candidate
        for candidate in _rejected_candidate_values(first, "profile_relations")
        if not _has_recovery_match(candidate, recovered_relations, kind="profile_relations")
    ]
    combined: dict[str, Any] = {
        "profile_items": list(first.get("profile_items", []))
        + first_failed_items
        + recovered_items,
        "profile_relations": list(first.get("profile_relations", []))
        + first_failed_relations
        + recovered_relations,
        "information_gaps": _domain_prefixed_gaps(
            domain,
            [*first.get("information_gaps", []), *recovery.get("information_gaps", [])],
        ),
        "conflicts": list(first.get("conflicts", []))
        + list(recovery.get("conflicts", [])),
        "unmapped_items": list(first.get("unmapped_items", []))
        + list(recovery.get("unmapped_items", [])),
    }
    filtered = filter_domain_candidates(
        combined,
        evidence_unit_ids=evidence_unit_ids,
        domain=domain,
        profile_type="current",
        evidence_contents=evidence_contents,
    )
    accepted_relations = list(filtered.get("profile_relations", []))
    filtered["rejected_candidates"] = [
        rejection
        for rejection in filtered.get("rejected_candidates", [])
        if rejection.get("kind") != "profile_relations"
        or not any(
            _rejection_matches_relation(rejection, relation)
            for relation in accepted_relations
        )
    ]
    for relation in filtered.get("profile_relations", []):
        relation.pop("_relation_scope_verified", None)
    known_rejections = {
        (item.get("kind"), item.get("candidate_id"))
        for item in filtered.get("rejected_candidates", [])
    }
    for rejection in recovery.get("rejected_candidates", []):
        if any(
            _rejection_matches_relation(rejection, relation)
            for relation in filtered.get("profile_relations", [])
        ):
            continue
        key = (rejection.get("kind"), rejection.get("candidate_id"))
        if key not in known_rejections:
            filtered.setdefault("rejected_candidates", []).append(rejection)
            known_rejections.add(key)
    return filtered


def _rejected_candidate_values(
    candidates: dict[str, Any],
    kind: str,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for rejection in candidates.get("rejected_candidates", []):
        if rejection.get("kind") != kind:
            continue
        candidate = rejection.get("candidate") or rejection.get("value")
        if isinstance(candidate, dict):
            values.append(candidate)
    return values


def _has_recovery_match(
    candidate: dict[str, Any],
    recovered: list[dict[str, Any]],
    *,
    kind: str,
) -> bool:
    if kind == "profile_items":
        return any(
            candidate.get("field_id") == item.get("field_id")
            and candidate.get("subject") == item.get("subject")
            and candidate.get("value") == item.get("value")
            for item in recovered
        )
    return any(
        candidate.get("relation_type") == relation.get("relation_type")
        and _strip_recovery_prefix(candidate.get("source_id"))
        == _strip_recovery_prefix(relation.get("source_id"))
        and _strip_recovery_prefix(candidate.get("target_id"))
        == _strip_recovery_prefix(relation.get("target_id"))
        for relation in recovered
    )


def _strip_recovery_prefix(value: Any) -> Any:
    return value[len("recovery:"):] if isinstance(value, str) and value.startswith("recovery:") else value


def _prefix_recovery_candidate_ids(data: dict[str, Any]) -> dict[str, Any]:
    prefix = "recovery:"
    normalized = dict(data)
    item_ids = {
        item.get("item_id")
        for item in data.get("profile_items", [])
        if isinstance(item, dict) and item.get("item_id")
    }
    mapping = {item_id: f"{prefix}{item_id}" for item_id in item_ids}
    items: list[dict[str, Any]] = []
    for item in data.get("profile_items", []):
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        copy["item_id"] = mapping.get(item.get("item_id"), item.get("item_id"))
        items.append(copy)
    relations: list[dict[str, Any]] = []
    for relation in data.get("profile_relations", []):
        if not isinstance(relation, dict):
            continue
        copy = dict(relation)
        copy["relation_id"] = f"{prefix}{relation.get('relation_id')}"
        copy["source_id"] = mapping.get(relation.get("source_id"), relation.get("source_id"))
        copy["target_id"] = mapping.get(relation.get("target_id"), relation.get("target_id"))
        relations.append(copy)
    normalized["profile_items"] = items
    normalized["profile_relations"] = relations
    return normalized


def _relation_endpoint_name(identifier: Any, item_values: dict[Any, Any]) -> str:
    if identifier == "the_enterprise":
        return "企业"
    return str(item_values.get(identifier) or identifier or "")


def _relation_endpoint_type(identifier: Any, item_types: dict[Any, str]) -> str | None:
    if identifier == "the_enterprise":
        return "Enterprise"
    return item_types.get(identifier)


def _unique_recovery_terms(values: Iterable[str]) -> list[str]:
    terms: list[str] = []
    for value in values:
        for term in re.split(r"[\s,，、;；/]+", str(value)):
            term = term.strip()
            if not term or term in {"the_enterprise", "企业"} or term in terms:
                continue
            terms.append(term)
    return terms[:8]


def _domain_prefixed_gaps(domain: str, gaps: Iterable[Any]) -> list[str]:
    prefix = f"{domain}:"
    return [
        gap if isinstance(gap, str) and gap.startswith(prefix) else f"{prefix} {gap}"
        for gap in gaps
        if isinstance(gap, str) and gap.strip()
    ]


def has_reviewable_candidates(candidates: dict[str, Any]) -> bool:
    """判断过滤结果中是否存在需要人工审核的内容。"""
    return any(
        candidates.get(key)
        for key in ("profile_items", "profile_relations", "information_gaps", "conflicts")
    )


def collect_agent_api_meta(messages: Iterable[AnyMessage]) -> list[dict[str, Any]]:
    """从模型消息中提取紧凑的模型名称、结束原因和 token 用量。"""
    records: list[dict[str, Any]] = []
    for message in messages:
        usage = getattr(message, "usage_metadata", None) or {}
        response = getattr(message, "response_metadata", None) or {}
        if not usage and not response:
            continue
        records.append(
            {
                "model": response.get("model_name") or response.get("model"),
                "finish_reason": response.get("finish_reason"),
                "tool_calls": [
                    call.get("name")
                    for call in (getattr(message, "tool_calls", None) or [])
                    if call.get("name")
                ],
                "invalid_tool_calls": [
                    {
                        "name": call.get("name"),
                        "error": call.get("error"),
                    }
                    for call in (getattr(message, "invalid_tool_calls", None) or [])
                ],
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
        )
    return records


def build_react_profile_run(
    *,
    session: ReactToolSession,
    status: str,
    candidates: dict[str, Any] | None,
    api_meta: list[dict[str, Any]],
) -> ReactProfileRun:
    """把单次 Agent 会话整理成现有审核入口可聚合的运行结果。"""
    domain_result = ReactDomainResult(
        domain=session.domain,
        status=status,
        evidence_units=tuple(session.read_units.values()),
        candidates=candidates,
        evidence_catalog=tuple(session.catalog_items.values()),
        selected_evidence_unit_ids=tuple(session.read_units),
        react_trace=tuple(session.trace),
        api_meta=tuple(api_meta),
    )
    return ReactProfileRun(case_id=session.case_id, domains=(domain_result,))
