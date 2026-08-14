"""用已校正的 11 条方向结论同步最终报告总体判断和五类依据。"""

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.overall_assessment import (
    ASSESSMENT_DIMENSIONS,
    build_overall_assessment_package,
    validate_overall_assessment_output,
)
from src.approval.repository import ApprovalRepository
from src.profiles.repository import ProfileRepository


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"
DIMENSION_SECTIONS = {
    "industry_and_commercialization": ("market_space", "competition_landscape"),
    "technology_and_transformation": ("technology_strength", "transformation"),
    "governance_and_capital": (
        "enterprise_norms",
        "equity_structure",
        "core_team",
        "equity_financing",
    ),
    "financial_and_operating_resilience": ("financial_position",),
    "compliance_and_uncertainty": ("aml_sanctions",),
}
RECOMMENDATION_LABELS = {
    "proceed_with_caution": "可推进",
    "proceed_with_review": "审慎推进",
    "conditional_proceed": "有条件推进",
    "do_not_proceed": "不建议推进",
}


def _status_label(status: str) -> str:
    return {
        "passed": "通过",
        "conditional_passed": "有条件通过",
        "failed": "不通过",
        "insufficient_information": "信息不足",
    }[status]


def main() -> None:
    approval_repository = ApprovalRepository(DATABASE)
    profile_repository = ProfileRepository(DATABASE)
    cohort = approval_repository.get_cohort(COHORT_ID)
    rankings = tuple(approval_repository.list_direction_rankings(COHORT_ID, review_status="pending"))

    for assessment in approval_repository.list_overall_assessments(
        cohort_id=COHORT_ID,
        review_status="pending",
    ):
        if not assessment.assessment_id.endswith("_final_v5"):
            continue
        profile = profile_repository.list(case_id=assessment.case_id)[0]
        reports = tuple(
            approval_repository.list_domain_reports(
                cohort_id=COHORT_ID,
                case_id=assessment.case_id,
                review_status="pending",
            )
        )
        package = build_overall_assessment_package(
            enterprise_name=profile.enterprise_name,
            profile_reporting_periods=tuple(
                sorted({item.reporting_period for item in profile.items if item.reporting_period})
            ),
            cohort_name=cohort.cohort_name,
            cohort_fiscal_period=cohort.fiscal_period,
            cohort_selection_rule=cohort.selection_rule,
            reports=reports,
            rankings=rankings,
            is_experimental=True,
        )
        results = {item.section_id: item for item in assessment.direction_results}
        rationale = []
        for dimension_id, title in ASSESSMENT_DIMENSIONS:
            sections = DIMENSION_SECTIONS[dimension_id]
            rationale.append(
                {
                    "dimension_id": dimension_id,
                    "title": title,
                    "judgment": "；".join(
                        f"{_status_label(results[section_id].status)}：{results[section_id].summary}"
                        for section_id in sections
                    ),
                }
            )
        insufficient = [
            item.section_id
            for item in assessment.direction_results
            if item.status == "insufficient_information"
            and item.section_id != "quantitative_assessment"
        ]
        risk_text = "；".join(assessment.core_risks[:2])
        overall = (
            f"强约束不通过{assessment.strong_constraint_failed_count}项、弱约束不通过"
            f"{assessment.weak_constraint_failed_count}项，综合等级为{assessment.rating_level}，"
            f"推进建议为“{RECOMMENDATION_LABELS[assessment.recommendation]}”。"
            f"已披露的主要风险为：{risk_text}。"
        )
        if insufficient:
            overall += f"仍需补充核实的方向为：{'、'.join(insufficient)}。"
        else:
            overall += "除试验性量化评估外，当前方向结论均可形成通过或有条件通过判断。"
        overall += "本报告仅适用于2025年同行样本假设口径下的流程验证。"
        raw = {
            "rating_level": assessment.rating_level,
            "overall_judgment": overall,
            "rating_rationale": rationale,
            "core_risks": list(assessment.core_risks),
            "mitigating_factors": list(assessment.mitigating_factors),
            "rating_boundaries": list(assessment.rating_boundaries),
            "verification_priorities": list(assessment.verification_priorities),
            "evidence_unit_ids": [item.evidence_unit_id for item in assessment.evidence_refs],
            "direction_results": [
                {
                    **asdict(item),
                    "strong_constraint_trigger_evidence_unit_ids": list(
                        item.strong_constraint_trigger_evidence_unit_ids
                    ),
                }
                for item in assessment.direction_results
            ],
        }
        corrected = validate_overall_assessment_output(
            assessment.assessment_id,
            package,
            reports,
            rankings,
            raw,
        )
        approval_repository.save_overall_assessment(corrected)
        print(assessment.case_id, corrected.rating_level, ",".join(insufficient) or "no_gaps")


if __name__ == "__main__":
    main()
