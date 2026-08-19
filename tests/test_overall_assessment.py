import pytest

from dataclasses import replace

from src.approval import ApprovalPoint, ApprovalRepository
from src.approval.direction_ranking import (
    DirectionRankPoint,
    DirectionRankingGroup,
    DirectionRankingResult,
)
from src.approval.guideline_definitions import GUIDELINE_SECTION_DEFINITIONS
from src.approval.overall_assessment import (
    ASSESSMENT_DIMENSIONS,
    approve_overall_assessment,
    build_overall_assessment_package,
    overall_assessment_to_markdown,
    validate_overall_assessment_output,
    generate_overall_assessment,
)
from src.llm.generation_config import GenerationConfig
from src.approval.models import DomainApprovalReport
from src.approval.models import PeerCohort, RATING_LEVEL_ORDER
from src.profiles.models import EvidenceReference


def _reports(*, review_status: str = "approved") -> tuple[DomainApprovalReport, ...]:
    return tuple(
        DomainApprovalReport(
            report_id=f"company-a-{section.section_id}",
            cohort_id="robotics-2025",
            case_id="company-a",
            domain_id=section.section_id,
            one_sentence_summary=f"{section.title}结论。",
            approval_points=(
                ApprovalPoint(
                    approval_point_id=f"{section.section_id}-point",
                    title=section.title,
                    enterprise_observation="企业已披露相关情况。",
                    industry_benchmark="行业处于发展阶段。",
                    peer_comparison="样本内具备可比位置。",
                    judgment="当前材料支持审慎判断。",
                    evidence_refs=(EvidenceReference(f"evidence-{section.section_id}"),),
                ),
            ),
            review_status=review_status,
        )
        for section in GUIDELINE_SECTION_DEFINITIONS
    )


def _rankings(*, review_status: str = "approved") -> tuple[DirectionRankingResult, ...]:
    return tuple(
        DirectionRankingResult(
            cohort_id="robotics-2025",
            section_id=section.section_id,
            comparable_company_count=2,
            ranking_groups=(
                DirectionRankingGroup(1, ("company-a",), "企业现有材料相对充分。"),
                DirectionRankingGroup(2, ("company-b",), "企业材料相对有限。"),
            ),
            not_comparable_case_ids=(),
            rank_points=(
                DirectionRankPoint("company-a", 1, 2),
                DirectionRankPoint("company-b", 2, 1),
            ),
            source_section_report_ids=(f"company-a-{section.section_id}",),
            review_status=review_status,
        )
        for section in GUIDELINE_SECTION_DEFINITIONS
        if section.ranking_enabled
    )


def _package(*, experimental: bool = False) -> dict:
    return build_overall_assessment_package(
        enterprise_name="测试企业",
        profile_reporting_periods=("2025",),
        cohort_name="机器人同行样本",
        cohort_fiscal_period="2025",
        cohort_selection_rule="同业同期企业",
        reports=_reports(review_status="pending" if experimental else "approved"),
        rankings=_rankings(review_status="pending" if experimental else "approved"),
        is_experimental=experimental,
    )


def _raw(package: dict, *, rating_level: str = "AAA3") -> dict:
    reports = package["direction_cards"]
    evidence_ids = [
        card["approval_points"][0]["key_evidence_unit_ids"][0]
        for card in reports
    ]
    direction_results = [
        {
            "section_id": section.section_id,
            "status": "conditional_passed",
            "score": section.score_weight,
            "summary": f"{section.title}当前材料支持审慎判断。",
            "strong_constraint_trigger_code": None,
            "strong_constraint_trigger_evidence_unit_ids": [],
        }
        for section in GUIDELINE_SECTION_DEFINITIONS
    ]
    if package["assessment_boundary"]["is_experimental"]:
        next(
            item
            for item in direction_results
            if item["section_id"] == "quantitative_assessment"
        )["status"] = "insufficient_information"
    return {
        "rating_level": rating_level,
        "overall_judgment": "企业具备一定基础，但仍需结合现金流和商业化持续核实。",
        "rating_rationale": [
            {"dimension_id": item[0], "title": item[1], "judgment": "已有材料可形成审慎判断。"}
            for item in ASSESSMENT_DIMENSIONS
        ],
        "core_risks": ["部分经营与财务信息仍需持续核实。"],
        "mitigating_factors": ["已形成技术和产品基础。"],
        "rating_boundaries": ["结论仅适用于当前同行样本和披露材料。"],
        "verification_priorities": ["核实后续收入和现金流变化。"],
        "direction_results": direction_results,
        "source_direction_report_ids": [card["source_direction_report_id"] for card in reports],
        "source_direction_ranking_sections": [
            section.section_id
            for section in GUIDELINE_SECTION_DEFINITIONS
            if section.ranking_enabled
        ],
        "evidence_unit_ids": evidence_ids,
    }


def test_overall_assessment_validates_full_direction_inputs_and_markdown():
    package = _package()
    assessment = validate_overall_assessment_output(
        "assessment-a", package, _reports(), _rankings(), _raw(package)
    )

    assert assessment.rating_level == ""
    assert assessment.total_score == 100
    assert len(assessment.rating_rationale) == 5
    assert len(assessment.source_direction_report_ids) == 11
    assert assessment.recommendation == "proceed_with_caution"
    assert len(assessment.direction_results) == 11
    assert "客户风险总分：100/100" in overall_assessment_to_markdown(assessment)


def test_direction_score_weights_sum_to_100():
    assert sum(section.score_weight for section in GUIDELINE_SECTION_DEFINITIONS) == 100


def test_overall_assessment_can_run_without_peer_rankings():
    reports = tuple(replace(report, cohort_id=None) for report in _reports())
    package = build_overall_assessment_package(
        enterprise_name="单企业测试",
        profile_reporting_periods=("2025",),
        cohort_name="单企业分析（未进行同行比较）",
        cohort_fiscal_period=None,
        cohort_selection_rule="未启用同行样本",
        reports=reports,
        rankings=(),
        is_experimental=False,
    )

    assessment = validate_overall_assessment_output(
        "standalone-assessment", package, reports, (), _raw(package)
    )

    assert assessment.cohort_id is None
    assert assessment.source_direction_ranking_sections == ()


def test_overall_assessment_rejects_out_of_range_score_and_derives_source_references():
    package = _package()
    raw = _raw(package)
    raw["direction_results"][0]["score"] = GUIDELINE_SECTION_DEFINITIONS[0].score_weight + 1
    with pytest.raises(ValueError, match="direction score"):
        validate_overall_assessment_output(
            "assessment-a", package, _reports(), _rankings(), raw
        )
    raw = _raw(package)
    raw["source_direction_report_ids"] = []
    raw["source_direction_ranking_sections"] = []
    assessment = validate_overall_assessment_output(
        "assessment-a", package, _reports(), _rankings(), raw
    )
    assert len(assessment.source_direction_report_ids) == 11
    assert len(assessment.source_direction_ranking_sections) == 10


def test_final_report_strong_constraint_failure_requires_hard_trigger_evidence():
    package = _package()
    raw = _raw(package, rating_level="C1")
    target = next(
        item for item in raw["direction_results"] if item["section_id"] == "aml_sanctions"
    )
    target["status"] = "failed"
    target["strong_constraint_trigger_code"] = "unresolved_sanctions_or_aml_violation"
    target["strong_constraint_trigger_evidence_unit_ids"] = ["evidence-aml_sanctions"]
    assessment = validate_overall_assessment_output(
        "assessment-a", package, _reports(), _rankings(), raw
    )
    assert assessment.recommendation == "do_not_proceed"
    assert assessment.strong_constraint_failed_count == 1

    target["strong_constraint_trigger_evidence_unit_ids"] = []
    with pytest.raises(ValueError, match="hard trigger"):
        validate_overall_assessment_output(
            "assessment-a", package, _reports(), _rankings(), raw
        )


def test_final_report_weak_constraint_failure_is_not_a_veto():
    package = _package()
    raw = _raw(package, rating_level="A3")
    target = next(
        item for item in raw["direction_results"] if item["section_id"] == "financial_position"
    )
    target["status"] = "failed"
    assessment = validate_overall_assessment_output(
        "assessment-a", package, _reports(), _rankings(), raw
    )
    assert assessment.recommendation == "conditional_proceed"
    assert assessment.strong_constraint_failed_count == 0
    assert assessment.weak_constraint_failed_count == 1


def test_quantitative_assessment_does_not_fail_or_count_as_enterprise_risk():
    package = _package()
    raw = _raw(package, rating_level="AAA3")
    target = next(
        item
        for item in raw["direction_results"]
        if item["section_id"] == "quantitative_assessment"
    )
    target["status"] = "failed"
    with pytest.raises(ValueError, match="quantitative assessment"):
        validate_overall_assessment_output(
            "assessment-a", package, _reports(), _rankings(), raw
        )

    experimental_package = _package(experimental=True)
    experimental_raw = _raw(experimental_package, rating_level="AAA3")
    quantitative = next(
        item
        for item in experimental_raw["direction_results"]
        if item["section_id"] == "quantitative_assessment"
    )
    quantitative["status"] = "conditional_passed"
    with pytest.raises(ValueError, match="experimental quantitative"):
        validate_overall_assessment_output(
            "assessment-test",
            experimental_package,
            _reports(review_status="pending"),
            _rankings(review_status="pending"),
            experimental_raw,
        )


def test_direction_scores_are_preserved_and_totalled():
    package = _package()
    raw = _raw(package)
    raw["direction_results"][0]["score"] = 3
    assessment = validate_overall_assessment_output(
        "assessment-b", package, _reports(), _rankings(), raw
    )
    assert assessment.direction_results[0].score == 3
    assert assessment.total_score == 93


def test_direction_score_changes_do_not_change_recommendation_rules():
    package = _package()
    weak_sections = [
        section.section_id
        for section in GUIDELINE_SECTION_DEFINITIONS
        if section.constraint_level == "weak"
        and section.section_id != "quantitative_assessment"
    ]
    raw = _raw(package)
    for section_id in weak_sections[:3]:
        next(
            item for item in raw["direction_results"]
            if item["section_id"] == section_id
        )["status"] = "failed"
    assert validate_overall_assessment_output(
        "assessment-low", package, _reports(), _rankings(), raw
    ).recommendation == "do_not_proceed"


def test_final_report_recommendations_follow_a_to_d_boundaries():
    package = _package()

    raw = _raw(package)
    assert validate_overall_assessment_output(
        "assessment-a", package, _reports(), _rankings(), raw
    ).recommendation == "proceed_with_caution"

    raw = _raw(package, rating_level="AA3")
    next(
        item for item in raw["direction_results"] if item["section_id"] == "core_team"
    )["status"] = "insufficient_information"
    assert validate_overall_assessment_output(
        "assessment-b", package, _reports(), _rankings(), raw
    ).recommendation == "proceed_with_review"

    raw = _raw(package, rating_level="A3")
    next(
        item
        for item in raw["direction_results"]
        if item["section_id"] == "financial_position"
    )["status"] = "failed"
    assert validate_overall_assessment_output(
        "assessment-c", package, _reports(), _rankings(), raw
    ).recommendation == "conditional_proceed"

    raw = _raw(package, rating_level="CC1")
    for section_id in ("enterprise_norms", "financial_position", "market_space"):
        next(
            item for item in raw["direction_results"] if item["section_id"] == section_id
        )["status"] = "failed"
    assert validate_overall_assessment_output(
        "assessment-d", package, _reports(), _rankings(), raw
    ).recommendation == "do_not_proceed"


def test_final_report_prompt_distinguishes_failed_from_insufficient_information():
    from src.approval.overall_assessment import build_overall_assessment_messages

    prompt = "\n".join(
        message["content"] for message in build_overall_assessment_messages(_package())
    )
    assert "明确不利事实不得被信息不足掩盖" in prompt
    assert "仍必须使用 failed" in prompt


def test_final_report_repair_prompt_restates_strong_constraint_and_rating_rules():
    from src.approval.overall_assessment import _build_format_repair_messages

    prompt = _build_format_repair_messages(_package(), _raw(_package()), ValueError("test"))[-1]["content"]
    assert "hard trigger code" in prompt
    assert "total_score" in prompt and "max_score" in prompt


def test_experimental_assessment_cannot_be_approved_and_persists(tmp_path):
    package = _package(experimental=True)
    assessment = validate_overall_assessment_output(
        "assessment-test",
        package,
        _reports(review_status="pending"),
        _rankings(review_status="pending"),
        _raw(package),
    )
    assert assessment.is_experimental
    with pytest.raises(ValueError, match="experimental"):
        approve_overall_assessment(assessment)

    repository = ApprovalRepository(tmp_path / "overall.db")
    repository.save_cohort(
        PeerCohort(
            cohort_id="robotics-2025",
            industry_id="robotics",
            cohort_name="机器人同行样本",
            fiscal_period="2025",
            company_case_ids=("company-a", "company-b"),
            selection_rule="同业同期企业",
            review_status="approved",
        )
    )
    repository.save_overall_assessment(assessment)
    assert repository.get_overall_assessment("assessment-test") == assessment


def test_overall_assessment_model_rejects_credit_terms():
    package = _package()
    raw = _raw(package)
    raw["overall_judgment"] = "建议授信额度为一千万元。"
    with pytest.raises(ValueError, match="credit terms"):
        validate_overall_assessment_output(
            "assessment-a", package, _reports(), _rankings(), raw
        )


def test_overall_assessment_allows_a_not_comparable_direction():
    package = _package()
    rankings = list(_rankings())
    first = rankings[0]
    rankings[0] = DirectionRankingResult(
        cohort_id=first.cohort_id,
        section_id=first.section_id,
        comparable_company_count=2,
        ranking_groups=(DirectionRankingGroup(1, ("company-b",), "仅另一家可比较。"),),
        not_comparable_case_ids=("company-a",),
        rank_points=(DirectionRankPoint("company-b", 1, 2),),
        source_section_report_ids=first.source_section_report_ids,
        review_status=first.review_status,
    )
    raw = _raw(package)
    raw["source_direction_ranking_sections"] = raw[
        "source_direction_ranking_sections"
    ][1:]
    assessment = validate_overall_assessment_output(
        "assessment-a", package, _reports(), tuple(rankings), raw
    )
    assert first.section_id not in assessment.source_direction_ranking_sections


def test_overall_assessment_repairs_one_invalid_model_format(monkeypatch):
    package = _package()
    calls = []

    def fake_call(messages, config):
        calls.append(messages)
        if len(calls) == 1:
            raw = _raw(package)
            raw["rating_boundaries"] = "边界未按数组返回"
            return raw
        return _raw(package)

    monkeypatch.setattr("src.approval.overall_assessment.call_deepseek", fake_call)
    assessment = generate_overall_assessment(
        "assessment-a",
        package,
        _reports(),
        _rankings(),
        config=GenerationConfig(mode="thinking"),
    )
    assert assessment.total_score == 100
    assert len(calls) == 2
