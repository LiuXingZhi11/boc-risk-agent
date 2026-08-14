"""从已审核企业画像生成可比指标候选值。"""

from __future__ import annotations

from src.ontology.registry import REGISTRY
from src.profiles.models import EnterpriseProfile, ProfileItem

from .models import (
    ComparableMetricDefinition,
    ComparableMetricValue,
    MetricProfileFieldBinding,
    PeerCohort,
)


NUMERIC_VALUE_TYPES = {"integer", "money", "ratio"}
MONEY_UNIT_FACTORS = {"元": 1.0, "万元": 10_000.0, "亿元": 100_000_000.0}
RATIO_COMPARISON_UNIT = "比例（小数）"
ENTERPRISE_WIDE_DISCLOSURE_SCOPE = "企业整体披露，合并范围以原报告为准"


def build_metric_value_candidates(
    cohort: PeerCohort,
    definition: ComparableMetricDefinition,
    binding: MetricProfileFieldBinding,
    profile: EnterpriseProfile,
) -> tuple[ComparableMetricValue, ...]:
    """返回画像中所有与既定口径完全一致的数值事实候选。"""
    _validate_binding(definition, binding)
    if profile.review_status != "approved" or profile.case_id not in cohort.company_case_ids:
        return ()
    candidates = []
    for item in profile.items:
        candidate = _build_candidate(cohort, definition, binding, profile, item)
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def _validate_binding(
    definition: ComparableMetricDefinition,
    binding: MetricProfileFieldBinding,
) -> None:
    if binding.metric_id != definition.metric_id:
        raise ValueError("binding metric_id must match the metric definition")
    field = REGISTRY.get_field(binding.field_id)
    if field.section_id != binding.section_id:
        raise ValueError("binding section_id must match the ontology field")
    if field.value_type not in NUMERIC_VALUE_TYPES:
        raise ValueError("a comparable numeric metric must bind to a numeric ontology field")


def _build_candidate(
    cohort: PeerCohort,
    definition: ComparableMetricDefinition,
    binding: MetricProfileFieldBinding,
    profile: EnterpriseProfile,
    item: ProfileItem,
) -> ComparableMetricValue | None:
    if not _matches_metric(item, cohort, definition, binding):
        return None
    value = _normalize_value(item, definition.unit)
    if value is None or _normalized_scope(item) != definition.value_scope:
        return None
    return ComparableMetricValue(
        cohort_id=cohort.cohort_id,
        metric_id=definition.metric_id,
        case_id=profile.case_id,
        value=value,
        reporting_period=item.reporting_period,
        unit=definition.unit,
        source_profile_id=profile.profile_id,
        source_item_id=item.item_id,
        evidence_refs=item.evidence_refs,
    )


def _matches_metric(
    item: ProfileItem,
    cohort: PeerCohort,
    definition: ComparableMetricDefinition,
    binding: MetricProfileFieldBinding,
) -> bool:
    return (
        item.review_status == "accepted"
        and item.section_id == binding.section_id
        and item.field_id == binding.field_id
        and item.value_type in NUMERIC_VALUE_TYPES
        and isinstance(item.value, (int, float))
        and not isinstance(item.value, bool)
        and item.reporting_period == cohort.fiscal_period
    )


def _normalize_value(item: ProfileItem, target_unit: str) -> float | None:
    """把允许比较的原始数值换算为指标单位，不修改画像事实。"""
    value = float(item.value)
    if item.value_type == "money":
        source_factor = MONEY_UNIT_FACTORS.get(item.unit or "")
        target_factor = MONEY_UNIT_FACTORS.get(target_unit)
        if source_factor is None or target_factor is None:
            return value if item.unit == target_unit else None
        return value * source_factor / target_factor
    if item.value_type == "ratio" and item.unit is None:
        return value if target_unit == RATIO_COMPARISON_UNIT else None
    return value if item.unit == target_unit else None


def _normalized_scope(item: ProfileItem) -> str | None:
    if item.value_scope:
        return item.value_scope
    if item.subject == "the_enterprise":
        return ENTERPRISE_WIDE_DISCLOSURE_SCOPE
    return None
