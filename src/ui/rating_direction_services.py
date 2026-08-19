"""风险评级分方向报告、审批点和同行排名页面服务。"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.approval import (
    ApprovalRepository,
    GUIDELINE_SECTION_DEFINITIONS,
    approve_direction_ranking,
    approve_domain_approval_report,
    build_direction_comparison_card,
    build_domain_approval_context,
    build_guideline_metric_comparisons,
    build_guideline_section_context,
    build_standalone_guideline_section_context,
    direction_ranking_to_markdown,
    domain_approval_report_to_markdown,
    generate_direction_ranking,
    generate_domain_approval_report,
    generate_guideline_section_report,
)
from src.approval.guideline_definitions import (
    GUIDELINE_SECTIONS_BY_ID,
    get_guideline_point_definitions,
)
from src.authorization import can_run_approval_section, filter_profile_for_role
from src.config.settings import get_settings
from src.industry import IndustryProfileRepository
from src.llm.generation_config import GenerationConfig
from src.profiles import ProfileRepository


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
    role: str | None = "senior_business",
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    cohort = repository.get_cohort(cohort_id)
    profile = ProfileRepository(database).get(profile_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if cohort is None or profile is None or industry_profile is None:
        raise ValueError("peer cohort, enterprise profile, or industry profile was not found")
    if not can_run_approval_section(role, domain_id):
        raise PermissionError(f"当前身份无权生成授信方向：{domain_id}")
    profile = filter_profile_for_role(profile, role)
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
    """返回风险评级指引方向，供页面按固定顺序展示。"""
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
    role: str | None = "senior_business",
) -> dict[str, Any]:
    """按风险评级指引方向生成一份跨画像领域的单企业报告。"""
    repository = ApprovalRepository(database)
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    cohort = repository.get_cohort(cohort_id)
    profile = ProfileRepository(database).get(profile_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if section is None:
        raise ValueError(f"guideline section was not found: {section_id}")
    if cohort is None or profile is None or industry_profile is None:
        raise ValueError("peer cohort, enterprise profile, or industry profile was not found")
    if not can_run_approval_section(role, section_id):
        raise PermissionError(f"当前身份无权生成授信方向：{section_id}")
    profile = filter_profile_for_role(profile, role)
    point_definitions = get_guideline_point_definitions(section_id)
    metric_ids = tuple(metric_id for point in point_definitions for metric_id in point.metric_ids)
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
        "section": {"section_id": section.section_id, "title": section.title},
        "report": asdict(report),
        "report_markdown": domain_approval_report_to_markdown(report),
    }


def generate_standalone_guideline_section_review(
    *,
    database: str | Path,
    report_id: str,
    profile_id: str,
    industry_profile_id: str,
    section_id: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
    role: str | None = "senior_business",
) -> dict[str, Any]:
    """不依赖同行样本，生成单企业风险评级方向报告。"""
    repository = ApprovalRepository(database)
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    profile = ProfileRepository(database).get(profile_id)
    industry_profile = IndustryProfileRepository(database).get(industry_profile_id)
    if section is None:
        raise ValueError(f"guideline section was not found: {section_id}")
    if profile is None or industry_profile is None:
        raise ValueError("enterprise profile or industry profile was not found")
    if not can_run_approval_section(role, section_id):
        raise PermissionError(f"当前身份无权生成风险评级方向：{section_id}")
    profile = filter_profile_for_role(profile, role)
    context = build_standalone_guideline_section_context(profile, industry_profile, section)
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
        "section": {"section_id": section.section_id, "title": section.title},
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
    role: str | None = "senior_business",
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
    if not can_run_approval_section(role, section_id):
        raise PermissionError(f"当前身份无权生成授信方向排名：{section_id}")
    reports = tuple(repository.list_domain_reports(cohort_id=cohort_id, domain_id=section_id, review_status="approved"))
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
        profile_rows = profiles.list(case_id=case_id, profile_type="current", review_status="approved")
        if len(profile_rows) != 1:
            raise ValueError(f"expected one approved current profile for {case_id}")
        profile = filter_profile_for_role(profile_rows[0], role)
        metric_comparisons = build_guideline_metric_comparisons(
            cohort, case_id, metric_ids, metric_definitions, metric_values
        )
        context = build_guideline_section_context(
            cohort, profile, industry_profile, section, metric_comparisons=metric_comparisons
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
    return {"ranking": asdict(result), "ranking_markdown": direction_ranking_to_markdown(result)}


def approve_direction_ranking_review(
    *, database: str | Path, cohort_id: str, section_id: str
) -> dict[str, Any]:
    repository = ApprovalRepository(database)
    result = repository.get_direction_ranking(cohort_id, section_id)
    if result is None:
        raise ValueError("direction ranking was not found")
    approved = approve_direction_ranking(result)
    repository.save_direction_ranking(approved)
    return {"ranking": asdict(approved), "ranking_markdown": direction_ranking_to_markdown(approved)}


def direction_ranking_detail(
    database: str | Path, cohort_id: str, section_id: str
) -> dict[str, Any] | None:
    result = ApprovalRepository(database).get_direction_ranking(cohort_id, section_id)
    if result is None:
        return None
    return {"ranking": asdict(result), "ranking_markdown": direction_ranking_to_markdown(result)}


def direction_ranking_basis_detail(
    *,
    database: str | Path,
    cohort_id: str,
    industry_profile_id: str,
    section_id: str,
    role: str | None = "senior_business",
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
    reports = tuple(repository.get_domain_report(report_id) for report_id in ranking.source_section_report_ids)
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
        profile_rows = profiles.list(case_id=case_id, profile_type="current", review_status="approved")
        if len(profile_rows) != 1:
            raise ValueError(f"expected one approved current profile for {case_id}")
        profile = filter_profile_for_role(profile_rows[0], role)
        context = build_guideline_section_context(
            cohort,
            profile,
            industry_profile,
            section,
            metric_comparisons=build_guideline_metric_comparisons(
                cohort, case_id, metric_ids, metric_definitions, metric_values
            ),
        )
        report = reports_by_case[case_id]
        card = build_direction_comparison_card(replace(report, review_status="approved"), context)
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


__all__ = [
    "approve_direction_ranking_review",
    "approve_domain_approval_review",
    "direction_ranking_basis_detail",
    "direction_ranking_detail",
    "domain_approval_report_detail",
    "generate_direction_ranking_review",
    "generate_domain_approval_review",
    "generate_guideline_section_review",
    "generate_standalone_guideline_section_review",
    "guideline_section_rows",
]
