"""用 UTF-8 源文件修复人工复核时被控制台转码损坏的综合评定文本。"""

from dataclasses import replace

from src.approval.models import OverallAssessmentRationale
from src.approval.repository import ApprovalRepository


COHORT_ID = "robotics_2025_assumption_test"


def save(repo: ApprovalRepository, assessments: dict[str, object], case_id: str, **changes: object) -> None:
    repo.save_overall_assessment(replace(assessments[case_id], **changes))


def main() -> None:
    repo = ApprovalRepository("data/current_project.db")
    assessments = {
        item.case_id: item
        for item in repo.list_overall_assessments(cohort_id=COHORT_ID)
    }

    save(
        repo,
        assessments,
        "Ecovacs",
        rating_level="A",
        overall_judgment="企业经营、盈利和现金流表现强劲，2023—2025年营业收入由155.02亿元增至190.40亿元，归母净利润由6.12亿元增至17.58亿元，经营活动现金流由10.91亿元增至33.87亿元；产品已商业化，治理基础明确。在当前12家试验样本和现有材料范围内，未发现足以改变整体判断的企业特有重大不利事项，综合评定为A。国际贸易、技术迭代和市场竞争属于持续跟踪事项；客户逐户KYC、债务明细等未入库信息仅构成核查边界，不作为不利事实。本结论为试验性待审核结果，不构成正式审批结论。",
        rating_rationale=(
            OverallAssessmentRationale("industry_and_commercialization", "行业与商业化", "主营业务覆盖家用服务机器人、智能生活电器、商用服务机器人及机器人智能零组件，多款产品已商业化；2025年营业收入约190.40亿元，位列当前12家试验样本第1。市场份额、渗透率等未入库指标限制精细比较，但不影响已披露商业化和经营规模判断。"),
            OverallAssessmentRationale("technology_and_transformation", "技术与转化", "企业拥有授权专利2903项，技术来源为自主研发；2025年研发费用率约5.15%，DEEBOT X11等产品已实现商业化。技术先进性缺少统一可比口径，应持续观察，但现有材料未显示技术转化存在重大障碍。"),
            OverallAssessmentRationale("governance_and_capital", "治理与资本", "实际控制关系明确，内部控制问题已完成整改且无监管整改要求，股权激励计划有效。控股股东具体持股和质押明细未在当前画像中结构化保存，属于后续核查事项，不据此推定控制权风险。"),
            OverallAssessmentRationale("financial_and_operating_resilience", "财务与经营韧性", "2023—2025年营业收入由155.02亿元增至190.40亿元，经营活动现金流由10.91亿元增至33.87亿元，归母净利润由6.12亿元增至17.58亿元，收入和现金流均位列样本第1，财务经营支撑强。债务构成仍应在正式审查时结合报表附注核实。"),
            OverallAssessmentRationale("compliance_and_uncertainty", "合规与不确定性", "现有材料未显示重大合规处罚或未决重大事项，主要客户和供应商均披露为非关联方。国际贸易、知识产权、出口管制和市场竞争是行业与跨境经营的持续跟踪事项；逐户交易对手筛查所需资料尚未进入画像，不能据此认定存在合规不利事实。"),
        ),
        core_risks=("国际贸易、知识产权和市场竞争变化可能影响经营表现", "关键零部件供应与技术迭代需持续跟踪", "跨境业务应持续关注出口管制及海外准入要求"),
        rating_boundaries=("当前画像未结构化保存有息负债、控股股东持股及质押等细项，正式审查应结合年报附注和权属材料核实；该缺口不等同于不利事实。", "市场份额、渗透率和技术先进性缺少统一同业可比口径，限制精细比较。", "本样本为试验假设，包含其他企业按非2025年事实参与排名，结果不得用于正式审批结论。"),
        verification_priorities=("正式审查时补充有息负债、现金及现金等价物、控股股东持股和质押等明细。", "获取核心零部件供应安排、高端产品占比及海外业务敞口资料。", "持续跟踪国际贸易、知识产权纠纷及出口管制政策变化。", "补充市场份额、渗透率和同行可比指标，完善相对竞争力判断。"),
    )

    unitree = assessments["Unitree"]
    unitree_rationale = list(unitree.rating_rationale)
    unitree_rationale[2] = OverallAssessmentRationale("governance_and_capital", "治理与资本", "实际控制人王兴兴明确，任董事长、总经理、首席技术官；原始材料已披露其持股及表决权安排，股权激励计划有效，核心团队以研发和经营管理背景为主。未来股份支付费用可能影响经营业绩，社保公积金缴纳人数与员工人数存在少量差异，需持续跟踪。")
    unitree_rationale[4] = OverallAssessmentRationale("compliance_and_uncertainty", "合规与不确定性", "企业披露的与露韦美公司相关专利诉讼已胜诉、驳回原告或审结，不能再表述为仍存未决诉讼风险；报告期内社保公积金无违法违规、未见行政处罚。境外交易对手以代称披露，正式审查仍应补充真实主体信息以完成制裁与出口管制核查，但该信息边界本身不等同于企业存在合规不利事实。")
    save(repo, assessments, "Unitree", overall_judgment="企业处于高成长机器人赛道，技术与商业化基础扎实，2023—2025年收入、利润和经营现金流快速增长，实际控制关系明确，已披露专利诉讼均已审结或获有利处理。考虑到人形机器人规模化商业化、研发投入趋势、股份支付以及跨境交易核查仍需持续观察，综合评定为B。交易对手名称未入库及债务明细不足属于核查边界，不直接作为不利事实。", rating_rationale=tuple(unitree_rationale), core_risks=("人形机器人规模化商业化和增长持续性仍需跨年度验证。", "未来股份支付费用可能对经营业绩产生影响。", "研发费用率下降需结合研发项目进展和技术投入材料持续观察。", "境外业务及关键供应链的出口管制、认证与供应连续性需持续跟踪。"), rating_boundaries=("本评定基于2025年智能机器人同行假设口径试验样本，结果不得用于正式审批结论。", "样本中哈工智能以2021年最新事实、赛为智能以2024年最新事实按2025年口径假设参与排名，保留企业画像原始报告期。", "输入材料未提供完整同行可比指标，部分方向缺少量化同行比较。", "已披露的实际控制人持股及表决权安排、专利诉讼结论已纳入判断；有息负债余额、产能利用率、成本结构、部分交易对手真实主体等尚未结构化入库，属于后续核查边界。", "方向名次仅反映样本内相对位置，不得简单相加或平均，重大风险不能被多个优势名次抵消。"), verification_priorities=("获取有息负债明细、产能利用率和成本结构，评估财务杠杆、盈利质量和规模化能力。", "对境外客户、供应商补充真实法律主体资料，完成制裁名单、出口管制物项和海外认证核查。", "持续跟踪人形机器人客户验证、市场份额、研发项目进展及股份支付对损益的影响。", "跟踪实际控制人持股、表决权安排及股权结构变动，不再将已披露持股安排视为缺失。"))

    saiwei = assessments["Saiwei"]
    saiwei_rationale = list(saiwei.rating_rationale)
    saiwei_rationale[4] = OverallAssessmentRationale("compliance_and_uncertainty", "合规与不确定性", "企业存在历史监管处罚（虚假陈述）、未决诉讼/仲裁、债务重组及保留意见审计报告，重大不确定性较高。前五大客户和供应商按年报惯例以代称列示，且客户集中度高；交易对手真实主体资料不足以完成制裁名单与受益所有人核查，该项属于信息边界，不单独作为企业已发生合规风险。")
    save(repo, assessments, "Saiwei", overall_judgment="企业在财务、治理、合规和商业化方面存在显著且有原始材料支撑的风险：2024年营业收入同比大幅下滑、净利润巨额亏损、经营现金流连续为负，财务报表被出具保留意见；报告期内多次受到监管处罚，并存在未决诉讼/仲裁和债务重组。尽管研发投入比例较高且具备一定产品储备，但商业化规模在样本中处于末位，重大风险无法被优势因素抵消，综合评定为D。交易对手名称以代称披露仅构成KYC核查边界，不作为独立不利事实。", rating_rationale=tuple(saiwei_rationale), core_risks=("财务持续性恶化：2024年营业收入同比下降68%，净利润巨额亏损，经营现金流连续两年为负。", "治理与信息披露问题：报告期内多次受到交易所纪律处分、证监会行政处罚，财务报表被出具保留意见。", "未决诉讼/仲裁和债务重组可能对财务与经营持续性形成不确定性。", "客户集中度高：前五名客户销售占比84.34%，大客户依赖明显。", "商业化基础偏弱：收入规模在当前样本中末位，部分产品仍处研发或结项阶段，转型支撑不足。"))

    stone = assessments["Stone"]
    stone_rationale = list(stone.rating_rationale)
    stone_rationale[0] = OverallAssessmentRationale("industry_and_commercialization", "行业与商业化", "企业产品已实现商业化，2025年营业收入约186.95亿元，位列当前12家试验样本第2。前五大客户销售占比26.99%、前五大供应商采购占比31.50%，均不存在单一客户或供应商占比超过50%的情形；名称以代称列示限制逐户核查，但不能据此推定集中度过高或合规异常。")
    stone_rationale[3] = OverallAssessmentRationale("financial_and_operating_resilience", "财务与经营韧性", "2025年营业收入增长56.51%至186.95亿元，但归母净利润同比下降31.03%至13.63亿元，经营活动现金流同比下降55.38%至7.74亿元。企业仍保持较强盈利和正向现金流，但利润与现金生成能力的变化需要持续跟踪，故不评为A。")
    stone_rationale[4] = OverallAssessmentRationale("compliance_and_uncertainty", "合规与不确定性", "现有材料未显示重大处罚或未决重大事项。交易对手名称按年报惯例以代称列示，限制反洗钱与制裁的逐户核查，但不构成已发生的合规不利事实；海外认证和出口管制属于行业与跨境经营的持续跟踪事项。")
    save(repo, assessments, "Stone", overall_judgment="企业经营与治理基础较好，2025年营业收入约186.95亿元，产品已商业化，仍保持13.63亿元归母净利润和7.74亿元正向经营现金流。但2025年归母净利润、经营活动现金流分别同比下降31.03%和55.38%，需重点分析盈利质量和营运资金变化，综合评定为B。客户/供应商以代称披露及债务明细未入库仅构成后续核查边界，不直接认定为合规或偿债风险。", rating_rationale=tuple(stone_rationale), core_risks=("2025年归母净利润同比下降31.03%，盈利增速承压。", "2025年经营活动现金流同比下降55.38%，需分析营运资金、回款和现金生成变化。", "海外业务面临市场竞争、技术迭代及出口管制、认证要求等持续性挑战。"), rating_boundaries=("本次评估基于2025年智能机器人同行假设口径试验样本，部分企业以非2025年事实参与，结果仅用于流程和敏感性验证，不构成正式结论。", "前五大客户和供应商按年报惯例以代称列示，现有材料无法逐户完成KYC、制裁名单和资金流核查；该限制不等同于交易对手存在不利事实。", "有息负债、融资协议、专利权利限制等细项未在当前画像中结构化保存，正式审查应结合年报附注及权属材料核实。", "市场渗透率、技术先进性等缺乏统一同业可比数据，无法进行完整量化对比。"))

    all_assessments = repo.list_overall_assessments(cohort_id=COHORT_ID)
    corrupted = [item.case_id for item in all_assessments if "?" in "".join((item.overall_judgment, *item.core_risks, *item.rating_boundaries, *item.verification_priorities, *(item.judgment for item in item.rating_rationale)))]
    if corrupted:
        raise RuntimeError(f"仍有乱码记录：{corrupted}")
    print("已修复并核验", len(all_assessments), "份综合评定文本。")


if __name__ == "__main__":
    main()
