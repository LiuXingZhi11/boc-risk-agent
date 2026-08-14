"""企业画像候选的校验和画像构建。"""

from __future__ import annotations

import re
from itertools import product
from typing import Any, Iterable

from src.evidence.models import EvidenceUnit
from src.ontology.registry import REGISTRY
from src.ontology.schema import INFORMATION_STATUSES, ONTOLOGY_VERSION, validate_relation

from .models import (
    CurrentEnterpriseProfile,
    EnterpriseProfile,
    EvidenceReference,
    HistoricalEnterpriseProfile,
    ProfileItem,
    ProfileRelation,
)


_GAP_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "enterprise.legal_name": ("企业名称", "法定名称"),
    "enterprise.founded_date": ("成立时间", "成立日期"),
    "enterprise.business_stage": ("发展阶段", "业务阶段"),
    "enterprise.main_business": ("主营业务", "主要业务"),
    "ownership.controller": ("实际控制人", "控制权"),
    "team.key_person": ("关键人员", "核心人员", "核心技术人员"),
    "team.education_background": ("学历", "教育背景", "毕业院校", "专业"),
    "team.professional_experience": ("职业经历", "从业经历", "工作经历", "任职经历"),
    "team.education_structure": ("学历结构", "教育结构", "专业构成", "教育背景"),
    "team.professional_background": ("职业背景", "从业背景", "任职经历", "实控人经历"),
    "governance.equity_incentive_plan_status": ("股权激励", "激励计划"),
    "technology.source": ("技术来源",),
    "technology.maturity_stage": ("成熟度", "成熟阶段", "产业化阶段"),
    "technology.ownership_status": ("技术权属", "知识产权权属", "所有权", "权利证明"),
    "intellectual_property.name": ("核心知识产权", "核心专利", "软件著作权"),
    "intellectual_property.patent_application_count": ("专利申请数量", "专利申请总量"),
    "intellectual_property.patent_grant_count": ("授权专利数量", "专利授权总量"),
    "intellectual_property.ownership_status": ("知识产权权属", "专利权属"),
    "intellectual_property.rights_restriction_status": ("知识产权权利限制", "专利权利限制"),
    "product.commercialization_stage": ("商业化阶段", "产品阶段"),
    "finance.operating_revenue": ("营业收入",),
    "finance.operating_cash_flow": ("经营活动现金流", "经营现金流"),
    "finance.net_profit": ("净利润",),
    "finance.net_profit_attributable_to_parent": ("归属于母公司所有者的净利润", "归母净利润"),
    "finance.adjusted_net_profit_attributable_to_parent": ("扣非归母净利润", "扣除非经常性损益"),
    "finance.research_expense": ("研发费用", "研发投入"),
    "finance.research_expense_ratio": ("研发费用率", "研发投入占比"),
    "customer_supplier.customer_concentration": ("客户集中度", "前五名客户"),
    "customer_supplier.supplier_concentration": ("供应商集中度", "前五名供应商"),
    "customer_supplier.counterparty_name": ("主要客户", "主要供应商", "交易对手"),
    "customer_supplier.transaction_amount": ("销售金额", "采购金额", "交易金额"),
    "customer_supplier.transaction_ratio": ("销售占比", "采购占比", "交易占比"),
    "customer_supplier.transaction_content": ("销售内容", "采购内容", "交易内容"),
    "customer_supplier.related_party_status": ("客户关联关系", "供应商关联关系"),
    "finance.customer_concentration": ("客户集中度",),
    "finance.cash_balance": ("现金余额", "货币资金"),
    "finance.interest_bearing_debt": ("有息负债", "有息债务"),
}

_LEGAL_NAME_GAP_TERMS = ("企业法定名称", "法定企业名称", "法定名称")


def is_cross_domain_legal_name_gap(value: str, *, domain: str | None = None) -> bool:
    """判断法定名称缺口是否被错误放入其他调查领域。"""
    if domain is None:
        domain = value.partition(":")[0] if ":" in value else None
    return domain != "enterprise_and_control" and any(
        term in value for term in _LEGAL_NAME_GAP_TERMS
    )


def validate_profile_candidates(
    data: dict[str, Any],
    *,
    evidence_unit_ids: Iterable[str],
    profile_type: str,
) -> dict[str, Any]:
    if profile_type not in {"historical", "current"}:
        raise ValueError("profile_type 必须是 historical 或 current。")
    if not isinstance(data, dict):
        raise ValueError("画像候选顶层必须是对象。")
    allowed_ids = set(evidence_unit_ids)
    for key in ("profile_items", "profile_relations", "information_gaps", "conflicts", "unmapped_items"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"{key} 必须是数组。")
    for item in data.get("profile_items", []):
        _validate_item(item, allowed_ids)
    for relation in data.get("profile_relations", []):
        _validate_relation(relation, allowed_ids)
    return data


def filter_profile_candidates(
    data: dict[str, Any],
    *,
    evidence_unit_ids: Iterable[str],
    profile_type: str,
    allowed_field_ids: Iterable[str] | None = None,
    allowed_relation_types: Iterable[str] | None = None,
    information_gap_prefix: str | None = None,
    require_subject: bool = False,
    evidence_contents: dict[str, str] | None = None,
    require_evidence_quote: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """逐条保留合法候选，忽略非法条目并返回校验记录。

    顶层 JSON 仍必须是对象；单个画像项或关系不合格时不影响其他合法内容。
    """
    if not isinstance(data, dict):
        raise ValueError("画像候选顶层必须是对象。")
    if profile_type not in {"historical", "current"}:
        raise ValueError("profile_type 必须是 historical 或 current。")
    allowed_ids = set(evidence_unit_ids)
    domain_fields = set(allowed_field_ids) if allowed_field_ids is not None else None
    domain_relations = (
        set(allowed_relation_types) if allowed_relation_types is not None else None
    )
    domain_name = information_gap_prefix.rstrip(":") if information_gap_prefix else None
    raw_gaps = _string_values(data.get("information_gaps", []))
    accepted: dict[str, Any] = {
        "profile_items": [],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": _string_values(data.get("conflicts", [])),
        "unmapped_items": data.get("unmapped_items", []),
        "consistency_warnings": [],
        "deduplicated_candidates": [],
        "deduplicated_relations": [],
    }
    rejected: list[dict[str, Any]] = []
    candidate_item_ids = {
        item["item_id"]
        for item in data.get("profile_items", [])
        if isinstance(item, dict)
        and isinstance(item.get("item_id"), str)
        and item["item_id"].strip()
    }
    candidate_item_names = {
        item["item_id"]: str(item.get("value") or item.get("subject") or "")
        for item in data.get("profile_items", [])
        if isinstance(item, dict)
        and isinstance(item.get("item_id"), str)
        and item["item_id"].strip()
    }
    for index, gap in enumerate(raw_gaps):
        if information_gap_prefix is not None and not gap.startswith(information_gap_prefix):
            rejected.append(
                {
                    "kind": "information_gaps",
                    "index": index,
                    "candidate_id": None,
                    "provided_evidence_unit_ids": [],
                    "reason": f"信息缺口必须以 {information_gap_prefix!r} 开头。",
                }
            )
            continue
        normalized_gap = (
            gap[len(information_gap_prefix):].strip()
            if information_gap_prefix is not None
            else gap
        )
        domain = information_gap_prefix.rstrip(":") if information_gap_prefix else None
        if is_cross_domain_legal_name_gap(normalized_gap, domain=domain):
            rejected.append(
                {
                    "kind": "information_gaps",
                    "index": index,
                    "candidate_id": None,
                    "provided_evidence_unit_ids": [],
                    "reason": "企业法定名称属于 enterprise_and_control，不应作为当前领域信息缺口。",
                }
            )
            continue
        accepted["information_gaps"].append(
            normalized_gap
        )
    for field_name, validator in (
        ("profile_items", _validate_item),
        ("profile_relations", _validate_relation),
    ):
        values = data.get(field_name, [])
        if not isinstance(values, list):
            rejected.append({"kind": field_name, "index": None, "reason": f"{field_name} 必须是数组。"})
            continue
        for index, item in enumerate(values):
            candidate = _normalize_candidate_evidence_ids(item, allowed_ids)
            if field_name == "profile_items":
                candidate = _ground_customer_supplier_evidence_quotes(
                    candidate,
                    evidence_contents=evidence_contents,
                )
                candidate = _ground_team_key_person_evidence_quotes(
                    candidate,
                    evidence_contents=evidence_contents,
                )
                candidate = _ground_enterprise_main_business_evidence_quotes(
                    candidate,
                    evidence_contents=evidence_contents,
                )
            try:
                validator(candidate, allowed_ids)
                _validate_candidate_quote(
                    candidate,
                    evidence_contents=evidence_contents,
                    required=require_evidence_quote,
                )
                if (
                    field_name == "profile_items"
                    and domain_fields is not None
                    and candidate["field_id"] not in domain_fields
                ):
                    raise ValueError(f"字段 {candidate['field_id']} 不属于当前调查领域。")
                if domain_name == "authoritative_findings":
                    _validate_authoritative_content_role(candidate)
                if (
                    field_name == "profile_items"
                    and require_subject
                    and not candidate.get("subject")
                ):
                    raise ValueError("画像项必须包含明确的 subject。")
                if (
                    require_evidence_quote
                    or candidate.get("evidence_quotes")
                    or candidate.get("evidence_quote")
                ):
                    semantic_text = _candidate_evidence_context(
                        candidate,
                        evidence_contents=evidence_contents,
                        context_chars=(
                            1000
                            if field_name == "profile_relations"
                            else 500
                            if candidate.get("field_id", "").startswith("customer_supplier.")
                            else 100
                        ),
                    )
                    if field_name == "profile_items":
                        _validate_profile_item_semantics(candidate, semantic_text)
                    else:
                        _validate_relation_semantics(
                            candidate,
                            semantic_text,
                            target_name=candidate_item_names.get(candidate.get("target_id"), ""),
                        )
                if (
                    field_name == "profile_relations"
                    and domain_relations is not None
                    and candidate["relation_type"] not in domain_relations
                ):
                    raise ValueError(
                        f"关系 {candidate['relation_type']} 不属于当前调查领域。"
                    )
            except (TypeError, ValueError, KeyError) as exc:
                rejected.append(
                    {
                        "kind": field_name,
                        "index": index,
                        "candidate_id": item.get("item_id" if field_name == "profile_items" else "relation_id")
                        if isinstance(item, dict)
                        else None,
                        "provided_evidence_unit_ids": item.get("evidence_unit_ids", [])
                        if isinstance(item, dict)
                        else [],
                        "candidate": _candidate_rejection_summary(candidate),
                        "reason": str(exc),
                    }
                )
                continue
            accepted[field_name].append(candidate)
    accepted["profile_items"], accepted["deduplicated_candidates"] = (
        _deduplicate_profile_items(accepted["profile_items"])
    )
    accepted["profile_relations"], dangling_relations = (
        _resolve_relation_item_references(
            accepted["profile_relations"],
            candidate_item_ids=candidate_item_ids,
            accepted_item_ids={
                item["item_id"] for item in accepted["profile_items"]
            },
            deduplicated_candidates=accepted["deduplicated_candidates"],
        )
    )
    rejected.extend(dangling_relations)
    accepted["profile_relations"], accepted["deduplicated_relations"] = (
        _deduplicate_profile_relations(accepted["profile_relations"])
    )
    _append_derived_research_expense_ratios(accepted["profile_items"])
    _append_anonymous_counterparty_gap(
        accepted["profile_items"],
        accepted["information_gaps"],
    )
    _remove_contradicted_counterparty_gaps(
        accepted["profile_items"],
        accepted["profile_relations"],
        accepted["information_gaps"],
    )
    accepted["consistency_warnings"] = _find_consistency_warnings(
        accepted["profile_items"], accepted["information_gaps"]
    )
    return accepted, rejected


def _append_derived_research_expense_ratios(items: list[dict[str, Any]]) -> None:
    """用同期间、同币种的已核验收入和研发费用计算研发费用率。"""
    revenues = [
        item for item in items if item["field_id"] == "finance.operating_revenue"
    ]
    expenses = [
        item for item in items if item["field_id"] == "finance.research_expense"
    ]
    existing_periods = {
        _reporting_period_key(item.get("reporting_period"))
        for item in items
        if item["field_id"] == "finance.research_expense_ratio"
    }
    item_ids = {str(item["item_id"]) for item in items}
    for expense in expenses:
        period_key = _reporting_period_key(expense.get("reporting_period"))
        if not period_key or period_key in existing_periods:
            continue
        revenue = next(
            (
                candidate
                for candidate in revenues
                if _reporting_period_key(candidate.get("reporting_period")) == period_key
                and candidate.get("unit") == expense.get("unit")
                and candidate.get("subject") == expense.get("subject")
                and candidate["value"] != 0
            ),
            None,
        )
        if revenue is None:
            continue
        item_id = _next_rule_item_id(item_ids, "rule_research_expense_ratio")
        items.append(
            {
                "item_id": item_id,
                "subject": expense["subject"],
                "section_id": "finance_capital",
                "field_id": "finance.research_expense_ratio",
                "value": round(float(expense["value"]) / float(revenue["value"]), 6),
                "value_type": "ratio",
                "information_status": (
                    expense["information_status"]
                    if expense["information_status"] == revenue["information_status"]
                    else "supported"
                ),
                "content_role": "internal_assessment",
                "evidence_unit_ids": list(
                    dict.fromkeys(
                        [*expense["evidence_unit_ids"], *revenue["evidence_unit_ids"]]
                    )
                ),
                "evidence_quotes": _merge_evidence_quotes(expense, revenue),
                "reporting_period": expense["reporting_period"],
                "extraction_method": "rule",
            }
        )
        existing_periods.add(period_key)


def _reporting_period_key(value: Any) -> str:
    text = str(value or "").strip()
    year = re.search(r"(?:19|20)\d{2}", text)
    return year.group() if year else _normalize_quote(text)


def _next_rule_item_id(item_ids: set[str], prefix: str) -> str:
    index = 1
    while f"{prefix}_{index}" in item_ids:
        index += 1
    item_id = f"{prefix}_{index}"
    item_ids.add(item_id)
    return item_id


def _deduplicate_profile_items(
    profile_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """合并主体、字段、值和限定条件完全相同的画像项，并汇总证据。"""
    unique_items: list[dict[str, Any]] = []
    key_to_index: dict[tuple[Any, ...], int] = {}
    records: list[dict[str, str]] = []

    for item in profile_items:
        subject = item.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            unique_items.append(item)
            continue
        key = (
            _dedup_subject_key(item),
            item["field_id"],
            _normalize_fingerprint_value(item["value"]),
            item["value_type"],
            item["information_status"],
            item["content_role"],
            *(
                _normalize_fingerprint_value(item.get(name))
                for name in (
                    "unit",
                    "source_date",
                    "reporting_period",
                    "event_date",
                    "effective_date",
                    "value_scope",
                )
            ),
        )
        existing_index = key_to_index.get(key)
        if existing_index is None:
            key_to_index[key] = len(unique_items)
            unique_items.append(item)
            continue

        kept = unique_items[existing_index]
        kept["evidence_unit_ids"] = list(
            dict.fromkeys([*kept["evidence_unit_ids"], *item["evidence_unit_ids"]])
        )
        kept["evidence_quotes"] = _merge_evidence_quotes(kept, item)
        records.append(
            {
                "kept_item_id": str(kept["item_id"]),
                "removed_item_id": str(item["item_id"]),
                "subject": subject.strip(),
                "field_id": str(item["field_id"]),
                "reason": "主体、字段、值和限定条件相同，已合并证据。",
            }
        )
    return unique_items, records


def _normalize_fingerprint_value(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, dict):
        return tuple(
            (str(key), _normalize_fingerprint_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, list):
        return tuple(_normalize_fingerprint_value(item) for item in value)
    return value


def _dedup_subject_key(item: dict[str, Any]) -> Any:
    """把企业主体和同名实体主体视为同一事实主体。"""
    subject = _normalize_fingerprint_value(item.get("subject"))
    field_id = item.get("field_id")
    value = _normalize_fingerprint_value(item.get("value"))
    if field_id in {
        "technology.name",
        "product.name",
        "intellectual_property.name",
    } and subject in {
        "the_enterprise",
        value,
    }:
        return value
    return subject


def _resolve_relation_item_references(
    relations: list[dict[str, Any]],
    *,
    candidate_item_ids: set[str],
    accepted_item_ids: set[str],
    deduplicated_candidates: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """重定向合并项，并拒绝指向已淘汰候选项的悬空关系。"""
    aliases = {
        record["removed_item_id"]: record["kept_item_id"]
        for record in deduplicated_candidates
    }
    resolved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, relation in enumerate(relations):
        normalized = dict(relation)
        for key in ("source_id", "target_id"):
            reference = normalized[key]
            if reference in aliases:
                normalized[key] = aliases[reference]
        dangling = [
            normalized[key]
            for key in ("source_id", "target_id")
            if normalized[key] in candidate_item_ids
            and normalized[key] not in accepted_item_ids
        ]
        if dangling:
            rejected.append(
                {
                    "kind": "profile_relations",
                    "index": index,
                    "candidate_id": relation["relation_id"],
                    "provided_evidence_unit_ids": relation["evidence_unit_ids"],
                    "reason": (
                        "关系引用的画像项未通过校验："
                        + "、".join(dict.fromkeys(dangling))
                    ),
                }
            )
            continue
        resolved.append(normalized)
    return resolved, rejected


def _deduplicate_profile_relations(
    relations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    unique: list[dict[str, Any]] = []
    key_to_index: dict[tuple[str, ...], int] = {}
    records: list[dict[str, str]] = []
    for relation in relations:
        key = (
            relation["relation_type"],
            relation["source_id"],
            relation["source_type"],
            relation["target_id"],
            relation["target_type"],
            relation["information_status"],
            relation["content_role"],
        )
        existing_index = key_to_index.get(key)
        if existing_index is None:
            key_to_index[key] = len(unique)
            unique.append(relation)
            continue
        kept = unique[existing_index]
        kept["evidence_unit_ids"] = list(
            dict.fromkeys(
                [*kept["evidence_unit_ids"], *relation["evidence_unit_ids"]]
            )
        )
        kept["evidence_quotes"] = _merge_evidence_quotes(kept, relation)
        records.append(
            {
                "kept_relation_id": str(kept["relation_id"]),
                "removed_relation_id": str(relation["relation_id"]),
                "reason": "关系类型、起点、终点和状态相同，已合并证据。",
            }
        )
    return unique, records


def _append_anonymous_counterparty_gap(
    items: list[dict[str, Any]],
    information_gaps: list[str],
) -> None:
    anonymous_names = [
        str(item["value"])
        for item in items
        if item["field_id"] == "customer_supplier.counterparty_name"
        and _looks_like_anonymous_counterparty(str(item["value"]))
    ]
    has_anonymous_customer = any("客户" in value for value in anonymous_names)
    has_anonymous_supplier = any("供应商" in value for value in anonymous_names)
    customer_gap = "部分主要客户仅以匿名代称披露，真实法律主体名称未披露。"
    supplier_gap = "部分主要供应商仅以匿名代称披露，真实法律主体名称未披露。"
    if (
        has_anonymous_customer
        and not any(
            "客户" in item and "真实法律主体名称未披露" in item
            for item in information_gaps
        )
    ):
        information_gaps.append(customer_gap)
    if (
        has_anonymous_supplier
        and not any(
            "供应商" in item and "真实法律主体名称未披露" in item
            for item in information_gaps
        )
    ):
        information_gaps.append(supplier_gap)


def _looks_like_anonymous_counterparty(value: str) -> bool:
    normalized = _normalize_quote(value)
    return (
        re.search(r"(?:境内|境外)?客户[A-ZＡ-Ｚ]\d*", normalized) is not None
        or re.search(r"供应商[A-ZＡ-Ｚ]{1,3}\d*", normalized) is not None
        or normalized.startswith(("某客户", "某供应商"))
    )


def _remove_contradicted_counterparty_gaps(
    items: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    information_gaps: list[str],
) -> None:
    has_customer_data = any(
        item["field_id"] == "customer_supplier.customer_concentration"
        for item in items
    ) or any(relation["relation_type"] == "sells_to" for relation in relations)
    has_supplier_data = any(
        item["field_id"] == "customer_supplier.supplier_concentration"
        for item in items
    ) or any(
        relation["relation_type"] == "purchases_from" for relation in relations
    )
    information_gaps[:] = [
        gap
        for gap in information_gaps
        if not (
            has_customer_data
            and any(
                term in gap
                for term in ("未披露前五大客户", "未披露客户集中度")
            )
        )
        and not (
            has_supplier_data
            and any(
                term in gap
                for term in ("未披露前五大供应商", "未披露供应商集中度")
            )
        )
    ]


def _candidate_rejection_summary(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    return {
        key: candidate.get(key)
        for key in (
            "item_id",
            "relation_id",
            "subject",
            "section_id",
            "field_id",
            "value",
            "value_type",
            "information_status",
            "content_role",
            "unit",
            "reporting_period",
            "value_scope",
            "evidence_unit_ids",
            "extraction_method",
            "source_id",
            "target_id",
            "relation_type",
            "evidence_quotes",
        )
        if key in candidate
    }


def _find_consistency_warnings(
    profile_items: list[dict[str, Any]],
    information_gaps: list[str],
) -> list[dict[str, str]]:
    """提示“已给出明确结论、同时又称证据不足”的候选，留给人工复核。"""
    warnings: list[dict[str, str]] = []
    for item in profile_items:
        terms = _GAP_FIELD_TERMS.get(item["field_id"], ())
        if not terms or item["information_status"] not in {"claimed", "supported", "confirmed"}:
            continue
        for gap in information_gaps:
            if any(term in gap for term in terms):
                warnings.append(
                    {
                        "item_id": item["item_id"],
                        "field_id": item["field_id"],
                        "information_gap": gap,
                        "reason": "该字段已有明确候选值，但信息缺口同时表示其证据仍不充分。",
                    }
                )
    return warnings


def build_profile_from_candidates(
    data: dict[str, Any],
    *,
    profile_id: str,
    case_id: str,
    enterprise_name: str,
    profile_type: str,
) -> EnterpriseProfile:
    evidence_ids = {
        evidence_id
        for item in data.get("profile_items", [])
        for evidence_id in item.get("evidence_unit_ids", [])
    }
    evidence_ids.update(
        evidence_id
        for relation in data.get("profile_relations", [])
        for evidence_id in relation.get("evidence_unit_ids", [])
    )
    validate_profile_candidates(data, evidence_unit_ids=evidence_ids, profile_type=profile_type)
    items = tuple(
        ProfileItem(
            item_id=item["item_id"],
            section_id=item["section_id"],
            field_id=item["field_id"],
            value=item["value"],
            value_type=item["value_type"],
            information_status=item["information_status"],
            content_role=item["content_role"],
            evidence_refs=_candidate_evidence_refs(item),
            subject=item.get("subject"),
            value_scope=item.get("value_scope"),
            unit=item.get("unit"),
            source_date=item.get("source_date"),
            reporting_period=item.get("reporting_period"),
            event_date=item.get("event_date"),
            effective_date=item.get("effective_date"),
            extraction_method=item.get("extraction_method", "llm"),
            ontology_version=item.get("ontology_version", ONTOLOGY_VERSION),
        )
        for item in data.get("profile_items", [])
    )
    relations = tuple(
        ProfileRelation(
            relation_id=relation["relation_id"],
            relation_type=relation["relation_type"],
            source_id=relation["source_id"],
            source_type=relation["source_type"],
            target_id=relation["target_id"],
            target_type=relation["target_type"],
            information_status=relation["information_status"],
            content_role=relation["content_role"],
            evidence_refs=_candidate_evidence_refs(relation),
        )
        for relation in data.get("profile_relations", [])
    )
    kwargs = {
        "profile_id": profile_id,
        "case_id": case_id,
        "enterprise_name": enterprise_name,
        "items": items,
        "relations": relations,
        "information_gaps": tuple(data.get("information_gaps", [])),
        "conflicts": tuple(data.get("conflicts", [])),
    }
    return HistoricalEnterpriseProfile(**kwargs) if profile_type == "historical" else CurrentEnterpriseProfile(**kwargs)


def _validate_item(item: Any, evidence_ids: set[str]) -> None:
    if not isinstance(item, dict):
        raise ValueError("profile_items 的每一项必须是对象。")
    required = (
        "item_id", "section_id", "field_id", "value", "value_type",
        "information_status", "content_role", "evidence_unit_ids",
    )
    if any(key not in item for key in required):
        raise ValueError("画像候选缺少必要字段。")
    if "subject" in item and (
        not isinstance(item["subject"], str) or not item["subject"].strip()
    ):
        raise ValueError("subject 必须是非空字符串。")
    if item["information_status"] not in INFORMATION_STATUSES:
        raise ValueError(f"information_status 非法：{item['information_status']!r}")
    field = REGISTRY.validate_field(
        item["field_id"], item["section_id"], item["value_type"]
    )
    REGISTRY.validate_value(item["field_id"], item["value"])
    if item["value_type"] == "integer" and (
        isinstance(item["value"], bool)
        or not isinstance(item["value"], int)
        or item["value"] < 0
    ):
        raise ValueError("integer 类型画像候选必须是非负整数。")
    if item["value_type"] == "ratio" and (
        isinstance(item["value"], bool)
        or not isinstance(item["value"], (int, float))
        or not 0 <= item["value"] <= 1
    ):
        raise ValueError("ratio 类型画像候选必须是 0 至 1 的数值。")
    if field.reporting_period_required and not str(
        item.get("reporting_period", "")
    ).strip():
        raise ValueError(f"字段 {item['field_id']} 必须包含 reporting_period。")
    if field.currency_required and not str(item.get("unit", "")).strip():
        raise ValueError(f"字段 {item['field_id']} 必须包含 unit。")
    if field.value_scope_required and not str(
        item.get("value_scope", "")
    ).strip():
        raise ValueError(f"字段 {item['field_id']} 必须包含 value_scope。")
    if item["field_id"] == "enterprise.legal_name":
        value = "".join(str(item["value"]).casefold().split())
        if value in {
            "发行人", "本公司", "公司", "该公司", "企业", "该企业",
            "未知", "未披露", "unknown", "notdisclosed",
        }:
            raise ValueError("enterprise.legal_name 不得使用企业指代词或未知占位值。")
    _validate_evidence_ids(item["evidence_unit_ids"], evidence_ids)


def _validate_relation(relation: Any, evidence_ids: set[str]) -> None:
    if not isinstance(relation, dict):
        raise ValueError("profile_relations 的每一项必须是对象。")
    required = (
        "relation_id", "relation_type", "source_id", "source_type", "target_id",
        "target_type", "information_status", "content_role", "evidence_unit_ids",
    )
    if any(key not in relation for key in required):
        raise ValueError("画像关系候选缺少必要字段。")
    if relation["information_status"] not in INFORMATION_STATUSES:
        raise ValueError(f"information_status 非法：{relation['information_status']!r}")
    validate_relation(relation["relation_type"], relation["source_type"], relation["target_type"])
    _validate_evidence_ids(relation["evidence_unit_ids"], evidence_ids)


def _validate_candidate_quote(
    candidate: dict[str, Any],
    *,
    evidence_contents: dict[str, str] | None,
    required: bool,
) -> None:
    quotes = _candidate_quote_pairs(candidate)
    if not quotes and not required:
        return
    if not quotes:
        raise ValueError("候选必须包含 evidence_quotes。")
    quote_ids = {evidence_id for evidence_id, _ in quotes}
    evidence_ids = set(candidate["evidence_unit_ids"])
    if not quote_ids <= evidence_ids:
        raise ValueError("evidence_quotes 只能引用 evidence_unit_ids 中的证据。")
    if required and quote_ids != evidence_ids:
        raise ValueError("每个 evidence_unit_id 都必须提供对应的证据摘录。")
    if evidence_contents is not None:
        for evidence_id, quote in quotes:
            content = evidence_contents.get(evidence_id)
            if content is None or _normalize_quote(quote) not in _normalize_quote(content):
                raise ValueError("每条证据摘录都必须逐字来自对应的 EvidenceUnit。")


def _validate_authoritative_content_role(candidate: dict[str, Any]) -> None:
    role = str(candidate.get("content_role", ""))
    quote = _candidate_raw_quote_text(candidate)
    if role not in {"regulatory_finding", "judicial_finding"}:
        raise ValueError("权威事项只能使用 regulatory_finding 或 judicial_finding。")
    if role == "judicial_finding" and not any(
        term in quote
        for term in ("法院", "人民法院", "判决", "裁定", "调解", "受理案件", "案号", "裁判")
    ):
        raise ValueError("司法认定必须引用法院、裁判、调解或案件受理事实。")
    if role == "regulatory_finding" and not any(
        term in quote
        for term in ("监管", "行政处罚", "处罚决定", "证监会", "交易所", "认定", "决定书", "复议")
    ):
        raise ValueError("监管认定必须引用监管、行政处罚或决定事实。")


def _validate_profile_item_semantics(
    item: dict[str, Any],
    semantic_text: str,
) -> None:
    field_id = item["field_id"]
    quote = _candidate_direct_quote_text(item)
    raw_quote = _candidate_raw_quote_text(item)
    if item["value_type"] in {"integer", "money", "ratio"} and any(
        term in raw_quote for term in ("未披露", "未提供", "无法确认", "未说明")
    ):
        raise ValueError("未披露或无法确认的数值不得写为零或其他数值。")
    if item["value_type"] in {"integer", "money"} and not _number_value_in_text(
        item["value"], raw_quote
    ):
        raise ValueError("直接数值必须逐字出现在至少一条证据摘录中。")
    if field_id == "risk.matter" and _is_negated_risk_statement(raw_quote):
        raise ValueError("无重大或未发生的风险事实不得作为风险事项。")
    if (
        item["value_type"] == "ratio"
        and not field_id.startswith("customer_supplier.")
        and item.get("extraction_method") != "rule"
        and not _ratio_value_in_text(item["value"], raw_quote)
    ):
        raise ValueError("比例必须由证据直接披露，不得由模型自行计算。")
    if (
        field_id == "team.education_structure"
        and any(term in str(item.get("value", "")) for term in ("未披露", "未提供"))
        and item.get("information_status")
        not in {"insufficient_evidence", "not_disclosed", "unknown"}
    ):
        raise ValueError(
            "教育结构包含未披露信息时，information_status 必须表示证据不足或未披露。"
        )
    if field_id in {
        "intellectual_property.patent_application_count",
        "intellectual_property.patent_grant_count",
    } and not str(item.get("value_scope", "")).strip():
        raise ValueError("专利数量必须包含 value_scope。")
    if (
        field_id == "intellectual_property.patent_application_count"
        and "申请" not in quote
    ):
        raise ValueError("专利申请数量的证据摘录必须明确表达申请。")
    if field_id == "intellectual_property.patent_grant_count" and not any(
        term in semantic_text for term in ("授权", "专利权", "拥有")
    ):
        raise ValueError("专利授权或拥有数量的证据摘录必须明确表达授权或拥有。")
    if field_id in {
        "intellectual_property.patent_application_count",
        "intellectual_property.patent_grant_count",
    }:
        scope = str(item.get("value_scope", "")).strip()
        if scope not in {"全部", "总数", "总量"} and _normalize_quote(scope) not in quote:
            raise ValueError("专利数量的统计范围必须直接出现在证据摘录中。")
        if scope in {"全部", "总数", "总量"} and not any(
            term in raw_quote for term in ("合计", "总计", "共计", "总数", "全部", "拥有")
        ):
            raise ValueError("专利子集数量不得写为无范围总量。")
        if scope in {"全部", "总数", "总量"} and any(
            term in raw_quote for term in ("新增", "本期", "报告期内", "当年", "年度")
        ):
            raise ValueError("本期新增专利数量不得写为全部或总量。")
    if field_id == "intellectual_property.ownership_status" and not any(
        term in semantic_text
        for term in ("权属", "所有", "拥有", "专利权人", "权利人")
    ):
        raise ValueError("知识产权权属的证据摘录必须明确表达权利归属。")
    if field_id == "intellectual_property.rights_restriction_status" and not any(
        term in semantic_text
        for term in ("质押", "查封", "冻结", "权利限制", "权利受到限制")
    ):
        raise ValueError("知识产权权利限制状态必须引用明确的限制或无限制表述。")
    if (
        field_id == "technology.source"
        and str(item["value"]).strip() in {"自研", "自主研发"}
        and not any(term in quote for term in ("自研", "自主研发", "研发", "开发"))
    ):
        raise ValueError("自研技术来源必须引用明确的自研、研发或开发表述。")
    if field_id == "technology.maturity_stage":
        subject = str(item.get("subject", "")).strip()
        if subject == "the_enterprise" or _normalize_quote(subject) not in quote:
            raise ValueError("技术成熟度必须引用具体技术名称。")
        has_named_time = re.search(r"(?:19|20)\d{2}", raw_quote) is not None
        has_maturity_statement = any(
            term in raw_quote
            for term in ("已量产", "实现量产", "投入生产", "批量生产", "商业化", "试点", "验证")
        )
        has_production_column = any(
            term in raw_quote for term in ("量产", "生产开始时间", "生产时间")
        )
        if not has_maturity_statement and not (has_production_column and has_named_time):
            raise ValueError("技术成熟度必须引用具体技术的量产、生产或成熟度事实。")
    if field_id in {
        "enterprise.legal_name",
        "team.key_person",
        "technology.name",
        "intellectual_property.name",
        "product.name",
        "customer_supplier.counterparty_name",
    } and _normalize_quote(str(item["value"])) not in quote:
        raise ValueError("实体名称必须直接出现在至少一条证据摘录中。")
    if field_id == "product.name" and any(
        term in str(item["value"])
        for term in ("客户", "供应商", "研发项目", "开发项目", "建设项目", "募投项目")
    ):
        raise ValueError("客户、供应商和研发或建设项目不得作为产品名称。")
    if field_id == "product.name" and any(
        term in str(item["value"])
        for term in (
            "技术",
            "算法",
            "模型",
            "电机",
            "减速器",
            "激光雷达",
            "灵巧手",
            "执行器",
            "传感器",
            "零部件",
        )
    ) and (
        str(item["value"]).strip().endswith("技术")
        or not _relation_term_shares_clause(
            raw_quote,
            str(item["value"]),
            ("产品", "型号", "系列", "机型"),
        )
    ):
        raise ValueError("技术或零部件必须被原文明确称为产品、型号或系列。")
    if field_id == "finance.net_profit" and any(
        term in quote
        for term in (
            "归属于母公司",
            "归属于上市公司股东",
            "归母净利润",
            "扣除非经常性损益",
            "扣非",
        )
    ):
        raise ValueError("归母或扣非归母净利润不得写入普通净利润字段。")
    if field_id == "finance.net_profit_attributable_to_parent":
        if not any(
            term in quote
            for term in ("归属于母公司", "归属于上市公司股东", "归母净利润")
        ):
            raise ValueError("归母净利润字段必须引用明确的归母口径。")
        if any(term in quote for term in ("扣除非经常性损益", "扣非")):
            raise ValueError("扣非归母净利润必须使用专门字段。")
    if field_id == "finance.adjusted_net_profit_attributable_to_parent" and not (
        any(term in quote for term in ("归属于母公司", "归母"))
        and any(term in quote for term in ("扣除非经常性损益", "扣非"))
    ):
        raise ValueError("扣非归母净利润字段必须同时引用归母和扣非口径。")
    if field_id == "finance.operating_cash_flow" and (
        "经营活动产生的现金流量净额" not in semantic_text
    ):
        raise ValueError("经营活动现金流字段必须引用现金流量净额。")
    if field_id == "finance.cash_balance" and (
        "期末现金及现金等价物余额" not in quote
    ):
        raise ValueError("现金余额字段只接受期末现金及现金等价物余额。")
    if field_id == "finance.interest_bearing_debt":
        if any(
            term in quote
            for term in ("取得借款收到的现金", "偿还债务支付的现金")
        ):
            raise ValueError("借款现金流不得作为有息负债余额。")
        if not any(
            term in semantic_text
            for term in (
                "有息负债",
                "借款余额",
                "短期借款",
                "长期借款",
                "应付债券",
                "租赁负债",
            )
        ):
            raise ValueError("有息负债字段必须引用明确的债务余额或组成项目。")
    if field_id == "customer_supplier.customer_concentration":
        scope = str(item.get("value_scope", ""))
        if "前五" not in scope or not any(
            term in scope for term in ("收入", "销售")
        ):
            raise ValueError("客户集中度范围必须说明前五大客户及收入分母。")
        if "前五" not in quote or not any(
            term in quote for term in ("收入", "销售")
        ):
            raise ValueError(
                "客户集中度证据摘录必须直接包含前五大客户及收入分母口径。"
            )
        if not _quote_supports_ratio_period(item, semantic_text):
            raise ValueError("客户集中度证据摘录必须包含对应期间和比例值。")
    if field_id == "customer_supplier.supplier_concentration":
        scope = str(item.get("value_scope", ""))
        if "前五" not in scope or "采购" not in scope:
            raise ValueError("供应商集中度范围必须说明前五大供应商及采购分母。")
        if "前五" not in quote or "采购" not in quote:
            raise ValueError(
                "供应商集中度证据摘录必须直接包含前五大供应商及采购分母口径。"
            )
        if not _quote_supports_ratio_period(item, semantic_text):
            raise ValueError("供应商集中度证据摘录必须包含对应期间和比例值。")
    if field_id in {
        "customer_supplier.transaction_amount",
        "customer_supplier.transaction_ratio",
        "customer_supplier.transaction_content",
    }:
        subject = str(item.get("subject", "")).strip()
        if subject == "the_enterprise" or _normalize_quote(subject) not in quote:
            raise ValueError("交易对手属性必须由包含交易对手名称或代称的表格行支持。")
        scope = str(item.get("value_scope", ""))
        if not any(term in scope for term in ("销售", "收入", "采购")):
            raise ValueError("交易对手属性范围必须说明客户销售或供应商采购口径。")
        if field_id == "customer_supplier.transaction_amount" and not (
            _number_value_in_text(item.get("value"), raw_quote)
        ):
            raise ValueError("交易金额证据摘录必须包含对应金额。")
        if field_id == "customer_supplier.transaction_ratio" and not (
            _ratio_value_in_text(item.get("value"), semantic_text)
        ):
            raise ValueError("交易占比证据摘录必须包含对应比例。")
        if field_id == "customer_supplier.transaction_content" and (
            _normalize_quote(str(item.get("value", ""))) not in quote
        ):
            raise ValueError("交易内容必须逐字出现在对应交易对手表格行中。")
        year_match = re.search(
            r"(?:19|20)\d{2}",
            str(item.get("reporting_period", "")),
        )
        if year_match is None:
            raise ValueError("交易对手属性必须填写 reporting_period。")
        if (
            year_match.group() not in semantic_text
            and "报告期" not in semantic_text
            and "年度" not in semantic_text
        ):
            raise ValueError("交易对手属性证据摘录必须包含对应年度。")
    if field_id == "customer_supplier.related_party_status":
        scope = str(item.get("value_scope", ""))
        if not any(term in scope for term in ("客户", "供应商")):
            raise ValueError("关联关系状态必须说明适用客户或供应商范围。")
        if item.get("value") == "non_related" and (
            "不存在关联关系" not in quote
            and not re.search(
                r"关联方[^。；\n]{0,20}(?:0万元|0%|为0)",
                quote,
            )
        ):
            raise ValueError("无关联关系状态必须引用明确的不存在关联关系表述。")


def _validate_relation_semantics(
    relation: dict[str, Any],
    semantic_text: str,
    *,
    target_name: str = "",
) -> None:
    quote = _candidate_direct_quote_text(relation)
    target_id = str(relation.get("target_id") or "").casefold()
    if relation["relation_type"] == "sells_to" and ":supplier:" in target_id:
        raise ValueError("sells_to 关系的目标必须是客户画像项。")
    if relation["relation_type"] == "purchases_from" and ":customer:" in target_id:
        raise ValueError("purchases_from 关系的目标必须是供应商画像项。")
    if relation["relation_type"] == "owns" and not any(
        term in quote for term in ("权属", "所有", "拥有", "权利人")
    ):
        raise ValueError("owns 关系必须引用明确的拥有或权属表述。")
    if relation["relation_type"] == "develops":
        if not any(term in quote for term in ("自研", "研发", "开发")):
            raise ValueError("develops 关系必须引用明确的自研、研发或开发表述。")
        if target_name and _compact_relation_text(target_name) not in _compact_relation_text(quote):
            raise ValueError("develops 关系证据必须直接出现目标对象。")
        if (
            target_name
            and not relation.get("_relation_scope_verified")
            and not _relation_term_shares_clause(
                quote,
                target_name,
                ("自研", "研发", "开发"),
            )
        ):
            raise ValueError("develops 关系的自研或研发证据未直接支持目标对象。")
    if relation["relation_type"] == "sells_to" and not any(
        term in semantic_text for term in ("客户", "销售", "收入占比")
    ):
        raise ValueError("sells_to 关系必须引用明确的客户或销售表述。")
    if relation["relation_type"] == "purchases_from" and not any(
        term in semantic_text for term in ("供应商", "采购")
    ):
        raise ValueError("purchases_from 关系必须引用明确的供应商或采购表述。")


def _relation_term_shares_clause(
    quote: str,
    target_name: str,
    relation_terms: tuple[str, ...],
) -> bool:
    """判断关系词和目标名称是否出现在同一分句。"""
    target = _compact_relation_text(target_name)
    text = _compact_relation_text(quote)
    clauses = re.split(r"[，,。；;：:！？!?]", text)
    return any(
        target in clause and any(term in clause for term in relation_terms)
        for clause in clauses
    )


def _compact_relation_text(value: Any) -> str:
    return "".join(str(value).split())


def _validate_evidence_ids(value: Any, allowed_ids: set[str]) -> None:
    if not isinstance(value, list) or not value or any(item not in allowed_ids for item in value):
        raise ValueError("每项画像候选必须引用当前输入中的 EvidenceUnit。")


def _string_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _candidate_evidence_refs(candidate: dict[str, Any]) -> tuple[EvidenceReference, ...]:
    """保留每条可验证摘录，避免把同一 EvidenceUnit 的非连续片段拼成伪引用。"""
    quotes = dict.fromkeys(_candidate_quote_pairs(candidate))
    refs: list[EvidenceReference] = []
    for evidence_id in candidate["evidence_unit_ids"]:
        evidence_quotes = [
            quote for quote_id, quote in quotes if quote_id == evidence_id
        ]
        if evidence_quotes:
            refs.extend(
                EvidenceReference(evidence_id, excerpt=quote)
                for quote in evidence_quotes
            )
        else:
            refs.append(EvidenceReference(evidence_id, excerpt=None))
    return tuple(refs)


def _normalize_quote(value: str) -> str:
    return "".join(value.split())


def _candidate_evidence_context(
    candidate: dict[str, Any],
    *,
    evidence_contents: dict[str, str] | None,
    context_chars: int = 100,
) -> str:
    contexts: list[str] = []
    for evidence_id, raw_quote in _candidate_quote_pairs(candidate):
        quote = _normalize_quote(raw_quote)
        if evidence_contents is None:
            contexts.append(quote)
            continue
        raw_content = evidence_contents.get(evidence_id, "")
        exact_start = raw_content.find(raw_quote)
        if exact_start >= 0:
            contexts.append(
                raw_content[
                    max(0, exact_start - context_chars):
                    exact_start + len(raw_quote) + context_chars
                ]
            )
            continue
        content = _normalize_quote(raw_content)
        start = content.find(quote)
        if start < 0:
            # The model excerpt may normalize spaces or line breaks.  Keep
            # the original unit as context in that case so table headers and
            # row separators remain available for semantic validation.
            contexts.append(raw_content)
            continue
        contexts.append(
            content[
                max(0, start - context_chars):
                start + len(quote) + context_chars
            ]
        )
    return "\n".join(contexts)


def _normalize_candidate_evidence_ids(item: Any, allowed_ids: set[str]) -> Any:
    """兼容证据摘录中已给出但顶层未重复列出的 EvidenceUnit ID。"""
    if not isinstance(item, dict):
        return item
    normalized = dict(item)
    if not isinstance(normalized.get("evidence_unit_ids"), list):
        quotes = normalized.get("evidence_quotes")
        if isinstance(quotes, list):
            normalized["evidence_unit_ids"] = [
                reference.get("evidence_unit_id")
                for reference in quotes
                if isinstance(reference, dict)
                and isinstance(reference.get("evidence_unit_id"), str)
            ]
        else:
            return item
    values: list[Any] = []
    for value in normalized["evidence_unit_ids"]:
        matches = [
            allowed
            for allowed in allowed_ids
            if value == allowed or value == allowed.rsplit(":", 1)[-1]
        ]
        values.append(matches[0] if len(matches) == 1 else value)
    normalized["evidence_unit_ids"] = values
    if isinstance(normalized.get("evidence_quote_id"), str):
        normalized["evidence_quote_id"] = _normalize_evidence_id(
            normalized["evidence_quote_id"], allowed_ids
        )
    if isinstance(normalized.get("evidence_quotes"), list):
        normalized["evidence_quotes"] = [
            {
                **reference,
                "evidence_unit_id": _normalize_evidence_id(
                    reference.get("evidence_unit_id"), allowed_ids
                ),
            }
            if isinstance(reference, dict)
            else reference
            for reference in normalized["evidence_quotes"]
        ]
    return normalized


def _normalize_evidence_id(value: Any, allowed_ids: set[str]) -> Any:
    matches = [
        allowed
        for allowed in allowed_ids
        if value == allowed or value == allowed.rsplit(":", 1)[-1]
    ]
    return matches[0] if len(matches) == 1 else value


def _ground_customer_supplier_evidence_quotes(
    candidate: Any,
    *,
    evidence_contents: dict[str, str] | None,
) -> Any:
    """从同一证据中确定性补齐集中度或交易对手表格摘录。"""
    supported_fields = {
        "customer_supplier.customer_concentration",
        "customer_supplier.supplier_concentration",
        "customer_supplier.counterparty_name",
        "customer_supplier.transaction_amount",
        "customer_supplier.transaction_ratio",
        "customer_supplier.transaction_content",
        "customer_supplier.related_party_status",
    }
    if (
        not isinstance(candidate, dict)
        or evidence_contents is None
        or candidate.get("field_id") not in supported_fields
        or not isinstance(candidate.get("evidence_unit_ids"), list)
    ):
        return candidate

    grounded: list[tuple[str, str]] = []
    try:
        model_quotes = _candidate_quote_pairs(candidate)
    except ValueError:
        return candidate
    for evidence_id, quote in model_quotes:
        content = evidence_contents.get(evidence_id, "")
        if _normalize_quote(quote) in _normalize_quote(content):
            grounded.append((evidence_id, quote))

    for evidence_id in candidate["evidence_unit_ids"]:
        content = evidence_contents.get(evidence_id, "")
        if candidate["field_id"] in {
            "customer_supplier.customer_concentration",
            "customer_supplier.supplier_concentration",
        }:
            excerpts = _concentration_support_excerpts(candidate, content)
        else:
            excerpts = _counterparty_support_excerpts(candidate, content)
        for excerpt in excerpts:
            grounded.append((evidence_id, excerpt))
    if not grounded:
        return candidate

    normalized = dict(candidate)
    normalized["evidence_quotes"] = [
        {"evidence_unit_id": evidence_id, "excerpt": excerpt}
        for evidence_id, excerpt in dict.fromkeys(grounded)
    ]
    return normalized


def _ground_team_key_person_evidence_quotes(
    candidate: Any,
    *,
    evidence_contents: dict[str, str] | None,
) -> Any:
    """为关键人员候选补齐包含完整姓名的连续原文摘录。"""
    if (
        not isinstance(candidate, dict)
        or evidence_contents is None
        or candidate.get("field_id") != "team.key_person"
        or not isinstance(candidate.get("evidence_unit_ids"), list)
    ):
        return candidate
    value = str(candidate.get("value") or "").strip()
    if not value:
        return candidate

    grounded: list[tuple[str, str]] = []
    try:
        model_quotes = _candidate_quote_pairs(candidate)
    except ValueError:
        model_quotes = []
    for evidence_id, quote in model_quotes:
        content = evidence_contents.get(evidence_id, "")
        if _normalize_quote(quote) in _normalize_quote(content):
            grounded.append((evidence_id, quote))

    normalized_value = _normalize_quote(value)
    for evidence_id in candidate["evidence_unit_ids"]:
        content = evidence_contents.get(evidence_id, "")
        if normalized_value not in _normalize_quote(content):
            continue
        for line in content.splitlines():
            excerpt = line.strip()
            if excerpt and normalized_value in _normalize_quote(excerpt):
                grounded.append((evidence_id, excerpt))
                break
    if not grounded:
        return candidate

    normalized = dict(candidate)
    normalized["evidence_quotes"] = [
        {"evidence_unit_id": evidence_id, "excerpt": excerpt}
        for evidence_id, excerpt in dict.fromkeys(grounded)
    ]
    return normalized


def _ground_enterprise_main_business_evidence_quotes(
    candidate: Any,
    *,
    evidence_contents: dict[str, str] | None,
) -> Any:
    """为主营业务汇总候选补齐包含业务类别的连续原文行。"""
    if (
        not isinstance(candidate, dict)
        or evidence_contents is None
        or candidate.get("field_id") != "enterprise.main_business"
        or not isinstance(candidate.get("evidence_unit_ids"), list)
    ):
        return candidate
    value = str(candidate.get("value") or "").strip()
    if not value:
        return candidate
    grounded: list[tuple[str, str]] = []
    try:
        model_quotes = _candidate_quote_pairs(candidate)
    except ValueError:
        model_quotes = []
    for evidence_id, quote in model_quotes:
        content = evidence_contents.get(evidence_id, "")
        if _normalize_quote(quote) in _normalize_quote(content):
            grounded.append((evidence_id, quote))

    terms = [term.strip() for term in re.split(r"[、,，；;和及与/]+", value) if term.strip()]
    for evidence_id in candidate["evidence_unit_ids"]:
        content = evidence_contents.get(evidence_id, "")
        for line in content.splitlines():
            excerpt = line.strip()
            if not excerpt:
                continue
            if any(_normalize_quote(term) in _normalize_quote(excerpt) for term in terms):
                grounded.append((evidence_id, excerpt))
    if not grounded:
        return candidate
    normalized = dict(candidate)
    normalized["evidence_quotes"] = [
        {"evidence_unit_id": evidence_id, "excerpt": excerpt}
        for evidence_id, excerpt in dict.fromkeys(grounded)
    ]
    return normalized


def _counterparty_support_excerpts(
    candidate: dict[str, Any],
    content: str,
) -> list[str]:
    if not content:
        return []
    field_id = candidate["field_id"]
    if field_id == "customer_supplier.related_party_status":
        scope = str(candidate.get("value_scope", ""))
        role_terms = ("客户",) if "客户" in scope else ("供应商",)
        excerpt = _shortest_keyword_excerpt(
            content,
            (role_terms, ("关联关系",), ("不存在", "存在")),
        )
        return [excerpt] if excerpt else []

    subject = str(candidate.get("subject", "")).strip()
    if not subject or subject == "the_enterprise":
        return []
    matching_rows: list[tuple[int, int, str]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        row = line.rstrip("\r\n")
        row_start = offset
        offset += len(line)
        if _normalize_quote(subject) not in _normalize_quote(row):
            continue
        if field_id == "customer_supplier.counterparty_name":
            value = str(candidate.get("value", ""))
            supported = _normalize_quote(value) in _normalize_quote(row)
        elif field_id == "customer_supplier.transaction_amount":
            supported = _number_value_in_text(candidate.get("value"), row)
        elif field_id == "customer_supplier.transaction_ratio":
            supported = _ratio_value_in_text(candidate.get("value"), row)
        else:
            value = str(candidate.get("value", ""))
            supported = _normalize_quote(value) in _normalize_quote(row)
        if supported:
            matching_rows.append((row_start, row_start + len(row), row.strip()))
    if not matching_rows:
        return []
    if field_id == "customer_supplier.counterparty_name":
        return [matching_rows[0][2]]

    year_match = re.search(
        r"(?:19|20)\d{2}",
        str(candidate.get("reporting_period", "")),
    )
    if year_match is None:
        return []
    year = year_match.group()
    period_rows: list[tuple[int, int]] = []
    for row_start, _, row in matching_rows:
        years = list(re.finditer(r"(?:19|20)\d{2}", content[:row_start + 1]))
        if years and years[-1].group() == year:
            start = content.rfind("\n", 0, years[-1].start()) + 1
            period_rows.append((start, row_start + len(row)))
            continue
        report_markers = list(re.finditer("报告期|年度", content[:row_start]))
        if report_markers:
            start = content.rfind("\n", 0, report_markers[-1].start()) + 1
            period_rows.append((start, row_start + len(row)))
    if len(period_rows) != 1:
        return []
    start, end = period_rows[0]
    return [content[start:end].strip()]


def _concentration_support_excerpts(
    candidate: dict[str, Any],
    content: str,
) -> list[str]:
    if not content:
        return []
    if candidate["field_id"] == "customer_supplier.customer_concentration":
        keyword_groups = (
            (("主要客户",), ("销售", "收入")),
            (("前五",), ("客户",)),
        )
    else:
        keyword_groups = (
            (("前五",), ("供应商",), ("采购",)),
        )
    excerpts = [
        excerpt
        for groups in keyword_groups
        if (excerpt := _shortest_keyword_excerpt(content, groups))
    ]
    value_excerpt = _ratio_period_excerpt(
        content,
        value=candidate.get("value"),
        reporting_period=candidate.get("reporting_period"),
    )
    if value_excerpt:
        excerpts.append(value_excerpt)
    return list(dict.fromkeys(excerpts))


def _shortest_keyword_excerpt(
    content: str,
    groups: tuple[tuple[str, ...], ...],
) -> str | None:
    occurrences: list[list[tuple[int, str]]] = []
    for alternatives in groups:
        matches = [
            (match.start(), term)
            for term in alternatives
            for match in re.finditer(re.escape(term), content)
        ]
        if not matches:
            return None
        occurrences.append(matches)
    positions = min(
        product(*occurrences),
        key=lambda values: (
            max(position + len(term) for position, term in values)
            - min(position for position, _ in values)
        ),
    )
    start = min(position for position, _ in positions)
    end = max(position + len(term) for position, term in positions)
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", end)
    if line_end < 0:
        line_end = len(content)
    return content[line_start:line_end].strip()


def _ratio_period_excerpt(
    content: str,
    *,
    value: Any,
    reporting_period: Any,
) -> str | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isinstance(reporting_period, str)
    ):
        return None
    year_match = re.search(r"(?:19|20)\d{2}", reporting_period)
    if year_match is None:
        return None
    year = year_match.group()
    percent = _ratio_percent_text(value)
    percent_matches = list(
        re.finditer(rf"(?<![\d.]){re.escape(percent)}\s*%", content)
    )
    candidates: list[tuple[int, int]] = []
    for match in percent_matches:
        line_start = content.rfind("\n", 0, match.start()) + 1
        line_end = content.find("\n", match.end())
        if line_end < 0:
            line_end = len(content)
        if "合计" not in content[line_start:line_end]:
            continue
        years = list(re.finditer(re.escape(year), content[:match.start()]))
        if not years:
            continue
        start = years[-1].start()
        intervening_years = re.findall(r"(?:19|20)\d{2}", content[start:match.start()])
        if intervening_years == [year]:
            candidates.append((start, match.end()))
    if len(candidates) != 1:
        return None
    start, end = candidates[0]
    return content[start:end].strip()


def _quote_supports_ratio_period(
    candidate: dict[str, Any],
    quote: str,
) -> bool:
    value = candidate.get("value")
    period = str(candidate.get("reporting_period", ""))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    year_match = re.search(r"(?:19|20)\d{2}", period)
    if year_match is None:
        return False
    period_ok = (
        year_match.group() in quote
        or "报告期" in quote
        or "年度" in quote
    )
    explicit_years = set(re.findall(r"(?:19|20)\d{2}", quote))
    if year_match.group() not in explicit_years and any(
        other_year != year_match.group() for other_year in explicit_years
    ):
        period_ok = False
    has_total = "合计" in quote or (
        "前五" in quote and any(term in quote for term in ("销售", "采购"))
    )
    return period_ok and has_total and _ratio_value_in_text(value, quote)


def _ratio_percent_text(value: float) -> str:
    return f"{value * 100:.6f}".rstrip("0").rstrip(".")


def _ratio_value_in_text(value: Any, text: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    percent_tokens = re.findall(r"-?\d+(?:\.\d+)?\s*%", text)
    tokens = [(token.rstrip("%").strip(), True) for token in percent_tokens]
    if any(marker in text for marker in ("(%)", "（%）", "比例", "占比")):
        # Annual-report tables often put (%) in the column header and omit
        # the percent sign from each row.  In that case treat the row number
        # as a percentage only when the surrounding header establishes it.
        tokens.extend(
            (token, True)
            for token in re.findall(r"-?\d+(?:\.\d+)?", text)
        )
    for token, is_percent in tokens:
        parsed = float(token) / 100 if is_percent else float(token)
        if abs(parsed - float(value)) < 0.0000005:
            return True
    return False


def _number_value_in_text(value: Any, text: str) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text):
        try:
            parsed = float(token.replace(",", ""))
        except ValueError:
            continue
        if abs(parsed - float(value)) < 0.005:
            return True
    return False


def _is_negated_risk_statement(text: str) -> bool:
    return re.search(
        r"(?:无重大|未发生|不存在重大|未发现).{0,12}(?:风险|诉讼|仲裁|处罚|违法|违规|担保)",
        text,
    ) is not None


def _candidate_quote_pairs(candidate: dict[str, Any]) -> list[tuple[str, str]]:
    raw_quotes = candidate.get("evidence_quotes")
    if raw_quotes is not None:
        if not isinstance(raw_quotes, list):
            raise ValueError("evidence_quotes 必须是数组。")
        pairs: list[tuple[str, str]] = []
        for reference in raw_quotes:
            if not isinstance(reference, dict):
                raise ValueError("evidence_quotes 的每一项必须是对象。")
            evidence_id = reference.get("evidence_unit_id")
            excerpt = reference.get("excerpt")
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ValueError("证据摘录必须包含 evidence_unit_id。")
            if not isinstance(excerpt, str) or not excerpt.strip():
                raise ValueError("证据摘录必须包含非空 excerpt。")
            pairs.append((evidence_id, excerpt.strip()))
        return pairs
    quote = candidate.get("evidence_quote")
    quote_id = candidate.get("evidence_quote_id")
    if isinstance(quote, str) and quote.strip() and isinstance(quote_id, str):
        return [(quote_id, quote.strip())]
    return []


def _candidate_direct_quote_text(candidate: dict[str, Any]) -> str:
    return "\n".join(
        _normalize_quote(quote)
        for _, quote in _candidate_quote_pairs(candidate)
    )


def _candidate_raw_quote_text(candidate: dict[str, Any]) -> str:
    return "\n".join(quote for _, quote in _candidate_quote_pairs(candidate))


def _merge_evidence_quotes(
    first: dict[str, Any],
    second: dict[str, Any],
) -> list[dict[str, str]]:
    return [
        {"evidence_unit_id": evidence_id, "excerpt": quote}
        for evidence_id, quote in dict.fromkeys(
            [*_candidate_quote_pairs(first), *_candidate_quote_pairs(second)]
        )
    ]
