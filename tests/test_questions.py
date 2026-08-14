from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.llm.generation_config import GenerationConfig
from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.review.case_context import build_new_case_bundle
from src.review.comparison import CaseComparison, RuleApplicability, SimilarityFinding
from src.review.questions import QuestionValidationError, generate_review_questions


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
        new_case_id="NEW_CASE_QUESTIONS",
    )


def historical_case() -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact("CASE_HIST_F001", "历史关联关系", "历史材料一", "relationship", "reported_fact", None, "known_before_target"),
        Fact("CASE_HIST_F002", "历史贷款风险", "历史材料二", "risk_event", "reported_fact", None, "known_at_target"),
    )
    return CaseBundle(
        case=Case(
            case_id="CASE_HIST",
            case_name="历史案例",
            raw_text="历史原文",
            target_event=TargetEvent("CASE_HIST_F002"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=facts,
        rule_hypotheses=(
            RuleHypothesis(
                rule_id="CASE_HIST_R001",
                case_id="CASE_HIST",
                rule_hypothesis="关联关系可能放大风险",
                supporting_fact_ids=("CASE_HIST_F001", "CASE_HIST_F002"),
                review_status="approved",
            ),
        ),
    )


def comparison() -> CaseComparison:
    return CaseComparison(
        historical_case_id="CASE_HIST",
        similarities=(
            SimilarityFinding(
                "两案均涉及关联关系",
                ("NEW_CASE_QUESTIONS_F001",),
                ("CASE_HIST_F001",),
                "high",
            ),
        ),
        differences=(),
        applicable_rule_hypotheses=(
            RuleApplicability("CASE_HIST_R001", "partially_relevant", "机制部分相似"),
        ),
        uncertainties=("关联关系具体形式不明确",),
    )


def config() -> GenerationConfig:
    return GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0)


def question_payload() -> dict:
    return {
        "questions": [
            {
                "question_id": "QUESTION_001",
                "question": "关联方之间具体存在何种控制关系？",
                "reason": "当前材料没有说明关联关系的法律或实际控制依据。",
                "related_new_fact_ids": ["NEW_CASE_QUESTIONS_F001"],
                "historical_case_ids": ["CASE_HIST"],
                "historical_fact_ids": ["CASE_HIST_F001"],
                "priority": "high",
                "answer_status": "unanswered",
            },
            {
                "question_id": "QUESTION_002",
                "question": "材料已经明确回答的问题",
                "reason": "模型标记为已经回答。",
                "related_new_fact_ids": ["NEW_CASE_QUESTIONS_F001"],
                "historical_case_ids": [],
                "historical_fact_ids": [],
                "priority": "low",
                "answer_status": "answered",
            },
        ],
        "api_meta": {"model": "fake"},
    }


def test_generate_questions_validates_and_filters_answered(monkeypatch) -> None:
    monkeypatch.setattr("src.review.questions.call_deepseek", lambda messages, config: question_payload())
    result = generate_review_questions(
        new_case(),
        [comparison()],
        config(),
        historical_cases=[historical_case()],
    )

    assert len(result) == 1
    assert result[0].question_id == "QUESTION_001"
    assert result[0].answer_status == "unanswered"

    filtered = generate_review_questions(
        new_case(),
        [comparison()],
        config(),
        historical_cases=[historical_case()],
        answered_questions=["QUESTION_001"],
    )
    assert filtered == ()


def test_generate_questions_rejects_unknown_ids_and_duplicates(monkeypatch) -> None:
    bad = question_payload()
    bad["questions"][0]["historical_fact_ids"] = ["NOT_A_FACT"]
    monkeypatch.setattr("src.review.questions.call_deepseek", lambda messages, config: bad)
    with pytest.raises(QuestionValidationError, match="不存在的 ID"):
        generate_review_questions(new_case(), [comparison()], config(), historical_cases=[historical_case()])

    duplicate = question_payload()
    duplicate["questions"].append(dict(duplicate["questions"][0]))
    duplicate["questions"][2]["question_id"] = "QUESTION_003"
    monkeypatch.setattr("src.review.questions.call_deepseek", lambda messages, config: duplicate)
    with pytest.raises(QuestionValidationError, match="问题内容重复"):
        generate_review_questions(new_case(), [comparison()], config(), historical_cases=[historical_case()])


def test_generate_questions_requires_thinking_high() -> None:
    sampling = GenerationConfig(mode="sampling", temperature=0.2)
    with pytest.raises(ValueError, match="thinking"):
        generate_review_questions(new_case(), [comparison()], sampling)
