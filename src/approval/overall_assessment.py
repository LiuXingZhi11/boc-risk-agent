"""企业 A-D 综合评定：组装有限输入、生成、校验和导出。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.profiles.models import EvidenceReference

from .direction_ranking import DirectionRankingResult
from .guideline_definitions import GUIDELINE_SECTION_DEFINITIONS
from .models import (
    DomainApprovalReport,
    EnterpriseOverallAssessment,
    FinalDirectionResult,
    OverallAssessmentRationale,
)
from .guideline_definitions import STRONG_CONSTRAINT_TRIGGER_CODES


ASSESSMENT_DIMENSIONS = (
    ("industry_and_commercialization", "行业与商业化基础"),
    ("technology_and_transformation", "技术与转化能力"),
    ("governance_and_capital", "治理与资本基础"),
    ("financial_and_operating_resilience", "财务与经营韧性"),
    ("compliance_and_uncertainty", "合规与重大不确定性"),
)

RATING_RULES = {
    "A": "无强弱约束不通过，且除试验量化边界外不存在信息不足。",
    "B": "无强弱约束不通过，但存在需要持续核实的信息边界。",
    "C": "存在一至四项明确弱约束不通过，且未达到多风险面 D 的门槛。",
    "D": "存在强约束不通过，或多个弱约束不通过并覆盖关键风险面。",
}

RECOMMENDATION_LABELS = {
    "proceed_with_caution": "可推进",
    "proceed_with_review": "审慎推进",
    "conditional_proceed": "有条件推进",
    "do_not_proceed": "不建议推进",
}

OVERALL_ASSESSMENT_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts" / "09_企业综合评级.md"
)


def build_overall_assessment_package(
    *,
    enterprise_name: str,
    profile_reporting_periods: tuple[str, ...],
    cohort_name: str,
    cohort_fiscal_period: str,
    cohort_selection_rule: str,
    reports: tuple[DomainApprovalReport, ...],
    rankings: tuple[DirectionRankingResult, ...],
    is_experimental: bool,
) -> dict[str, Any]:
    """将已生成方向报告压缩为单家企业综合评定包。"""
    _validate_assessment_inputs(reports, rankings, is_experimental=is_experimental)
    case_id = reports[0].case_id
    ranking_by_section = {ranking.section_id: ranking for ranking in rankings}
    direction_cards = []
    for report in reports:
        ranking = ranking_by_section.get(report.domain_id)
        direction_cards.append(
            {
                "section_id": report.domain_id,
                "constraint_level": next(
                    section.constraint_level
                    for section in GUIDELINE_SECTION_DEFINITIONS
                    if section.section_id == report.domain_id
                ),
                "one_sentence_summary": report.one_sentence_summary,
                "approval_points": [
                    {
                        "title": point.title,
                        "enterprise_observation": point.enterprise_observation,
                        "industry_benchmark": point.industry_benchmark,
                        "peer_comparison": point.peer_comparison,
                        "judgment": point.judgment,
                        "key_evidence_unit_ids": [
                            reference.evidence_unit_id for reference in point.evidence_refs[:2]
                        ],
                        "metric_rankings": [
                            {
                                "rank": item.rank,
                                "sample_size": item.sample_size,
                                "rank_points": item.rank_points,
                            }
                            for item in point.ranking_results
                        ],
                        "information_gaps": list(point.information_gaps),
                    }
                    for point in report.approval_points
                ],
                "peer_position": _peer_position(ranking, case_id),
                "source_direction_report_id": report.report_id,
            }
        )
    return {
        "assessment_boundary": {
            "enterprise_name": enterprise_name,
            "profile_reporting_periods": list(profile_reporting_periods),
            "cohort_name": cohort_name,
            "cohort_fiscal_period": cohort_fiscal_period,
            "cohort_selection_rule": cohort_selection_rule,
            "is_experimental": is_experimental,
        },
        "rating_rules": RATING_RULES,
        "strong_constraint_trigger_codes": STRONG_CONSTRAINT_TRIGGER_CODES,
        "assessment_dimensions": [
            {"dimension_id": dimension_id, "title": title}
            for dimension_id, title in ASSESSMENT_DIMENSIONS
        ],
        "direction_cards": direction_cards,
    }


def build_overall_assessment_messages(package: dict[str, Any]) -> list[dict[str, str]]:
    system = _prompt_section("系统提示词")
    user = _prompt_section("用户提示词").replace(
        "{{ASSESSMENT_PACKAGE_JSON}}", json.dumps(package, ensure_ascii=False)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_overall_assessment(
    assessment_id: str,
    package: dict[str, Any],
    reports: tuple[DomainApprovalReport, ...],
    rankings: tuple[DirectionRankingResult, ...],
    *,
    config: GenerationConfig,
) -> EnterpriseOverallAssessment:
    raw = call_deepseek(build_overall_assessment_messages(package), config)
    try:
        return validate_overall_assessment_output(
            assessment_id,
            package,
            reports,
            rankings,
            raw,
        )
    except ValueError as error:
        repaired = call_deepseek(
            _build_format_repair_messages(package, raw, error), config
        )
        return validate_overall_assessment_output(
            assessment_id,
            package,
            reports,
            rankings,
            repaired,
        )


def _build_format_repair_messages(
    package: dict[str, Any], raw: dict[str, Any], error: ValueError
) -> list[dict[str, str]]:
    """仅修复结构或引用格式，不追加任何事实材料。"""
    messages = build_overall_assessment_messages(package)
    messages.extend(
        (
            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
            {
                "role": "user",
                "content": _prompt_section("格式修复提示词").replace(
                    "{{VALIDATION_ERROR}}", str(error)
                ),
            },
        )
    )
    return messages


def _prompt_section(title: str) -> str:
    """读取综合评级提示词中的一个固定章节。"""
    content = OVERALL_ASSESSMENT_PROMPT_PATH.read_text(encoding="utf-8")
    return content.split(f"## {title}", 1)[1].split("\n## ", 1)[0].strip()


def validate_overall_assessment_output(
    assessment_id: str,
    package: dict[str, Any],
    reports: tuple[DomainApprovalReport, ...],
    rankings: tuple[DirectionRankingResult, ...],
    raw: dict[str, Any],
) -> EnterpriseOverallAssessment:
    """校验等级、五类依据与来源引用均未越出综合评定包。"""
    if not isinstance(raw, dict):
        raise ValueError("overall assessment output must be an object")
    _validate_assessment_inputs(
        reports,
        rankings,
        is_experimental=bool(package["assessment_boundary"]["is_experimental"]),
    )
    report_ids = tuple(report.report_id for report in reports)
    expected_ranking_sections = tuple(
        ranking.section_id
        for ranking in rankings
        if any(point.case_id == reports[0].case_id for point in ranking.rank_points)
    )
    source_report_ids = report_ids
    ranking_sections = expected_ranking_sections
    rationale = _build_rationale(raw.get("rating_rationale"))
    direction_results = _build_direction_results(raw.get("direction_results"), package)
    strong_failed_count, weak_failed_count, recommendation = _recommendation(direction_results)
    _validate_rating_boundary(
        _required_text(raw.get("rating_level"), "rating_level"),
        direction_results,
        recommendation,
    )
    allowed_evidence = {
        reference.evidence_unit_id
        for report in reports
        for point in report.approval_points
        for reference in point.evidence_refs
    }
    evidence_ids = _selected_ids(
        raw.get("evidence_unit_ids"), tuple(sorted(allowed_evidence)), "evidence_unit_ids"
    )
    if not evidence_ids:
        raise ValueError("overall assessment must cite evidence")
    text_values = _all_text_values(raw)
    if any(term in text_values for term in ("授信额度", "贷款额度", "利率", "自动审批")):
        raise ValueError("overall assessment must not contain credit terms or automatic approval")
    boundary = package["assessment_boundary"]
    return EnterpriseOverallAssessment(
        assessment_id=assessment_id,
        cohort_id=reports[0].cohort_id,
        case_id=reports[0].case_id,
        rating_level=_required_text(raw.get("rating_level"), "rating_level"),
        overall_judgment=_required_text(raw.get("overall_judgment"), "overall_judgment"),
        rating_rationale=rationale,
        core_risks=_text_list(raw.get("core_risks"), "core_risks"),
        mitigating_factors=_text_list(raw.get("mitigating_factors"), "mitigating_factors"),
        rating_boundaries=_text_list(raw.get("rating_boundaries"), "rating_boundaries"),
        verification_priorities=_text_list(
            raw.get("verification_priorities"), "verification_priorities"
        ),
        source_direction_report_ids=source_report_ids,
        source_direction_ranking_sections=ranking_sections,
        evidence_refs=tuple(EvidenceReference(evidence_unit_id=item) for item in evidence_ids),
        recommendation=recommendation,
        strong_constraint_failed_count=strong_failed_count,
        weak_constraint_failed_count=weak_failed_count,
        direction_results=direction_results,
        is_experimental=bool(boundary["is_experimental"]),
    )


def approve_overall_assessment(
    assessment: EnterpriseOverallAssessment,
) -> EnterpriseOverallAssessment:
    if assessment.review_status != "pending":
        raise ValueError("only pending overall assessments can be approved")
    if assessment.is_experimental:
        raise ValueError("experimental overall assessments cannot be approved")
    return replace(assessment, review_status="approved")


def overall_assessment_to_markdown(assessment: EnterpriseOverallAssessment) -> str:
    status = "试验性待审核" if assessment.is_experimental else assessment.review_status
    lines = [
        "# 最终授信审批报告",
        "",
        f"- 推进建议：{RECOMMENDATION_LABELS[assessment.recommendation]}",
        f"- 综合等级：{assessment.rating_level}",
        f"- 强约束不通过：{assessment.strong_constraint_failed_count} 条",
        f"- 弱约束不通过：{assessment.weak_constraint_failed_count} 条",
        f"- 审核状态：{status}",
        "",
        assessment.overall_judgment,
    ]
    if assessment.direction_results:
        lines.extend(["", "## 授信审批指引逐条结论", ""])
        titles = {item.section_id: item.title for item in GUIDELINE_SECTION_DEFINITIONS}
        status_labels = {
            "passed": "通过",
            "conditional_passed": "有条件通过",
            "failed": "不通过",
            "insufficient_information": "信息不足",
        }
        constraint_labels = {"strong": "强约束", "weak": "弱约束"}
        for item in assessment.direction_results:
            lines.extend(
                (
                    f"### {titles[item.section_id]}",
                    f"- 约束类型：{constraint_labels[item.constraint_level]}",
                    f"- 状态：{status_labels[item.status]}",
                    f"- 结论：{item.summary}",
                    "",
                )
            )
    lines.extend(["", "## 五类评定依据", ""])
    for item in assessment.rating_rationale:
        lines.append(f"- **{item.title}**：{item.judgment}")
    for title, values in (
        ("主要风险", assessment.core_risks),
        ("缓释因素", assessment.mitigating_factors),
        ("判断边界", assessment.rating_boundaries),
        ("优先核实事项", assessment.verification_priorities),
    ):
        if values:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)
    return "\n".join(lines) + "\n"


def _validate_assessment_inputs(
    reports: tuple[DomainApprovalReport, ...],
    rankings: tuple[DirectionRankingResult, ...],
    *,
    is_experimental: bool,
) -> None:
    expected_sections = tuple(section.section_id for section in GUIDELINE_SECTION_DEFINITIONS)
    if len(reports) != len(expected_sections):
        raise ValueError("overall assessment requires all 11 direction reports")
    first = reports[0]
    if {report.domain_id for report in reports} != set(expected_sections):
        raise ValueError("overall assessment reports must cover all guideline sections")
    expected_status = "pending" if is_experimental else "approved"
    for report in reports:
        if report.cohort_id != first.cohort_id or report.case_id != first.case_id:
            raise ValueError("direction reports must belong to the same enterprise and cohort")
        if report.review_status != expected_status:
            raise ValueError("direction report status does not match assessment type")
    expected_ranked_sections = {
        section.section_id for section in GUIDELINE_SECTION_DEFINITIONS if section.ranking_enabled
    }
    if {ranking.section_id for ranking in rankings} != expected_ranked_sections:
        raise ValueError("overall assessment requires every enabled direction ranking")
    for ranking in rankings:
        if ranking.cohort_id != first.cohort_id or ranking.review_status != expected_status:
            raise ValueError("direction ranking status does not match assessment type")


def _build_direction_results(
    raw: Any, package: dict[str, Any]
) -> tuple[FinalDirectionResult, ...]:
    if not isinstance(raw, list):
        raise ValueError("direction_results must be a list")
    cards = {item["section_id"]: item for item in package["direction_cards"]}
    by_section = {
        item.get("section_id"): item
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("section_id"), str)
    }
    if set(by_section) != set(cards) or len(by_section) != len(raw):
        raise ValueError("direction_results must cover all 11 guideline sections exactly once")

    results = []
    for section in GUIDELINE_SECTION_DEFINITIONS:
        item = by_section[section.section_id]
        status = _required_text(item.get("status"), "direction result status")
        trigger_code = item.get("strong_constraint_trigger_code")
        trigger_evidence_ids = item.get("strong_constraint_trigger_evidence_unit_ids", [])
        if trigger_code is not None and not isinstance(trigger_code, str):
            raise ValueError("strong_constraint_trigger_code must be a string or null")
        if not isinstance(trigger_evidence_ids, list) or not all(
            isinstance(value, str) for value in trigger_evidence_ids
        ):
            raise ValueError("strong constraint trigger evidence must be a list of strings")
        allowed_evidence_ids = {
            evidence_unit_id
            for point in cards[section.section_id]["approval_points"]
            for evidence_unit_id in point["key_evidence_unit_ids"]
        }
        if len(trigger_evidence_ids) != len(set(trigger_evidence_ids)) or not set(
            trigger_evidence_ids
        ).issubset(allowed_evidence_ids):
            raise ValueError("strong constraint trigger evidence is not from this direction")
        if section.constraint_level == "weak" and trigger_code is not None:
            raise ValueError("weak constraints cannot have a strong constraint trigger")
        if section.constraint_level == "weak" and trigger_evidence_ids:
            raise ValueError("weak constraints cannot have strong constraint trigger evidence")
        if section.constraint_level == "strong":
            allowed_codes = STRONG_CONSTRAINT_TRIGGER_CODES[section.section_id]
            if status == "failed" and (
                trigger_code not in allowed_codes or not trigger_evidence_ids
            ):
                raise ValueError("strong constraint failure requires an allowed hard trigger")
            if status != "failed" and (trigger_code is not None or trigger_evidence_ids):
                raise ValueError("only failed strong constraints may have a trigger")
        if section.section_id == "quantitative_assessment":
            if status == "failed":
                raise ValueError("quantitative assessment must not fail an enterprise")
            if package["assessment_boundary"]["is_experimental"] and status != "insufficient_information":
                raise ValueError("experimental quantitative assessment must be insufficient information")
        results.append(
            FinalDirectionResult(
                section_id=section.section_id,
                constraint_level=section.constraint_level,
                status=status,
                summary=_required_text(item.get("summary"), "direction result summary"),
                strong_constraint_trigger_code=trigger_code,
                strong_constraint_trigger_evidence_unit_ids=tuple(trigger_evidence_ids),
            )
        )
    return tuple(results)


def _recommendation(
    direction_results: tuple[FinalDirectionResult, ...]
) -> tuple[int, int, str]:
    strong_failed_count = sum(
        item.constraint_level == "strong" and item.status == "failed"
        for item in direction_results
    )
    weak_failed_count = sum(
        item.constraint_level == "weak"
        and item.section_id != "quantitative_assessment"
        and item.status == "failed"
        for item in direction_results
    )
    if strong_failed_count:
        return strong_failed_count, weak_failed_count, "do_not_proceed"
    if weak_failed_count >= 3:
        return strong_failed_count, weak_failed_count, "do_not_proceed"
    if weak_failed_count:
        return strong_failed_count, weak_failed_count, "conditional_proceed"
    if any(
        item.section_id != "quantitative_assessment"
        and item.status == "insufficient_information"
        for item in direction_results
    ):
        return strong_failed_count, weak_failed_count, "proceed_with_review"
    return strong_failed_count, weak_failed_count, "proceed_with_caution"


def _validate_rating_boundary(
    rating_level: str,
    direction_results: tuple[FinalDirectionResult, ...],
    recommendation: str,
) -> None:
    weak_failed = {
        item.section_id
        for item in direction_results
        if item.constraint_level == "weak"
        and item.section_id != "quantitative_assessment"
        and item.status == "failed"
    }
    non_methodology_information_gap = any(
        item.section_id != "quantitative_assessment"
        and item.status == "insufficient_information"
        for item in direction_results
    )
    if recommendation == "do_not_proceed":
        expected = "D"
    elif len(weak_failed) >= 5 or {
        "enterprise_norms",
        "financial_position",
    }.issubset(weak_failed) and len(weak_failed) >= 3:
        expected = "D"
    elif weak_failed:
        expected = "C"
    elif non_methodology_information_gap:
        expected = "B"
    else:
        expected = "A"
    if rating_level != expected:
        raise ValueError("rating_level does not match fixed quality boundary")


def _peer_position(
    ranking: DirectionRankingResult | None, case_id: str
) -> dict[str, Any] | None:
    if ranking is None:
        return None
    point = next((item for item in ranking.rank_points if item.case_id == case_id), None)
    if point is not None:
        group = next(group for group in ranking.ranking_groups if case_id in group.case_ids)
        return {
            "rank": point.rank,
            "comparable_company_count": ranking.comparable_company_count,
            "rank_points": point.rank_points,
            "comparison_reason": group.comparison_reason,
        }
    if case_id in ranking.not_comparable_case_ids:
        return {"not_comparable": True, "reason": "该方向材料或口径不足以形成同口径比较。"}
    raise ValueError("direction ranking does not cover the assessment enterprise")


def _build_rationale(raw: Any) -> tuple[OverallAssessmentRationale, ...]:
    if not isinstance(raw, list):
        raise ValueError("rating_rationale must be a list")
    by_id = {
        item.get("dimension_id"): item
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("dimension_id"), str)
    }
    expected = {item[0] for item in ASSESSMENT_DIMENSIONS}
    if set(by_id) != expected or len(by_id) != len(raw):
        raise ValueError("rating_rationale must cover exactly five assessment dimensions")
    titles = dict(ASSESSMENT_DIMENSIONS)
    return tuple(
        OverallAssessmentRationale(
            dimension_id=dimension_id,
            title=titles[dimension_id],
            judgment=_required_text(by_id[dimension_id].get("judgment"), "rationale judgment"),
        )
        for dimension_id, _ in ASSESSMENT_DIMENSIONS
    )


def _selected_ids(raw: Any, allowed: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{field_name} must be a list of strings")
    if len(raw) != len(set(raw)) or not set(raw).issubset(allowed):
        raise ValueError(f"{field_name} contains an unknown or duplicate value")
    return tuple(raw)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)


def _all_text_values(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_all_text_values(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_all_text_values(item) for item in value)
    return ""
