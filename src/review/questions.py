"""生成可核实、可追溯的待核实问题。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.models import CaseBundle

from .comparison import CaseComparison


PRIORITIES = {"high", "medium", "low"}
ANSWER_STATUSES = {"unanswered", "answered"}


class QuestionValidationError(ValueError):
    """待核实问题不符合协议或证据引用范围。"""


@dataclass(frozen=True)
class ReviewQuestion:
    question_id: str
    question: str
    reason: str
    related_new_fact_ids: tuple[str, ...]
    historical_case_ids: tuple[str, ...]
    historical_fact_ids: tuple[str, ...]
    priority: str
    answer_status: str = "unanswered"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "reason": self.reason,
            "related_new_fact_ids": list(self.related_new_fact_ids),
            "historical_case_ids": list(self.historical_case_ids),
            "historical_fact_ids": list(self.historical_fact_ids),
            "priority": self.priority,
            "answer_status": self.answer_status,
        }


def generate_review_questions(
    new_case: CaseBundle,
    comparisons: Sequence[CaseComparison],
    config: GenerationConfig,
    *,
    historical_cases: Sequence[CaseBundle] = (),
    answered_questions: Iterable[str] = (),
    max_questions: int = 10,
) -> tuple[ReviewQuestion, ...]:
    """根据比较结果生成问题，并过滤已回答或重复问题。"""
    if config.mode != "thinking" or config.reasoning_effort != "high":
        raise ValueError("待核实问题生成必须使用 thinking 模式和 reasoning_effort=high")
    if max_questions <= 0:
        raise ValueError("max_questions 必须大于 0")
    comparison_ids = [item.historical_case_id for item in comparisons]
    if len(comparison_ids) != len(set(comparison_ids)):
        raise ValueError("比较结果中的历史案例不得重复")

    raw_result = call_deepseek(
        _build_messages(new_case, comparisons),
        config,
    )
    known_historical_ids = set(comparison_ids)
    known_historical_fact_ids = _historical_fact_ids(comparisons, historical_cases)
    answered = {_normalize(value) for value in answered_questions if isinstance(value, str)}
    return _validate_questions(
        raw_result,
        new_fact_ids={fact.fact_id for fact in new_case.facts},
        historical_case_ids=known_historical_ids,
        historical_fact_ids=known_historical_fact_ids,
        answered_questions=answered,
        max_questions=max_questions,
    )


def _build_messages(
    new_case: CaseBundle,
    comparisons: Sequence[CaseComparison],
) -> list[dict[str, str]]:
    payload = {
        "task": "根据新旧案例比较结果生成待核实问题。问题必须能通过材料、访谈、流水或合同进一步核实。",
        "constraints": [
            "问题只能来源于新案例信息缺口、比较差异或历史案例中值得核实的机制差异。",
            "related_new_fact_ids、historical_case_ids、historical_fact_ids 只能引用输入中的 ID。",
            "不重复询问材料已经明确回答的问题。",
            "不生成审批、授信、风险定级或业务决策结论。",
            "问题应是可回答的核查事项，不要写成结论或泛泛建议。",
            "answer_status 必须为 unanswered。",
        ],
        "new_case": {
            "case_id": new_case.case.case_id,
            "case_name": new_case.case.case_name,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "statement": fact.statement,
                    "source_excerpt": fact.source_excerpt,
                }
                for fact in new_case.facts
            ],
        },
        "comparisons": [comparison.to_dict() for comparison in comparisons],
        "output_schema": {
            "questions": [
                {
                    "question_id": "QUESTION_001",
                    "question": "",
                    "reason": "",
                    "related_new_fact_ids": [],
                    "historical_case_ids": [],
                    "historical_fact_ids": [],
                    "priority": "high|medium|low",
                    "answer_status": "unanswered",
                }
            ]
        },
    }
    return [
        {
            "role": "system",
            "content": "你是金融风险案例核查问题生成器。只输出一个合法 JSON 对象，不输出 Markdown，不生成审批结论。",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _validate_questions(
    raw_result: dict[str, Any],
    *,
    new_fact_ids: set[str],
    historical_case_ids: set[str],
    historical_fact_ids: set[str],
    answered_questions: set[str],
    max_questions: int,
) -> tuple[ReviewQuestion, ...]:
    if not isinstance(raw_result, dict):
        raise QuestionValidationError("问题结果顶层必须是对象")
    if set(raw_result) - {"questions", "api_meta"}:
        raise QuestionValidationError("问题结果包含协议之外的顶层字段")
    raw_questions = raw_result.get("questions")
    if not isinstance(raw_questions, list):
        raise QuestionValidationError("问题结果缺少 questions 数组")
    if len(raw_questions) > max_questions:
        raise QuestionValidationError(f"问题数量超过 max_questions={max_questions}")

    required_keys = {
        "question_id",
        "question",
        "reason",
        "related_new_fact_ids",
        "historical_case_ids",
        "historical_fact_ids",
        "priority",
        "answer_status",
    }
    seen_ids: set[str] = set()
    seen_questions: set[str] = set()
    result: list[ReviewQuestion] = []
    for index, item in enumerate(raw_questions, start=1):
        if not isinstance(item, dict) or set(item) != required_keys:
            raise QuestionValidationError(f"第 {index} 个问题字段不符合协议")
        question_id = _nonempty_text(item["question_id"], "question_id")
        if question_id in seen_ids:
            raise QuestionValidationError(f"question_id 重复：{question_id}")
        seen_ids.add(question_id)
        question = _nonempty_text(item["question"], "question")
        normalized_question = _normalize(question)
        if normalized_question in seen_questions:
            raise QuestionValidationError("问题内容重复")
        seen_questions.add(normalized_question)
        if normalized_question in answered_questions or _normalize(question_id) in answered_questions:
            continue
        reason = _nonempty_text(item["reason"], "reason")
        related_new = _id_list(item["related_new_fact_ids"], new_fact_ids, "related_new_fact_ids")
        historical_cases = _id_list(
            item["historical_case_ids"], historical_case_ids, "historical_case_ids"
        )
        historical_facts = _id_list(
            item["historical_fact_ids"], historical_fact_ids, "historical_fact_ids"
        )
        if item["priority"] not in PRIORITIES:
            raise QuestionValidationError("priority 非法")
        if item["answer_status"] not in ANSWER_STATUSES:
            raise QuestionValidationError("answer_status 非法")
        if item["answer_status"] == "answered":
            continue
        result.append(
            ReviewQuestion(
                question_id=question_id,
                question=question,
                reason=reason,
                related_new_fact_ids=tuple(related_new),
                historical_case_ids=tuple(historical_cases),
                historical_fact_ids=tuple(historical_facts),
                priority=item["priority"],
                answer_status="unanswered",
            )
        )
    return tuple(result)


def _historical_fact_ids(
    comparisons: Sequence[CaseComparison],
    historical_cases: Sequence[CaseBundle],
) -> set[str]:
    if historical_cases:
        return {
            fact.fact_id
            for bundle in historical_cases
            for fact in bundle.facts
        }
    return {
        fact_id
        for comparison in comparisons
        for finding in (*comparison.similarities, *comparison.differences)
        for fact_id in finding.historical_fact_ids
    }


def _id_list(value: Any, allowed: set[str], field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise QuestionValidationError(f"{field_name} 必须是数组")
    if any(not isinstance(item, str) or item not in allowed for item in value):
        raise QuestionValidationError(f"{field_name} 引用了不存在的 ID")
    if len(value) != len(set(value)):
        raise QuestionValidationError(f"{field_name} 不得重复")
    return value


def _nonempty_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuestionValidationError(f"{field_name} 不能为空")
    return value.strip()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()
