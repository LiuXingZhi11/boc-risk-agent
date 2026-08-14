"""按授信审批指引生成单企业分方向报告。"""

from __future__ import annotations

import json
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.profiles.models import EvidenceReference

from .guideline_context import GuidelinePointContext, GuidelineSectionContext
from .guideline_definitions import get_guideline_point_definitions
from .models import ApprovalPoint, DomainApprovalReport


def build_guideline_section_report_messages(
    context: GuidelineSectionContext,
) -> list[dict[str, str]]:
    point_payloads = [_point_payload(point) for point in context.point_contexts]
    system = (
        "你根据已审核的当前企业事实、行业背景和同行指标，撰写授信审批指引中的一个方向报告。"
        "只能使用输入材料，不得补充外部事实，不得自行计算或改写指标名次。"
        "行业背景只能解释外部环境，不能单独证明企业现状。"
        "输出必须是合法 JSON，不得包含 Markdown。"
    )
    user = (
        "输出顶层字段 one_sentence_summary 和 approval_points。"
        "approval_points 必须与输入审批点一一对应，每项包含："
        "approval_point_id、enterprise_observation、industry_benchmark、"
        "peer_comparison、judgment、enterprise_item_ids、industry_insight_ids、"
        "metric_ids、information_gap_numbers。"
        "所有 ID 和编号只能从对应审批点输入中复制。"
        "enterprise_observation、industry_benchmark、peer_comparison 和 judgment 必须使用业务自然语言，"
        "不得写出 metric_id、enterprise_item_id、industry_insight_id、information_gap_numbers 或其他内部 ID。"
        "每个有明确企业判断的审批点至少引用一个 enterprise_item_id 或 metric_id；"
        "材料不足时在 judgment 中说明信息不足，不得编造事实。\n"
        f"{json.dumps({'cohort': {'cohort_id': context.cohort_id, 'fiscal_period': context.cohort_fiscal_period, 'selection_rule': context.cohort_selection_rule}, 'section_id': context.section_id, 'section_title': context.section_title, 'section_information_gaps': list(context.information_gaps), 'approval_points': point_payloads}, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_guideline_section_report(
    report_id: str,
    context: GuidelineSectionContext,
    *,
    config: GenerationConfig,
) -> DomainApprovalReport:
    raw = call_deepseek(build_guideline_section_report_messages(context), config)
    try:
        return _validate_guideline_section_report_output(report_id, context, raw)
    except ValueError as error:
        repaired = call_deepseek(
            _build_format_repair_messages(context, raw, error), config
        )
        return _validate_guideline_section_report_output(report_id, context, repaired)


def _build_format_repair_messages(
    context: GuidelineSectionContext,
    raw: dict[str, Any],
    error: ValueError,
) -> list[dict[str, str]]:
    """对一次不合格输出做受限格式修复，不新增任何业务材料。"""
    messages = build_guideline_section_report_messages(context)
    messages.extend(
        (
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {
                "role": "user",
                "content": (
                    f"上一版输出未通过校验：{error}。"
                    "请仅根据上方同一份输入重新输出完整合法 JSON；"
                    "所有引用 ID 和信息缺口编号必须从对应审批点允许列表逐字复制，"
                    "不要增加任何新事实或解释。"
                ),
            },
        )
    )
    return messages


def _point_payload(point: GuidelinePointContext) -> dict[str, Any]:
    return {
        "approval_point_id": point.point_id,
        "title": point.title,
        "enterprise_items": [
            {
                "item_id": item.item_id,
                "field_id": item.field_id,
                "value": item.value,
                "unit": item.unit,
                "value_scope": item.value_scope,
                "reporting_period": item.reporting_period,
            }
            for item in point.enterprise_items
        ],
        "industry_insights": [
            {
                "insight_id": insight.insight_id,
                "dimension_id": insight.dimension_id,
                "statement": insight.statement,
            }
            for insight in point.industry_insights
        ],
        "metric_comparisons": [
            {
                "metric_id": metric.metric_id,
                "name": metric.metric_name,
                "value": metric.value,
                "unit": metric.unit,
                "value_scope": metric.value_scope,
                "sample_rank": metric.ranking.rank,
                "sample_size": metric.ranking.sample_size,
                "rank_points": metric.ranking.rank_points,
            }
            for metric in point.metric_comparisons
        ],
        "information_gaps": [
            {"number": index, "text": gap}
            for index, gap in enumerate(point.information_gaps, start=1)
        ],
    }


def _validate_guideline_section_report_output(
    report_id: str,
    context: GuidelineSectionContext,
    raw: dict[str, Any],
) -> DomainApprovalReport:
    summary = _required_text(raw.get("one_sentence_summary"), "one_sentence_summary")
    raw_points = raw.get("approval_points")
    if not isinstance(raw_points, list):
        raise ValueError("approval_points must be a list")
    raw_by_id = {
        point.get("approval_point_id"): point
        for point in raw_points
        if isinstance(point, dict) and isinstance(point.get("approval_point_id"), str)
    }
    expected_ids = {point.point_id for point in context.point_contexts}
    if set(raw_by_id) != expected_ids or len(raw_by_id) != len(raw_points):
        raise ValueError("model output must contain exactly the configured approval points")
    points = tuple(
        _build_approval_point(raw_by_id[point.point_id], point)
        for point in context.point_contexts
    )
    return DomainApprovalReport(
        report_id=report_id,
        cohort_id=context.cohort_id,
        case_id=context.case_id,
        domain_id=context.section_id,
        one_sentence_summary=summary,
        approval_points=points,
    )


def _build_approval_point(
    raw: dict[str, Any],
    context: GuidelinePointContext,
) -> ApprovalPoint:
    items = {item.item_id: item for item in context.enterprise_items}
    insights = {insight.insight_id: insight for insight in context.industry_insights}
    metrics = {metric.metric_id: metric for metric in context.metric_comparisons}
    item_ids = _selected_ids(raw.get("enterprise_item_ids"), items, "enterprise_item_ids")
    insight_ids = _selected_ids(raw.get("industry_insight_ids"), insights, "industry_insight_ids")
    metric_ids = _selected_ids(raw.get("metric_ids"), metrics, "metric_ids")
    gaps = _selected_gaps(raw.get("information_gap_numbers"), context.information_gaps)
    if not item_ids and not metric_ids and not gaps:
        raise ValueError("an approval point must cite enterprise facts, metrics, or an information gap")
    evidence_refs = _unique_refs(
        *(items[item_id].evidence_refs for item_id in item_ids),
        *(insights[insight_id].evidence_refs for insight_id in insight_ids),
        *(metrics[metric_id].evidence_refs for metric_id in metric_ids),
    )
    return ApprovalPoint(
        approval_point_id=context.point_id,
        title=context.title,
        enterprise_observation=_required_text(
            raw.get("enterprise_observation"), "enterprise_observation"
        ),
        industry_benchmark=_optional_text(raw.get("industry_benchmark")),
        peer_comparison=_optional_text(raw.get("peer_comparison")),
        judgment=_required_text(raw.get("judgment"), "judgment"),
        ranking_results=tuple(metrics[metric_id].ranking for metric_id in metric_ids),
        evidence_refs=evidence_refs,
        information_gaps=gaps,
    )


def _selected_ids(
    raw: Any,
    allowed: dict[str, Any],
    field_name: str,
) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ValueError(f"{field_name} must be a list of strings")
    if not set(raw).issubset(allowed):
        raise ValueError(f"{field_name} contains an unknown ID")
    return tuple(dict.fromkeys(raw))


def _selected_gaps(raw: Any, gaps: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(value, int) for value in raw):
        raise ValueError("information_gap_numbers must be a list of integers")
    if not all(1 <= value <= len(gaps) for value in raw):
        raise ValueError("information_gap_numbers contains an unknown number")
    return tuple(gaps[value - 1] for value in dict.fromkeys(raw))


def _unique_refs(*groups: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    seen: set[str] = set()
    result: list[EvidenceReference] = []
    for group in groups:
        for reference in group:
            if reference.evidence_unit_id not in seen:
                seen.add(reference.evidence_unit_id)
                result.append(reference)
    return tuple(result)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "optional text")
