from __future__ import annotations

from dataclasses import replace

import pytest

from src.approval import (
    DOMAIN_INDUSTRY_DIMENSIONS,
    ApprovalPoint,
    ApprovalPointDefinition,
    ApprovalRepository,
    ComparableMetricDefinition,
    ComparableMetricValue,
    DomainApprovalReport,
    CompositeApprovalReport,
    MetricProfileFieldBinding,
    PeerCohort,
    build_metric_value_candidates,
    build_domain_approval_context,
    approve_composite_approval_report,
    approve_domain_approval_report,
    composite_approval_report_to_markdown,
    domain_approval_report_to_markdown,
    generate_composite_approval_report,
    generate_domain_approval_report,
    rank_metric_values,
    validate_domain_industry_mapping,
)
from src.llm.generation_config import GenerationConfig
from src.industry.models import IndustryBackgroundProfile, IndustryInsight
from src.industry.repository import IndustryProfileRepository
from src.profiles.models import CurrentEnterpriseProfile, EvidenceReference, ProfileItem
from src.profiles.repository import ProfileRepository
from src.ui.v5_services import (
    approve_composite_approval_review,
    approve_domain_approval_review,
    composite_approval_report_detail,
    domain_approval_report_detail,
    generate_composite_approval_review,
    generate_domain_approval_review,
)


def _cohort() -> PeerCohort:
    return PeerCohort(
        cohort_id="humanoid-2025",
        industry_id="humanoid_robotics",
        cohort_name="Humanoid robotics sample",
        fiscal_period="2025",
        company_case_ids=("company-a", "company-b", "company-c"),
        selection_rule="same industry and fiscal year",
        source_ids=("source-annual-reports",),
        review_status="approved",
    )


def _definition(direction: str = "higher_is_better") -> ComparableMetricDefinition:
    return ComparableMetricDefinition(
        metric_id="revenue-2025",
        approval_direction_id="finance_and_funding",
        approval_point_id="revenue_scale",
        name="Operating revenue",
        comparison_direction=direction,
        unit="CNY million",
        value_scope="consolidated",
        review_status="approved",
    )


def _metric_value(case_id: str, value: float) -> ComparableMetricValue:
    return ComparableMetricValue(
        cohort_id="humanoid-2025",
        metric_id="revenue-2025",
        case_id=case_id,
        value=value,
        reporting_period="2025",
        unit="CNY million",
        source_profile_id=f"profile-{case_id}",
        source_item_id=f"item-{case_id}",
        evidence_refs=(EvidenceReference(f"evidence-{case_id}"),),
        review_status="approved",
    )


def test_rank_metric_values_supports_positive_direction_and_missing_values() -> None:
    results = rank_metric_values(
        _cohort(),
        _definition(),
        (_metric_value("company-a", 30), _metric_value("company-b", 10)),
    )

    assert [(result.case_id, result.rank, result.rank_points) for result in results] == [
        ("company-a", 1, 2),
        ("company-b", 2, 1),
    ]
    assert {result.sample_size for result in results} == {2}
    assert "company-c" not in {result.case_id for result in results}


def test_rank_metric_values_supports_negative_direction_and_dense_ties() -> None:
    definition = _definition("lower_is_better")
    results = rank_metric_values(
        _cohort(),
        definition,
        (
            _metric_value("company-a", 8),
            _metric_value("company-b", 3),
            _metric_value("company-c", 3),
        ),
    )

    assert [(result.case_id, result.rank) for result in results] == [
        ("company-b", 1),
        ("company-c", 1),
        ("company-a", 2),
    ]
    assert [result.rank_points for result in results] == [3, 3, 2]


def test_domain_industry_mapping_covers_all_profile_domains() -> None:
    validate_domain_industry_mapping()
    assert set(DOMAIN_INDUSTRY_DIMENSIONS) == {
        "enterprise_and_control",
        "team",
        "technology_and_ip",
        "product_and_project",
        "market_and_commercialization",
        "customer_and_supplier",
        "finance_and_funding",
        "risk_matters",
        "authoritative_findings",
        "outcome_and_resolution",
    }


def test_approval_repository_round_trip(tmp_path) -> None:
    repository = ApprovalRepository(tmp_path / "approval.db")
    cohort = _cohort()
    definition = _definition()
    binding = MetricProfileFieldBinding(
        metric_id=definition.metric_id,
        section_id="finance_capital",
        field_id="finance.operating_revenue",
    )
    point_definition = _point_definition()
    metric_value = _metric_value("company-a", 30)
    ranking = rank_metric_values(cohort, definition, (metric_value,))[0]
    report = DomainApprovalReport(
        report_id="company-a-finance-2025",
        cohort_id=cohort.cohort_id,
        case_id="company-a",
        domain_id="finance_and_funding",
        one_sentence_summary="Revenue is the highest among the available sample.",
        approval_points=(
            ApprovalPoint(
                approval_point_id="revenue_scale",
                title="Revenue scale",
                enterprise_observation="2025 operating revenue is 30 CNY million.",
                industry_benchmark="Commercialization remains an industry focus.",
                peer_comparison="Ranked first in the available sample.",
                judgment="The company has a leading revenue scale in this sample.",
                ranking_results=(ranking,),
                evidence_refs=(EvidenceReference("evidence-company-a"),),
            ),
        ),
        review_status="approved",
    )

    repository.save_cohort(cohort)
    repository.save_metric_definition(definition)
    repository.save_metric_binding(binding)
    repository.save_approval_point_definition(point_definition)
    repository.save_metric_value(metric_value)
    repository.save_domain_report(report)

    assert repository.get_cohort(cohort.cohort_id) == cohort
    assert repository.get_metric_definition(definition.metric_id) == definition
    assert repository.get_metric_binding(definition.metric_id) == binding
    assert repository.list_approval_point_definitions("finance_and_funding") == [
        point_definition
    ]
    assert repository.list_metric_values(cohort.cohort_id, definition.metric_id) == [
        metric_value
    ]
    assert repository.get_domain_report(report.report_id) == report
    assert repository.list_domain_reports(case_id="company-a") == [report]

    standalone_report = replace(
        report,
        report_id="company-a-standalone-finance-2025",
        cohort_id=None,
        review_status="pending",
    )
    repository.save_domain_report(standalone_report)
    assert repository.get_domain_report(standalone_report.report_id) == standalone_report
    assert repository.list_domain_reports(case_id="company-a") == [report, standalone_report]

    repository.save_metric_definition(replace(definition, review_status="pending"))

    assert repository.get_metric_binding(definition.metric_id) == binding


def _revenue_profile(
    *,
    review_status: str = "approved",
    item_status: str = "accepted",
    period: str = "2025",
    unit: str = "CNY million",
    value_scope: str = "consolidated",
    subject: str | None = None,
    duplicate: bool = False,
) -> CurrentEnterpriseProfile:
    first_item = ProfileItem(
        item_id="revenue-1",
        section_id="finance_capital",
        field_id="finance.operating_revenue",
        value=30.0,
        value_type="money",
        information_status="supported",
        content_role="audited_information",
        evidence_refs=(EvidenceReference("evidence-revenue-1"),),
        reporting_period=period,
        unit=unit,
        value_scope=value_scope,
        subject=subject,
        review_status=item_status,
    )
    items = (first_item,)
    if duplicate:
        items += (
            ProfileItem(
                item_id="revenue-2",
                section_id="finance_capital",
                field_id="finance.operating_revenue",
                value=35.0,
                value_type="money",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference("evidence-revenue-2"),),
                reporting_period=period,
                unit=unit,
                value_scope=value_scope,
                review_status=item_status,
            ),
        )
    return CurrentEnterpriseProfile(
        profile_id="profile-company-a",
        case_id="company-a",
        enterprise_name="Company A",
        items=items,
        review_status=review_status,
    )


def test_build_metric_value_candidates_preserves_profile_item_traceability() -> None:
    definition = _definition()
    binding = MetricProfileFieldBinding(
        metric_id=definition.metric_id,
        section_id="finance_capital",
        field_id="finance.operating_revenue",
    )

    candidates = build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile()
    )

    assert len(candidates) == 1
    assert candidates[0].source_profile_id == "profile-company-a"
    assert candidates[0].source_item_id == "revenue-1"
    assert candidates[0].evidence_refs == (EvidenceReference("evidence-revenue-1"),)


def test_build_metric_value_candidates_filters_unmatched_facts_and_keeps_duplicates() -> None:
    definition = _definition()
    binding = MetricProfileFieldBinding(
        metric_id=definition.metric_id,
        section_id="finance_capital",
        field_id="finance.operating_revenue",
    )

    assert build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(period="2024")
    ) == ()
    assert build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(unit="CNY thousand")
    ) == ()
    assert build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(value_scope="parent_only")
    ) == ()
    assert build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(review_status="pending")
    ) == ()
    assert build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(item_status="pending")
    ) == ()
    assert [candidate.source_item_id for candidate in build_metric_value_candidates(
        _cohort(), definition, binding, _revenue_profile(duplicate=True)
    )] == ["revenue-1", "revenue-2"]


def test_build_metric_value_candidates_normalizes_money_and_enterprise_wide_scope() -> None:
    definition = replace(
        _definition(),
        unit="万元",
        value_scope="企业整体披露，合并范围以原报告为准",
    )
    binding = MetricProfileFieldBinding(
        metric_id=definition.metric_id,
        section_id="finance_capital",
        field_id="finance.operating_revenue",
    )
    profile = _revenue_profile(
        unit="元",
        value_scope=None,
        subject="the_enterprise",
    )

    candidates = build_metric_value_candidates(_cohort(), definition, binding, profile)

    assert len(candidates) == 1
    assert candidates[0].value == pytest.approx(0.003)
    assert candidates[0].unit == "万元"


def test_build_metric_value_candidates_normalizes_unitless_ratio() -> None:
    definition = ComparableMetricDefinition(
        metric_id="rd-ratio-2025",
        approval_direction_id="finance_and_funding",
        approval_point_id="rd-intensity",
        name="R&D expense ratio",
        comparison_direction="higher_is_better",
        unit="比例（小数）",
        value_scope="企业整体披露，合并范围以原报告为准",
        review_status="approved",
    )
    binding = MetricProfileFieldBinding(
        metric_id=definition.metric_id,
        section_id="finance_capital",
        field_id="finance.research_expense_ratio",
    )
    profile = CurrentEnterpriseProfile(
        profile_id="profile-company-a",
        case_id="company-a",
        enterprise_name="Company A",
        items=(
            ProfileItem(
                item_id="rd-ratio-1",
                section_id="finance_capital",
                field_id="finance.research_expense_ratio",
                value=0.2,
                value_type="ratio",
                information_status="supported",
                content_role="audited_information",
                evidence_refs=(EvidenceReference("evidence-rd-ratio-1"),),
                reporting_period="2025",
                subject="the_enterprise",
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )

    candidates = build_metric_value_candidates(_cohort(), definition, binding, profile)

    assert len(candidates) == 1
    assert candidates[0].value == 0.2
    assert candidates[0].unit == "比例（小数）"


def _industry_profile() -> IndustryBackgroundProfile:
    return IndustryBackgroundProfile(
        profile_id="industry-humanoid-2025",
        industry_id="humanoid_robotics",
        industry_name="Humanoid robotics",
        source_ids=("industry-report",),
        insights=(
            IndustryInsight(
                insight_id="commercialization-focus",
                dimension_id="commercialization",
                statement="Commercialization remains a key industry focus.",
                insight_type="analysis_judgment",
                evidence_refs=(EvidenceReference("industry-evidence-1"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )


def _point_definition() -> ApprovalPointDefinition:
    return ApprovalPointDefinition(
        approval_point_id="revenue_scale",
        approval_direction_id="finance_and_funding",
        title="Revenue scale",
        enterprise_field_ids=("finance.operating_revenue",),
        metric_ids=("revenue-2025",),
        industry_dimension_ids=("commercialization",),
        review_status="approved",
    )


def test_build_domain_approval_context_links_facts_industry_and_rankings() -> None:
    definition = _definition()
    context = build_domain_approval_context(
        _cohort(),
        _revenue_profile(),
        _industry_profile(),
        "finance_and_funding",
        (definition,),
        (
            _metric_value("company-a", 30),
            _metric_value("company-b", 10),
        ),
    )

    assert [item.item_id for item in context.enterprise_items] == ["revenue-1"]
    assert [insight.insight_id for insight in context.industry_insights] == [
        "commercialization-focus"
    ]
    assert [(comparison.value, comparison.ranking.rank) for comparison in context.metric_comparisons] == [
        (30, 1)
    ]
    assert context.information_gaps == ()


def test_build_domain_approval_context_reports_missing_comparable_value() -> None:
    context = build_domain_approval_context(
        _cohort(),
        _revenue_profile(),
        _industry_profile(),
        "finance_and_funding",
        (_definition(),),
        (
            _metric_value("company-b", 10),
            _metric_value("company-c", 20),
        ),
    )

    assert context.metric_comparisons == ()
    assert context.information_gaps == (
        "No comparable ranking is available for metric revenue-2025.",
    )


def test_build_domain_approval_context_filters_unaccepted_children_and_requires_approval() -> None:
    profile = _revenue_profile()
    industry_profile = _industry_profile()
    context = build_domain_approval_context(
        _cohort(),
        _revenue_profile(item_status="pending"),
        replace(
            industry_profile,
            insights=(replace(industry_profile.insights[0], review_status="pending"),),
        ),
        "finance_and_funding",
        (),
        (),
    )

    assert context.enterprise_items == ()
    assert context.industry_insights == ()
    assert set(context.information_gaps) == {
        "No accepted enterprise facts for domain finance_and_funding.",
        "No accepted industry insights for domain finance_and_funding.",
    }
    with pytest.raises(ValueError, match="approved peer cohort"):
        build_domain_approval_context(
            replace(_cohort(), review_status="pending"),
            profile,
            industry_profile,
            "finance_and_funding",
            (),
            (),
        )


def _finance_context():
    return build_domain_approval_context(
        _cohort(),
        _revenue_profile(),
        _industry_profile(),
        "finance_and_funding",
        (_definition(),),
        (_metric_value("company-a", 30), _metric_value("company-b", 10)),
    )


def test_generate_domain_report_validates_citations_and_exports_markdown(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.approval.reporting.call_deepseek",
        lambda messages, config: {
            "one_sentence_summary": "The company ranks first in the available revenue sample.",
            "approval_points": [
                {
                    "approval_point_id": "revenue_scale",
                    "enterprise_observation": "2025 revenue is 30 CNY million.",
                    "industry_benchmark": "Commercialization remains important.",
                    "peer_comparison": "The company ranks first out of two available companies.",
                    "judgment": "Revenue scale is leading in the available sample.",
                    "enterprise_item_ids": ["revenue-1"],
                    "industry_insight_ids": ["commercialization-focus"],
                    "metric_ids": ["revenue-2025"],
                    "information_gap_numbers": [],
                }
            ],
        },
    )

    report = generate_domain_approval_report(
        "company-a-finance-report",
        _finance_context(),
        (_point_definition(),),
        config=GenerationConfig(mode="thinking"),
    )

    assert report.review_status == "pending"
    assert report.approval_points[0].ranking_results[0].rank == 1
    assert "样本内排名：1/2" in domain_approval_report_to_markdown(report)
    assert "指标：revenue-2025" in domain_approval_report_to_markdown(report)
    assert approve_domain_approval_report(report).review_status == "approved"


def test_generate_domain_report_rejects_unknown_citation(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.approval.reporting.call_deepseek",
        lambda messages, config: {
            "one_sentence_summary": "Summary.",
            "approval_points": [
                {
                    "approval_point_id": "revenue_scale",
                    "enterprise_observation": "Observation.",
                    "industry_benchmark": None,
                    "peer_comparison": None,
                    "judgment": "Judgment.",
                    "enterprise_item_ids": ["unknown-item"],
                    "industry_insight_ids": [],
                    "metric_ids": [],
                    "information_gap_numbers": [],
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="enterprise_item_ids"):
        generate_domain_approval_report(
            "company-a-finance-report",
            _finance_context(),
            (_point_definition(),),
            config=GenerationConfig(mode="thinking"),
        )


def test_generate_composite_report_uses_approved_domain_reports(monkeypatch, tmp_path) -> None:
    domain_report = DomainApprovalReport(
        report_id="company-a-finance-report",
        cohort_id="humanoid-2025",
        case_id="company-a",
        domain_id="finance_and_funding",
        one_sentence_summary="Revenue is leading in the available sample.",
        approval_points=(
            ApprovalPoint(
                approval_point_id="revenue_scale",
                title="Revenue scale",
                enterprise_observation="Revenue is 30 CNY million.",
                industry_benchmark=None,
                peer_comparison="Sample rank 1/2.",
                judgment="Leading in this sample.",
                evidence_refs=(EvidenceReference("evidence-company-a"),),
            ),
        ),
    )
    approved_domain_report = approve_domain_approval_report(domain_report)
    monkeypatch.setattr(
        "src.approval.reporting.call_deepseek",
        lambda messages, config: {
            "overall_judgment": "The company has a leading revenue scale in the available sample.",
            "key_risks": ["The sample remains limited."],
            "mitigating_factors": ["Revenue ranks first in the available sample."],
            "judgment_boundaries": ["This is not an industry-wide ranking."],
            "verification_priorities": ["Verify the remaining peer annual reports."],
            "source_domain_report_ids": ["company-a-finance-report"],
        },
    )

    report = generate_composite_approval_report(
        "company-a-composite",
        (approved_domain_report,),
        config=GenerationConfig(mode="thinking"),
    )

    assert report.review_status == "pending"
    assert "企业综合核心风险判断" in composite_approval_report_to_markdown(report)
    approved = approve_composite_approval_report(report)
    repository = ApprovalRepository(tmp_path / "approval.db")
    repository.save_cohort(_cohort())
    repository.save_composite_report(approved)
    assert repository.get_composite_report(approved.report_id) == approved
    assert repository.list_composite_reports(case_id="company-a") == [approved]


def test_approval_service_generates_approves_and_exports_reports(monkeypatch, tmp_path) -> None:
    database = tmp_path / "approval-service.db"
    repository = ApprovalRepository(database)
    repository.save_cohort(_cohort())
    repository.save_metric_definition(_definition())
    repository.save_metric_value(_metric_value("company-a", 30))
    repository.save_metric_value(_metric_value("company-b", 10))
    repository.save_approval_point_definition(_point_definition())
    ProfileRepository(database).save(_revenue_profile())
    IndustryProfileRepository(database).save(_industry_profile())

    def fake_call(messages, config):
        if "approval_points 必须" in messages[1]["content"]:
            return {
                "one_sentence_summary": "Revenue ranks first in the available sample.",
                "approval_points": [
                    {
                        "approval_point_id": "revenue_scale",
                        "enterprise_observation": "Revenue is 30 CNY million.",
                        "industry_benchmark": "Commercialization is important.",
                        "peer_comparison": "Sample rank 1/2.",
                        "judgment": "Leading in this sample.",
                        "enterprise_item_ids": ["revenue-1"],
                        "industry_insight_ids": ["commercialization-focus"],
                        "metric_ids": ["revenue-2025"],
                        "information_gap_numbers": [],
                    }
                ],
            }
        return {
            "overall_judgment": "Revenue is leading in the available sample.",
            "key_risks": ["The sample remains limited."],
            "mitigating_factors": ["Revenue ranks first."],
            "judgment_boundaries": ["Not an industry-wide ranking."],
            "verification_priorities": ["Complete peer reports."],
            "source_domain_report_ids": ["company-a-finance-service"],
        }

    monkeypatch.setattr("src.approval.reporting.call_deepseek", fake_call)
    generated_domain = generate_domain_approval_review(
        database=database,
        report_id="company-a-finance-service",
        cohort_id="humanoid-2025",
        profile_id="profile-company-a",
        industry_profile_id="industry-humanoid-2025",
        domain_id="finance_and_funding",
    )

    assert generated_domain["report"]["review_status"] == "pending"
    assert domain_approval_report_detail(database, "company-a-finance-service") is not None
    approve_domain_approval_review(database=database, report_id="company-a-finance-service")
    generated_composite = generate_composite_approval_review(
        database=database,
        report_id="company-a-composite-service",
        cohort_id="humanoid-2025",
        case_id="company-a",
    )

    assert generated_composite["report"]["review_status"] == "pending"
    approve_composite_approval_review(database=database, report_id="company-a-composite-service")
    assert composite_approval_report_detail(database, "company-a-composite-service") is not None
