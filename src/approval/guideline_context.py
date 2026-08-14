"""按授信审批指引跨企业画像领域组装有限上下文。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.industry.models import IndustryBackgroundProfile, IndustryInsight
from src.profiles.models import EnterpriseProfile, ProfileItem

from .context import MetricComparison
from .guideline_definitions import (
    GuidelineApprovalPointDefinition,
    GuidelineSectionDefinition,
    get_guideline_point_definitions,
)
from .models import PeerCohort
from .models import ComparableMetricDefinition, ComparableMetricValue
from .ranking import rank_metric_values


@dataclass(frozen=True)
class GuidelinePointContext:
    point_id: str
    title: str
    enterprise_items: tuple[ProfileItem, ...] = field(default_factory=tuple)
    industry_insights: tuple[IndustryInsight, ...] = field(default_factory=tuple)
    metric_comparisons: tuple[MetricComparison, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GuidelineSectionContext:
    cohort_id: str
    cohort_fiscal_period: str
    cohort_selection_rule: str
    case_id: str
    section_id: str
    section_title: str
    enterprise_profile_id: str
    industry_profile_id: str
    point_contexts: tuple[GuidelinePointContext, ...]
    information_gaps: tuple[str, ...] = field(default_factory=tuple)


def build_guideline_section_context(
    cohort: PeerCohort,
    profile: EnterpriseProfile,
    industry_profile: IndustryBackgroundProfile,
    section: GuidelineSectionDefinition,
    *,
    metric_comparisons: tuple[MetricComparison, ...] = (),
) -> GuidelineSectionContext:
    """为一个授信指引方向组装有限、已审核的企业和行业材料。"""
    _validate_inputs(cohort, profile, industry_profile, section)
    accepted_items = tuple(item for item in profile.items if item.review_status == "accepted")
    accepted_insights = tuple(
        insight
        for insight in industry_profile.insights
        if insight.review_status == "accepted"
    )
    point_contexts = tuple(
        _build_point_context(
            definition,
            accepted_items,
            accepted_insights,
            metric_comparisons,
        )
        for definition in get_guideline_point_definitions(section.section_id)
    )
    gaps = list(profile.information_gaps)
    gaps.extend(profile.conflicts)
    gaps.extend(industry_profile.information_gaps)
    for point in point_contexts:
        gaps.extend(point.information_gaps)
    return GuidelineSectionContext(
        cohort_id=cohort.cohort_id,
        cohort_fiscal_period=cohort.fiscal_period,
        cohort_selection_rule=cohort.selection_rule,
        case_id=profile.case_id,
        section_id=section.section_id,
        section_title=section.title,
        enterprise_profile_id=profile.profile_id,
        industry_profile_id=industry_profile.profile_id,
        point_contexts=point_contexts,
        information_gaps=tuple(dict.fromkeys(gaps)),
    )


def build_guideline_metric_comparisons(
    cohort: PeerCohort,
    case_id: str,
    metric_ids: tuple[str, ...],
    metric_definitions: tuple[ComparableMetricDefinition, ...],
    metric_values: tuple[ComparableMetricValue, ...],
) -> tuple[MetricComparison, ...]:
    """按授信方向允许的指标，为一家企业取得 Python 已计算的指标排名。"""
    comparisons: list[MetricComparison] = []
    allowed = set(metric_ids)
    definitions = tuple(
        definition
        for definition in metric_definitions
        if definition.review_status == "approved" and definition.metric_id in allowed
    )
    for definition in definitions:
        values = tuple(
            value
            for value in metric_values
            if value.review_status == "approved"
            and value.cohort_id == cohort.cohort_id
            and value.metric_id == definition.metric_id
        )
        target_values = tuple(value for value in values if value.case_id == case_id)
        if len(values) < 2 or len(target_values) != 1:
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
    return tuple(comparisons)


def _build_point_context(
    definition: GuidelineApprovalPointDefinition,
    accepted_items: tuple[ProfileItem, ...],
    accepted_insights: tuple[IndustryInsight, ...],
    metric_comparisons: tuple[MetricComparison, ...],
) -> GuidelinePointContext:
    items = _select_enterprise_items(definition, accepted_items)
    insights = tuple(
        sorted(
            (
                insight
                for insight in accepted_insights
                if insight.dimension_id in definition.industry_dimension_ids
            ),
            key=lambda insight: (definition.industry_dimension_ids.index(insight.dimension_id), insight.insight_id),
        )[: definition.max_industry_insights]
    )
    metrics = tuple(
        sorted(
            (
                metric
                for metric in metric_comparisons
                if metric.metric_id in definition.metric_ids
            ),
            key=lambda metric: (definition.metric_ids.index(metric.metric_id), metric.metric_id),
        )[: definition.max_metrics]
    )
    gaps: list[str] = []
    if not items:
        gaps.append(f"审批点 {definition.title} 缺少已审核企业事实。")
    if definition.industry_dimension_ids and not insights:
        gaps.append(f"审批点 {definition.title} 缺少已审核行业基准。")
    if definition.metric_ids and not metrics:
        gaps.append(f"审批点 {definition.title} 缺少可比指标。")
    return GuidelinePointContext(
        point_id=definition.point_id,
        title=definition.title,
        enterprise_items=items,
        industry_insights=insights,
        metric_comparisons=metrics,
        information_gaps=tuple(gaps),
    )


def _select_enterprise_items(
    definition: GuidelineApprovalPointDefinition,
    accepted_items: tuple[ProfileItem, ...],
) -> tuple[ProfileItem, ...]:
    """按事实组选择输入，保证字段覆盖后再使用剩余额度。"""
    field_ids = set(definition.enterprise_field_ids)
    candidates = tuple(item for item in accepted_items if item.field_id in field_ids)
    groups: dict[tuple[Any, ...], list[ProfileItem]] = {}
    for item in candidates:
        groups.setdefault(_enterprise_group_key(item), []).append(item)

    ordered_groups = sorted(
        groups.values(),
        key=lambda group: (
            min(definition.enterprise_field_ids.index(item.field_id) for item in group),
            min(item.item_id for item in group),
        ),
    )
    selected: list[list[ProfileItem]] = []
    selected_keys: set[tuple[Any, ...]] = set()
    for field_id in definition.enterprise_field_ids:
        group = next(
            (
                group
                for group in ordered_groups
                if _enterprise_group_key(group[0]) not in selected_keys
                and any(item.field_id == field_id for item in group)
            ),
            None,
        )
        if group is None:
            continue
        selected.append(group)
        selected_keys.add(_enterprise_group_key(group[0]))
        if len(selected) >= definition.max_enterprise_groups:
            break

    if len(selected) < definition.max_enterprise_groups:
        for group in ordered_groups:
            key = _enterprise_group_key(group[0])
            if key in selected_keys:
                continue
            selected.append(group)
            selected_keys.add(key)
            if len(selected) >= definition.max_enterprise_groups:
                break

    return tuple(
        item
        for group in selected
        for item in sorted(
            group,
            key=lambda item: (
                definition.enterprise_field_ids.index(item.field_id),
                item.item_id,
            ),
        )
    )


def _enterprise_group_key(item: ProfileItem) -> tuple[Any, ...]:
    if item.subject:
        return ("subject", item.subject)
    if item.reporting_period:
        return ("period", item.reporting_period)
    return (
        "field_value",
        item.field_id,
        json.dumps(item.value, ensure_ascii=False, sort_keys=True, default=str),
        item.value_scope,
    )


def _validate_inputs(
    cohort: PeerCohort,
    profile: EnterpriseProfile,
    industry_profile: IndustryBackgroundProfile,
    section: GuidelineSectionDefinition,
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
    if section.review_status != "approved":
        raise ValueError("the guideline section must be approved")
