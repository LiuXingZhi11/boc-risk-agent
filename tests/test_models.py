from datetime import datetime, timezone

import pytest

from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent


def _case() -> Case:
    now = datetime.now(timezone.utc).isoformat()
    return Case(
        case_id="CASE_001",
        case_name="测试案例",
        raw_text="案例原文",
        target_event=TargetEvent("CASE_001_F002"),
        created_at=now,
        updated_at=now,
    )


def _facts() -> tuple[Fact, Fact]:
    return (
        Fact(
            fact_id="CASE_001_F001",
            statement="主体存在关联关系",
            source_excerpt="主体存在关联关系",
            category="relationship",
            assertion_type="reported_fact",
            event_time=None,
            knowledge_status="known_before_target",
        ),
        Fact(
            fact_id="CASE_001_F002",
            statement="发生目标风险事件",
            source_excerpt="发生目标风险事件",
            category="risk_event",
            assertion_type="reported_fact",
            event_time=None,
            knowledge_status="known_at_target",
        ),
    )


def test_case_bundle_preserves_fact_and_rule_references() -> None:
    facts = _facts()
    rule = RuleHypothesis(
        rule_id="RULE_001",
        case_id="CASE_001",
        rule_hypothesis="关联关系可能放大风险",
        supporting_fact_ids=("CASE_001_F001", "CASE_001_F002"),
    )

    bundle = CaseBundle(case=_case(), facts=facts, rule_hypotheses=(rule,))

    assert bundle.case.target_event is not None
    assert bundle.case.target_event.target_fact_id == "CASE_001_F002"
    assert bundle.rule_hypotheses[0].supporting_fact_ids == (
        "CASE_001_F001",
        "CASE_001_F002",
    )


def test_case_bundle_rejects_invalid_rule_reference() -> None:
    rule = RuleHypothesis(
        rule_id="RULE_001",
        case_id="CASE_001",
        rule_hypothesis="关联关系可能放大风险",
        supporting_fact_ids=("MISSING_FACT",),
    )

    with pytest.raises(ValueError, match="当前案例之外"):
        CaseBundle(case=_case(), facts=_facts(), rule_hypotheses=(rule,))


def test_rule_hypothesis_rejects_invalid_review_status() -> None:
    with pytest.raises(ValueError, match="review_status"):
        RuleHypothesis(
            rule_id="RULE_001",
            case_id="CASE_001",
            rule_hypothesis="关联关系可能放大风险",
            supporting_fact_ids=("CASE_001_F001",),
            review_status="unknown",
        )
