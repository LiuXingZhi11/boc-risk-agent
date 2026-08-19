"""同行样本、指标和审批点配置页面服务。"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.approval import (
    ApprovalPointDefinition,
    ApprovalRepository,
    ComparableMetricDefinition,
    MetricProfileFieldBinding,
    PeerCohort,
    build_metric_value_candidates,
)
from src.profiles import ProfileRepository
from src.profiles.models import EvidenceReference

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


__all__ = [
    "approval_workspace_rows",
    "approve_approval_point_definition",
    "approve_comparable_metric_definition",
    "approve_metric_value_candidate",
    "approve_peer_cohort",
    "create_approval_point_definition",
    "create_comparable_metric_definition",
    "create_peer_cohort",
    "metric_value_candidates",
]
