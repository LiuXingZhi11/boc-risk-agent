"""分方向审批报告的结构化输入组装。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.industry.models import IndustryBackgroundProfile, IndustryInsight
from src.profiles.extraction import PROFILE_DOMAIN_FIELDS, PROFILE_DOMAINS
from src.profiles.models import EnterpriseProfile, EvidenceReference, ProfileItem

from .mappings import DOMAIN_INDUSTRY_DIMENSIONS
from .models import (
    ComparableMetricDefinition,
    ComparableMetricValue,
    PeerCohort,
    RankingResult,
)
from .ranking import rank_metric_values


@dataclass(frozen=True)
class MetricComparison:
    metric_id: str
    metric_name: str
    unit: str
    value_scope: str
    value: float
    ranking: RankingResult
    source_profile_id: str
    source_item_id: str
    evidence_refs: tuple[EvidenceReference, ...]


@dataclass(frozen=True)
class DomainApprovalContext:
    cohort_id: str
    case_id: str
    domain_id: str
    enterprise_profile_id: str
    industry_profile_id: str
    enterprise_items: tuple[ProfileItem, ...] = field(default_factory=tuple)
    industry_insights: tuple[IndustryInsight, ...] = field(default_factory=tuple)
    metric_comparisons: tuple[MetricComparison, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)


def build_domain_approval_context(
    cohort: PeerCohort,
    profile: EnterpriseProfile,
    industry_profile: IndustryBackgroundProfile,
    domain_id: str,
    metric_definitions: tuple[ComparableMetricDefinition, ...],
    metric_values: tuple[ComparableMetricValue, ...],
) -> DomainApprovalContext:
    """汇总一个企业领域已审核的事实、行业基准和样本内排名。"""
    _validate_context_inputs(cohort, profile, industry_profile, domain_id)
    enterprise_items = tuple(
        item
        for item in profile.items
        if item.review_status == "accepted"
        and item.field_id in PROFILE_DOMAIN_FIELDS[domain_id]
    )
    industry_insights = tuple(
        insight
        for insight in industry_profile.insights
        if insight.review_status == "accepted"
        and insight.dimension_id in DOMAIN_INDUSTRY_DIMENSIONS[domain_id]
    )
    metric_comparisons, metric_gaps = _build_metric_comparisons(
        cohort, profile.case_id, domain_id, metric_definitions, metric_values
    )
    information_gaps = list(metric_gaps)
    if not enterprise_items:
        information_gaps.append(f"No accepted enterprise facts for domain {domain_id}.")
    if not industry_insights:
        information_gaps.append(f"No accepted industry insights for domain {domain_id}.")
    return DomainApprovalContext(
        cohort_id=cohort.cohort_id,
        case_id=profile.case_id,
        domain_id=domain_id,
        enterprise_profile_id=profile.profile_id,
        industry_profile_id=industry_profile.profile_id,
        enterprise_items=enterprise_items,
        industry_insights=industry_insights,
        metric_comparisons=metric_comparisons,
        information_gaps=tuple(information_gaps),
    )


def _validate_context_inputs(
    cohort: PeerCohort,
    profile: EnterpriseProfile,
    industry_profile: IndustryBackgroundProfile,
    domain_id: str,
) -> None:
    if cohort.review_status != "approved":
        raise ValueError("an approval context requires an approved peer cohort")
    if profile.review_status != "approved":
        raise ValueError("an approval context requires an approved enterprise profile")
    if industry_profile.review_status != "approved":
        raise ValueError("an approval context requires an approved industry profile")
    if profile.case_id not in cohort.company_case_ids:
        raise ValueError("the enterprise profile must belong to the peer cohort")
    if industry_profile.industry_id != cohort.industry_id:
        raise ValueError("the industry profile must match the peer cohort industry")
    if domain_id not in PROFILE_DOMAINS:
        raise ValueError("domain_id must be a profile domain")


def _build_metric_comparisons(
    cohort: PeerCohort,
    case_id: str,
    domain_id: str,
    metric_definitions: tuple[ComparableMetricDefinition, ...],
    metric_values: tuple[ComparableMetricValue, ...],
) -> tuple[tuple[MetricComparison, ...], tuple[str, ...]]:
    comparisons: list[MetricComparison] = []
    information_gaps: list[str] = []
    for definition in metric_definitions:
        if definition.review_status != "approved" or definition.approval_direction_id != domain_id:
            continue
        values = tuple(
            value
            for value in metric_values
            if value.review_status == "approved"
            and value.cohort_id == cohort.cohort_id
            and value.metric_id == definition.metric_id
        )
        target_values = tuple(value for value in values if value.case_id == case_id)
        if len(values) < 2 or len(target_values) != 1:
            information_gaps.append(
                f"No comparable ranking is available for metric {definition.metric_id}."
            )
            continue
        rankings = rank_metric_values(cohort, definition, values)
        target_ranking = next(ranking for ranking in rankings if ranking.case_id == case_id)
        target_value = target_values[0]
        comparisons.append(
            MetricComparison(
                metric_id=definition.metric_id,
                metric_name=definition.name,
                unit=definition.unit,
                value_scope=definition.value_scope,
                value=target_value.value,
                ranking=target_ranking,
                source_profile_id=target_value.source_profile_id,
                source_item_id=target_value.source_item_id,
                evidence_refs=target_value.evidence_refs,
            )
        )
    return tuple(comparisons), tuple(information_gaps)
