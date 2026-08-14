"""第一阶段结构化案例结果校验。"""

from __future__ import annotations

from typing import Any


STRUCTURE_TOP_LEVEL_KEYS = {"case_records", "uncertainties"}
CATEGORIES = {
    "context", "entity_attribute", "relationship", "action", "transaction",
    "financial_observation", "business_observation", "review_action",
    "risk_event", "outcome", "other",
}
ASSERTION_TYPES = {
    "reported_fact", "attributed_assessment", "estimate_or_plan", "uncertain_statement",
}
KNOWLEDGE_STATUSES = {
    "known_before_target", "known_at_target", "discovered_after_target", "time_unknown",
}


def _core(data: Any) -> Any:
    if isinstance(data, dict) and "api_meta" in data:
        return {key: value for key, value in data.items() if key != "api_meta"}
    return data


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 必须是非空字符串。")
    return value


def _validate_top_level(data: Any) -> dict[str, Any]:
    data = _core(data)
    if not isinstance(data, dict):
        raise ValueError("结构化输出顶层必须是对象。")
    missing = STRUCTURE_TOP_LEVEL_KEYS - set(data)
    extra = set(data) - STRUCTURE_TOP_LEVEL_KEYS
    if missing:
        raise ValueError(f"结构化输出缺少顶层字段：{sorted(missing)}")
    if extra:
        raise ValueError(f"结构化输出包含协议之外的顶层字段：{sorted(extra)}")
    for key in STRUCTURE_TOP_LEVEL_KEYS:
        if not isinstance(data[key], list):
            raise ValueError(f"结构化输出字段 {key!r} 必须是数组。")
    return data


def validate_structured_cases(data: dict[str, Any]) -> None:
    """校验结构化案例；失败时抛出 ValueError，不修改输入。"""
    data = _validate_top_level(data)
    case_ids: set[str] = set()
    global_fact_ids: set[str] = set()

    for case_index, case in enumerate(data["case_records"], start=1):
        if not isinstance(case, dict):
            raise ValueError(f"case_records[{case_index - 1}] 必须是对象。")
        case_id = _nonempty_string(case.get("case_id"), f"第{case_index}个案例的 case_id")
        if case_id in case_ids:
            raise ValueError(f"case_id 重复：{case_id}")
        case_ids.add(case_id)

        facts = case.get("facts")
        if not isinstance(facts, list) or not facts:
            raise ValueError(f"案例 {case_id} 的 facts 必须是非空数组。")
        fact_ids: set[str] = set()
        statuses: dict[str, str] = {}
        for fact_index, fact in enumerate(facts, start=1):
            if not isinstance(fact, dict):
                raise ValueError(f"案例 {case_id} 的第{fact_index}条事实必须是对象。")
            fact_id = _nonempty_string(fact.get("fact_id"), f"案例 {case_id} 第{fact_index}条事实的 fact_id")
            _nonempty_string(fact.get("statement"), f"事实 {fact_id} 的 statement")
            _nonempty_string(fact.get("source_excerpt"), f"事实 {fact_id} 的 source_excerpt")
            if fact_id in fact_ids:
                raise ValueError(f"案例 {case_id} 的 fact_id 重复：{fact_id}")
            if fact_id in global_fact_ids:
                raise ValueError(f"fact_id 必须全局唯一，发现重复：{fact_id}")
            category = fact.get("category")
            if category not in CATEGORIES:
                raise ValueError(f"事实 {fact_id} 的 category 非法：{category!r}")
            assertion_type = fact.get("assertion_type")
            if assertion_type not in ASSERTION_TYPES:
                raise ValueError(f"事实 {fact_id} 的 assertion_type 非法：{assertion_type!r}")
            knowledge_status = fact.get("knowledge_status")
            if knowledge_status not in KNOWLEDGE_STATUSES:
                raise ValueError(f"事实 {fact_id} 的 knowledge_status 非法：{knowledge_status!r}")
            fact_ids.add(fact_id)
            global_fact_ids.add(fact_id)
            statuses[fact_id] = knowledge_status

        target_event = case.get("target_event")
        if not isinstance(target_event, dict):
            raise ValueError(f"案例 {case_id} 的 target_event 必须是对象。")
        target_fact_id = _nonempty_string(target_event.get("target_fact_id"), f"案例 {case_id} 的 target_fact_id")
        if target_fact_id not in fact_ids:
            raise ValueError(f"案例 {case_id} 的 target_fact_id 不属于当前案例：{target_fact_id}")
        if statuses[target_fact_id] != "known_at_target":
            raise ValueError(f"案例 {case_id} 的目标事实 {target_fact_id} 必须标记为 known_at_target。")
        if not isinstance(case.get("uncertainties"), list):
            raise ValueError(f"案例 {case_id} 的 uncertainties 必须是数组。")

