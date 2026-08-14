"""比较新旧案例并整理可追溯的历史规则参考。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.models import CaseBundle
from src.utils.json_utils import load_text


CONFIDENCE_LEVELS = {"high", "medium", "low"}
IMPORTANCE_LEVELS = {"high", "medium", "low"}
APPLICABILITY_LEVELS = {"relevant", "partially_relevant", "not_supported"}
COMPARISON_GUIDE_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "金融风险案例比较协议_第五阶段_最终精简版.md"
)


class ComparisonValidationError(ValueError):
    """案例比较结果不符合协议或引用了不存在的证据。"""


@dataclass(frozen=True)
class SimilarityFinding:
    description: str
    new_case_fact_ids: tuple[str, ...]
    historical_fact_ids: tuple[str, ...]
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "new_case_fact_ids": list(self.new_case_fact_ids),
            "historical_fact_ids": list(self.historical_fact_ids),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class DifferenceFinding:
    description: str
    new_case_fact_ids: tuple[str, ...]
    historical_fact_ids: tuple[str, ...]
    importance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "new_case_fact_ids": list(self.new_case_fact_ids),
            "historical_fact_ids": list(self.historical_fact_ids),
            "importance": self.importance,
        }


@dataclass(frozen=True)
class RuleApplicability:
    rule_id: str
    applicability: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "applicability": self.applicability,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CaseComparison:
    historical_case_id: str
    similarities: tuple[SimilarityFinding, ...]
    differences: tuple[DifferenceFinding, ...]
    applicable_rule_hypotheses: tuple[RuleApplicability, ...]
    uncertainties: tuple[str, ...]
    api_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "historical_case_id": self.historical_case_id,
            "similarities": [item.to_dict() for item in self.similarities],
            "differences": [item.to_dict() for item in self.differences],
            "applicable_rule_hypotheses": [
                item.to_dict() for item in self.applicable_rule_hypotheses
            ],
            "uncertainties": list(self.uncertainties),
            "api_meta": self.api_meta,
        }


def compare_case_pair(
    new_case: CaseBundle,
    historical_case: CaseBundle,
    config: GenerationConfig,
) -> CaseComparison:
    """调用模型比较一对案例，并对所有证据引用做确定性校验。"""
    if config.mode != "thinking" or config.reasoning_effort != "high":
        raise ValueError("案例比较必须使用 thinking 模式和 reasoning_effort=high")
    if not new_case.case.case_id.startswith("NEW_CASE_"):
        raise ValueError("new_case 必须是 NEW_CASE_ 临时案例")
    if historical_case.case.review_status != "approved":
        raise ValueError("只有 approved 历史案例才能参与比较")

    raw_result = call_deepseek(
        _build_messages(new_case, historical_case),
        config,
    )
    return _validate_comparison(raw_result, new_case, historical_case)


def compare_case_pairs(
    new_case: CaseBundle,
    historical_cases: Sequence[CaseBundle],
    config: GenerationConfig,
) -> tuple[CaseComparison, ...]:
    """按传入顺序比较多组案例，不改变历史详情。"""
    ids = [bundle.case.case_id for bundle in historical_cases]
    if len(ids) != len(set(ids)):
        raise ValueError("待比较历史案例不得重复")
    return tuple(compare_case_pair(new_case, historical_case, config) for historical_case in historical_cases)


def collect_historical_rule_references(
    comparisons: Sequence[CaseComparison],
) -> tuple[dict[str, Any], ...]:
    """只汇总 relevant/partially_relevant 的历史规则，并保留案例来源。"""
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for comparison in comparisons:
        for rule in comparison.applicable_rule_hypotheses:
            if rule.applicability == "not_supported":
                continue
            key = (comparison.historical_case_id, rule.rule_id)
            if key in seen:
                continue
            seen.add(key)
            references.append(
                {
                    "historical_case_id": comparison.historical_case_id,
                    "rule_id": rule.rule_id,
                    "applicability": rule.applicability,
                    "reason": rule.reason,
                }
            )
    return tuple(references)


def _build_messages(new_case: CaseBundle, historical_case: CaseBundle) -> list[dict[str, str]]:
    payload = {
        "task": "比较一个新案例和一个历史案例，只输出证据支持的相似点、差异、历史规则参考和不确定性。",
        "constraints": [
            "新案例事实只能填入 new_case_fact_ids，历史事实只能填入 historical_fact_ids。",
            "不得因为历史案例有某事实，就断言新案例也有该事实。",
            "缺失信息必须写入 differences 或 uncertainties。",
            "历史规则只能作为参考机制，不得生成审批、授信、风险定级或业务决策结论。",
            "所有 rule_id 只能来自 historical_case.rules。",
        ],
        "new_case": _case_payload(new_case, include_rules=False),
        "historical_case": _case_payload(historical_case, include_rules=True),
        "output_schema": {
            "historical_case_id": historical_case.case.case_id,
            "similarities": [
                {
                    "description": "",
                    "new_case_fact_ids": [],
                    "historical_fact_ids": [],
                    "confidence": "high|medium|low",
                }
            ],
            "differences": [
                {
                    "description": "",
                    "new_case_fact_ids": [],
                    "historical_fact_ids": [],
                    "importance": "high|medium|low",
                }
            ],
            "applicable_rule_hypotheses": [
                {
                    "rule_id": "",
                    "applicability": "relevant|partially_relevant|not_supported",
                    "reason": "",
                }
            ],
            "uncertainties": [],
        },
    }
    return [
        {
            "role": "system",
            "content": (
                load_text(COMPARISON_GUIDE_PATH)
                + "\n\n你是金融风险案例比较器。严格优先执行上面的输出格式硬约束。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _case_payload(bundle: CaseBundle, *, include_rules: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": bundle.case.case_id,
        "case_name": bundle.case.case_name,
        "target_event": (
            {
                "target_fact_id": bundle.case.target_event.target_fact_id,
                "uncertainty": bundle.case.target_event.uncertainty,
            }
            if bundle.case.target_event
            else None
        ),
        "facts": [
            {
                "fact_id": fact.fact_id,
                "statement": fact.statement,
                "source_excerpt": fact.source_excerpt,
                "category": fact.category,
                "knowledge_status": fact.knowledge_status,
            }
            for fact in bundle.facts
        ],
    }
    if include_rules:
        payload["rules"] = [
            {
                "rule_id": rule.rule_id,
                "rule_hypothesis": rule.rule_hypothesis,
                "supporting_fact_ids": list(rule.supporting_fact_ids),
            }
            for rule in bundle.rule_hypotheses
        ]
    return payload


def _validate_comparison(
    raw_result: dict[str, Any],
    new_case: CaseBundle,
    historical_case: CaseBundle,
) -> CaseComparison:
    if not isinstance(raw_result, dict):
        raise ComparisonValidationError("比较结果顶层必须是对象")
    required_top_level = {
        "historical_case_id",
        "similarities",
        "differences",
        "applicable_rule_hypotheses",
        "uncertainties",
    }
    if set(raw_result) - required_top_level - {"api_meta"}:
        raise ComparisonValidationError("比较结果包含协议之外的顶层字段")
    if raw_result.get("historical_case_id") != historical_case.case.case_id:
        raise ComparisonValidationError("historical_case_id 与当前比较案例不一致")

    new_fact_ids = {fact.fact_id for fact in new_case.facts}
    historical_fact_ids = {fact.fact_id for fact in historical_case.facts}
    rule_ids = {rule.rule_id for rule in historical_case.rule_hypotheses}
    similarities = tuple(
        _similarity_from_item(item, new_fact_ids, historical_fact_ids)
        for item in _required_list(raw_result, "similarities")
    )
    differences = tuple(
        _difference_from_item(item, new_fact_ids, historical_fact_ids)
        for item in _required_list(raw_result, "differences")
    )
    rule_references = tuple(
        _rule_from_item(item, rule_ids)
        for item in _required_list(raw_result, "applicable_rule_hypotheses")
    )
    uncertainties = _string_list(raw_result.get("uncertainties"), "uncertainties")
    api_meta = raw_result.get("api_meta")
    if api_meta is not None and not isinstance(api_meta, dict):
        raise ComparisonValidationError("api_meta 必须是对象")
    return CaseComparison(
        historical_case_id=historical_case.case.case_id,
        similarities=similarities,
        differences=differences,
        applicable_rule_hypotheses=rule_references,
        uncertainties=tuple(uncertainties),
        api_meta=api_meta,
    )


def _similarity_from_item(
    item: Any,
    new_fact_ids: set[str],
    historical_fact_ids: set[str],
) -> SimilarityFinding:
    data = _finding_payload(item, "similarity")
    _validate_ids(data["new_case_fact_ids"], new_fact_ids, "new_case_fact_ids")
    _validate_ids(data["historical_fact_ids"], historical_fact_ids, "historical_fact_ids")
    if data["confidence"] not in CONFIDENCE_LEVELS:
        raise ComparisonValidationError("similarity confidence 非法")
    return SimilarityFinding(
        data["description"],
        tuple(data["new_case_fact_ids"]),
        tuple(data["historical_fact_ids"]),
        data["confidence"],
    )


def _difference_from_item(
    item: Any,
    new_fact_ids: set[str],
    historical_fact_ids: set[str],
) -> DifferenceFinding:
    data = _finding_payload(item, "difference")
    _validate_ids(data["new_case_fact_ids"], new_fact_ids, "new_case_fact_ids")
    _validate_ids(data["historical_fact_ids"], historical_fact_ids, "historical_fact_ids")
    if data["importance"] not in IMPORTANCE_LEVELS:
        raise ComparisonValidationError("difference importance 非法")
    return DifferenceFinding(
        data["description"],
        tuple(data["new_case_fact_ids"]),
        tuple(data["historical_fact_ids"]),
        data["importance"],
    )


def _rule_from_item(item: Any, rule_ids: set[str]) -> RuleApplicability:
    if not isinstance(item, dict) or set(item) != {"rule_id", "applicability", "reason"}:
        raise ComparisonValidationError("历史规则参考字段不符合协议")
    if item["rule_id"] not in rule_ids:
        raise ComparisonValidationError(f"历史规则参考引用了不存在的 rule_id：{item['rule_id']!r}")
    if item["applicability"] not in APPLICABILITY_LEVELS:
        raise ComparisonValidationError("历史规则 applicability 非法")
    if not isinstance(item["reason"], str) or not item["reason"].strip():
        raise ComparisonValidationError("历史规则 reason 不能为空")
    return RuleApplicability(item["rule_id"], item["applicability"], item["reason"])


def _finding_payload(item: Any, kind: str) -> dict[str, Any]:
    expected = {
        "description",
        "new_case_fact_ids",
        "historical_fact_ids",
        "confidence" if kind == "similarity" else "importance",
    }
    if not isinstance(item, dict) or set(item) != expected:
        raise ComparisonValidationError(f"{kind} 字段不符合协议")
    if not isinstance(item["description"], str) or not item["description"].strip():
        raise ComparisonValidationError(f"{kind} description 不能为空")
    if not isinstance(item["new_case_fact_ids"], list) or not isinstance(
        item["historical_fact_ids"], list
    ):
        raise ComparisonValidationError(f"{kind} fact ID 引用必须是数组")
    return item


def _validate_ids(values: list[Any], allowed: set[str], field_name: str) -> None:
    if any(not isinstance(value, str) or value not in allowed for value in values):
        raise ComparisonValidationError(f"{field_name} 引用了不存在的 fact_id")
    if len(values) != len(set(values)):
        raise ComparisonValidationError(f"{field_name} 不得重复")


def _required_list(data: dict[str, Any], field_name: str) -> list[Any]:
    value = data.get(field_name)
    if not isinstance(value, list):
        raise ComparisonValidationError(f"{field_name} 必须是数组")
    return value


def _string_list(value: Any, field_name: str) -> list[str]:
    # 模型偶尔会把没有不确定性的结果写成 null 或 [""]；这两种情况
    # 等价于空数组，不能因此丢弃整组比较结果。非字符串内容仍然拒绝。
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ComparisonValidationError(
            f"{field_name} 必须是字符串数组，每项必须是字符串；无内容时使用空数组"
        )
    return [item.strip() for item in value if item.strip()]
