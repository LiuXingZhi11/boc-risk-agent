"""依据已入库的方向报告补齐 DeepSeek 空响应的最终报告。"""

import sys
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

ASSESSMENTS = {
    "DeepRobotics": {
        "profile_id": "DeepRobotics-rechunk-profile-2026-08-07",
        "rating_level": "B",
        "overall_judgment": "企业在四足、轮足及具身智能机器人领域已形成产品布局，2023—2025 年收入增长、净利润和经营现金流由负转正，治理与团队基础总体可接受；但境外及匿名客户主体、制裁筛查、股权结构明细、债务与现金余额、市场份额及人形机器人放量等关键材料不足。强约束和弱约束均无不通过项，多个非量化方向信息不足，综合评定为 B，建议有条件推进。",
        "rationales": {
            "industry_and_commercialization": "四足和轮足产品已有商业化基础，客户和供应商集中度下降；但人形机器人仍在商业化探索期，市场份额、场景复制和供应链自主可控证据不足。",
            "technology_and_transformation": "企业覆盖感知、控制和具身智能技术路线，四足及轮足产品已实现商业化；技术先进性的同业可比指标、人形产品后续放量及转型配套资料仍需补充。",
            "governance_and_capital": "实际控制人、有效股权激励及无重大未决诉讼等事实形成基础支撑；持股比例、控股股东、激励细节、估值和历史投资协议尚未完整披露。",
            "financial_and_operating_resilience": "收入增长、2025 年净利润转正且经营现金流转正，经营趋势改善；但期末现金余额和有息负债资料缺失，偿债基础尚不能完整验证。",
            "compliance_and_uncertainty": "材料未披露反洗钱或制裁处罚，但部分客户以代称披露，且缺少制裁筛查、出口管制和目标市场认证的专项证据，应在尽调阶段补充。",
        },
        "statuses": {
            "market_space": ("insufficient_information", "四足及轮足产品已实现商业化，人形机器人仍处探索期；缺少市场份额、场景复制和规模化渗透数据，暂无法完整判断市场空间承接能力。"),
            "competition_landscape": ("insufficient_information", "产品覆盖多个具身智能机器人品类，客户与供应商集中度下降；但高端核心零部件依赖、市场份额和上下游明细不足，竞争位置尚不能量化判断。"),
            "enterprise_norms": ("conditional_passed", "实际控制人已披露、股权激励有效且未见重大诉讼或环保处罚披露；持股比例、现金及有息负债等资料仍需补充核实。"),
            "technology_strength": ("conditional_passed", "企业具备多路线技术布局和较高研发投入，四足及轮足产品已形成商业化；同业技术可比指标及人形产品放量能力仍待验证。"),
            "equity_structure": ("insufficient_information", "实际控制人为朱秋国且股权激励有效，未见控制权纠纷的直接披露；持股比例、控股股东和激励安排明细不足，控制权集中度无法完整判断。"),
            "transformation": ("insufficient_information", "企业产品和收入增长反映转型方向明确，但客户主体、商业化细节、关键人员与股权安排等支撑资料不完整，需补充后判断。"),
            "core_team": ("insufficient_information", "核心团队具备高校和产业复合背景并设有激励安排；关键人员履历、实际控制人持股比例和激励细节未完整披露。"),
            "equity_financing": ("insufficient_information", "公司处于成长期且披露已终止回购等特殊权利条款；估值、融资节奏、投资机构和股东协议等核心资料不足，无法形成完整判断。"),
            "financial_position": ("insufficient_information", "2025 年收入增长、净利润和经营现金流转正，但样本内收入排名第 9、现金流排名第 6，且缺少现金余额和有息负债资料，偿债基础待核实。"),
            "quantitative_assessment": ("insufficient_information", "该方向仅用于 2025 年口径假设下的流程验证，不构成正式审批结论。"),
            "aml_sanctions": ("insufficient_information", "未发现反洗钱或制裁处罚的直接披露，但匿名客户真实主体、制裁筛查、出口管制和市场认证资料不足，需完成专项尽调。"),
        },
        "core_risks": (
            "匿名及境外客户真实主体、制裁筛查和出口管制资料不足，合规尽调存在边界。",
            "未披露期末现金余额及有息负债，偿债基础尚不能完整确认。",
            "人形机器人仍处商业化探索阶段，市场份额、场景复制与放量能力待验证。",
        ),
        "mitigating_factors": (
            "2023—2025 年营业收入增长，净利润和经营现金流于 2025 年转正。",
            "四足及轮足机器人已实现商业化，产品覆盖多个具身智能机器人品类。",
            "实际控制人已披露、股权激励有效，且材料未见重大未决诉讼或环保处罚披露。",
        ),
        "verification_priorities": (
            "补充境外及匿名客户、主要供应商的真实法律主体，并完成制裁名单和出口管制筛查。",
            "获取实际控制人持股比例、控股股东、股权激励和历史投资协议明细。",
            "核实期末现金余额、有息负债、期限结构及偿债安排。",
        ),
    },
    "HIT": {
        "profile_id": "HIT-profile-2026-08-11",
        "rating_level": "C",
        "overall_judgment": "企业收入规模在试验样本中相对靠前并具备工业机器人及智能装备产品基础，但 2021 年出现大额亏损、经营现金流再次转负，同时存在多项诉讼和重大担保事项，财务与规范经营压力已有直接不利事实支持。强约束无不通过项，弱约束有企业规范性和财务情况两项不通过，综合评定为 C，建议有条件推进并以风险核实和缓释为前提。",
        "rationales": {
            "industry_and_commercialization": "企业覆盖工业机器人本体、系统集成和智能装备等多类产品，收入规模在样本中居前；但机器人业务占比、细分产品收入、市场份额和客户验证资料不足，商业化质量无法完整评估。",
            "technology_and_transformation": "企业拥有自主研发与专利积累，部分产品已投产或批量供货；研发费用率偏低且下降，产品商业化阶段不一，技术投入持续性和转型支撑需继续验证。",
            "governance_and_capital": "内控无重大缺陷及无重大处罚形成一定基础，但多项诉讼、担保事项和控制权结构明细不足，治理透明度及或有负债影响需审慎评估。",
            "financial_and_operating_resilience": "收入规模相对稳定，但 2021 年大额亏损且经营现金流转负；在缺少期末现金和有息负债资料的情况下，偿债与持续经营压力不能忽略。",
            "compliance_and_uncertainty": "未发现已确认的反洗钱或制裁违规，但客户和供应商匿名、未决诉讼及担保资料不完整，须完成交易对手和事项尽调。",
        },
        "statuses": {
            "market_space": ("insufficient_information", "企业产品覆盖多个机器人应用场景，收入规模在样本中排名第 3；但机器人业务占比、分产品收入和市场渗透数据不足，无法完整判断市场空间。"),
            "competition_landscape": ("insufficient_information", "企业覆盖本体制造、系统集成和应用环节，但市场份额、核心零部件来源及客户供应商真实主体资料不足，竞争位置难以精确判断。"),
            "enterprise_norms": ("failed", "虽然内控无重大缺陷且未见重大处罚披露，但存在多项诉讼、赔偿和重大担保事项，且经营现金流承压，已对规范经营和或有负债形成直接不利影响。"),
            "technology_strength": ("conditional_passed", "企业具有自主研发、专利积累和多产品商业化基础；但研发费用率偏低且下降，技术稳定性和同行先进性资料不足，需持续跟踪。"),
            "equity_structure": ("insufficient_information", "实际控制人为乔徽和艾迪，未见控制权纠纷的直接披露；但持股比例、最终控制结构及诉讼担保对控制权稳定性的影响资料不足。"),
            "transformation": ("insufficient_information", "部分机器人产品已投产或批量供货，但产品商业化阶段差异较大，近三年收入基本持平且缺少分产品数据，转型支撑能力尚无法完整判断。"),
            "core_team": ("insufficient_information", "核心团队具有机器人、投资、财务和管理背景，但股权激励不适用，长期技术路线及关键人员稳定性的证据不足。"),
            "equity_financing": ("conditional_passed", "融资、估值和投资协议资料不足，且诉讼和担保可能影响后续融资；现有材料不足以认定其已构成融资方向的直接不通过，但需补充协议与估值资料。"),
            "financial_position": ("failed", "2021 年出现大额亏损，经营活动现金流再次转负；同时缺少期末现金和有息负债资料，已披露的盈利与现金流压力直接影响偿债基础判断。"),
            "quantitative_assessment": ("insufficient_information", "该方向仅用于 2025 年口径假设下的流程验证，不构成正式审批结论。"),
            "aml_sanctions": ("insufficient_information", "未披露已确认的反洗钱或制裁违规；但客户和供应商匿名、未决诉讼及担保细节不足，应开展强化交易对手和事项尽调。"),
        },
        "core_risks": (
            "2021 年大额亏损且经营现金流再次转负，盈利与现金回收承压。",
            "存在多项诉讼、赔偿和重大担保事项，或有负债及其对经营的影响需核实。",
            "期末现金余额、有息负债、客户供应商真实主体及融资协议资料不足。",
        ),
        "mitigating_factors": (
            "企业具备工业机器人及智能装备多产品布局，部分产品已投产或批量供货。",
            "收入规模在试验样本中排名第 3，且内控评价未见重大缺陷、材料未见重大处罚披露。",
            "企业具有自主研发与专利积累，形成一定技术转化基础。",
        ),
        "verification_priorities": (
            "核实重大担保余额、被担保方、期限、反担保及诉讼事项的最新进展和预计损失。",
            "补充期末现金余额、有息负债、债务期限结构和偿债安排。",
            "补充客户供应商真实主体、股权结构、融资协议及估值资料，并完成交易对手尽调。",
        ),
    },
}


def main() -> None:
    approval_repository = ApprovalRepository(DATABASE)
    profile_repository = ProfileRepository(DATABASE)
    cohort = approval_repository.get_cohort(COHORT_ID)
    rankings = tuple(
        approval_repository.list_direction_rankings(COHORT_ID, review_status="pending")
    )
    for case_id, content in ASSESSMENTS.items():
        profile = profile_repository.get(content["profile_id"])
        reports = tuple(
            approval_repository.list_domain_reports(
                cohort_id=COHORT_ID,
                case_id=case_id,
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
        evidence_ids = tuple(
            dict.fromkeys(
                report.approval_points[0].evidence_refs[0].evidence_unit_id
                for report in reports
            )
        )
        raw = {
            "rating_level": content["rating_level"],
            "overall_judgment": content["overall_judgment"],
            "rating_rationale": [
                {
                    "dimension_id": dimension_id,
                    "title": title,
                    "judgment": content["rationales"][dimension_id],
                }
                for dimension_id, title in ASSESSMENT_DIMENSIONS
            ],
            "core_risks": list(content["core_risks"]),
            "mitigating_factors": list(content["mitigating_factors"]),
            "rating_boundaries": [
                "本评定基于 2025 年智能机器人同行假设口径试验样本，结果仅用于流程验证，不得用于正式审批结论。",
                "企业画像保留各自源文件报告期；方向名次仅用于相对位置参考，不能相加、平均或直接换算等级。",
                "量化评估工具应用为试验性方法检查，不构成企业风险不通过项。",
            ],
            "verification_priorities": list(content["verification_priorities"]),
            "evidence_unit_ids": list(evidence_ids),
            "direction_results": [
                {
                    "section_id": section_id,
                    "status": status,
                    "summary": summary,
                    "strong_constraint_trigger_code": None,
                    "strong_constraint_trigger_evidence_unit_ids": [],
                }
                for section_id, (status, summary) in content["statuses"].items()
            ],
        }
        assessment = validate_overall_assessment_output(
            f"robotics_2025_assumption_{case_id}_final_v5",
            package,
            reports,
            rankings,
            raw,
        )
        approval_repository.save_overall_assessment(assessment)
        print(
            case_id,
            assessment.rating_level,
            assessment.recommendation,
            assessment.strong_constraint_failed_count,
            assessment.weak_constraint_failed_count,
        )


if __name__ == "__main__":
    main()
