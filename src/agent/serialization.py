"""Agent 图状态使用的领域对象 JSON 序列化边界。"""

from __future__ import annotations

from typing import Any, Mapping

from src.models import Case, CaseBundle, Fact, ProcessingRun, RuleHypothesis, TargetEvent


class AgentSerializationError(ValueError):
    """Agent 状态中的领域对象无法安全序列化或恢复。"""


def case_bundle_to_dict(bundle: CaseBundle) -> dict[str, Any]:
    """把 CaseBundle 转成只包含 JSON 基础类型的对象。"""
    return {
        "case": {
            "case_id": bundle.case.case_id,
            "case_name": bundle.case.case_name,
            "raw_text": bundle.case.raw_text,
            "source": bundle.case.source,
            "case_type": bundle.case.case_type,
            "target_event": (
                {
                    "target_fact_id": bundle.case.target_event.target_fact_id,
                    "uncertainty": bundle.case.target_event.uncertainty,
                }
                if bundle.case.target_event
                else None
            ),
            "review_status": bundle.case.review_status,
            "created_at": bundle.case.created_at,
            "updated_at": bundle.case.updated_at,
        },
        "facts": [
            {
                "fact_id": fact.fact_id,
                "statement": fact.statement,
                "source_excerpt": fact.source_excerpt,
                "category": fact.category,
                "assertion_type": fact.assertion_type,
                "event_time": fact.event_time,
                "knowledge_status": fact.knowledge_status,
                "uncertainty": fact.uncertainty,
            }
            for fact in bundle.facts
        ],
        "rule_hypotheses": [
            {
                "rule_id": rule.rule_id,
                "case_id": rule.case_id,
                "rule_hypothesis": rule.rule_hypothesis,
                "supporting_fact_ids": list(rule.supporting_fact_ids),
                "uncertainty": rule.uncertainty,
                "generalization_status": rule.generalization_status,
                "review_status": rule.review_status,
            }
            for rule in bundle.rule_hypotheses
        ],
        "processing_runs": [
            {
                "run_id": run.run_id,
                "case_id": run.case_id,
                "stage": run.stage,
                "model": run.model,
                "generation_mode": run.generation_mode,
                "reasoning_effort": run.reasoning_effort,
                "temperature": run.temperature,
                "prompt_tokens": run.prompt_tokens,
                "completion_tokens": run.completion_tokens,
                "total_tokens": run.total_tokens,
                "status": run.status,
                "error_message": run.error_message,
                "created_at": run.created_at,
            }
            for run in bundle.processing_runs
        ],
        "api_meta": dict(bundle.api_meta or {}),
    }


def case_bundle_from_dict(data: Mapping[str, Any]) -> CaseBundle:
    """严格从 JSON 基础类型恢复 CaseBundle。"""
    if not isinstance(data, Mapping):
        raise AgentSerializationError("CaseBundle 必须是对象。")
    case_data = data.get("case")
    if not isinstance(case_data, Mapping):
        raise AgentSerializationError("CaseBundle.case 必须是对象。")
    target_data = case_data.get("target_event")
    target_event = None
    if target_data is not None:
        if not isinstance(target_data, Mapping):
            raise AgentSerializationError("target_event 必须是对象或 None。")
        target_event = TargetEvent(
            target_data.get("target_fact_id"), target_data.get("uncertainty")
        )
    facts_data = data.get("facts", [])
    rules_data = data.get("rule_hypotheses", [])
    runs_data = data.get("processing_runs", [])
    if not all(isinstance(value, list) for value in (facts_data, rules_data, runs_data)):
        raise AgentSerializationError("facts、rule_hypotheses、processing_runs 必须是数组。")
    case = Case(
        case_id=case_data.get("case_id"),
        case_name=case_data.get("case_name"),
        raw_text=case_data.get("raw_text"),
        source=case_data.get("source"),
        case_type=case_data.get("case_type"),
        target_event=target_event,
        review_status=case_data.get("review_status", "pending"),
        created_at=case_data.get("created_at"),
        updated_at=case_data.get("updated_at"),
    )
    facts = tuple(Fact.from_dict(item) for item in facts_data)
    rules = tuple(
        RuleHypothesis.from_dict(item, review_status=item.get("review_status", "pending"))
        for item in rules_data
    )
    runs = tuple(
        ProcessingRun(
            run_id=item.get("run_id"),
            case_id=item.get("case_id"),
            stage=item.get("stage"),
            model=item.get("model"),
            generation_mode=item.get("generation_mode"),
            reasoning_effort=item.get("reasoning_effort"),
            temperature=item.get("temperature"),
            prompt_tokens=item.get("prompt_tokens"),
            completion_tokens=item.get("completion_tokens"),
            total_tokens=item.get("total_tokens"),
            status=item.get("status"),
            error_message=item.get("error_message"),
            created_at=item.get("created_at"),
        )
        for item in runs_data
    )
    api_meta = data.get("api_meta")
    if api_meta is not None and not isinstance(api_meta, Mapping):
        raise AgentSerializationError("api_meta 必须是对象或 None。")
    try:
        return CaseBundle(case=case, facts=facts, rule_hypotheses=rules, processing_runs=runs, api_meta=dict(api_meta or {}))
    except (TypeError, ValueError) as exc:
        raise AgentSerializationError(f"CaseBundle 校验失败：{exc}") from exc
