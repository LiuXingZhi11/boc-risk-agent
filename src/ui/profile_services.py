"""企业画像工作区的页面服务。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.authorization import (
    can_run_profile_dimension,
    can_run_profile_domain,
    filter_profile_for_role,
)
from src.config.settings import get_settings
from src.evidence import EvidenceQueryService, EvidenceRepository
from src.llm.generation_config import GenerationConfig
from src.profiles import (
    ProfileRepository,
    aggregate_profile_run,
    build_enterprise_visual_card,
    finalize_and_save_profile_review,
)
from src.profiles.current_workflow import CurrentProfileWorkflow
from src.profiles.historical_workflow import HistoricalProfileWorkflow
from src.profiles.react_models import ReactLimits
from src.profiles.react_workflow import (
    ControlledReactProfileWorkflow,
    build_deepseek_chat_model,
)
from src.profiles.topic_analysis import (
    ControlledReactTopicAnalysisWorkflow,
    TopicAnalysisLimits,
    TopicAnalysisRun,
    apply_topic_analysis,
)
from src.profiles.topic_analysis_repository import ProfileTopicAnalysisRepository


def load_profile_review(content: bytes | str) -> dict[str, Any]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    return aggregate_profile_run(json.loads(text))


def run_domain_investigation(
    *,
    database: str | Path,
    case_id: str,
    profile_type: str,
    domains: tuple[str, ...],
    query: str = "",
    max_evidence_per_domain: int = 20,
    max_selected_evidence_per_domain: int = 5,
    max_tokens: int = 18000,
    max_retries: int = 2,
    role: str | None = "senior_business",
    historical_workflow_class: Any = HistoricalProfileWorkflow,
    current_workflow_class: Any = CurrentProfileWorkflow,
) -> dict[str, Any]:
    denied_domains = [domain for domain in domains if not can_run_profile_domain(role, domain)]
    if denied_domains:
        raise PermissionError("当前身份无权调查领域：" + ", ".join(denied_domains))
    settings = get_settings()
    selection_config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=max_tokens,
        max_retries=max_retries,
    )
    extraction_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=max_tokens,
        max_retries=max_retries,
    )
    evidence_service = EvidenceQueryService(EvidenceRepository(database))
    common = {
        "case_id": case_id,
        "selection_config": selection_config,
        "extraction_config": extraction_config,
        "domains": domains,
        "max_evidence_per_domain": max_evidence_per_domain,
        "max_selected_evidence_per_domain": max_selected_evidence_per_domain,
        "guide_text": "",
    }
    if profile_type == "historical":
        result = historical_workflow_class(evidence_service).run(**common)
    elif profile_type == "current":
        result = current_workflow_class(evidence_service).run(query=query, **common)
    else:
        raise ValueError("profile_type 必须为 historical 或 current。")
    return asdict(result)


def run_react_domain_investigation(
    *,
    database: str | Path,
    case_id: str,
    domain: str,
    query: str = "",
    max_catalog_items: int = 10,
    max_read_units: int = 5,
    max_tokens: int = 18000,
    max_retries: int = 2,
    role: str | None = "senior_business",
    workflow_class: Any = ControlledReactProfileWorkflow,
) -> dict[str, Any]:
    """执行当前企业单领域受控 ReAct 调查。"""
    if not can_run_profile_domain(role, domain):
        raise PermissionError(f"当前身份无权调查领域：{domain}")
    settings = get_settings()
    react_config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=max_tokens,
        max_retries=max_retries,
    )
    extraction_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=max_tokens,
        max_retries=max_retries,
    )
    workflow = workflow_class(EvidenceQueryService(EvidenceRepository(database)))
    result = workflow.run_current_domain(
        case_id=case_id,
        domain=domain,
        react_config=react_config,
        extraction_config=extraction_config,
        query=query,
        limits=ReactLimits(
            max_catalog_items=max_catalog_items,
            max_read_units=max_read_units,
        ),
        guide_text="",
    )
    return asdict(result)


def run_react_profile_investigation(
    *,
    database: str | Path,
    case_id: str,
    domains: tuple[str, ...],
    query: str = "",
    max_catalog_items: int = 10,
    max_read_units: int = 5,
    max_tokens: int = 18000,
    max_retries: int = 2,
    role: str | None = "senior_business",
    domain_runner: Any | None = None,
) -> dict[str, Any]:
    """按领域顺序执行当前企业 ReAct，并合并为一次候选运行。"""
    if not domains:
        raise ValueError("至少选择一个企业画像领域。")
    runner = domain_runner or run_react_domain_investigation
    domain_results: list[dict[str, Any]] = []
    for domain in domains:
        result = runner(
            database=database,
            case_id=case_id,
            domain=domain,
            query=query,
            max_catalog_items=max_catalog_items,
            max_read_units=max_read_units,
            max_tokens=max_tokens,
            max_retries=max_retries,
            role=role,
        )
        domain_results.extend(result.get("domains", []))
    return {
        "case_id": case_id,
        "profile_type": "current",
        "execution_mode": "react",
        "domains": domain_results,
    }


def approve_profile_review(
    *,
    database: str | Path,
    bundle: dict[str, Any],
    profile_id: str,
    enterprise_name: str,
) -> dict[str, Any]:
    profile = finalize_and_save_profile_review(
        bundle["candidates"],
        repository=ProfileRepository(database),
        evidence_unit_ids=bundle["evidence_unit_ids"],
        decision="accept",
        profile_id=profile_id,
        case_id=bundle["case_id"],
        enterprise_name=enterprise_name,
        profile_type=bundle["profile_type"],
    )
    return asdict(profile) if profile is not None else {}


def profile_rows(database: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "case_id": profile.case_id,
            "enterprise_name": profile.enterprise_name,
            "profile_type": profile.profile_type,
            "review_status": profile.review_status,
            "items": len(profile.items),
            "relations": len(profile.relations),
        }
        for profile in ProfileRepository(database).list()
    ]


def profile_detail(database: str | Path, profile_id: str) -> dict[str, Any] | None:
    profile = ProfileRepository(database).get(profile_id)
    return asdict(profile) if profile is not None else None


def profile_visual_card(
    database: str | Path,
    profile_id: str,
    *,
    role: str | None = "senior_business",
) -> dict[str, Any] | None:
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        return None
    profile = filter_profile_for_role(profile, role)
    evidence_repository = EvidenceRepository(database)
    evidence_ids = {
        reference.evidence_unit_id
        for item in profile.items
        for reference in item.evidence_refs
    }
    evidence_by_id = {
        evidence_id: unit
        for evidence_id in evidence_ids
        if (unit := evidence_repository.get(evidence_id)) is not None
    }
    card = build_enterprise_visual_card(profile, evidence_by_id=evidence_by_id)
    for saved in ProfileTopicAnalysisRepository(database).list_for_profile(profile_id):
        if saved["status"] != "completed":
            continue
        if not can_run_profile_dimension(role, saved["dimension_id"]):
            continue
        card = apply_topic_analysis(
            card,
            TopicAnalysisRun(
                dimension_id=saved["dimension_id"],
                status=saved["status"],
                result=saved["result"],
                api_meta=tuple(saved["api_meta"]),
            ),
        )
    return card.to_dict()


def run_profile_topic_analysis(
    *,
    database: str | Path,
    profile_id: str,
    dimension_id: str,
    max_model_calls: int = 6,
    max_topic_reads: int = 12,
    max_facts_per_read: int = 30,
    max_tokens: int = 18000,
    role: str | None = "senior_business",
) -> dict[str, Any]:
    """对已审核企业画像的一个领域执行主题分析，返回待查看结果。"""
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        raise ValueError("未找到企业画像。")
    if not can_run_profile_dimension(role, dimension_id):
        raise PermissionError(f"当前身份无权生成画像方向：{dimension_id}")
    profile = filter_profile_for_role(profile, role)
    evidence_repository = EvidenceRepository(database)
    evidence_ids = {
        ref.evidence_unit_id
        for item in profile.items
        if item.review_status != "rejected"
        for ref in item.evidence_refs
    }
    evidence_by_id = {
        evidence_id: unit
        for evidence_id in evidence_ids
        if (unit := evidence_repository.get(evidence_id)) is not None
    }
    card = build_enterprise_visual_card(profile, evidence_by_id=evidence_by_id)
    settings = get_settings()
    config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        max_tokens=max_tokens,
        max_retries=2,
    )
    workflow = ControlledReactTopicAnalysisWorkflow(model_factory=build_deepseek_chat_model)
    run = workflow.run(
        card=card,
        dimension_id=dimension_id,
        config=config,
        limits=TopicAnalysisLimits(
            max_model_calls=max_model_calls,
            max_topic_reads=max_topic_reads,
            max_facts_per_read=max_facts_per_read,
        ),
    )
    if run.status == "completed" and run.result is not None:
        ProfileTopicAnalysisRepository(database).save(
            profile_id=profile_id,
            dimension_id=dimension_id,
            result=run.result,
            status=run.status,
            model=config.model,
            api_meta=run.api_meta,
            react_trace=[asdict(entry) for entry in run.react_trace],
        )
    analyzed_card = apply_topic_analysis(card, run)
    return {
        "run": run.to_dict(),
        "card": analyzed_card.to_dict(),
    }


__all__ = [
    "approve_profile_review",
    "load_profile_review",
    "profile_detail",
    "profile_rows",
    "profile_visual_card",
    "run_domain_investigation",
    "run_profile_topic_analysis",
    "run_react_domain_investigation",
    "run_react_profile_investigation",
]
