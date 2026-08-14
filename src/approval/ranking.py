"""可比数值指标的确定性样本内排名。"""

from __future__ import annotations

from .models import (
    ComparableMetricDefinition,
    ComparableMetricValue,
    PeerCohort,
    RankingResult,
)


def rank_metric_values(
    cohort: PeerCohort,
    definition: ComparableMetricDefinition,
    values: tuple[ComparableMetricValue, ...],
) -> tuple[RankingResult, ...]:
    """对同一同行样本的一个数值指标计算稠密排名。"""
    _validate_ranking_inputs(cohort, definition, values)
    ordered_values = sorted(
        values,
        key=lambda item: item.value,
        reverse=definition.comparison_direction == "higher_is_better",
    )
    ranks_by_value = {
        value: index + 1 for index, value in enumerate(sorted({item.value for item in values}, reverse=definition.comparison_direction == "higher_is_better"))
    }
    sample_size = len(values)
    return tuple(
        RankingResult(
            cohort_id=value.cohort_id,
            metric_id=value.metric_id,
            case_id=value.case_id,
            value=value.value,
            sample_size=sample_size,
            rank=ranks_by_value[value.value],
            rank_points=sample_size - ranks_by_value[value.value] + 1,
        )
        for value in ordered_values
    )


def _validate_ranking_inputs(
    cohort: PeerCohort,
    definition: ComparableMetricDefinition,
    values: tuple[ComparableMetricValue, ...],
) -> None:
    if not values:
        raise ValueError("at least one metric value is required")
    case_ids = [value.case_id for value in values]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("a company can only provide one value for a metric")
    for value in values:
        if value.cohort_id != cohort.cohort_id:
            raise ValueError("metric value cohort_id must match the cohort")
        if value.metric_id != definition.metric_id:
            raise ValueError("metric value metric_id must match the definition")
        if value.case_id not in cohort.company_case_ids:
            raise ValueError("metric value case_id must belong to the cohort")
        if value.reporting_period != cohort.fiscal_period:
            raise ValueError("metric value reporting_period must match the cohort")
        if value.unit != definition.unit:
            raise ValueError("metric value unit must match the definition")
