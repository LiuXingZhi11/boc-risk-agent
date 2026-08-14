from __future__ import annotations

from copy import deepcopy

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.graphs.ingestion_graph import build_ingestion_graph
from src.llm.generation_config import GenerationConfig
from src.storage.repository import CaseRepository


def valid_structure(case_id: str = "CASE_GRAPH_001") -> dict:
    return {
        "case_records": [
            {
                "case_id": case_id,
                "case_name": "图测试案例",
                "source": "测试来源",
                "target_event": {
                    "target_fact_id": f"{case_id}_F002",
                    "uncertainty": "",
                },
                "facts": [
                    {
                        "fact_id": f"{case_id}_F001",
                        "statement": "存在关联关系",
                        "source_excerpt": "存在关联关系",
                        "category": "relationship",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_before_target",
                        "uncertainty": "",
                    },
                    {
                        "fact_id": f"{case_id}_F002",
                        "statement": "发生目标事件",
                        "source_excerpt": "发生目标事件",
                        "category": "risk_event",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_at_target",
                        "uncertainty": "",
                    },
                ],
                "uncertainties": [],
            }
        ],
        "uncertainties": [],
        "api_meta": {
            "stage": "structure",
            "model": "fake-model",
            "generation_mode": "thinking",
            "reasoning_effort": "high",
        },
    }


def valid_rules(case_id: str = "CASE_GRAPH_001") -> dict:
    return {
        "single_case_rule_hypotheses": [
            {
                "rule_id": f"{case_id}_RULE_001",
                "case_id": case_id,
                "rule_hypothesis": "关联关系可能放大风险",
                "supporting_fact_ids": [f"{case_id}_F001", f"{case_id}_F002"],
                "uncertainty": "仍需核实",
                "generalization_status": "single_case_hypothesis",
            }
        ],
        "uncertainties": [],
        "api_meta": {
            "stage": "rules",
            "model": "fake-model",
            "generation_mode": "thinking",
            "reasoning_effort": "high",
        },
    }


def make_graph(tmp_path, monkeypatch, *, structure=None, rules=None):
    structure_result = structure or valid_structure()
    rules_result = rules or valid_rules()
    monkeypatch.setattr(
        "src.graphs.ingestion_graph.structure_case",
        lambda case_text, guide_text, config: deepcopy(structure_result),
    )
    monkeypatch.setattr(
        "src.graphs.ingestion_graph.extract_rule_hypotheses",
        lambda structured_cases, guide_text, config: deepcopy(rules_result),
    )
    checkpoint_path = tmp_path / "checkpoints.db"
    business_path = tmp_path / "business.db"
    checkpointer_context = SqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = checkpointer_context.__enter__()
    graph = build_ingestion_graph(
        structure_guide="structure guide",
        rule_guide="rule guide",
        structure_config=GenerationConfig(mode="thinking"),
        rule_config=GenerationConfig(mode="thinking"),
        database_path=str(business_path),
        checkpointer=checkpointer,
    )
    return graph, checkpointer_context, business_path


def invoke_until_review(graph, thread_id: str = "thread-001"):
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {
            "thread_id": thread_id,
            "raw_case_text": "历史案例原文",
            "source": "测试来源",
        },
        config,
    )
    return result, config


def test_ingestion_pauses_then_accepts_and_saves(tmp_path, monkeypatch) -> None:
    graph, checkpointer_context, business_path = make_graph(tmp_path, monkeypatch)
    try:
        paused, config = invoke_until_review(graph)
        assert "__interrupt__" in paused
        assert graph.get_state(config).next == ("human_review",)

        completed = graph.invoke(Command(resume={"decision": "accept"}), config)
        assert completed["saved_case_id"] == "CASE_GRAPH_001"
        bundle = CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001")
        assert bundle is not None
        assert len(bundle.processing_runs) == 3
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_reject_does_not_save(tmp_path, monkeypatch) -> None:
    graph, checkpointer_context, business_path = make_graph(tmp_path, monkeypatch)
    try:
        _, config = invoke_until_review(graph, "thread-reject")
        completed = graph.invoke(Command(resume={"decision": "reject"}), config)
        assert completed.get("saved_case_id") is None
        assert completed["error"]["code"] == "human_rejected"
        assert CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001") is None
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_accept_with_edits_revalidates_before_save(tmp_path, monkeypatch) -> None:
    graph, checkpointer_context, business_path = make_graph(tmp_path, monkeypatch)
    try:
        _, config = invoke_until_review(graph, "thread-edit")
        edited_structure = valid_structure()
        edited_structure["case_records"][0]["case_name"] = "人工修改后的案例"
        completed = graph.invoke(
            Command(
                resume={
                    "decision": "accept_with_edits",
                    "structured_case": edited_structure,
                    "rule_hypotheses": valid_rules(),
                }
            ),
            config,
        )
        assert completed["saved_case_id"] == "CASE_GRAPH_001"
        bundle = CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001")
        assert bundle is not None
        assert bundle.case.case_name == "人工修改后的案例"
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_structure_validation_failure_does_not_save(tmp_path, monkeypatch) -> None:
    invalid = valid_structure()
    invalid["case_records"][0]["target_event"]["target_fact_id"] = "MISSING"
    graph, checkpointer_context, business_path = make_graph(
        tmp_path, monkeypatch, structure=invalid
    )
    try:
        result, _ = invoke_until_review(graph, "thread-structure-fail")
        assert result["error"]["code"] == "structure_validation_error"
        assert result["current_stage"] == "failure"
        assert CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001") is None
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_rules_validation_failure_does_not_save(tmp_path, monkeypatch) -> None:
    invalid = valid_rules()
    invalid["single_case_rule_hypotheses"][0]["supporting_fact_ids"] = ["MISSING"]
    graph, checkpointer_context, business_path = make_graph(
        tmp_path, monkeypatch, rules=invalid
    )
    try:
        result, _ = invoke_until_review(graph, "thread-rules-fail")
        assert result["error"]["code"] == "rules_validation_error"
        assert result["current_stage"] == "failure"
        assert CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001") is None
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_save_failure_is_recorded_and_does_not_save(tmp_path, monkeypatch) -> None:
    graph, checkpointer_context, business_path = make_graph(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.graphs.ingestion_graph.CaseRepository.save_case_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("模拟数据库失败")),
    )
    try:
        _, config = invoke_until_review(graph, "thread-save-fail")
        result = graph.invoke(Command(resume={"decision": "accept"}), config)
        assert result["error"]["code"] == "save_error"
        assert result["current_stage"] == "failure"
        assert any(
            run["stage"] == "save_case" and run["status"] == "failed"
            for run in result["processing_runs"]
        )
        assert CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001") is None
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_threads_do_not_share_paused_state(tmp_path, monkeypatch) -> None:
    graph, checkpointer_context, business_path = make_graph(tmp_path, monkeypatch)
    try:
        _, first_config = invoke_until_review(graph, "thread-one")
        _, second_config = invoke_until_review(graph, "thread-two")
        assert graph.get_state(first_config).next == ("human_review",)
        assert graph.get_state(second_config).next == ("human_review",)

        graph.invoke(Command(resume={"decision": "accept"}), first_config)
        assert graph.get_state(second_config).next == ("human_review",)
        assert CaseRepository(business_path).get_case_bundle("CASE_GRAPH_001") is not None
    finally:
        checkpointer_context.__exit__(None, None, None)


def test_empty_input_fails_without_model_call(tmp_path, monkeypatch) -> None:
    structure_called = False

    def fail_if_called(*args, **kwargs):
        nonlocal structure_called
        structure_called = True
        raise AssertionError("不应调用模型")

    monkeypatch.setattr("src.graphs.ingestion_graph.structure_case", fail_if_called)
    monkeypatch.setattr(
        "src.graphs.ingestion_graph.extract_rule_hypotheses", fail_if_called
    )
    graph, checkpointer_context, _ = make_graph(tmp_path, monkeypatch)
    try:
        config = {"configurable": {"thread_id": "thread-empty"}}
        result = graph.invoke({"raw_case_text": ""}, config)
        assert result["error"]["code"] == "input_error"
        assert not structure_called
    finally:
        checkpointer_context.__exit__(None, None, None)
