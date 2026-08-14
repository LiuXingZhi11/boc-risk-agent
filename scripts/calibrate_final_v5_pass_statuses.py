"""按统一口径校准 final_v5 的通过状态和推进建议，不调用模型。"""

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

# 仅包含原文事实充分、旧结论只是因“同行指标/非关键明细待补充”而保守的项目。
PASSED_SUMMARIES = {
    "DeepBlue": {
        "technology_strength": "公司已披露核心技术自主研发并实现产业化，拥有392项专利、108项境内发明专利及持续研发投入，技术实力可形成正面判断。",
        "core_team": "招股说明书已披露董事、高管及核心技术人员简历，股权激励已实施，团队基础和稳定性可形成判断。",
    },
    "DeepRobotics": {
        "competition_landscape": "公司已披露产品布局、客户供应商集中度、头部厂商竞争格局及产品出货增长，现有材料足以形成基础竞争判断。",
        "equity_structure": "招股说明书披露朱秋国直接持股15.61%、通过员工持股平台间接控制10.23%，并与李超签署一致行动协议，控制权结构清晰。",
        "core_team": "招股说明书已披露董事、高管、核心技术人员及股权激励安排，团队基础可形成判断。",
        "financial_position": "2025年末货币资金45,479万元、短期借款2,001万元且无长期借款披露，偿债基础可形成判断。",
    },
    "Dobot": {
        "market_space": "公司已披露协作机器人产品商业化、客户验证和收入增长情况，现有材料足以判断其已具备市场化基础。",
        "competition_landscape": "公司已披露产品布局、客户供应商情况及行业竞争事实，现有材料足以形成基础竞争判断。",
    },
    "Ecovacs": {
        "market_space": "企业营业收入在样本中靠前，产品线丰富且均已商业化，市场空间和产品认可度可形成正面判断。",
        "competition_landscape": "企业具备多品类产品布局，2025年前五名客户销售额占17.83%、前五名供应商采购额占14.55%，上下游集中度较低，竞争与供应链基础可形成判断。",
        "enterprise_norms": "公司治理机制规范，内控问题已完成整改且无监管整改要求，2023—2025年营收和经营现金流连续正向，规范性可形成判断。",
        "technology_strength": "企业拥有授权专利2903项，其中发明专利844项，研发投入持续，多款产品已商业化，技术基础可形成判断。",
        "equity_structure": "实际控制人明确，股权激励计划持续实施，治理问题已完成整改，未见控制权争议事实。",
        "transformation": "主营家用服务机器人、智能生活电器、商用服务机器人及零组件，多款产品已商业化，2025年营收约190.4亿元，转型与规模化基础明确。",
        "core_team": "核心团队具备相关管理经验，实际控制人明确，股权激励计划处于有效状态，团队基础可形成判断。",
        "financial_position": "2023—2025年营业收入、经营活动现金流和归母净利润均增长，2025年收入和经营现金流均为样本第1，财务与经营韧性可形成判断。",
    },
    "Efort": {
        "equity_structure": "年报已披露直接控股股东、实际控制人为芜湖市国资委及员工持股平台情况，控制权结构可形成判断。",
        "core_team": "年报已披露创始人长期经营、治理架构及人才投入安排，团队基础可形成判断。",
    },
    "HIT": {
        "equity_structure": "年报已披露控股股东、实际控制人及一致行动关系，控制权结构可形成判断。",
        "core_team": "年报已披露董事、高级管理人员、管理层设置及人才培养安排，团队基础可形成判断。",
    },
    "Leju": {
        "market_space": "招股说明书已披露人形机器人2025年出货量/装机量全球排名及全尺寸产品销售收入，市场化基础可形成判断。",
        "technology_strength": "招股说明书已披露175项授权专利、85项发明专利、研发投入和全栈技术布局，技术实力可形成判断。",
        "core_team": "招股说明书已披露核心技术人员、岗位和员工持股平台信息，团队基础可形成判断。",
        "equity_financing": "招股说明书已披露历次融资、投资协议和股权激励安排，融资事项可形成判断。",
    },
    "Saiwei": {
        "core_team": "年报已披露董事和高级管理人员设置，团队基本信息可形成判断。",
    },
    "Stone": {
        "market_space": "企业2025年营收约186.95亿元、样本第2，产品均已商业化，市场空间和商业化基础可形成判断。",
        "enterprise_norms": "公司治理机制健全，内控无重大或重要缺陷且一般缺陷已整改，营业收入和经营现金流连续三年为正，规范性可形成判断。",
        "technology_strength": "年报已披露研发费用、专利、核心技术人员及产品迭代信息，技术实力可形成判断。",
        "equity_structure": "年报已披露控股股东、实际控制人昌敬及公司治理独立性安排，控制权结构可形成判断。",
        "transformation": "扫地机器人、洗地机、割草机等产品均已商业化，2025年营收较2023年增长超一倍，转型与规模化基础明确。",
        "core_team": "核心团队具备技术、产品和管理复合背景，股权激励有效，团队基础可形成判断。",
    },
    "Tinavi": {
        "equity_structure": "年报已披露控股股东、实际控制人张送根及员工持股平台，控制权结构可形成判断。",
        "core_team": "核心团队专业背景覆盖研发、管理、财务和投资，实际控制人及关键人员均在关键岗位任职，股权激励计划有效，团队基础可形成判断。",
    },
    "Unitree": {
        "market_space": "招股说明书已披露人形机器人2025年出货量超过5,500台、全球第一，以及四足和人形产品商业化增长，市场化基础明确。",
        "competition_landscape": "招股说明书已披露主要客户、客户集中度、产品出货和行业竞争信息，竞争位置可形成判断。",
        "enterprise_norms": "治理机制健全，2023—2025年收入、净利润和经营现金流大幅增长，专利诉讼全部胜诉，规范性可形成判断。",
        "technology_strength": "自研技术覆盖一体化关节、高动态运动控制算法和具身大模型，授权专利262项，核心技术已达大批量生产成熟度，技术实力可形成判断。",
        "equity_structure": "招股说明书已披露王兴兴控制股份及表决权比例、特别表决权机制和股东结构，控制权结构清晰。",
        "core_team": "实际控制人长期担任董事长、总经理和首席技术官，股权激励有效，团队背景与技术路线匹配，团队基础可形成判断。",
        "financial_position": "2025年末货币资金141,925.79万元、短期借款为零且流动负债结构已披露，财务与偿债基础可形成判断。",
    },
    "Yijiahe": {
        "technology_strength": "年报已披露481项授权专利、154项软件著作权、研发费用和自主核心技术，技术实力可形成判断。",
        "equity_structure": "年报已披露控股股东、实际控制人朱付云及一致行动关系变化，控制权结构可形成判断。",
        "core_team": "年报已披露创始人长期经营、治理架构及员工持股计划，团队基础可形成判断。",
    },
}


def _rationale(results):
    groups = {
        "industry_and_commercialization": ("market_space", "competition_landscape"),
        "technology_and_transformation": ("technology_strength", "transformation"),
        "governance_and_capital": (
            "enterprise_norms", "equity_structure", "core_team", "equity_financing"
        ),
        "financial_and_operating_resilience": ("financial_position",),
        "compliance_and_uncertainty": ("aml_sanctions",),
    }
    labels = {
        "passed": "通过",
        "conditional_passed": "有条件通过",
        "failed": "不通过",
        "insufficient_information": "信息不足",
    }
    by_id = {item["section_id"]: item for item in results}
    return [
        {
            "dimension_id": dimension_id,
            "title": title,
            "judgment": "；".join(
                f"{labels[by_id[section_id]['status']]}：{by_id[section_id]['summary']}"
                for section_id in section_ids
            ),
        }
        for dimension_id, title in ASSESSMENT_DIMENSIONS
        for section_ids in (groups[dimension_id],)
    ]


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
        changes = PASSED_SUMMARIES.get(assessment.case_id, {})
        results = []
        for item in assessment.direction_results:
            results.append({
                "section_id": item.section_id,
                "status": "passed" if item.section_id in changes else item.status,
                "summary": changes.get(item.section_id, item.summary),
                "strong_constraint_trigger_code": item.strong_constraint_trigger_code,
                "strong_constraint_trigger_evidence_unit_ids": list(
                    item.strong_constraint_trigger_evidence_unit_ids
                ),
            })
        raw = {
            "rating_level": assessment.rating_level,
            "overall_judgment": assessment.overall_judgment,
            "rating_rationale": _rationale(results),
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
        print(assessment.case_id, len(changes), corrected.recommendation)


if __name__ == "__main__":
    main()
