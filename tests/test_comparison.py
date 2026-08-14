from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.llm.generation_config import GenerationConfig
from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.review.case_context import build_new_case_bundle
from src.review.comparison import (
    ComparisonValidationError,
    compare_case_pair,
    compare_case_pairs,
    collect_historical_rule_references,
)


def new_case() -> CaseBundle:
    return build_new_case_bundle(
        {
            "case_records": [
                {
                    "case_id": "MODEL_NEW",
                    "case_name": "新案例",
                    "facts": [
                        {
                            "fact_id": "MODEL_F001",
                            "statement": "新案例存在关联关系",
                            "source_excerpt": "新材料一",
                            "category": "relationship",
                            "assertion_type": "reported_fact",
                            "event_time": None,
                            "knowledge_status": "known_before_target",
                            "uncertainty": None,
                        },
                        {
                            "fact_id": "MODEL_F002",
                            "statement": "新案例贷款出现风险",
                            "source_excerpt": "新材料二",
                            "category": "risk_event",
                            "assertion_type": "reported_fact",
                            "event_time": None,
                            "knowledge_status": "known_at_target",
                            "uncertainty": None,
                        },
                    ],
                    "target_event": {"target_fact_id": "MODEL_F002", "uncertainty": None},
                    "uncertainties": [],
                }
            ],
            "uncertainties": [],
        },
        raw_text="新案例原文",
        new_case_id="NEW_CASE_COMPARE",
    )


def historical_case(case_id: str = "CASE_HIST") -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact(f"{case_id}_F001", "历史案例存在关联关系", "历史材料一", "relationship", "reported_fact", None, "known_before_target"),
        Fact(f"{case_id}_F002", "历史案例贷款出现风险", "历史材料二", "risk_event", "reported_fact", None, "known_at_target"),
    )
    return CaseBundle(
        case=Case(
            case_id=case_id,
            case_name="历史案例",
            raw_text="历史原文",
            target_event=TargetEvent(f"{case_id}_F002"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=facts,
        rule_hypotheses=(
            RuleHypothesis(
                rule_id=f"{case_id}_R001",
                case_id=case_id,
                rule_hypothesis="关联关系可能放大风险",
                supporting_fact_ids=(f"{case_id}_F001", f"{case_id}_F002"),
                review_status="approved",
            ),
        ),
    )


def config() -> GenerationConfig:
    return GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0)


def payload(case_id: str = "CASE_HIST") -> dict:
    return {
        "historical_case_id": case_id,
        "similarities": [
            {
                "description": "两案均存在关联关系并出现贷款风险",
                "new_case_fact_ids": ["NEW_CASE_COMPARE_F001", "NEW_CASE_COMPARE_F002"],
                "historical_fact_ids": [f"{case_id}_F001", f"{case_id}_F002"],
                "confidence": "high",
            }
        ],
        "differences": [
            {
                "description": "历史案例具体主体信息更多",
                "new_case_fact_ids": ["NEW_CASE_COMPARE_F001"],
                "historical_fact_ids": [f"{case_id}_F001"],
                "importance": "medium",
            }
        ],
        "applicable_rule_hypotheses": [
            {
                "rule_id": f"{case_id}_R001",
                "applicability": "partially_relevant",
                "reason": "两案均涉及关联关系，但具体机制仍需核实",
            }
        ],
        "uncertainties": ["新案例的关联关系具体形式尚不明确"],
        "api_meta": {"model": "fake", "generation_mode": "thinking"},
    }


def test_compare_case_pair_validates_and_preserves_evidence(monkeypatch) -> None:
    captured = {}

    def fake_call(messages, generation_config):
        captured["messages"] = messages
        captured["config"] = generation_config
        return payload()

    monkeypatch.setattr("src.review.comparison.call_deepseek", fake_call)
    comparison = compare_case_pair(new_case(), historical_case(), config())

    assert comparison.historical_case_id == "CASE_HIST"
    assert comparison.similarities[0].new_case_fact_ids == (
        "NEW_CASE_COMPARE_F001",
        "NEW_CASE_COMPARE_F002",
    )
    assert comparison.differences[0].historical_fact_ids == ("CASE_HIST_F001",)
    assert comparison.applicable_rule_hypotheses[0].rule_id == "CASE_HIST_R001"
    assert captured["config"].reasoning_effort == "high"
    assert "CASE_HIST_F001" in captured["messages"][1]["content"]
    assert "`uncertainties` 必须是纯文本字符串数组" in captured["messages"][0]["content"]


def test_compare_rejects_unknown_fact_and_rule_ids(monkeypatch) -> None:
    monkeypatch.setattr("src.review.comparison.call_deepseek", lambda messages, config: payload())
    bad_fact = payload()
    bad_fact["similarities"][0]["new_case_fact_ids"] = ["NOT_A_FACT"]
    monkeypatch.setattr("src.review.comparison.call_deepseek", lambda messages, config: bad_fact)
    with pytest.raises(ComparisonValidationError, match="不存在的 fact_id"):
        compare_case_pair(new_case(), historical_case(), config())

    bad_rule = payload()
    bad_rule["applicable_rule_hypotheses"][0]["rule_id"] = "NOT_A_RULE"
    monkeypatch.setattr("src.review.comparison.call_deepseek", lambda messages, config: bad_rule)
    with pytest.raises(ComparisonValidationError, match="不存在的 rule_id"):
        compare_case_pair(new_case(), historical_case(), config())


def test_compare_pairs_preserve_order_and_collect_references(monkeypatch) -> None:
    def fake_call(messages, generation_config):
        return payload("CASE_HIST_2") if "CASE_HIST_2" in messages[1]["content"] else payload("CASE_HIST")

    monkeypatch.setattr("src.review.comparison.call_deepseek", fake_call)
    comparisons = compare_case_pairs(
        new_case(),
        [historical_case("CASE_HIST"), historical_case("CASE_HIST_2")],
        config(),
    )

    assert [item.historical_case_id for item in comparisons] == ["CASE_HIST", "CASE_HIST_2"]
    references = collect_historical_rule_references(comparisons)
    assert [(item["historical_case_id"], item["rule_id"]) for item in references] == [
        ("CASE_HIST", "CASE_HIST_R001"),
        ("CASE_HIST_2", "CASE_HIST_2_R001"),
    ]

    unsupported = payload()
    unsupported["applicable_rule_hypotheses"][0]["applicability"] = "not_supported"
    monkeypatch.setattr("src.review.comparison.call_deepseek", lambda messages, config: unsupported)
    comparison = compare_case_pair(new_case(), historical_case(), config())
    assert collect_historical_rule_references([comparison]) == ()


def test_compare_requires_thinking_high_and_approved_history() -> None:
    sampling = GenerationConfig(mode="sampling", temperature=0.2)
    with pytest.raises(ValueError, match="thinking"):
        compare_case_pair(new_case(), historical_case(), sampling)

    pending = historical_case()
    pending_case = Case(
        **{**pending.case.__dict__, "review_status": "pending"}
    )
    pending_bundle = CaseBundle(
        case=pending_case,
        facts=pending.facts,
        rule_hypotheses=pending.rule_hypotheses,
    )
    with pytest.raises(ValueError, match="approved"):
        compare_case_pair(new_case(), pending_bundle, config())
