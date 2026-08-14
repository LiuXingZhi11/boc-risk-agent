"""将全量原 PDF 复核确认的遗漏事实补入当前 final_v5。"""

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.overall_assessment import (
    build_overall_assessment_package,
    validate_overall_assessment_output,
)
from src.approval.repository import ApprovalRepository
from src.profiles.repository import ProfileRepository


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"
CORRECTIONS = {
    "Efort": {
        "market_space": "年报披露公司在锂电、电子制造、汽车及汽车零部件等行业的工业机器人销量增长和灯塔客户订单突破；但2025年整机营业收入下降、价格竞争加剧，市场增长兑现仍需跟踪，结论为有条件通过。",
        "competition_landscape": "年报披露喷涂机器人示范应用、批量推广、软件产品销售，以及与多家行业客户合作；但价格竞争、核心零部件外购及海外订单波动仍影响竞争稳定性，结论为有条件通过。",
    },
    "HIT": {
        "market_space": "年报披露机器人本体销售出货量783台、已签约订单千余台并与23家客户达成年度战略合作，企业具备市场化基础；但机器人业务规模、回款和持续经营压力仍需跟踪，结论为有条件通过。",
        "competition_landscape": "年报披露机器人本体、系统集成和应用布局及主要汽车客户，现有材料足以形成基础竞争判断；但企业自身市场份额、核心零部件来源和竞争稳定性仍需持续核实，结论为有条件通过。",
    },
    "Yijiahe": {
        "market_space": "年报披露清洁、巡检、操作、消防等机器人产品与电力、商用清洁等客户场景，并披露2025年营业收入；但收入连续下降、部分产品仍在开发或测试，市场增长与渗透空间需跟踪，结论为有条件通过。",
        "competition_landscape": "年报披露不同业务的客户类型、获取订单方式、产品差异化定位和供应链组织，现有材料足以形成基础竞争与产业链判断；但细分赛道份额、排名和核心零部件自给率未披露，结论为有条件通过。",
    },
}


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
        changes = CORRECTIONS.get(assessment.case_id, {})
        if not changes:
            continue
        profile = profiles.list(case_id=assessment.case_id)[0]
        reports = tuple(approvals.list_domain_reports(
            cohort_id=COHORT_ID, case_id=assessment.case_id, review_status="pending"
        ))
        package = build_overall_assessment_package(
            enterprise_name=profile.enterprise_name,
            profile_reporting_periods=tuple(sorted({
                item.reporting_period for item in profile.items if item.reporting_period
            })),
            cohort_name=cohort.cohort_name,
            cohort_fiscal_period=cohort.fiscal_period,
            cohort_selection_rule=cohort.selection_rule,
            reports=reports,
            rankings=rankings,
            is_experimental=True,
        )
        results = [
            {
                "section_id": item.section_id,
                "status": "conditional_passed" if item.section_id in changes else item.status,
                "summary": changes.get(item.section_id, item.summary),
                "strong_constraint_trigger_code": item.strong_constraint_trigger_code,
                "strong_constraint_trigger_evidence_unit_ids": list(
                    item.strong_constraint_trigger_evidence_unit_ids
                ),
            }
            for item in assessment.direction_results
        ]
        raw = {
            "rating_level": assessment.rating_level,
            "overall_judgment": assessment.overall_judgment,
            "rating_rationale": [asdict(item) for item in assessment.rating_rationale],
            "core_risks": list(assessment.core_risks),
            "mitigating_factors": list(assessment.mitigating_factors),
            "rating_boundaries": list(assessment.rating_boundaries),
            "verification_priorities": list(assessment.verification_priorities),
            "evidence_unit_ids": [item.evidence_unit_id for item in assessment.evidence_refs],
            "direction_results": results,
        }
        corrected = validate_overall_assessment_output(
            assessment.assessment_id, package, reports, rankings, raw
        )
        approvals.save_overall_assessment(corrected)
        print(assessment.case_id, ",".join(changes), corrected.rating_level)


if __name__ == "__main__":
    main()
