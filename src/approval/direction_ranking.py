"""同一授信审批方向的多企业横向比较、排名和名次分转换。"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.prompts import load_prompt_section

from .guideline_context import GuidelineSectionContext
from .guideline_definitions import GuidelineSectionDefinition
from .models import DomainApprovalReport


@dataclass(frozen=True)
class DirectionPointCard:
    point_id: str
    title: str
    enterprise_observation: str
    industry_benchmark: str | None
    peer_comparison: str | None
    judgment: str
    key_facts: tuple[dict[str, Any], ...]
    metric_results: tuple[dict[str, Any], ...]
    information_gaps: tuple[str, ...]


@dataclass(frozen=True)
class DirectionComparisonCard:
    cohort_id: str
    cohort_fiscal_period: str
    cohort_selection_rule: str
    section_id: str
    case_id: str
    one_sentence_summary: str
    approval_points: tuple[DirectionPointCard, ...]
    source_section_report_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "cohort_fiscal_period": self.cohort_fiscal_period,
            "cohort_selection_rule": self.cohort_selection_rule,
            "one_sentence_summary": self.one_sentence_summary,
            "approval_points": [
                {
                    "point_id": point.point_id,
                    "title": point.title,
                    "enterprise_observation": point.enterprise_observation,
                    "industry_benchmark": point.industry_benchmark,
                    "peer_comparison": point.peer_comparison,
                    "judgment": point.judgment,
                    "key_facts": list(point.key_facts),
                    "metric_results": list(point.metric_results),
                    "information_gaps": list(point.information_gaps),
                }
                for point in self.approval_points
            ],
        }


@dataclass(frozen=True)
class DirectionRankingGroup:
    rank: int
    case_ids: tuple[str, ...]
    comparison_reason: str


@dataclass(frozen=True)
class DirectionRankPoint:
    case_id: str
    rank: int
    rank_points: int


@dataclass(frozen=True)
class DirectionRankingResult:
    cohort_id: str
    section_id: str
    comparable_company_count: int
    ranking_groups: tuple[DirectionRankingGroup, ...]
    not_comparable_case_ids: tuple[str, ...]
    rank_points: tuple[DirectionRankPoint, ...]
    source_section_report_ids: tuple[str, ...]
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if self.comparable_company_count < 2:
            raise ValueError("direction ranking requires at least two comparable companies")
        if self.review_status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"invalid review_status: {self.review_status!r}")
        if len(self.source_section_report_ids) != len(set(self.source_section_report_ids)):
            raise ValueError("source_section_report_ids must not contain duplicates")


def build_direction_comparison_card(
    report: DomainApprovalReport,
    context: GuidelineSectionContext,
) -> DirectionComparisonCard:
    """把已批准的单企业方向报告压缩成同口径比较卡。"""
    if report.review_status != "approved":
        raise ValueError("only approved section reports can form comparison cards")
    if report.cohort_id != context.cohort_id or report.case_id != context.case_id:
        raise ValueError("report and context must belong to the same company and cohort")
    if report.domain_id != context.section_id:
        raise ValueError("report and context must belong to the same guideline section")
    context_by_id = {point.point_id: point for point in context.point_contexts}
    cards: list[DirectionPointCard] = []
    for report_point in report.approval_points:
        point_context = context_by_id.get(report_point.approval_point_id)
        if point_context is None:
            raise ValueError("report contains an unknown guideline point")
        evidence_ids = {reference.evidence_unit_id for reference in report_point.evidence_refs}
        facts = tuple(
            {
                "item_id": item.item_id,
                "field_id": item.field_id,
                "value": item.value,
                "unit": item.unit,
                "reporting_period": item.reporting_period,
            }
            for item in point_context.enterprise_items
            if evidence_ids.intersection(
                reference.evidence_unit_id for reference in item.evidence_refs
            )
        )[:5]
        metric_results = tuple(
            {
                "metric_id": result.metric_id,
                "value": result.value,
                "sample_size": result.sample_size,
                "rank": result.rank,
                "rank_points": result.rank_points,
            }
            for result in report_point.ranking_results
        )
        cards.append(
            DirectionPointCard(
                point_id=report_point.approval_point_id,
                title=report_point.title,
                enterprise_observation=report_point.enterprise_observation,
                industry_benchmark=report_point.industry_benchmark,
                peer_comparison=report_point.peer_comparison,
                judgment=report_point.judgment,
                key_facts=facts,
                metric_results=metric_results,
                information_gaps=report_point.information_gaps,
            )
        )
    return DirectionComparisonCard(
        cohort_id=context.cohort_id,
        cohort_fiscal_period=context.cohort_fiscal_period,
        cohort_selection_rule=context.cohort_selection_rule,
        section_id=context.section_id,
        case_id=context.case_id,
        one_sentence_summary=report.one_sentence_summary,
        approval_points=tuple(cards),
        source_section_report_id=report.report_id,
    )


def build_direction_ranking_messages(
    section: GuidelineSectionDefinition,
    cards: tuple[DirectionComparisonCard, ...],
) -> list[dict[str, str]]:
    if not section.ranking_enabled:
        raise ValueError("direction ranking is disabled for this section")
    if len(cards) < 2:
        raise ValueError("direction ranking requires at least two comparison cards")
    system = load_prompt_section("logic/授信审批逻辑规则.md", "同行分方向排名")
    user = (
        "当前方向比较卡如下，请按 system 规则输出完整 JSON：\n"
        f"{json.dumps({'section_id': section.section_id, 'section_title': section.title, 'comparison_criteria': section.comparison_criteria, 'cards': [card.to_payload() for card in cards]}, ensure_ascii=False)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_direction_ranking(
    section: GuidelineSectionDefinition,
    cards: tuple[DirectionComparisonCard, ...],
    *,
    config: GenerationConfig,
) -> DirectionRankingResult:
    raw = call_deepseek(build_direction_ranking_messages(section, cards), config)
    return _validate_direction_ranking_output(section, cards, raw)


def approve_direction_ranking(result: DirectionRankingResult) -> DirectionRankingResult:
    if result.review_status != "pending":
        raise ValueError("only pending direction rankings can be approved")
    return replace(result, review_status="approved")


def direction_ranking_to_markdown(result: DirectionRankingResult) -> str:
    lines = [
        f"# {result.section_id} 样本内方向排名",
        "",
        f"可比较企业数：{result.comparable_company_count}",
    ]
    for group in result.ranking_groups:
        points = result.comparable_company_count - group.rank + 1
        lines.append(
            f"- 第{group.rank}名（{points}分）：{'、'.join(group.case_ids)}；{group.comparison_reason}"
        )
    if result.not_comparable_case_ids:
        lines.extend(
            ["", f"不可比较：{'、'.join(result.not_comparable_case_ids)}"]
        )
    return "\n".join(lines) + "\n"


def _validate_direction_ranking_output(
    section: GuidelineSectionDefinition,
    cards: tuple[DirectionComparisonCard, ...],
    raw: dict[str, Any],
) -> DirectionRankingResult:
    if not isinstance(raw, dict):
        raise ValueError("direction ranking output must be an object")
    raw_groups = raw.get("ranking_groups")
    raw_not_comparable = raw.get("not_comparable_case_ids", [])
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ValueError("ranking_groups must be a non-empty list")
    if not isinstance(raw_not_comparable, list) or not all(
        isinstance(case_id, str) for case_id in raw_not_comparable
    ):
        raise ValueError("not_comparable_case_ids must be a list of strings")
    case_ids = {card.case_id for card in cards}
    if len(case_ids) != len(cards):
        raise ValueError("comparison cards must contain unique companies")
    not_comparable = tuple(raw_not_comparable)
    if len(not_comparable) != len(set(not_comparable)):
        raise ValueError("not_comparable_case_ids must not contain duplicates")
    groups: list[DirectionRankingGroup] = []
    ranked_ids: list[str] = []
    previous_rank = 0
    for expected_rank, raw_group in enumerate(raw_groups, start=1):
        if not isinstance(raw_group, dict):
            raise ValueError("each ranking group must be an object")
        rank = raw_group.get("rank")
        group_case_ids = raw_group.get("case_ids")
        reason = raw_group.get("comparison_reason")
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("ranking group rank must be an integer")
        if (expected_rank == 1 and rank != 1) or rank <= previous_rank:
            raise ValueError("ranking groups must be ordered from rank 1")
        if (
            not isinstance(group_case_ids, list)
            or not group_case_ids
            or not all(isinstance(case_id, str) for case_id in group_case_ids)
        ):
            raise ValueError("each ranking group needs a non-empty case_ids list")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("comparison_reason must be a non-empty string")
        ranked_ids.extend(group_case_ids)
        groups.append(
            DirectionRankingGroup(
                rank=expected_rank,
                case_ids=tuple(group_case_ids),
                comparison_reason=reason.strip(),
            )
        )
        previous_rank = rank
    if len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("a company cannot appear in multiple ranking groups")
    if len(not_comparable) != len(set(not_comparable)):
        raise ValueError("not_comparable_case_ids must not contain duplicates")
    if set(ranked_ids) | set(not_comparable) != case_ids:
        raise ValueError("ranking output must cover every comparison card exactly once")
    if set(ranked_ids) & set(not_comparable):
        raise ValueError("a company cannot be ranked and not comparable")
    comparable_count = len(ranked_ids)
    if comparable_count < 2:
        raise ValueError("direction ranking needs at least two comparable companies")
    rank_points = tuple(
        DirectionRankPoint(
            case_id=case_id,
            rank=group.rank,
            rank_points=comparable_count - group.rank + 1,
        )
        for group in groups
        for case_id in group.case_ids
    )
    return DirectionRankingResult(
        cohort_id=cards[0].cohort_id,
        section_id=section.section_id,
        comparable_company_count=comparable_count,
        ranking_groups=tuple(groups),
        not_comparable_case_ids=not_comparable,
        rank_points=rank_points,
        source_section_report_ids=tuple(card.source_section_report_id for card in cards),
    )
