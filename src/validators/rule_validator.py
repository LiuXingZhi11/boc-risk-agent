"""第二阶段规则假设结果校验。"""

from __future__ import annotations

from typing import Any

from src.validators.structure_validator import validate_structured_cases


RULE_TOP_LEVEL_KEYS = {"single_case_rule_hypotheses", "uncertainties"}
REQUIRED_RULE_KEYS = {
    "rule_id", "case_id", "rule_hypothesis", "supporting_fact_ids",
    "uncertainty", "generalization_status",
}


def _core(data: Any) -> Any:
    if isinstance(data, dict) and "api_meta" in data:
        return {key: value for key, value in data.items() if key != "api_meta"}
    return data


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必须是非空字符串。")
    return value


def _facts_by_case(structured_cases: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for case in structured_cases["case_records"]:
        result[case["case_id"]] = {
            fact["fact_id"] for fact in case["facts"]
        }
    return result


def validate_rule_hypotheses(
    data: dict[str, Any],
    structured_cases: dict[str, Any],
) -> None:
    """校验规则假设及其事实引用，不自动修改模型结果。"""
    clean_data = _core(data)
    clean_structured = _core(structured_cases)
    validate_structured_cases(clean_structured)
    if not isinstance(clean_data, dict):
        raise ValueError("规则输出顶层必须是对象。")
    missing = RULE_TOP_LEVEL_KEYS - set(clean_data)
    extra = set(clean_data) - RULE_TOP_LEVEL_KEYS
    if missing:
        raise ValueError(f"规则输出缺少顶层字段：{sorted(missing)}")
    if extra:
        raise ValueError(f"规则输出包含协议之外的顶层字段：{sorted(extra)}")
    for key in RULE_TOP_LEVEL_KEYS:
        if not isinstance(clean_data[key], list):
            raise ValueError(f"规则输出字段 {key!r} 必须是数组。")

    facts_by_case = _facts_by_case(clean_structured)
    rule_ids: set[str] = set()
    for rule_index, rule in enumerate(clean_data["single_case_rule_hypotheses"], start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"第{rule_index}条规则必须是对象。")
        missing = REQUIRED_RULE_KEYS - set(rule)
        extra = set(rule) - REQUIRED_RULE_KEYS
        if missing:
            raise ValueError(f"第{rule_index}条规则缺少字段：{sorted(missing)}")
        if extra:
            raise ValueError(f"第{rule_index}条规则包含协议之外字段：{sorted(extra)}")
        rule_id = _nonempty_string(rule.get("rule_id"), f"第{rule_index}条规则的 rule_id")
        if rule_id in rule_ids:
            raise ValueError(f"rule_id 重复：{rule_id}")
        rule_ids.add(rule_id)
        case_id = _nonempty_string(rule.get("case_id"), f"规则 {rule_id} 的 case_id")
        if case_id not in facts_by_case:
            raise ValueError(f"规则 {rule_id} 引用了不存在的 case_id：{case_id}")
        _nonempty_string(rule.get("rule_hypothesis"), f"规则 {rule_id} 的 rule_hypothesis")
        fact_ids = rule.get("supporting_fact_ids")
        if not isinstance(fact_ids, list) or not fact_ids:
            raise ValueError(f"规则 {rule_id} 的 supporting_fact_ids 必须是非空数组。")
        if any(not isinstance(fact_id, str) or not fact_id.strip() for fact_id in fact_ids):
            raise ValueError(f"规则 {rule_id} 的 supporting_fact_ids 存在无效事实ID。")
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError(f"规则 {rule_id} 的 supporting_fact_ids 存在重复。")
        invalid = [fact_id for fact_id in fact_ids if fact_id not in facts_by_case[case_id]]
        if invalid:
            raise ValueError(f"规则 {rule_id} 引用了当前案例之外或不存在的事实：{invalid}")
        if rule.get("generalization_status") != "single_case_hypothesis":
            raise ValueError(f"规则 {rule_id} 的 generalization_status 必须为 single_case_hypothesis。")

