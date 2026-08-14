"""科技型企业 V5 页面使用的轻量应用服务。"""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.evidence import EvidenceRepository
from src.evidence import EvidenceQueryService
from src.case_analysis import (
    HistoricalCaseAnalysisRepository,
    approve_historical_case_analysis,
    generate_historical_case_analysis,
)
from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig
from src.industry import (
    ControlledReactIndustryWorkflow,
    IndustryReactLimits,
    IndustryProfileRepository,
    approve_industry_profile,
    industry_scope_id,
)
from src.approval import (
    ApprovalPointDefinition,
    ApprovalRepository,
    ComparableMetricDefinition,
    GUIDELINE_SECTION_DEFINITIONS,
    MetricProfileFieldBinding,
    PeerCohort,
    approve_composite_approval_report,
    approve_domain_approval_report,
    build_domain_approval_context,
    build_direction_comparison_card,
    build_guideline_metric_comparisons,
    build_guideline_section_context,
    composite_approval_report_to_markdown,
    direction_ranking_to_markdown,
    domain_approval_report_to_markdown,
    generate_direction_ranking,
    generate_composite_approval_report,
    generate_domain_approval_report,
    generate_guideline_section_report,
    generate_overall_assessment,
    build_overall_assessment_package,
    overall_assessment_to_markdown,
    approve_overall_assessment,
    approve_direction_ranking,
    build_metric_value_candidates,
)
from src.approval.guideline_definitions import (
    GUIDELINE_SECTIONS_BY_ID,
    get_guideline_point_definitions,
)
from src.profiles import (
    ComparisonCardRepository,
    ComparisonCardSimilarityService,
    ProfileRepository,
    approve_comparison_card,
    aggregate_profile_run,
    finalize_and_save_profile_review,
    generate_comparison_card,
    build_v5_review_report,
    build_enterprise_visual_card,
    compare_profile_candidates,
    generate_core_risk_judgment,
)
from src.profiles.material_context import build_profile_material_context
from src.profiles.models import (
    CurrentEnterpriseProfile,
    EvidenceReference,
    HistoricalEnterpriseProfile,
)
from src.profiles.current_workflow import CurrentProfileWorkflow
from src.profiles.detailed_comparison import DetailedComparisonRun
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
from src.sources import ingest_source


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _material_context(database: str | Path, profile) -> dict[str, Any]:
    sources = EvidenceRepository(database).list_sources(case_id=profile.case_id)
    return build_profile_material_context(profile, sources)


def ingest_uploaded_source(
    *,
    database: str | Path,
    case_id: str,
    upload_root: str | Path,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    target = Path(upload_root) / case_id / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    source, units = ingest_source(target, case_id=case_id)
    repository = EvidenceRepository(database)
    repository.save_source(source)
    repository.save_units(list(units))
    return {"source_id": source.source_id, "path": str(target), "evidence_units": len(units)}


def source_rows(database: str | Path, case_id: str = "") -> list[dict[str, Any]]:
    repository = EvidenceRepository(database)
    sources = repository.list_sources(case_id=case_id or None)
    return [
        {
            "case_id": source.case_id,
            "source_id": source.source_id,
            "type": source.source_type,
            "title": source.title,
            "evidence_units": len(repository.list_units(source_id=source.source_id)),
            "path": source.path,
        }
        for source in sources
    ]


def ingest_industry_source(
    *,
    database: str | Path,
    industry_id: str,
    industry_name: str,
    upload_root: str | Path,
    filename: str,
    content: bytes,
    source_date: str | None = None,
) -> dict[str, Any]:
    scope_id = industry_scope_id(industry_id)
    target = Path(upload_root) / "industry" / industry_id / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    source, units = ingest_source(
        target,
        case_id=scope_id,
        source_date=source_date,
    )
    source = replace(
        source,
        metadata={
            "material_role": "industry_report",
            "industry_id": industry_id,
            "industry_name": industry_name,
        },
    )
    repository = EvidenceRepository(database)
    repository.save_source(source)
    repository.save_units(list(units))
    return {
        "source_id": source.source_id,
        "industry_id": industry_id,
        "path": str(target),
        "evidence_units": len(units),
    }


def industry_source_rows(
    database: str | Path,
    industry_id: str = "",
) -> list[dict[str, Any]]:
    repository = EvidenceRepository(database)
    sources = repository.list_sources(
        case_id=industry_scope_id(industry_id) if industry_id.strip() else None
    )
    return [
        {
            "source_id": source.source_id,
            "industry_id": source.metadata.get("industry_id"),
            "industry_name": source.metadata.get("industry_name"),
            "title": source.title,
            "source_date": source.source_date,
            "evidence_units": len(repository.list_units(source_id=source.source_id)),
            "path": source.path,
        }
        for source in sources
        if source.metadata.get("material_role") == "industry_report"
    ]


def generate_industry_profile_review(
    *,
    database: str | Path,
    profile_id: str,
    industry_id: str,
    industry_name: str,
    max_model_calls: int = 8,
    max_search_calls: int = 10,
    max_read_calls: int = 10,
    max_read_units: int = 36,
    max_catalog_items: int = 16,
    max_tokens: int = 24000,
    max_retries: int = 2,
) -> dict[str, Any]:
    evidence_service = EvidenceQueryService(EvidenceRepository(database))
    settings = get_settings()
    run = ControlledReactIndustryWorkflow(evidence_service).run(
        profile_id=profile_id,
        industry_id=industry_id,
        industry_name=industry_name,
        react_config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        extraction_config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        limits=IndustryReactLimits(
            max_model_calls=max_model_calls,
            max_search_calls=max_search_calls,
            max_read_calls=max_read_calls,
            max_read_units=max_read_units,
            max_catalog_items=max_catalog_items,
        ),
        guide_text=(
            PROJECT_ROOT / "prompts" / "科技型企业行业背景画像生成协议_V1.md"
        ).read_text(encoding="utf-8"),
    )
    if run.generation is not None:
        IndustryProfileRepository(database).save(run.generation.profile)
    return run.to_dict()


def approve_industry_profile_review(
    *,
    database: str | Path,
    profile_id: str,
) -> dict[str, Any]:
    repository = IndustryProfileRepository(database)
    profile = repository.get(profile_id)
    if profile is None:
        raise ValueError(f"IndustryBackgroundProfile 不存在：{profile_id}")
    approved = approve_industry_profile(profile)
    repository.save(approved)
    return approved.to_dict()


def industry_profile_rows(database: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "industry_id": profile.industry_id,
            "industry_name": profile.industry_name,
            "review_status": profile.review_status,
            "insights": len(profile.insights),
            "sources": len(profile.source_ids),
        }
        for profile in IndustryProfileRepository(database).list()
    ]


def industry_profile_detail(
    database: str | Path,
    profile_id: str,
) -> dict[str, Any] | None:
    profile = IndustryProfileRepository(database).get(profile_id)
    return profile.to_dict() if profile is not None else None


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
) -> dict[str, Any]:
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
    guide_text = (PROJECT_ROOT / "prompts" / "科技型企业企业画像抽取协议_V1.md").read_text(
        encoding="utf-8"
    )
    common = {
        "case_id": case_id,
        "selection_config": selection_config,
        "extraction_config": extraction_config,
        "domains": domains,
        "max_evidence_per_domain": max_evidence_per_domain,
        "max_selected_evidence_per_domain": max_selected_evidence_per_domain,
        "guide_text": guide_text,
    }
    if profile_type == "historical":
        result = HistoricalProfileWorkflow(evidence_service).run(**common)
    elif profile_type == "current":
        result = CurrentProfileWorkflow(evidence_service).run(query=query, **common)
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
) -> dict[str, Any]:
    """执行当前企业单领域受控 ReAct 调查。"""
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
    workflow = ControlledReactProfileWorkflow(
        EvidenceQueryService(EvidenceRepository(database))
    )
    guide_text = (PROJECT_ROOT / "prompts" / "科技型企业企业画像抽取协议_V1.md").read_text(
        encoding="utf-8"
    )
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
        guide_text=guide_text,
    )
    return asdict(result)


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


def profile_visual_card(database: str | Path, profile_id: str) -> dict[str, Any] | None:
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        return None
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
) -> dict[str, Any]:
    """对已审核企业画像的一个领域执行主题分析，返回待查看结果。"""
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        raise ValueError("未找到企业画像。")
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
    workflow = ControlledReactTopicAnalysisWorkflow(
        model_factory=build_deepseek_chat_model,
    )
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


def generate_domain_approval_review(
    *,
    database: str | Path,
    report_id: str,
    cohort_id: str,
    profile_id: str,
    industry_profile_id: str,
    domain_id: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    cohort = repository.get_cohort(cohort_id)
    profile = ProfileRepository(database).get(profile_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if cohort is None or profile is None or industry_profile is None:
        raise ValueError("peer cohort, enterprise profile, or industry profile was not found")
    context = build_domain_approval_context(
        cohort,
        profile,
        industry_profile,
        domain_id,
        tuple(repository.list_metric_definitions(domain_id)),
        tuple(repository.list_cohort_metric_values(cohort_id)),
    )
    report = generate_domain_approval_report(
        report_id,
        context,
        tuple(repository.list_approval_point_definitions(domain_id)),
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
    )
    repository.save_domain_report(report)
    return {"report": asdict(report), "report_markdown": domain_approval_report_to_markdown(report)}


def approve_domain_approval_review(
    *, database: str | Path, report_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    report = repository.get_domain_report(report_id)
    if report is None:
        raise ValueError("domain approval report was not found")
    approved = approve_domain_approval_report(report)
    repository.save_domain_report(approved)
    return {"report": asdict(approved), "report_markdown": domain_approval_report_to_markdown(approved)}


def domain_approval_report_detail(
    database: str | Path, report_id: str
) -> dict[str, Any] | None:
    report = ApprovalRepository(database).get_domain_report(report_id)
    if report is None:
        return None
    metric_names = {
        definition.metric_id: definition.name
        for definition in ApprovalRepository(database).list_metric_definitions()
    }
    return {
        "report": asdict(report),
        "report_markdown": domain_approval_report_to_markdown(report, metric_names),
    }


def guideline_section_rows() -> list[dict[str, Any]]:
    """返回授信审批指引方向，供页面按固定顺序展示。"""
    return [
        {
            "section_id": section.section_id,
            "title": section.title,
            "point_ids": list(section.point_ids),
            "ranking_enabled": section.ranking_enabled,
        }
        for section in GUIDELINE_SECTION_DEFINITIONS
    ]


def generate_guideline_section_review(
    *,
    database: str | Path,
    report_id: str,
    cohort_id: str,
    profile_id: str,
    industry_profile_id: str,
    section_id: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> dict[str, Any]:
    """按授信指引方向生成一份跨画像领域的单企业审批报告。"""
    repository = ApprovalRepository(database)
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    cohort = repository.get_cohort(cohort_id)
    profile = ProfileRepository(database).get(profile_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if section is None:
        raise ValueError(f"guideline section was not found: {section_id}")
    if cohort is None or profile is None or industry_profile is None:
        raise ValueError("peer cohort, enterprise profile, or industry profile was not found")
    point_definitions = get_guideline_point_definitions(section_id)
    metric_ids = tuple(
        metric_id
        for point in point_definitions
        for metric_id in point.metric_ids
    )
    metric_comparisons = build_guideline_metric_comparisons(
        cohort,
        profile.case_id,
        metric_ids,
        tuple(repository.list_metric_definitions()),
        tuple(repository.list_cohort_metric_values(cohort_id)),
    )
    context = build_guideline_section_context(
        cohort,
        profile,
        industry_profile,
        section,
        metric_comparisons=metric_comparisons,
    )
    report = generate_guideline_section_report(
        report_id,
        context,
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
    )
    repository.save_domain_report(report)
    return {
        "section": {
            "section_id": section.section_id,
            "title": section.title,
        },
        "report": asdict(report),
        "report_markdown": domain_approval_report_to_markdown(report),
    }


def generate_direction_ranking_review(
    *,
    database: str | Path,
    cohort_id: str,
    industry_profile_id: str,
    section_id: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> dict[str, Any]:
    """汇总同一方向的已批准报告，生成多企业方向排名。"""
    repository = ApprovalRepository(database)
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    cohort = repository.get_cohort(cohort_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if section is None:
        raise ValueError(f"guideline section was not found: {section_id}")
    if not section.ranking_enabled:
        raise ValueError(f"guideline section does not support ranking: {section_id}")
    if cohort is None or industry_profile is None:
        raise ValueError("peer cohort or industry profile was not found")
    reports = tuple(
        repository.list_domain_reports(
            cohort_id=cohort_id,
            domain_id=section_id,
            review_status="approved",
        )
    )
    reports_by_case = {report.case_id: report for report in reports}
    if len(reports_by_case) != len(reports):
        raise ValueError("each cohort company needs exactly one approved report for this section")
    if set(reports_by_case) != set(cohort.company_case_ids):
        raise ValueError("all cohort companies need an approved report for this section")
    point_definitions = get_guideline_point_definitions(section_id)
    metric_ids = tuple(metric_id for point in point_definitions for metric_id in point.metric_ids)
    profiles = ProfileRepository(database)
    metric_definitions = tuple(repository.list_metric_definitions())
    metric_values = tuple(repository.list_cohort_metric_values(cohort_id))
    cards = []
    for case_id in cohort.company_case_ids:
        profile_rows = profiles.list(
            case_id=case_id,
            profile_type="current",
            review_status="approved",
        )
        if len(profile_rows) != 1:
            raise ValueError(f"expected one approved current profile for {case_id}")
        profile = profile_rows[0]
        metric_comparisons = build_guideline_metric_comparisons(
            cohort,
            case_id,
            metric_ids,
            metric_definitions,
            metric_values,
        )
        context = build_guideline_section_context(
            cohort,
            profile,
            industry_profile,
            section,
            metric_comparisons=metric_comparisons,
        )
        cards.append(build_direction_comparison_card(reports_by_case[case_id], context))
    result = generate_direction_ranking(
        section,
        tuple(cards),
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
    )
    repository.save_direction_ranking(result)
    return {
        "ranking": asdict(result),
        "ranking_markdown": direction_ranking_to_markdown(result),
    }


def approve_direction_ranking_review(
    *, database: str | Path, cohort_id: str, section_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    result = repository.get_direction_ranking(cohort_id, section_id)
    if result is None:
        raise ValueError("direction ranking was not found")
    approved = approve_direction_ranking(result)
    repository.save_direction_ranking(approved)
    return {
        "ranking": asdict(approved),
        "ranking_markdown": direction_ranking_to_markdown(approved),
    }


def direction_ranking_detail(
    database: str | Path, cohort_id: str, section_id: str
) -> dict[str, Any] | None:
    result = ApprovalRepository(database).get_direction_ranking(cohort_id, section_id)
    if result is None:
        return None
    return {
        "ranking": asdict(result),
        "ranking_markdown": direction_ranking_to_markdown(result),
    }


def direction_ranking_basis_detail(
    *,
    database: str | Path,
    cohort_id: str,
    industry_profile_id: str,
    section_id: str,
) -> dict[str, Any] | None:
    """重建已保存方向排名实际使用的比较卡，供页面审阅，不调用模型。"""
    repository = ApprovalRepository(database)
    ranking = repository.get_direction_ranking(cohort_id, section_id)
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    cohort = repository.get_cohort(cohort_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if ranking is None:
        return None
    if section is None or cohort is None or industry_profile is None:
        raise ValueError("guideline section, peer cohort, or industry profile was not found")

    reports = tuple(
        repository.get_domain_report(report_id)
        for report_id in ranking.source_section_report_ids
    )
    if any(report is None for report in reports):
        raise ValueError("source section report was not found")
    reports_by_case = {report.case_id: report for report in reports if report is not None}
    if set(reports_by_case) != set(cohort.company_case_ids):
        raise ValueError("ranking source reports do not cover the cohort exactly once")

    point_definitions = get_guideline_point_definitions(section_id)
    metric_ids = tuple(metric_id for point in point_definitions for metric_id in point.metric_ids)
    profiles = ProfileRepository(database)
    metric_definitions = tuple(repository.list_metric_definitions())
    metric_values = tuple(repository.list_cohort_metric_values(cohort_id))
    cards: list[dict[str, Any]] = []
    for case_id in cohort.company_case_ids:
        profile_rows = profiles.list(
            case_id=case_id,
            profile_type="current",
            review_status="approved",
        )
        if len(profile_rows) != 1:
            raise ValueError(f"expected one approved current profile for {case_id}")
        profile = profile_rows[0]
        context = build_guideline_section_context(
            cohort,
            profile,
            industry_profile,
            section,
            metric_comparisons=build_guideline_metric_comparisons(
                cohort,
                case_id,
                metric_ids,
                metric_definitions,
                metric_values,
            ),
        )
        report = reports_by_case[case_id]
        card = build_direction_comparison_card(
            replace(report, review_status="approved"), context
        )
        cards.append(
            {
                "case_id": case_id,
                "enterprise_name": profile.enterprise_name,
                "source_section_report_id": report.report_id,
                "source_report_review_status": report.review_status,
                "card": card.to_payload(),
            }
        )
    return {
        "section": {
            "section_id": section.section_id,
            "title": section.title,
            "comparison_criteria": list(section.comparison_criteria),
        },
        "cohort": {
            "cohort_id": cohort.cohort_id,
            "fiscal_period": cohort.fiscal_period,
            "selection_rule": cohort.selection_rule,
        },
        "ranking": asdict(ranking),
        "cards": cards,
    }


def generate_enterprise_overall_assessment_review(
    *,
    database: str | Path,
    assessment_id: str,
    cohort_id: str,
    profile_id: str,
) -> dict[str, Any]:
    """基于 11 个方向报告和方向排名生成 A-D 综合评定。"""
    repository = ApprovalRepository(database)
    cohort = repository.get_cohort(cohort_id)
    profile = ProfileRepository(database).get(profile_id)
    if cohort is None or profile is None:
        raise ValueError("peer cohort or enterprise profile was not found")
    if profile.case_id not in cohort.company_case_ids:
        raise ValueError("enterprise profile does not belong to the peer cohort")
    is_experimental = cohort_id.endswith("_test")
    expected_status = "pending" if is_experimental else "approved"
    reports = tuple(
        repository.list_domain_reports(
            cohort_id=cohort_id,
            case_id=profile.case_id,
            review_status=expected_status,
        )
    )
    rankings = tuple(
        repository.list_direction_rankings(cohort_id, review_status=expected_status)
    )
    reporting_periods = tuple(
        sorted({item.reporting_period for item in profile.items if item.reporting_period})
    )
    package = build_overall_assessment_package(
        enterprise_name=profile.enterprise_name,
        profile_reporting_periods=reporting_periods,
        cohort_name=cohort.cohort_name,
        cohort_fiscal_period=cohort.fiscal_period,
        cohort_selection_rule=cohort.selection_rule,
        reports=reports,
        rankings=rankings,
        is_experimental=is_experimental,
    )
    assessment = generate_overall_assessment(
        assessment_id,
        package,
        reports,
        rankings,
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=30000,
            max_retries=2,
        ),
    )
    repository.save_overall_assessment(assessment)
    return {
        "assessment": asdict(assessment),
        "assessment_package": package,
        "assessment_markdown": overall_assessment_to_markdown(assessment),
    }


def enterprise_overall_assessment_detail(
    database: str | Path, assessment_id: str
) -> dict[str, Any] | None:
    assessment = ApprovalRepository(database).get_overall_assessment(assessment_id)
    if assessment is None:
        return None
    return {
        "assessment": asdict(assessment),
        "assessment_markdown": overall_assessment_to_markdown(assessment),
    }


def approve_enterprise_overall_assessment_review(
    *, database: str | Path, assessment_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    assessment = repository.get_overall_assessment(assessment_id)
    if assessment is None:
        raise ValueError("overall assessment was not found")
    approved = approve_overall_assessment(assessment)
    repository.save_overall_assessment(approved)
    return {
        "assessment": asdict(approved),
        "assessment_markdown": overall_assessment_to_markdown(approved),
    }


def generate_composite_approval_review(
    *,
    database: str | Path,
    report_id: str,
    cohort_id: str,
    case_id: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    reports = tuple(
        repository.list_domain_reports(
            cohort_id=cohort_id,
            case_id=case_id,
            review_status="approved",
        )
    )
    guideline_reports = tuple(
        report for report in reports if report.domain_id in GUIDELINE_SECTIONS_BY_ID
    )
    if guideline_reports:
        expected_sections = set(GUIDELINE_SECTIONS_BY_ID)
        actual_sections = {report.domain_id for report in guideline_reports}
        if actual_sections != expected_sections or len(guideline_reports) != len(expected_sections):
            missing = sorted(expected_sections - actual_sections)
            if missing:
                detail = "缺少：" + "、".join(missing)
            else:
                detail = "每个方向必须且只能有一份已批准报告"
            raise ValueError("授信指引综合报告需要11个方向的已批准报告，" + detail)
        reports = guideline_reports
    direction_rankings = tuple(
        ranking
        for ranking in repository.list_direction_rankings(cohort_id, review_status="approved")
        if not guideline_reports or ranking.section_id in {report.domain_id for report in reports}
    )
    report = generate_composite_approval_report(
        report_id,
        reports,
        direction_rankings=direction_rankings,
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
    )
    repository.save_composite_report(report)
    return {"report": asdict(report), "report_markdown": composite_approval_report_to_markdown(report)}


def approve_composite_approval_review(
    *, database: str | Path, report_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    report = repository.get_composite_report(report_id)
    if report is None:
        raise ValueError("composite approval report was not found")
    approved = approve_composite_approval_report(report)
    repository.save_composite_report(approved)
    return {"report": asdict(approved), "report_markdown": composite_approval_report_to_markdown(approved)}


def composite_approval_report_detail(
    database: str | Path, report_id: str
) -> dict[str, Any] | None:
    report = ApprovalRepository(database).get_composite_report(report_id)
    if report is None:
        return None
    return {"report": asdict(report), "report_markdown": composite_approval_report_to_markdown(report)}


def create_peer_cohort(
    *,
    database: str | Path,
    cohort_id: str,
    industry_id: str,
    cohort_name: str,
    fiscal_period: str,
    company_case_ids: tuple[str, ...],
    selection_rule: str,
    source_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    cohort = PeerCohort(
        cohort_id=cohort_id,
        industry_id=industry_id,
        cohort_name=cohort_name,
        fiscal_period=fiscal_period,
        company_case_ids=company_case_ids,
        selection_rule=selection_rule,
        source_ids=source_ids,
    )
    ApprovalRepository(database).save_cohort(cohort)
    return asdict(cohort)


def approve_peer_cohort(*, database: str | Path, cohort_id: str) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    cohort = repository.get_cohort(cohort_id)
    if cohort is None or cohort.review_status != "pending":
        raise ValueError("pending peer cohort was not found")
    approved = replace(cohort, review_status="approved")
    repository.save_cohort(approved)
    return asdict(approved)


def create_comparable_metric_definition(
    *,
    database: str | Path,
    metric_id: str,
    approval_direction_id: str,
    approval_point_id: str,
    name: str,
    comparison_direction: str,
    unit: str,
    value_scope: str,
    section_id: str,
    field_id: str,
) -> dict[str, Any]:
    definition = ComparableMetricDefinition(
        metric_id=metric_id,
        approval_direction_id=approval_direction_id,
        approval_point_id=approval_point_id,
        name=name,
        comparison_direction=comparison_direction,
        unit=unit,
        value_scope=value_scope,
    )
    repository = ApprovalRepository(database)
    repository.save_metric_definition(definition)
    repository.save_metric_binding(
        MetricProfileFieldBinding(
            metric_id=metric_id,
            section_id=section_id,
            field_id=field_id,
        )
    )
    return asdict(definition)


def approve_comparable_metric_definition(
    *, database: str | Path, metric_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    definition = repository.get_metric_definition(metric_id)
    if definition is None or definition.review_status != "pending":
        raise ValueError("pending comparable metric definition was not found")
    approved = replace(definition, review_status="approved")
    repository.save_metric_definition(approved)
    return asdict(approved)


def create_approval_point_definition(
    *,
    database: str | Path,
    approval_point_id: str,
    approval_direction_id: str,
    title: str,
    enterprise_field_ids: tuple[str, ...],
    metric_ids: tuple[str, ...],
    industry_dimension_ids: tuple[str, ...],
) -> dict[str, Any]:
    definition = ApprovalPointDefinition(
        approval_point_id=approval_point_id,
        approval_direction_id=approval_direction_id,
        title=title,
        enterprise_field_ids=enterprise_field_ids,
        metric_ids=metric_ids,
        industry_dimension_ids=industry_dimension_ids,
    )
    ApprovalRepository(database).save_approval_point_definition(definition)
    return asdict(definition)


def approve_approval_point_definition(
    *, database: str | Path, approval_point_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    definition = repository.get_approval_point_definition(approval_point_id)
    if definition is None or definition.review_status != "pending":
        raise ValueError("pending approval point definition was not found")
    approved = replace(definition, review_status="approved")
    repository.save_approval_point_definition(approved)
    return asdict(approved)


def metric_value_candidates(
    *, database: str | Path, cohort_id: str, profile_id: str, metric_id: str
) -> list[dict[str, Any]]:
    repository = ApprovalRepository(database)
    cohort = repository.get_cohort(cohort_id)
    definition = repository.get_metric_definition(metric_id)
    binding = repository.get_metric_binding(metric_id)
    profile = ProfileRepository(database).get(profile_id)
    if cohort is None or definition is None or binding is None or profile is None:
        raise ValueError("cohort, metric definition, binding, or profile was not found")
    return [
        asdict(candidate)
        for candidate in build_metric_value_candidates(cohort, definition, binding, profile)
    ]


def approve_metric_value_candidate(
    *,
    database: str | Path,
    cohort_id: str,
    profile_id: str,
    metric_id: str,
    source_item_id: str,
) -> dict[str, Any]:
    candidates = metric_value_candidates(
        database=database,
        cohort_id=cohort_id,
        profile_id=profile_id,
        metric_id=metric_id,
    )
    selected = next(
        (candidate for candidate in candidates if candidate["source_item_id"] == source_item_id),
        None,
    )
    if selected is None:
        raise ValueError("selected metric candidate was not found")
    from src.approval.models import ComparableMetricValue

    approved = ComparableMetricValue(
        cohort_id=selected["cohort_id"],
        metric_id=selected["metric_id"],
        case_id=selected["case_id"],
        value=selected["value"],
        reporting_period=selected["reporting_period"],
        unit=selected["unit"],
        source_profile_id=selected["source_profile_id"],
        source_item_id=selected["source_item_id"],
        evidence_refs=tuple(
            EvidenceReference(**reference) for reference in selected["evidence_refs"]
        ),
        review_status="approved",
    )
    ApprovalRepository(database).save_metric_value(approved)
    return asdict(approved)


def approval_workspace_rows(database: str | Path) -> dict[str, list[dict[str, Any]]]:
    repository = ApprovalRepository(database)
    return {
        "cohorts": [asdict(cohort) for cohort in repository.list_cohorts()],
        "metrics": [asdict(item) for item in repository.list_metric_definitions()],
        "domain_reports": [asdict(item) for item in repository.list_domain_reports()],
        "composite_reports": [asdict(item) for item in repository.list_composite_reports()],
        "overall_assessments": [
            asdict(item) for item in repository.list_overall_assessments()
        ],
    }


def historical_case_analysis_rows(database: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "analysis_id": item.analysis_id,
            "profile_id": item.profile_id,
            "enterprise_name": item.enterprise_name,
            "outcome_status": item.outcome_status,
            "review_status": item.review_status,
            "factors": len(item.factors),
            "current": HistoricalCaseAnalysisRepository(database).is_current(item, profile),
        }
        for item in HistoricalCaseAnalysisRepository(database).list()
        if (profile := ProfileRepository(database).get(item.profile_id)) is not None
    ]


def historical_case_analysis_detail(database: str | Path, analysis_id: str) -> dict[str, Any] | None:
    item = HistoricalCaseAnalysisRepository(database).get(analysis_id)
    if item is None:
        return None
    return {"human": item.to_human_dict(), "human_markdown": item.to_markdown(), "debug": item.to_dict()}


def generate_historical_case_analysis_review(*, database: str | Path, profile_id: str, max_tokens: int = 8000, max_retries: int = 2) -> dict[str, Any]:
    profile = ProfileRepository(database).get(profile_id)
    if not isinstance(profile, HistoricalEnterpriseProfile):
        raise ValueError("未找到匹配的 historical EnterpriseProfile。")
    settings = get_settings()
    config = GenerationConfig(model=settings.model, mode="thinking", reasoning_effort="high", max_tokens=max_tokens, max_retries=max_retries)
    guide = (PROJECT_ROOT / "prompts" / "科技型企业历史案例分析协议_V1.md").read_text(encoding="utf-8")
    analysis = generate_historical_case_analysis(
        profile,
        config=config,
        guide_text=guide,
        material_context=_material_context(database, profile),
    )
    HistoricalCaseAnalysisRepository(database).save(analysis)
    return {"human": analysis.to_human_dict(), "human_markdown": analysis.to_markdown(), "debug": analysis.to_dict()}


def approve_historical_case_analysis_review(*, database: str | Path, analysis_id: str) -> dict[str, Any]:
    repository = HistoricalCaseAnalysisRepository(database)
    analysis = repository.get(analysis_id)
    if analysis is None:
        raise ValueError(f"HistoricalCaseAnalysis 不存在：{analysis_id}")
    profile = ProfileRepository(database).get(analysis.profile_id)
    if profile is None or not repository.is_current(analysis, profile):
        raise ValueError("案例分析对应的企业画像已经变化，请重新生成后再审核。")
    approved = approve_historical_case_analysis(analysis)
    repository.save(approved)
    return {"human": approved.to_human_dict(), "human_markdown": approved.to_markdown(), "debug": approved.to_dict()}


def comparison_card_rows(database: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "card_id": card.card_id,
            "profile_id": card.profile_id,
            "enterprise_name": card.enterprise_name,
            "profile_type": card.profile_type,
            "review_status": card.review_status,
            "dimensions": len(card.dimensions),
        }
        for card in ComparisonCardRepository(database).list()
    ]


def generate_profile_comparison_card(
    *,
    database: str | Path,
    profile_id: str,
    approve: bool = False,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> dict[str, Any]:
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        raise ValueError(f"EnterpriseProfile 不存在：{profile_id}")
    settings = get_settings()
    config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=max_tokens,
        max_retries=max_retries,
    )
    guide_text = (PROJECT_ROOT / "prompts" / "科技型企业比较卡生成协议_V1.md").read_text(
        encoding="utf-8"
    )
    card, api_meta = generate_comparison_card(
        profile,
        config=config,
        guide_text=guide_text,
        material_context=_material_context(database, profile),
    )
    if approve:
        card = approve_comparison_card(card)
    ComparisonCardRepository(database).save(card)
    return {"comparison_card": card.to_dict(), "api_meta": api_meta}


def find_similar_profiles(
    database: str | Path,
    current_card_id: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    repository = ComparisonCardRepository(database)
    card = repository.get(current_card_id)
    if card is None:
        raise ValueError(f"ComparisonCard 不存在：{current_card_id}")
    return [
        match.to_dict()
        for match in ComparisonCardSimilarityService(repository).find_similar(card, limit=limit)
    ]


def run_detailed_review_report(
    *,
    database: str | Path,
    current_profile_id: str,
    current_card_id: str,
    limit: int = 5,
    max_tokens: int = 12000,
    max_retries: int = 2,
    industry_profile_id: str = "",
) -> dict[str, Any]:
    profile_repository = ProfileRepository(database)
    current = profile_repository.get(current_profile_id)
    if not isinstance(current, CurrentEnterpriseProfile):
        raise ValueError("未找到匹配的 current EnterpriseProfile。")
    card_repository = ComparisonCardRepository(database)
    current_card = card_repository.get(current_card_id)
    if current_card is None or current_card.profile_id != current.profile_id:
        raise ValueError("当前 ComparisonCard 不存在或与画像不匹配。")
    industry_profile = None
    if industry_profile_id:
        industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
        if industry_profile is None or industry_profile.review_status != "approved":
            raise ValueError("所选行业背景画像不存在或尚未批准。")
    matches = ComparisonCardSimilarityService(card_repository).find_similar(
        current_card, limit=limit
    )
    historical_profiles = tuple(
        profile
        for match in matches
        if isinstance(
            (profile := profile_repository.get(match.historical_profile_id)),
            HistoricalEnterpriseProfile,
        )
    )
    if not historical_profiles:
        comparison = DetailedComparisonRun(
            current_profile_id=current.profile_id,
            comparisons=(),
            api_meta={"skipped": True, "reason": "没有召回可用的 approved 历史画像。"},
        )
        settings = get_settings()
        risk_judgment = generate_core_risk_judgment(
            current,
            comparison,
            config=GenerationConfig(
                model=settings.model,
                mode="thinking",
                reasoning_effort="high",
                max_tokens=max_tokens,
                max_retries=max_retries,
            ),
            guide_text=(
                PROJECT_ROOT / "prompts" / "科技型企业核心风险判断协议_V1.md"
            ).read_text(encoding="utf-8"),
            industry_profile=industry_profile,
        )
        report = build_v5_review_report(current, comparison, risk_judgment)
        return {
            "detailed_comparison": comparison.to_dict(),
            "core_risk_judgment": risk_judgment.to_dict(),
            "report": report.to_dict(),
            "report_markdown": report.to_markdown(),
        }
    settings = get_settings()
    analysis_repository = HistoricalCaseAnalysisRepository(database)
    approved_case_analyses = {}
    for profile in historical_profiles:
        analysis = analysis_repository.get_by_profile(profile.profile_id, review_status="approved")
        if analysis is not None and analysis_repository.is_current(analysis, profile):
            approved_case_analyses[profile.profile_id] = analysis.to_human_dict()
    comparison = compare_profile_candidates(
        current,
        historical_profiles,
        matches,
        config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        guide_text=(
            PROJECT_ROOT / "prompts" / "科技型企业画像详细比较协议_V1.md"
        ).read_text(encoding="utf-8"),
        historical_case_analyses=approved_case_analyses,
        material_contexts={
            profile.profile_id: _material_context(database, profile)
            for profile in (current, *historical_profiles)
        },
    )
    risk_judgment = generate_core_risk_judgment(
        current,
        comparison,
        config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        guide_text=(
            PROJECT_ROOT / "prompts" / "科技型企业核心风险判断协议_V1.md"
        ).read_text(encoding="utf-8"),
        industry_profile=industry_profile,
    )
    report = build_v5_review_report(current, comparison, risk_judgment)
    return {
        "detailed_comparison": comparison.to_dict(),
        "core_risk_judgment": risk_judgment.to_dict(),
        "report": report.to_dict(),
        "report_markdown": report.to_markdown(),
    }
