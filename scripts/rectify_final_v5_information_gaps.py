"""依据原始 PDF 已入库证据，修正 final_v5 中误判为信息不足的方向。"""

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

# 仅列入“企业自身原文已明确披露”的方向；市场份额、制裁筛查等仍缺企业直接披露的事项不改。
CORRECTIONS = {
    "DeepBlue": {
        "market_space": "公司水下机器人产品已有销售基础，核心人员主持的缆控水下机器人年出货量超过100台；但企业自身细分市场份额和客户验证口径未统一披露，结论调整为有条件通过。",
        "competition_landscape": "公司产品覆盖缆控、自主及助推水下机器人，客户集中度下降，且已有产品出货和行业应用基础；缺少统一口径的企业市场份额，结论调整为有条件通过。",
        "technology_strength": "公司披露核心技术自主研发并实现产业化，拥有392项专利、108项境内发明专利及稳定研发投入；缺少同行量化对照，结论调整为有条件通过。",
        "core_team": "招股说明书已披露董事、高管及核心技术人员简历，股权激励已实施；团队能力可形成实质判断，结论调整为有条件通过。",
        "equity_financing": "招股说明书已披露历次增资、投资协议及特殊权利安排；仍需关注相关条款的当前效力，结论调整为有条件通过。",
    },
    "DeepRobotics": {
        "market_space": "公司在电力巡检、应急消防、工业巡检和警务安防等领域已有场景探索和规模化落地，绝影 Lite 系列出货增长；缺少统一市场份额口径，结论调整为有条件通过。",
        "competition_landscape": "公司已披露产品布局、客户供应商集中度、头部厂商竞争格局及产品出货增长；虽缺精确市场份额，仍可形成竞争判断，结论调整为有条件通过。",
        "equity_structure": "招股说明书披露朱秋国直接持股15.61%、通过员工持股平台间接控制10.23%，并与李超签署一致行动协议；控制权结构可形成判断，结论调整为有条件通过。",
        "transformation": "四足及轮足产品已在多场景落地，绝影 Lite 系列出货增长并带动单位成本下降；人形机器人后续放量仍待观察，结论调整为有条件通过。",
        "core_team": "招股说明书已披露董事、高管、核心技术人员及股权激励安排；部分人员信息可继续补充，但团队基础可形成判断，结论调整为有条件通过。",
        "equity_financing": "公司已披露多轮股权融资、投资协议及实际控制人向公司提供借款的安排；需持续关注关联资金安排，结论调整为有条件通过。",
        "financial_position": "2025年末货币资金45,479万元、短期借款2,001万元且无长期借款披露，偿债资料已可形成基础判断；结论调整为有条件通过。",
    },
    "Dobot": {
        "market_space": "公司已披露协作机器人产品商业化、客户验证和收入增长情况；虽缺统一市场份额口径，结论调整为有条件通过。",
        "competition_landscape": "公司已披露产品布局、客户供应商情况及行业竞争事实；缺少精确市场份额不妨碍形成基础竞争判断，结论调整为有条件通过。",
        "equity_financing": "公司已披露港股上市、历次投资协议及特殊股东权利终止安排；需持续关注条款恢复条件，结论调整为有条件通过。",
    },
    "Efort": {
        "technology_strength": "年报已披露研发投入、专利和工业机器人产品技术基础；虽存在研发持续性与经营压力，技术方向可形成判断，结论调整为有条件通过。",
        "equity_structure": "年报已披露直接控股股东、实际控制人为芜湖市国资委及员工持股平台情况；结论调整为有条件通过。",
        "transformation": "年报已披露具身智能投入、产品研发、量产组织及募投项目情况；转型成效仍需跟踪，结论调整为有条件通过。",
        "core_team": "年报已披露创始人长期经营、治理架构及人才投入安排；团队基础可形成判断，结论调整为有条件通过。",
        "equity_financing": "年报已披露子公司融资、股权交易和资本运作事项；需关注亏损背景下的融资影响，结论调整为有条件通过。",
    },
    "HIT": {
        "equity_structure": "年报已披露控股股东为无锡哲方哈工智能机器人投资企业、实际控制人为乔徽和艾迪，并披露一致行动关系；诉讼和担保影响仍需持续核实，结论调整为有条件通过。",
        "transformation": "年报已披露机器人本体销售783台、千余台签约订单、23家年度战略合作客户及研发中心募投项目；转型成效存在经营压力，结论调整为有条件通过。",
        "core_team": "年报已披露董事、高级管理人员、管理层设置及人才培养安排；股权激励尚未实施，结论调整为有条件通过。",
    },
    "Leju": {
        "market_space": "招股说明书已披露公司人形机器人2025年出货量/装机量全球排名及全尺寸产品销售收入；结论调整为有条件通过。",
        "technology_strength": "招股说明书已披露175项授权专利、85项发明专利、研发投入和全栈技术布局；结论调整为有条件通过。",
        "transformation": "招股说明书已披露全尺寸人形机器人销售收入17,778.26万元及收入快速增长；工业规模化应用仍在起步期，结论调整为有条件通过。",
        "core_team": "招股说明书已披露核心技术人员、岗位和员工持股平台信息；结论调整为有条件通过。",
        "equity_financing": "招股说明书已披露历次融资、投资协议和股权激励安排；结论调整为有条件通过。",
    },
    "Saiwei": {
        "equity_structure": "年报已披露控股股东、实际控制人及股权结构相关事项；在既有法律风险背景下，结论调整为有条件通过。",
        "core_team": "年报已披露董事和高级管理人员设置；虽缺更细技术团队资料，结论调整为有条件通过。",
        "equity_financing": "年报已披露融资、增资和资本运作事项；在经营与合规风险背景下，结论调整为有条件通过。",
    },
    "Stone": {
        "competition_landscape": "年报已披露主要客户供应商、产品销售和行业竞争信息；缺少统一市场份额口径，结论调整为有条件通过。",
        "technology_strength": "年报已披露研发费用、专利、核心技术人员及产品迭代信息；结论调整为有条件通过。",
        "equity_structure": "年报已披露控股股东、实际控制人昌敬及公司治理独立性安排；结论调整为有条件通过。",
        "equity_financing": "年报已披露私募基金投资、股权投资及资本运作信息；结论调整为有条件通过。",
    },
    "Tinavi": {
        "competition_landscape": "年报已披露骨科手术机器人产品、商业化和行业竞争信息；缺少统一市场份额口径，结论调整为有条件通过。",
        "equity_structure": "年报已披露控股股东、实际控制人张送根及员工持股平台；结论调整为有条件通过。",
        "transformation": "年报已披露产品商业化、募投项目和技术服务布局；结论调整为有条件通过。",
        "equity_financing": "年报已披露限制性股票激励、子公司投资协议及潜在回购义务；结论调整为有条件通过。",
    },
    "Unitree": {
        "market_space": "招股说明书已披露人形机器人2025年出货量超过5,500台、全球第一，以及四足和人形产品商业化增长；结论调整为有条件通过。",
        "competition_landscape": "招股说明书已披露主要客户、客户集中度、产品出货和行业竞争信息；结论调整为有条件通过。",
        "equity_structure": "招股说明书已披露王兴兴控制股份及表决权比例、特别表决权机制和股东结构；结论调整为有条件通过。",
        "transformation": "公司已披露多产品商业化、快速收入增长和人形机器人出货增长；结论调整为有条件通过。",
        "financial_position": "2025年末货币资金141,925.79万元、短期借款为零且流动负债结构已披露；结论调整为有条件通过。",
    },
    "Yijiahe": {
        "technology_strength": "年报已披露481项授权专利、154项软件著作权、研发费用和自主核心技术；结论调整为有条件通过。",
        "equity_structure": "年报已披露控股股东、实际控制人朱付云及一致行动关系变化；结论调整为有条件通过。",
        "transformation": "年报已披露具身智能子公司、场景测试、产品研发及募投项目；转型仍处验证阶段，结论调整为有条件通过。",
        "core_team": "年报已披露创始人长期经营、治理架构及员工持股计划；结论调整为有条件通过。",
        "equity_financing": "年报已披露员工持股计划、对子公司增资及资本运作事项；结论调整为有条件通过。",
    },
}


def main() -> None:
    approval_repository = ApprovalRepository(DATABASE)
    profile_repository = ProfileRepository(DATABASE)
    cohort = approval_repository.get_cohort(COHORT_ID)
    rankings = tuple(approval_repository.list_direction_rankings(COHORT_ID, review_status="pending"))
    lines = ["# final_v5 信息不足专项审查结果", "", "## 修正原则", "", "仅将原始 PDF 已明确披露、但最终方向结论未使用的企业事实调整为“有条件通过”；企业自身市场份额、制裁筛查等仍无直接披露的事项保留为“信息不足”。", ""]

    for assessment in approval_repository.list_overall_assessments(
        cohort_id=COHORT_ID,
        review_status="pending",
    ):
        if not assessment.assessment_id.endswith("_final_v5"):
            continue
        corrections = CORRECTIONS.get(assessment.case_id, {})
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
        results = []
        for item in assessment.direction_results:
            status, summary = (
                ("conditional_passed", corrections[item.section_id])
                if item.section_id in corrections
                else (item.status, item.summary)
            )
            results.append(
                {
                    "section_id": item.section_id,
                    "status": status,
                    "summary": summary,
                    "strong_constraint_trigger_code": item.strong_constraint_trigger_code,
                    "strong_constraint_trigger_evidence_unit_ids": list(
                        item.strong_constraint_trigger_evidence_unit_ids
                    ),
                }
            )
        constraints = {
            item.section_id: item.constraint_level for item in GUIDELINE_SECTION_DEFINITIONS
        }
        weak_failed = {
            item["section_id"]
            for item in results
            if constraints[item["section_id"]] == "weak"
            and item["section_id"] != "quantitative_assessment"
            and item["status"] == "failed"
        }
        strong_failed = any(
            constraints[item["section_id"]] == "strong" and item["status"] == "failed"
            for item in results
        )
        has_non_quantitative_gap = any(
            item["section_id"] != "quantitative_assessment"
            and item["status"] == "insufficient_information"
            for item in results
        )
        if strong_failed or len(weak_failed) >= 5 or (
            len(weak_failed) >= 3
            and {"enterprise_norms", "financial_position"}.issubset(weak_failed)
        ):
            rating_level = "D"
        elif weak_failed:
            rating_level = "C"
        elif has_non_quantitative_gap:
            rating_level = "B"
        else:
            rating_level = "A"
        raw = {
            "rating_level": rating_level,
            "overall_judgment": assessment.overall_judgment + " 原始报告已披露的控制权、团队、财务或融资事实已在本次专项审查中纳入判断；未披露企业自身市场份额、制裁筛查等事项仍保留为后续核实边界。",
            "rating_rationale": [asdict(item) for item in assessment.rating_rationale],
            "core_risks": list(assessment.core_risks),
            "mitigating_factors": list(assessment.mitigating_factors),
            "rating_boundaries": list(assessment.rating_boundaries),
            "verification_priorities": list(assessment.verification_priorities),
            "evidence_unit_ids": [item.evidence_unit_id for item in assessment.evidence_refs],
            "direction_results": results,
        }
        corrected = validate_overall_assessment_output(
            assessment.assessment_id,
            package,
            reports,
            rankings,
            raw,
        )
        approval_repository.save_overall_assessment(corrected)
        retained = [
            item["section_id"]
            for item in results
            if item["status"] == "insufficient_information"
            and item["section_id"] != "quantitative_assessment"
        ]
        lines.extend(
            (
                f"## {assessment.case_id}",
                "",
                f"- 已修正为有条件通过：{'、'.join(corrections) or '无'}。",
                f"- 保留信息不足：{'、'.join(retained) or '无'}。",
                f"- 修正后等级：{corrected.rating_level}；强约束不通过 {corrected.strong_constraint_failed_count} 条，弱约束不通过 {corrected.weak_constraint_failed_count} 条。",
                "",
            )
        )
    Path("data/audits/final_v5_information_gap_review.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print("data/audits/final_v5_information_gap_review.md")


if __name__ == "__main__":
    main()
