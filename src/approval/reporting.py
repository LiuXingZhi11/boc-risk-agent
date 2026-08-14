"""受限生成分方向审批报告与综合风险判断。"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.profiles.models import EvidenceReference

from .context import DomainApprovalContext, MetricComparison
from .direction_ranking import DirectionRankingResult
from .mappings import DOMAIN_INDUSTRY_DIMENSIONS
from .models import (
    ApprovalPoint,
    ApprovalPointDefinition,
    CompositeApprovalReport,
    DomainApprovalReport,
)


def build_domain_approval_report_messages(
    context: DomainApprovalContext,
    definitions: tuple[ApprovalPointDefinition, ...],
) -> list[dict[str, str]]:
    """构造只包含审批点允许材料的分方向报告提示词。"""
    point_payloads = [
        _point_payload(context, definition) for definition in definitions
    ]
    system = (
        "你根据已审核的企业、行业和样本内比较材料撰写审批报告。"
        "只能使用输入中的材料，不得补充外部事实，不得计算或改写名次。"
        "行业材料只能解释环境，不能单独证明企业现状。"
        "输出必须是合法 JSON，不得包含 Markdown。"
    )
    user = (
        "输出顶层字段 one_sentence_summary 和 approval_points。"
        "approval_points 必须与输入审批点一一对应，每项包含："
        "approval_point_id、enterprise_observation、industry_benchmark、"
        "peer_comparison、judgment、enterprise_item_ids、industry_insight_ids、"
        "metric_ids、information_gap_numbers。"
        "所有 ID 和编号只能从对应审批点输入中逐字复制。"
        "每个审批点至少引用一个 enterprise_item_id 或 metric_id；"
        "没有材料时应在 judgment 中说明信息不足，但不得编造事实。\n"
        f"{json.dumps({'domain_id': context.domain_id, 'approval_points': point_payloads}, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_domain_approval_report(
    report_id: str,
    context: DomainApprovalContext,
    definitions: tuple[ApprovalPointDefinition, ...],
    *,
    config: GenerationConfig,
) -> DomainApprovalReport:
    _validate_point_definitions(context, definitions)
    raw = call_deepseek(build_domain_approval_report_messages(context, definitions), config)
    return _validate_domain_report_output(report_id, context, definitions, raw)


def approve_domain_approval_report(report: DomainApprovalReport) -> DomainApprovalReport:
    if report.review_status != "pending":
        raise ValueError("only pending domain reports can be approved")
    return replace(report, review_status="approved")


def domain_approval_report_to_markdown(
    report: DomainApprovalReport,
    metric_names: dict[str, str] | None = None,
) -> str:
    lines = [f"# {report.domain_id} 审批报告", "", report.one_sentence_summary]
    for index, point in enumerate(report.approval_points, start=1):
        lines.extend(["", f"## 审批点 {index}：{point.title}", ""])
        lines.extend([f"- 企业现状：{point.enterprise_observation}"])
        if point.industry_benchmark:
            lines.append(f"- 行业基准：{point.industry_benchmark}")
        if point.peer_comparison:
            lines.append(f"- 同行比较：{point.peer_comparison}")
        lines.append(f"- 审批判断：{point.judgment}")
        for ranking in point.ranking_results:
            metric_name = (metric_names or {}).get(ranking.metric_id, ranking.metric_id)
            lines.append(
                f"- 样本内排名：{ranking.rank}/{ranking.sample_size}，"
                f"指标：{metric_name}，名次分 {ranking.rank_points}"
            )
        if point.information_gaps:
            lines.append(f"- 信息缺口：{'；'.join(point.information_gaps)}")
    return "\n".join(lines) + "\n"


def build_composite_approval_report_messages(
    reports: tuple[DomainApprovalReport, ...],
    direction_rankings: tuple[DirectionRankingResult, ...] = (),
) -> list[dict[str, str]]:
    payload = [
        {
            "report_id": report.report_id,
            "domain_id": report.domain_id,
            "one_sentence_summary": report.one_sentence_summary,
            "approval_points": [
                {
                    "title": point.title,
                    "enterprise_observation": point.enterprise_observation,
                    "industry_benchmark": point.industry_benchmark,
                    "peer_comparison": point.peer_comparison,
                    "judgment": point.judgment,
                    "information_gaps": point.information_gaps,
                }
                for point in report.approval_points
            ],
        }
        for report in reports
    ]
    ranking_payload = []
    for ranking in direction_rankings:
        target = next(
            (
                point
                for point in ranking.rank_points
                if point.case_id == reports[0].case_id
            ),
            None,
        )
        ranking_payload.append(
            {
                "section_id": ranking.section_id,
                "comparable_company_count": ranking.comparable_company_count,
                "target_rank": target.rank if target else None,
                "target_rank_points": target.rank_points if target else None,
                "not_comparable": reports[0].case_id in ranking.not_comparable_case_ids,
            }
        )
    system = (
        "你根据已批准的分方向审批报告形成企业综合核心风险判断。"
        "只能使用输入报告中的结论，不得补充企业事实，不得把样本内排名写成全行业排名。"
        "材料不足时必须保留判断边界。输出合法 JSON，不得包含 Markdown。"
    )
    user = (
        "输出字段 overall_judgment、key_risks、mitigating_factors、"
        "judgment_boundaries、verification_priorities、source_domain_report_ids。"
        "前五项均为简洁中文文本或文本数组；source_domain_report_ids 只能引用输入 report_id。\n"
        f"{json.dumps({'domain_reports': payload, 'direction_rankings': ranking_payload}, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_composite_approval_report(
    report_id: str,
    reports: tuple[DomainApprovalReport, ...],
    *,
    direction_rankings: tuple[DirectionRankingResult, ...] = (),
    config: GenerationConfig,
) -> CompositeApprovalReport:
    _validate_composite_inputs(reports)
    _validate_direction_rankings_for_composite(reports, direction_rankings)
    raw = call_deepseek(
        build_composite_approval_report_messages(reports, direction_rankings),
        config,
    )
    return _validate_composite_output(report_id, reports, raw)


def approve_composite_approval_report(
    report: CompositeApprovalReport,
) -> CompositeApprovalReport:
    if report.review_status != "pending":
        raise ValueError("only pending composite reports can be approved")
    return replace(report, review_status="approved")


def composite_approval_report_to_markdown(report: CompositeApprovalReport) -> str:
    lines = ["# 企业综合核心风险判断", "", report.overall_judgment]
    for title, values in (
        ("主要风险", report.key_risks),
        ("优势或缓释因素", report.mitigating_factors),
        ("判断边界", report.judgment_boundaries),
        ("待核实事项", report.verification_priorities),
    ):
        if values:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines) + "\n"


def _validate_point_definitions(
    context: DomainApprovalContext,
    definitions: tuple[ApprovalPointDefinition, ...],
) -> None:
    if not definitions:
        raise ValueError("at least one approval point definition is required")
    point_ids = [definition.approval_point_id for definition in definitions]
    if len(point_ids) != len(set(point_ids)):
        raise ValueError("approval point definitions must not contain duplicates")
    allowed_fields = {item.field_id for item in context.enterprise_items}
    allowed_metrics = {comparison.metric_id for comparison in context.metric_comparisons}
    valid_dimensions = set(DOMAIN_INDUSTRY_DIMENSIONS[context.domain_id])
    for definition in definitions:
        if definition.review_status != "approved":
            raise ValueError("approval point definitions must be approved")
        if definition.approval_direction_id != context.domain_id:
            raise ValueError("approval point definition domain must match the context")
        if not set(definition.enterprise_field_ids).issubset(allowed_fields):
            raise ValueError("approval point definition references unavailable enterprise fields")
        if not set(definition.metric_ids).issubset(allowed_metrics):
            raise ValueError("approval point definition references unavailable metrics")
        if not set(definition.industry_dimension_ids).issubset(valid_dimensions):
            raise ValueError("approval point definition references an unrelated industry dimension")


def _point_payload(
    context: DomainApprovalContext, definition: ApprovalPointDefinition
) -> dict[str, Any]:
    return {
        "approval_point_id": definition.approval_point_id,
        "title": definition.title,
        "enterprise_items": [
            {
                "item_id": item.item_id,
                "field_id": item.field_id,
                "value": item.value,
                "unit": item.unit,
                "reporting_period": item.reporting_period,
            }
            for item in context.enterprise_items
            if item.field_id in definition.enterprise_field_ids
        ],
        "metric_comparisons": [
            _metric_payload(comparison)
            for comparison in context.metric_comparisons
            if comparison.metric_id in definition.metric_ids
        ],
        "industry_insights": [
            {
                "insight_id": insight.insight_id,
                "dimension_id": insight.dimension_id,
                "statement": insight.statement,
            }
            for insight in context.industry_insights
            if insight.dimension_id in definition.industry_dimension_ids
        ],
        "information_gaps": [
            {"number": index, "text": value}
            for index, value in enumerate(context.information_gaps, start=1)
        ],
    }


def _metric_payload(comparison: MetricComparison) -> dict[str, Any]:
    return {
        "metric_id": comparison.metric_id,
        "name": comparison.metric_name,
        "value": comparison.value,
        "unit": comparison.unit,
        "value_scope": comparison.value_scope,
        "sample_rank": comparison.ranking.rank,
        "sample_size": comparison.ranking.sample_size,
        "rank_points": comparison.ranking.rank_points,
    }


def _validate_domain_report_output(
    report_id: str,
    context: DomainApprovalContext,
    definitions: tuple[ApprovalPointDefinition, ...],
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
    expected_ids = {definition.approval_point_id for definition in definitions}
    if set(raw_by_id) != expected_ids or len(raw_by_id) != len(raw_points):
        raise ValueError("model output must contain exactly the configured approval points")
    items = {item.item_id: item for item in context.enterprise_items}
    insights = {insight.insight_id: insight for insight in context.industry_insights}
    metrics = {comparison.metric_id: comparison for comparison in context.metric_comparisons}
    points = tuple(
        _build_approval_point(
            raw_by_id[definition.approval_point_id],
            definition,
            items,
            insights,
            metrics,
            context.information_gaps,
        )
        for definition in definitions
    )
    return DomainApprovalReport(
        report_id=report_id,
        cohort_id=context.cohort_id,
        case_id=context.case_id,
        domain_id=context.domain_id,
        one_sentence_summary=summary,
        approval_points=points,
    )


def _build_approval_point(
    raw: dict[str, Any],
    definition: ApprovalPointDefinition,
    items: dict[str, Any],
    insights: dict[str, Any],
    metrics: dict[str, MetricComparison],
    information_gaps: tuple[str, ...],
) -> ApprovalPoint:
    item_ids = _selected_ids(raw.get("enterprise_item_ids"), items, "enterprise_item_ids")
    insight_ids = _selected_ids(raw.get("industry_insight_ids"), insights, "industry_insight_ids")
    metric_ids = _selected_ids(raw.get("metric_ids"), metrics, "metric_ids")
    if not set(item_ids).issubset(definition.enterprise_field_ids and {
        item_id for item_id, item in items.items() if item.field_id in definition.enterprise_field_ids
    }):
        raise ValueError("enterprise item is not allowed for this approval point")
    if not set(metric_ids).issubset(definition.metric_ids):
        raise ValueError("metric is not allowed for this approval point")
    if not set(insight_ids).issubset({
        insight_id
        for insight_id, insight in insights.items()
        if insight.dimension_id in definition.industry_dimension_ids
    }):
        raise ValueError("industry insight is not allowed for this approval point")
    if not item_ids and not metric_ids:
        raise ValueError("an approval point must cite enterprise facts or metrics")
    gaps = _selected_gaps(raw.get("information_gap_numbers"), information_gaps)
    evidence_refs = _unique_refs(
        *(items[item_id].evidence_refs for item_id in item_ids),
        *(insights[insight_id].evidence_refs for insight_id in insight_ids),
        *(metrics[metric_id].evidence_refs for metric_id in metric_ids),
    )
    return ApprovalPoint(
        approval_point_id=definition.approval_point_id,
        title=definition.title,
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


def _validate_composite_inputs(reports: tuple[DomainApprovalReport, ...]) -> None:
    if not reports:
        raise ValueError("at least one approved domain report is required")
    first = reports[0]
    report_ids = [report.report_id for report in reports]
    if len(report_ids) != len(set(report_ids)):
        raise ValueError("domain reports must not contain duplicates")
    for report in reports:
        if report.review_status != "approved":
            raise ValueError("only approved domain reports can form a composite report")
        if report.cohort_id != first.cohort_id or report.case_id != first.case_id:
            raise ValueError("domain reports must belong to the same cohort and enterprise")


def _validate_direction_rankings_for_composite(
    reports: tuple[DomainApprovalReport, ...],
    rankings: tuple[DirectionRankingResult, ...],
) -> None:
    if not rankings:
        return
    first = reports[0]
    report_sections = {report.domain_id for report in reports}
    section_ids = [ranking.section_id for ranking in rankings]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("direction rankings must not contain duplicate sections")
    for ranking in rankings:
        if ranking.review_status != "approved":
            raise ValueError("only approved direction rankings can form a composite report")
        if ranking.cohort_id != first.cohort_id:
            raise ValueError("direction ranking cohort must match domain reports")
        if ranking.section_id not in report_sections:
            raise ValueError("direction ranking must match an input domain report")
        target_is_ranked = any(point.case_id == first.case_id for point in ranking.rank_points)
        target_is_not_comparable = first.case_id in ranking.not_comparable_case_ids
        if target_is_ranked == target_is_not_comparable:
            raise ValueError("direction ranking must cover the composite enterprise exactly once")


def _validate_composite_output(
    report_id: str, reports: tuple[DomainApprovalReport, ...], raw: dict[str, Any]
) -> CompositeApprovalReport:
    allowed_ids = {report.report_id for report in reports}
    source_ids = _selected_ids(
        raw.get("source_domain_report_ids"),
        {report_id: report_id for report_id in allowed_ids},
        "source_domain_report_ids",
    )
    if not source_ids:
        raise ValueError("a composite report must cite source domain reports")
    selected_reports = [report for report in reports if report.report_id in source_ids]
    return CompositeApprovalReport(
        report_id=report_id,
        cohort_id=reports[0].cohort_id,
        case_id=reports[0].case_id,
        overall_judgment=_required_text(raw.get("overall_judgment"), "overall_judgment"),
        key_risks=_text_list(raw.get("key_risks"), "key_risks"),
        mitigating_factors=_text_list(raw.get("mitigating_factors"), "mitigating_factors"),
        judgment_boundaries=_text_list(
            raw.get("judgment_boundaries"), "judgment_boundaries"
        ),
        verification_priorities=_text_list(
            raw.get("verification_priorities"), "verification_priorities"
        ),
        source_domain_report_ids=source_ids,
        evidence_refs=_unique_refs(
            *(point.evidence_refs for report in selected_reports for point in report.approval_points)
        ),
    )


def _selected_ids(raw: Any, allowed: dict[str, Any], field_name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(value, str) for value in raw):
        raise ValueError(f"{field_name} must be a list of strings")
    if len(raw) != len(set(raw)) or not set(raw).issubset(allowed):
        raise ValueError(f"{field_name} contains an unknown or duplicate ID")
    return tuple(raw)


def _selected_gaps(raw: Any, gaps: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(value, int) for value in raw):
        raise ValueError("information_gap_numbers must be a list of integers")
    if len(raw) != len(set(raw)) or not all(1 <= value <= len(gaps) for value in raw):
        raise ValueError("information_gap_numbers contains an unknown or duplicate number")
    return tuple(gaps[value - 1] for value in raw)


def _unique_refs(*groups: tuple[EvidenceReference, ...]) -> tuple[EvidenceReference, ...]:
    seen: set[str] = set()
    references: list[EvidenceReference] = []
    for group in groups:
        for reference in group:
            if reference.evidence_unit_id not in seen:
                seen.add(reference.evidence_unit_id)
                references.append(reference)
    return tuple(references)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return _required_text(value, "optional text")


def _text_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)
