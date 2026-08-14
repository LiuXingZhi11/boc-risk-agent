from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.retrieval.reranker import RerankResponse, RerankedCase
from src.review.comparison import CaseComparison, DifferenceFinding, RuleApplicability, SimilarityFinding
from src.review.fixed_review import FixedReviewComparison, FixedReviewContext
from src.review.questions import ReviewQuestion
from src.review.report import (
    DISCLAIMER,
    ReportValidationError,
    ReviewReport,
    build_review_report,
    validate_review_report,
)


def bundles() -> tuple[CaseBundle, CaseBundle]:
    now = datetime.now(timezone.utc).isoformat()
    new_facts = (
        Fact("NEW_CASE_REPORT_F001", "新案例存在关联关系", "新材料片段", "relationship", "reported_fact", None, "known_before_target"),
        Fact("NEW_CASE_REPORT_F002", "新案例贷款出现风险", "新风险片段", "risk_event", "reported_fact", None, "known_at_target"),
    )
    historical_facts = (
        Fact("CASE_REPORT_F001", "历史案例存在关联关系", "历史材料片段", "relationship", "reported_fact", None, "known_before_target"),
        Fact("CASE_REPORT_F002", "历史案例贷款出现风险", "历史风险片段", "risk_event", "reported_fact", None, "known_at_target"),
    )
    new_case = CaseBundle(
        case=Case(
            "NEW_CASE_REPORT",
            "新案例",
            "新案例原文",
            target_event=TargetEvent("NEW_CASE_REPORT_F002"),
            created_at=now,
            updated_at=now,
        ),
        facts=new_facts,
    )
    historical_case = CaseBundle(
        case=Case(
            "CASE_REPORT",
            "历史案例",
            "历史原文",
            target_event=TargetEvent("CASE_REPORT_F002"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=historical_facts,
        rule_hypotheses=(
            RuleHypothesis(
                "CASE_REPORT_R001",
                "CASE_REPORT",
                "关联关系可能放大风险",
                ("CASE_REPORT_F001", "CASE_REPORT_F002"),
                review_status="approved",
            ),
        ),
    )
    return new_case, historical_case


def comparison_context() -> FixedReviewComparison:
    new_case, historical_case = bundles()
    context = FixedReviewContext(
        run_id="REVIEW_REPORT",
        raw_case_text="新案例原文",
        structured_case={"case_records": []},
        new_case_bundle=new_case,
        retrieval_query="关联关系 贷款风险",
        candidates=(),
        rerank=RerankResponse(
            ranked_cases=(
                RerankedCase(
                    "CASE_REPORT",
                    1,
                    "high",
                    ("关联关系相似",),
                    ("主体信息不同",),
                    (),
                ),
            )
        ),
        historical_cases=(historical_case,),
    )
    comparison = CaseComparison(
        "CASE_REPORT",
        (SimilarityFinding("两案均有关联关系", ("NEW_CASE_REPORT_F001",), ("CASE_REPORT_F001",), "high"),),
        (DifferenceFinding("历史案例信息更完整", ("NEW_CASE_REPORT_F001",), ("CASE_REPORT_F001",), "medium"),),
        (RuleApplicability("CASE_REPORT_R001", "partially_relevant", "风险机制部分相似"),),
        ("关联关系具体形式仍需核实",),
    )
    return FixedReviewComparison(
        context=context,
        comparisons=(comparison,),
        historical_rule_references=(
            {
                "historical_case_id": "CASE_REPORT",
                "rule_id": "CASE_REPORT_R001",
                "applicability": "partially_relevant",
                "reason": "风险机制部分相似",
            },
        ),
    )


def test_build_review_report_has_evidence_and_disclaimer() -> None:
    report = build_review_report(
        comparison_context(),
        (
            ReviewQuestion(
                "QUESTION_001",
                "关联关系具体形式是什么？",
                "材料未明确",
                ("NEW_CASE_REPORT_F001",),
                ("CASE_REPORT",),
                ("CASE_REPORT_F001",),
                "high",
            ),
        ),
    )
    payload = report.to_dict()

    assert payload["run_id"] == "REVIEW_REPORT"
    assert payload["disclaimer"] == DISCLAIMER
    assert payload["similar_cases"][0]["historical_case_id"] == "CASE_REPORT"
    assert payload["cross_case_findings"][0]["historical_fact_ids"] == ["CASE_REPORT_F001"]
    assert payload["evidence_index"]["NEW_CASE_REPORT_F001"]["source_excerpt"] == "新材料片段"
    assert payload["evidence_index"]["CASE_REPORT_R001"]["type"] == "historical_rule_reference"
    assert payload["questions_to_verify"][0]["answer_status"] == "unanswered"


def test_empty_report_has_limitation_and_no_fabricated_history() -> None:
    new_case, _ = bundles()
    context = FixedReviewComparison(
        context=FixedReviewContext(
            run_id="REVIEW_EMPTY",
            raw_case_text="新案例",
            structured_case={},
            new_case_bundle=new_case,
            retrieval_query="查询",
            candidates=(),
            rerank=RerankResponse(()),
            historical_cases=(),
        ),
        comparisons=(),
        historical_rule_references=(),
    )
    report = build_review_report(context)
    assert report.similar_cases == ()
    assert any("没有召回" in item for item in report.limitations)
    assert any("没有加载" in item for item in report.limitations)


def test_severely_incomplete_new_case_hides_relevance_level() -> None:
    _, historical_case = bundles()
    now = datetime.now(timezone.utc).isoformat()
    sparse_new_case = CaseBundle(
        case=Case(
            "NEW_CASE_SPARSE",
            "信息缺失案例",
            "材料只有一句话",
            target_event=TargetEvent("NEW_CASE_SPARSE_F001"),
            created_at=now,
            updated_at=now,
        ),
        facts=(
            Fact(
                "NEW_CASE_SPARSE_F001",
                "企业贷款出现风险",
                "企业贷款出现风险",
                "risk_event",
                "reported_fact",
                None,
                "known_at_target",
            ),
        ),
    )
    base = comparison_context()
    sparse_context = FixedReviewComparison(
        context=FixedReviewContext(
            run_id="REVIEW_SPARSE",
            raw_case_text="材料只有一句话",
            structured_case={},
            new_case_bundle=sparse_new_case,
            retrieval_query="贷款风险",
            candidates=(),
            rerank=base.context.rerank,
            historical_cases=(historical_case,),
        ),
        comparisons=base.comparisons,
        historical_rule_references=base.historical_rule_references,
    )

    report = build_review_report(sparse_context)

    assert report.similar_cases[0]["relevance"] is None
    assert report.similar_cases[0]["relevance_limited_by_evidence"] is True
    assert any("事实严重不足" in item for item in report.limitations)


def test_report_rejects_forbidden_fields_and_answered_questions() -> None:
    report = ReviewReport(
        run_id="RUN",
        new_case_summary={"approval_decision": "approve"},
        similar_cases=(),
        cross_case_findings=(),
        important_differences=(),
        historical_rule_references=(),
        questions_to_verify=(),
        limitations=(),
        evidence_index={},
    )
    with pytest.raises(ReportValidationError, match="禁止字段"):
        validate_review_report(report)
