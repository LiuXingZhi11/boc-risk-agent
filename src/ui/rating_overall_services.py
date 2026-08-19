"""综合客户风险评级、行动建议和组合报告页面服务。"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.approval import (
    ApprovalRepository,
    approve_composite_approval_report,
    approve_overall_assessment,
    build_overall_assessment_package,
    composite_approval_report_to_markdown,
    generate_composite_approval_report,
    generate_overall_assessment,
    overall_assessment_to_markdown,
)
from src.approval.action_recommendations import generate_action_recommendations
from src.approval.guideline_definitions import GUIDELINE_SECTIONS_BY_ID
from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig
from src.profiles import ProfileRepository

def generate_enterprise_overall_assessment_review(
    *,
    database: str | Path,
    assessment_id: str,
    cohort_id: str,
    profile_id: str,
) -> dict[str, Any]:
    """基于 11 个方向报告和方向排名生成客户风险评级报告。"""
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
    assessment = replace(
        assessment,
        verification_priorities=generate_action_recommendations(
            assessment,
            enterprise_name=profile.enterprise_name,
            config=GenerationConfig(
                model=get_settings().model,
                mode="thinking",
                reasoning_effort="high",
                max_tokens=30000,
                max_retries=1,
            ),
        ),
    )
    repository.save_overall_assessment(assessment)
    return {
        "assessment": asdict(assessment),
        "assessment_package": package,
        "assessment_markdown": overall_assessment_to_markdown(assessment),
    }


def generate_standalone_enterprise_overall_assessment_review(
    *,
    database: str | Path,
    assessment_id: str,
    profile_id: str,
) -> dict[str, Any]:
    """基于单家企业的 11 个方向报告生成客户风险评级，不要求同行排名。"""
    repository = ApprovalRepository(database)
    profile = ProfileRepository(database).get(profile_id)
    if profile is None:
        raise ValueError("enterprise profile was not found")
    reports = tuple(
        report
        for report in repository.list_domain_reports(case_id=profile.case_id)
        if report.cohort_id is None
    )
    reporting_periods = tuple(
        sorted({item.reporting_period for item in profile.items if item.reporting_period})
    )
    package = build_overall_assessment_package(
        enterprise_name=profile.enterprise_name,
        profile_reporting_periods=reporting_periods,
        cohort_name="单企业分析（未进行同行比较）",
        cohort_fiscal_period=None,
        cohort_selection_rule="未启用同行样本",
        reports=reports,
        rankings=(),
        is_experimental=False,
    )
    assessment = generate_overall_assessment(
        assessment_id,
        package,
        reports,
        (),
        config=GenerationConfig(
            model=get_settings().model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=30000,
            max_retries=2,
        ),
    )
    assessment = replace(
        assessment,
        verification_priorities=generate_action_recommendations(
            assessment,
            enterprise_name=profile.enterprise_name,
            config=GenerationConfig(
                model=get_settings().model,
                mode="thinking",
                reasoning_effort="high",
                max_tokens=30000,
                max_retries=1,
            ),
        ),
    )
    repository.save_overall_assessment(assessment)
    return {
        "assessment": asdict(assessment),
        "assessment_package": package,
        "assessment_markdown": overall_assessment_to_markdown(assessment),
    }


def generate_enterprise_action_recommendations(
    *,
    database: str | Path,
    assessment_id: str,
    profile_id: str,
) -> dict[str, Any]:
    """为已有客户风险评级报告补生成详细行动建议。"""
    repository = ApprovalRepository(database)
    assessment = repository.get_overall_assessment(assessment_id)
    profile = ProfileRepository(database).get(profile_id)
    if assessment is None or profile is None:
        raise ValueError("overall assessment or enterprise profile was not found")
    updated = replace(
        assessment,
        verification_priorities=generate_action_recommendations(
            assessment,
            enterprise_name=profile.enterprise_name,
            config=GenerationConfig(
                model=get_settings().model,
                mode="thinking",
                reasoning_effort="high",
                max_tokens=30000,
                max_retries=1,
            ),
        ),
    )
    repository.save_overall_assessment(updated)
    return {
        "assessment": asdict(updated),
        "assessment_markdown": overall_assessment_to_markdown(updated),
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



__all__ = [
    "approve_composite_approval_review",
    "approve_enterprise_overall_assessment_review",
    "composite_approval_report_detail",
    "enterprise_overall_assessment_detail",
    "generate_composite_approval_review",
    "generate_enterprise_action_recommendations",
    "generate_enterprise_overall_assessment_review",
    "generate_standalone_enterprise_overall_assessment_review",
]
