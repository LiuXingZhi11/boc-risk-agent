"""用已校正的逐条审批结论重建最终报告的风险与核实清单。"""

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.overall_assessment import (
    build_overall_assessment_package,
    validate_overall_assessment_output,
)
from src.approval.repository import ApprovalRepository
from src.approval.guideline_definitions import GUIDELINE_SECTION_DEFINITIONS
from src.profiles.repository import ProfileRepository


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"
SECTION_TITLES = {
    item.section_id: item.title for item in GUIDELINE_SECTION_DEFINITIONS
}
VERIFICATION_ACTIONS = {
    "market_space": "补充企业自身细分市场份额、口径和主要客户验证材料。",
    "competition_landscape": "补充主要竞争对手、客户和供应商集中度的最新口径。",
    "technology_strength": "补充核心技术成熟度、应用成效及可比竞争证明。",
    "equity_structure": "补充最新股权穿透、控制权及权利负担核验材料。",
    "transformation": "补充产品量产、订单、收入或场景落地的最新证明。",
    "core_team": "补充核心人员稳定性、激励约束及关键岗位安排。",
    "equity_financing": "补充融资协议、特殊权利和潜在回购义务的当前状态。",
    "financial_position": "补充最新财务报表、债务明细和现金流资料。",
    "enterprise_norms": "补充公司治理、诉讼担保及关联交易的最新核验材料。",
    "aml_sanctions": "补充客户、交易对手的实名穿透及制裁、反洗钱筛查资料。",
    "quantitative_assessment": "待样本口径稳定后，再补充可比指标和量化结果。",
}


def _selected_results(assessment):
    return tuple(
        item
        for item in assessment.direction_results
        if item.status in {"failed", "insufficient_information"}
    )


def main() -> None:
    approvals = ApprovalRepository(DATABASE)
    profiles = ProfileRepository(DATABASE)
    cohort = approvals.get_cohort(COHORT_ID)
    rankings = tuple(approvals.list_direction_rankings(COHORT_ID, review_status="pending"))

    for assessment in approvals.list_overall_assessments(
        cohort_id=COHORT_ID, review_status="pending"
    ):
        if not assessment.assessment_id.endswith("_final_v5"):
            continue
        profile = profiles.list(case_id=assessment.case_id)[0]
        reports = tuple(
            approvals.list_domain_reports(
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
        selected = _selected_results(assessment)
        core_risks = [
            f"{SECTION_TITLES[item.section_id]}：{item.summary}"
            for item in selected
            if item.section_id != "quantitative_assessment"
        ]
        priorities = [
            f"{SECTION_TITLES[item.section_id]}：{VERIFICATION_ACTIONS[item.section_id]}"
            for item in selected
        ]
        raw = {
            "rating_level": assessment.rating_level,
            "overall_judgment": assessment.overall_judgment,
            "rating_rationale": [asdict(item) for item in assessment.rating_rationale],
            "core_risks": core_risks or list(assessment.core_risks),
            "mitigating_factors": list(assessment.mitigating_factors),
            "rating_boundaries": list(assessment.rating_boundaries),
            "verification_priorities": priorities or list(assessment.verification_priorities),
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
            assessment.assessment_id, package, reports, rankings, raw
        )
        approvals.save_overall_assessment(corrected)
        print(assessment.case_id, len(core_risks), len(priorities))


if __name__ == "__main__":
    main()
