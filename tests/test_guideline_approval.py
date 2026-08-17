import json
from dataclasses import replace

import pytest

from src.approval import (
    ApprovalPoint,
    ApprovalRepository,
    GUIDELINE_SECTION_DEFINITIONS,
    PeerCohort,
    approve_direction_ranking,
    build_direction_comparison_card,
    build_guideline_section_context,
    build_standalone_guideline_section_context,
    direction_ranking_to_markdown,
    generate_direction_ranking,
    generate_guideline_section_report,
)
from src.approval.direction_ranking import (
    DirectionRankPoint,
    DirectionRankingGroup,
    DirectionRankingResult,
)
from src.approval.guideline_definitions import GUIDELINE_SECTIONS_BY_ID
from src.approval.guideline_reporting import build_guideline_section_report_messages
from src.industry.models import IndustryBackgroundProfile, IndustryInsight
from src.llm.generation_config import GenerationConfig
from src.profiles.models import CurrentEnterpriseProfile, EvidenceReference, ProfileItem


def _cohort() -> PeerCohort:
    return PeerCohort(
        cohort_id="robotics-2025",
        industry_id="robotics",
        cohort_name="robotics sample",
        fiscal_period="2025",
        company_case_ids=("company-a", "company-b", "company-c"),
        selection_rule="same industry and reporting period",
        review_status="approved",
    )


def _profile(case_id: str) -> CurrentEnterpriseProfile:
    return CurrentEnterpriseProfile(
        profile_id=f"profile-{case_id}",
        case_id=case_id,
        enterprise_name=case_id,
        items=(
            ProfileItem(
                item_id=f"{case_id}-business",
                field_id="enterprise.main_business",
                section_id="basic_information",
                value="机器人产品研发与销售",
                value_type="text",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference(f"{case_id}-business-evidence"),),
                review_status="accepted",
            ),
            ProfileItem(
                item_id=f"{case_id}-product",
                field_id="product.name",
                section_id="product_research_commercialization",
                value="机器人产品",
                value_type="entity_ref",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference(f"{case_id}-product-evidence"),),
                review_status="accepted",
            ),
            ProfileItem(
                item_id=f"{case_id}-stage",
                field_id="product.commercialization_stage",
                section_id="product_research_commercialization",
                value="commercialized",
                value_type="enum",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference(f"{case_id}-stage-evidence"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )


def _industry_profile() -> IndustryBackgroundProfile:
    return IndustryBackgroundProfile(
        profile_id="industry-robotics",
        industry_id="robotics",
        industry_name="机器人",
        source_ids=("industry-report",),
        insights=(
            IndustryInsight(
                insight_id="market-growth",
                dimension_id="market_size_and_growth",
                statement="机器人市场仍处于增长阶段。",
                insight_type="reported_fact",
                evidence_refs=(EvidenceReference("industry-market-evidence"),),
                review_status="accepted",
            ),
            IndustryInsight(
                insight_id="commercialization",
                dimension_id="commercialization",
                statement="产品商业化和客户验证是行业关键。",
                insight_type="analysis_judgment",
                evidence_refs=(EvidenceReference("industry-commercial-evidence"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )


def _market_context(case_id: str):
    section = GUIDELINE_SECTIONS_BY_ID["market_space"]
    return build_guideline_section_context(
        _cohort(),
        _profile(case_id),
        _industry_profile(),
        section,
    )


def test_guideline_definitions_have_eleven_sections_and_cross_domain_fields():
    assert len(GUIDELINE_SECTION_DEFINITIONS) == 11
    market = GUIDELINE_SECTIONS_BY_ID["market_space"]
    context = _market_context("company-a")
    market_size = context.point_contexts[0]
    assert market_size.point_id == "market_size"
    assert {item.field_id for item in market_size.enterprise_items} == {
        "enterprise.main_business",
        "product.name",
        "product.commercialization_stage",
    }
    assert context.point_contexts[0].industry_insights
    assert context.section_id == market.section_id
    payload = json.loads(
        build_guideline_section_report_messages(context)[1]["content"].rsplit("\n", 1)[-1]
    )
    assert payload["cohort"] == {
        "cohort_id": "robotics-2025",
        "fiscal_period": "2025",
        "selection_rule": "same industry and reporting period",
    }


def test_standalone_guideline_context_does_not_require_peer_metrics():
    context = build_standalone_guideline_section_context(
        _profile("company-a"),
        _industry_profile(),
        GUIDELINE_SECTIONS_BY_ID["market_space"],
    )

    assert context.cohort_id is None
    assert all("可比指标" not in gap for gap in context.information_gaps)


def test_guideline_context_selects_fact_groups_across_allowed_fields():
    cohort = _cohort()
    base_profile = _profile("company-a")
    profile = CurrentEnterpriseProfile(
        profile_id=base_profile.profile_id,
        case_id=base_profile.case_id,
        enterprise_name=base_profile.enterprise_name,
        ontology_version=base_profile.ontology_version,
        relations=base_profile.relations,
        information_gaps=base_profile.information_gaps,
        conflicts=base_profile.conflicts,
        review_status=base_profile.review_status,
        items=base_profile.items
        + (
            ProfileItem(
                item_id="company-a-person",
                field_id="team.key_person",
                section_id="ownership_governance_team",
                value="核心人员",
                value_type="entity_ref",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference("company-a-person-evidence"),),
                subject="核心人员",
                review_status="accepted",
            ),
            ProfileItem(
                item_id="company-a-education",
                field_id="team.education_structure",
                section_id="ownership_governance_team",
                value="团队学历结构已披露。",
                value_type="text",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference("company-a-education-evidence"),),
                subject="the_enterprise",
                review_status="accepted",
            ),
            ProfileItem(
                item_id="company-a-background",
                field_id="team.professional_background",
                section_id="ownership_governance_team",
                value="团队具备行业经验。",
                value_type="text",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference("company-a-background-evidence"),),
                subject="the_enterprise",
                review_status="accepted",
            ),
        ),
    )
    industry = _industry_profile()
    core_team = build_guideline_section_context(
        cohort,
        profile,
        industry,
        GUIDELINE_SECTIONS_BY_ID["core_team"],
    )
    fields = {item.field_id for item in core_team.point_contexts[0].enterprise_items}
    assert "team.key_person" in fields
    assert "team.education_structure" in fields
    assert "team.professional_background" in fields


def test_guideline_section_report_uses_exact_points_and_citations(monkeypatch):
    context = _market_context("company-a")
    monkeypatch.setattr(
        "src.approval.guideline_reporting.call_deepseek",
        lambda messages, config: {
            "one_sentence_summary": "企业已有产品和商业化基础，但市场空间仍需结合行业数据判断。",
            "approval_points": [
                {
                    "approval_point_id": "market_size",
                    "enterprise_observation": "企业主营机器人产品并已进入商业化阶段。",
                    "industry_benchmark": "机器人市场仍处于增长阶段。",
                    "peer_comparison": None,
                    "judgment": "企业具备进入市场的基础，但规模空间证据有限。",
                    "enterprise_item_ids": ["company-a-business", "company-a-business", "company-a-product"],
                    "industry_insight_ids": ["market-growth", "market-growth"],
                    "metric_ids": [],
                    "information_gap_numbers": [],
                },
                {
                    "approval_point_id": "market_penetration",
                    "enterprise_observation": "企业产品已商业化。",
                    "industry_benchmark": "行业商业化和客户验证是关键。",
                    "peer_comparison": None,
                    "judgment": "产品处于已有商业化基础但仍需验证规模扩张的阶段。",
                    "enterprise_item_ids": ["company-a-stage"],
                    "industry_insight_ids": ["commercialization"],
                    "metric_ids": [],
                    "information_gap_numbers": [],
                },
            ],
        },
    )
    report = generate_guideline_section_report(
        "company-a-market-report", context, config=GenerationConfig(mode="thinking")
    )
    assert report.domain_id == "market_space"
    assert [point.approval_point_id for point in report.approval_points] == [
        "market_size",
        "market_penetration",
    ]
    assert report.review_status == "pending"
    assert len(report.approval_points[0].evidence_refs) == 3


def test_guideline_section_report_can_express_missing_enterprise_material(monkeypatch):
    context = _market_context("company-a")
    context = replace(
        context,
        point_contexts=(
            replace(
                context.point_contexts[0],
                enterprise_items=(),
                information_gaps=("缺少已审核企业事实。",),
            ),
            context.point_contexts[1],
        ),
    )
    monkeypatch.setattr(
        "src.approval.guideline_reporting.call_deepseek",
        lambda messages, config: {
            "one_sentence_summary": "当前材料不足，暂不能确认市场规模判断。",
            "approval_points": [
                {
                    "approval_point_id": "market_size",
                    "enterprise_observation": "当前材料不足。",
                    "industry_benchmark": "机器人市场仍处于增长阶段。",
                    "peer_comparison": None,
                    "judgment": "暂不能确认企业市场规模，需补充企业事实。",
                    "enterprise_item_ids": [],
                    "industry_insight_ids": ["market-growth"],
                    "metric_ids": [],
                    "information_gap_numbers": [1, 1],
                },
                {
                    "approval_point_id": "market_penetration",
                    "enterprise_observation": "企业产品已商业化。",
                    "industry_benchmark": "行业商业化和客户验证是关键。",
                    "peer_comparison": None,
                    "judgment": "仍需观察市场扩张。",
                    "enterprise_item_ids": ["company-a-stage"],
                    "industry_insight_ids": ["commercialization"],
                    "metric_ids": [],
                    "information_gap_numbers": [],
                },
            ],
        },
    )
    report = generate_guideline_section_report(
        "company-a-market-gap-report", context, config=GenerationConfig(mode="thinking")
    )
    assert report.approval_points[0].information_gaps == ("缺少已审核企业事实。",)


def test_guideline_section_report_repairs_invalid_citation_once(monkeypatch):
    context = _market_context("company-a")
    outputs = iter(
        (
            {
                "one_sentence_summary": "企业具备市场基础。",
                "approval_points": [
                    {
                        "approval_point_id": "market_size",
                        "enterprise_observation": "企业主营机器人产品。",
                        "industry_benchmark": "市场处于增长阶段。",
                        "peer_comparison": None,
                        "judgment": "具备进入市场基础。",
                        "enterprise_item_ids": ["unknown-item"],
                        "industry_insight_ids": ["market-growth"],
                        "metric_ids": [],
                        "information_gap_numbers": [],
                    },
                    {
                        "approval_point_id": "market_penetration",
                        "enterprise_observation": "企业产品已商业化。",
                        "industry_benchmark": "商业化和客户验证是关键。",
                        "peer_comparison": None,
                        "judgment": "仍需观察市场扩张。",
                        "enterprise_item_ids": ["company-a-stage"],
                        "industry_insight_ids": ["commercialization"],
                        "metric_ids": [],
                        "information_gap_numbers": [],
                    },
                ],
            },
            {
                "one_sentence_summary": "企业具备市场基础。",
                "approval_points": [
                    {
                        "approval_point_id": "market_size",
                        "enterprise_observation": "企业主营机器人产品。",
                        "industry_benchmark": "市场处于增长阶段。",
                        "peer_comparison": None,
                        "judgment": "具备进入市场基础。",
                        "enterprise_item_ids": ["company-a-business"],
                        "industry_insight_ids": ["market-growth"],
                        "metric_ids": [],
                        "information_gap_numbers": [],
                    },
                    {
                        "approval_point_id": "market_penetration",
                        "enterprise_observation": "企业产品已商业化。",
                        "industry_benchmark": "商业化和客户验证是关键。",
                        "peer_comparison": None,
                        "judgment": "仍需观察市场扩张。",
                        "enterprise_item_ids": ["company-a-stage"],
                        "industry_insight_ids": ["commercialization"],
                        "metric_ids": [],
                        "information_gap_numbers": [],
                    },
                ],
            },
        )
    )
    monkeypatch.setattr(
        "src.approval.guideline_reporting.call_deepseek",
        lambda messages, config: next(outputs),
    )

    report = generate_guideline_section_report(
        "company-a-market-repaired-report", context, config=GenerationConfig(mode="thinking")
    )

    assert report.approval_points[0].evidence_refs == (
        EvidenceReference("company-a-business-evidence"),
        EvidenceReference("industry-market-evidence"),
    )


def _approved_market_report(case_id: str):
    return replace(
        # The report is deliberately built from the same fixed points for every company.
        _report_from_context(case_id),
        review_status="approved",
    )


def _report_from_context(case_id: str):
    from src.approval.models import DomainApprovalReport

    return DomainApprovalReport(
        report_id=f"{case_id}-market-report",
        cohort_id="robotics-2025",
        case_id=case_id,
        domain_id="market_space",
        one_sentence_summary=f"{case_id}市场判断。",
        approval_points=(
            ApprovalPoint(
                approval_point_id="market_size",
                title="市场规模与增长空间",
                enterprise_observation=f"{case_id}已形成机器人产品。",
                industry_benchmark="行业仍处于增长阶段。",
                peer_comparison=None,
                judgment=f"{case_id}具备一定市场基础。",
                evidence_refs=(EvidenceReference(f"{case_id}-business-evidence"),),
            ),
            ApprovalPoint(
                approval_point_id="market_penetration",
                title="市场渗透与替代空间",
                enterprise_observation=f"{case_id}产品已商业化。",
                industry_benchmark="行业重视商业化和客户验证。",
                peer_comparison=None,
                judgment=f"{case_id}仍需观察市场扩张。",
                evidence_refs=(EvidenceReference(f"{case_id}-stage-evidence"),),
            ),
        ),
        review_status="approved",
    )


def test_direction_ranking_compares_cards_and_converts_dense_points(monkeypatch):
    section = GUIDELINE_SECTIONS_BY_ID["market_space"]
    cards = tuple(
        build_direction_comparison_card(
            _approved_market_report(case_id),
            _market_context(case_id),
        )
        for case_id in ("company-a", "company-b", "company-c")
    )
    monkeypatch.setattr(
        "src.approval.direction_ranking.call_deepseek",
        lambda messages, config: {
            "ranking_groups": [
                {
                    "rank": 1,
                    "case_ids": ["company-a"],
                    "comparison_reason": "商业化事实更完整。",
                },
                {
                    "rank": 2,
                    "case_ids": ["company-b", "company-c"],
                    "comparison_reason": "两家企业现有材料接近。",
                },
            ],
            "not_comparable_case_ids": [],
        },
    )
    result = generate_direction_ranking(
        section, cards, config=GenerationConfig(mode="thinking")
    )
    assert result.comparable_company_count == 3
    assert [(point.case_id, point.rank_points) for point in result.rank_points] == [
        ("company-a", 3),
        ("company-b", 2),
        ("company-c", 2),
    ]
    assert "第1名（3分）" in direction_ranking_to_markdown(result)
    assert approve_direction_ranking(result).review_status == "approved"


def test_direction_ranking_normalizes_skipped_rank_labels(monkeypatch):
    section = GUIDELINE_SECTIONS_BY_ID["market_space"]
    cards = tuple(
        build_direction_comparison_card(
            _approved_market_report(case_id),
            _market_context(case_id),
        )
        for case_id in ("company-a", "company-b", "company-c")
    )
    monkeypatch.setattr(
        "src.approval.direction_ranking.call_deepseek",
        lambda messages, config: {
            "ranking_groups": [
                {"rank": 1, "case_ids": ["company-a"], "comparison_reason": "领先。"},
                {"rank": 3, "case_ids": ["company-b", "company-c"], "comparison_reason": "相近。"},
            ],
            "not_comparable_case_ids": [],
        },
    )

    result = generate_direction_ranking(
        section, cards, config=GenerationConfig(mode="thinking")
    )

    assert [(group.rank, group.case_ids) for group in result.ranking_groups] == [
        (1, ("company-a",)),
        (2, ("company-b", "company-c")),
    ]


def test_direction_ranking_requires_every_company_to_be_covered(monkeypatch):
    section = GUIDELINE_SECTIONS_BY_ID["market_space"]
    cards = tuple(
        build_direction_comparison_card(
            _approved_market_report(case_id),
            _market_context(case_id),
        )
        for case_id in ("company-a", "company-b", "company-c")
    )
    monkeypatch.setattr(
        "src.approval.direction_ranking.call_deepseek",
        lambda messages, config: {
            "ranking_groups": [
                {
                    "rank": 1,
                    "case_ids": ["company-a", "company-b"],
                    "comparison_reason": "相近。",
                }
            ],
            "not_comparable_case_ids": [],
        },
    )
    with pytest.raises(ValueError, match="cover every comparison card"):
        generate_direction_ranking(
            section, cards, config=GenerationConfig(mode="thinking")
        )


def test_direction_ranking_repository_round_trip(tmp_path):
    result = DirectionRankingResult(
        cohort_id="robotics-2025",
        section_id="market_space",
        comparable_company_count=3,
        ranking_groups=(
            # This object exercises persistence independently of model calling.
            DirectionRankingGroup(1, ("company-a",), "商业化事实更完整。"),
            DirectionRankingGroup(2, ("company-b", "company-c"), "材料接近。"),
        ),
        not_comparable_case_ids=(),
        rank_points=(
            DirectionRankPoint("company-a", 1, 3),
            DirectionRankPoint("company-b", 2, 2),
            DirectionRankPoint("company-c", 2, 2),
        ),
        source_section_report_ids=("company-a-market-report", "company-b-market-report", "company-c-market-report"),
    )
    repository = ApprovalRepository(tmp_path / "guideline.db")
    repository.save_cohort(_cohort())
    repository.save_direction_ranking(result)
    assert repository.get_direction_ranking("robotics-2025", "market_space") == result
