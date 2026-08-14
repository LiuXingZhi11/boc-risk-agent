from __future__ import annotations

from src.profiles import CurrentEnterpriseProfile, EvidenceReference, ProfileItem
from src.profiles.detailed_comparison import (
    ComparisonPoint,
    DetailedComparisonRun,
    HistoricalProfileComparison,
)
from src.profiles.report import build_v5_review_report
from src.profiles.risk_judgment import CoreRiskJudgment, RiskJudgmentPoint


def test_v5_report_deterministically_collects_questions_and_evidence():
    current = CurrentEnterpriseProfile(
        profile_id="current-1",
        case_id="CURRENT",
        enterprise_name="当前科技企业",
        items=(
            ProfileItem(
                item_id="current-tech",
                section_id="technology_ip",
                field_id="technology.ownership_status",
                value="licensed",
                value_type="enum",
                information_status="supported",
                content_role="external_observation",
                evidence_refs=(EvidenceReference("src:current"),),
                review_status="accepted",
            ),
        ),
        information_gaps=(
            "technology_and_ip: 缺少企业法定名称，无法关联核心技术。",
            "technology_and_ip: 技术许可协议期限待核实",
        ),
        review_status="approved",
    )
    point = ComparisonPoint(
        dimension_id="technology_and_ip",
        explanation="双方均涉及外部技术许可。",
        current_item_ids=("current-tech",),
        historical_item_ids=("historical-tech",),
        current_relation_ids=(),
        historical_relation_ids=(),
        evidence_unit_ids=("src:current", "src:historical"),
    )
    comparison = HistoricalProfileComparison(
        historical_profile_id="historical-1",
        historical_case_id="H1",
        historical_enterprise_name="历史科技企业",
        retrieval_score=0.8,
        similarity_basis=(point,),
        key_differences=(),
        historical_outcomes=(),
        applicability_limits=("当前材料尚未证明许可已经失效。",),
        verification_questions=("技术许可协议是否持续有效？",),
    )
    run = DetailedComparisonRun(
        current_profile_id=current.profile_id,
        comparisons=(comparison,),
        api_meta={},
    )
    risk_point = RiskJudgmentPoint(
        title="技术许可稳定性",
        explanation="技术许可期限尚未核实，可能影响核心技术的持续使用。",
        current_item_ids=("current-tech",),
        current_relation_ids=(),
        supporting_information_gaps=("technology_and_ip: 技术许可协议期限待核实",),
        supporting_conflicts=(),
        evidence_unit_ids=("src:current",),
    )
    judgment = CoreRiskJudgment(
        current_profile_id=current.profile_id,
        overall_judgment="当前最需要关注技术许可的持续有效性，现有材料不足以形成更确定的判断。",
        key_risks=(risk_point,),
        mitigating_factors=(),
        uncertainties=("技术许可期限尚未得到完整证明。",),
        verification_priorities=("优先核实技术许可协议及有效期限。",),
        evidence_unit_ids=("src:current",),
        api_meta={"model": "fake-model"},
    )

    report = build_v5_review_report(current, run, judgment)

    assert report.verification_questions == ("技术许可协议是否持续有效？",)
    assert report.information_gaps == ("technology_and_ip: 技术许可协议期限待核实",)
    assert report.evidence_unit_ids == ("src:current", "src:historical")
    assert "1 条相似依据" in report.summary
    assert "不构成授信审批" in report.to_markdown()
    assert report.to_markdown().index("## 核心风险判断") < report.to_markdown().index("## 汇总")
    assert "**技术许可稳定性**" in report.to_markdown()


def test_v5_report_handles_no_historical_comparison():
    current = CurrentEnterpriseProfile(
        profile_id="current-empty",
        case_id="CURRENT",
        enterprise_name="当前科技企业",
        review_status="approved",
    )

    report = build_v5_review_report(
        current,
        DetailedComparisonRun(current.profile_id, (), {}),
    )

    assert report.summary == "当前没有可用的历史企业详细比较结果。"
    assert report.limitations


def test_v5_report_separates_industry_background_evidence():
    current = CurrentEnterpriseProfile(
        profile_id="current-industry",
        case_id="CURRENT",
        enterprise_name="当前科技企业",
        review_status="approved",
    )
    judgment = CoreRiskJudgment(
        current_profile_id=current.profile_id,
        overall_judgment="当前材料有限，行业背景只能作为进一步核实的参考。",
        key_risks=(),
        mitigating_factors=(),
        uncertainties=("当前企业事实仍需补充。",),
        verification_priorities=("优先补充企业自身材料。",),
        evidence_unit_ids=(),
        api_meta={},
        industry_profile_id="industry-profile",
        industry_name="机器人",
        industry_evidence_unit_ids=("industry:1",),
    )

    report = build_v5_review_report(
        current,
        DetailedComparisonRun(current.profile_id, (), {}),
        judgment,
    )

    assert report.industry_evidence_unit_ids == ("industry:1",)
    assert "采用的行业背景：机器人" in report.to_markdown()
    assert "## 行业背景证据索引" in report.to_markdown()
