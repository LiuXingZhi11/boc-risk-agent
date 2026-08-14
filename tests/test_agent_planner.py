from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agent.planner import PlanValidationError, build_default_plan, plan_review, validate_plan
from src.agent.executor import ExecutorError, ExecutorServices, STEP_EXECUTORS, execute_step
from src.agent.evaluator import evaluate_step
from src.agent.replanner import replan
from src.agent.executor import ExecutionResult
from src.agent.state import AgentDecision
from src.llm.generation_config import GenerationConfig
from src.agent.state import PlanStep, PlanStepStatus, StepType
from src.graphs.agent_graph import build_agent_graph


def test_default_plan_is_whitelisted_and_ordered() -> None:
    plan = build_default_plan("完成新案例辅助审查")

    assert [step.step_type for step in plan] == [
        StepType.STRUCTURE_NEW_CASE,
        StepType.SEARCH_SIMILAR_CASES,
        StepType.LOAD_CASE_DETAILS,
        StepType.COMPARE_CASES,
        StepType.INSPECT_RULE_HYPOTHESES,
        StepType.GENERATE_REVIEW_QUESTIONS,
        StepType.SYNTHESIZE_REPORT,
    ]


def test_plan_can_round_trip_from_dict() -> None:
    plan = build_default_plan("审查案例")

    assert [PlanStep.from_dict(step.to_dict()) for step in plan] == list(plan)


def test_invalid_step_type_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="枚举值非法"):
        validate_plan(
            [
                {
                    "step_id": "step_01",
                    "step_type": "run_shell",
                    "reason": "模型建议",
                }
            ]
        )


def test_plan_must_start_with_structure() -> None:
    with pytest.raises(PlanValidationError, match="第一步"):
        validate_plan(
            [PlanStep("step_01", StepType.SEARCH_SIMILAR_CASES, "先检索")]
        )


def test_report_requires_all_evidence_preparation_steps() -> None:
    with pytest.raises(PlanValidationError, match="缺少前置步骤"):
        validate_plan(
            [
                PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化"),
                PlanStep("step_02", StepType.SYNTHESIZE_REPORT, "出报告"),
            ]
        )


def test_plan_step_limit_is_hard() -> None:
    steps = [
        PlanStep(f"step_{index:02d}", step_type, step_type.value)
        for index, step_type in enumerate(StepType, start=1)
    ]
    with pytest.raises(PlanValidationError, match="不得超过"):
        validate_plan(steps, max_steps=7)


def test_completed_step_cannot_be_reopened() -> None:
    with pytest.raises(PlanValidationError, match="不得被重新置为"):
        validate_plan(
            [
                PlanStep(
                    "step_01",
                    StepType.STRUCTURE_NEW_CASE,
                    "结构化",
                    status=PlanStepStatus.PENDING,
                )
            ],
            completed_steps=("step_01",),
        )


def test_planner_accepts_valid_structured_model_plan() -> None:
    def fake_caller(messages, config):
        assert config.mode == "thinking"
        assert "structure_new_case" in messages[1]["content"]
        assert "step_id" in messages[1]["content"]
        return {
            "plan": [step.to_dict() for step in build_default_plan("审查案例")],
            "api_meta": {"total_tokens": 12},
        }

    response = plan_review(
        "审查案例",
        {"completed_steps": [], "candidate_cases": [], "loaded_cases": []},
        GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        caller=fake_caller,
    )

    assert response.degraded is False
    assert response.error is None
    assert response.api_meta["total_tokens"] == 12


def test_planner_invalid_output_falls_back_to_default_plan() -> None:
    response = plan_review(
        "审查案例",
        {"completed_steps": [], "candidate_cases": [], "loaded_cases": []},
        GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        caller=lambda messages, config: {"plan": [{"step_type": "run_shell"}]},
    )

    assert response.degraded is True
    assert "降级" in response.error
    assert response.plan[0].step_type is StepType.STRUCTURE_NEW_CASE


def test_planner_failure_preserves_completed_steps_in_fallback() -> None:
    response = plan_review(
        "审查案例",
        {"completed_steps": ["step_01"], "candidate_cases": [], "loaded_cases": []},
        GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        caller=lambda messages, config: (_ for _ in ()).throw(RuntimeError("API down")),
    )

    assert response.degraded is True
    assert response.plan[0].status is PlanStepStatus.COMPLETED


def test_executor_exposes_only_static_step_whitelist() -> None:
    assert set(STEP_EXECUTORS) == set(StepType)
    assert all(isinstance(name, str) for name in STEP_EXECUTORS.values())


def test_executor_runs_handler_and_limits_state_updates() -> None:
    step = PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化")
    services = ExecutorServices(
        {"structure_new_case": lambda state: {"structured_new_case": {"case_records": []}}}
    )

    result = execute_step(step, {}, services)

    assert result.updates["structured_new_case"] == {"case_records": []}
    assert result.step_type is StepType.STRUCTURE_NEW_CASE


def test_executor_rejects_unexpected_state_update() -> None:
    step = PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化")
    services = ExecutorServices(
        {"structure_new_case": lambda state: {"final_report": {"bad": True}}}
    )

    with pytest.raises(ExecutorError, match="未授权状态字段"):
        execute_step(step, {}, services)


def test_executor_rejects_repeated_step() -> None:
    step = PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化")
    services = ExecutorServices(
        {"structure_new_case": lambda state: {"structured_new_case": {}}}
    )

    with pytest.raises(ExecutorError, match="不得重复执行"):
        execute_step(step, {"completed_steps": ["step_01"]}, services)


def test_executor_rejects_missing_service() -> None:
    step = PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化")

    with pytest.raises(ExecutorError, match="未提供步骤服务"):
        execute_step(step, {}, ExecutorServices({}))


def test_evaluator_continues_after_valid_non_report_step() -> None:
    step = PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化")
    result = ExecutionResult("step_01", step.step_type, {"structured_new_case": {"ok": True}}, "完成")

    evaluation = evaluate_step(step, result)

    assert evaluation.decision is AgentDecision.CONTINUE


def test_evaluator_finishes_after_report() -> None:
    step = PlanStep("step_07", StepType.SYNTHESIZE_REPORT, "报告")
    result = ExecutionResult("step_07", step.step_type, {"final_report": {"ok": True}}, "完成")

    assert evaluate_step(step, result).decision is AgentDecision.FINISH


def test_evaluator_requests_human_input_when_missing() -> None:
    step = PlanStep("human", StepType.REQUEST_HUMAN_INPUT, "补充")
    result = ExecutionResult("human", step.step_type, {}, "等待")

    evaluation = evaluate_step(step, result)

    assert evaluation.decision is AgentDecision.NEED_HUMAN_INPUT
    assert evaluation.missing_information


def test_evaluator_replans_when_required_result_is_missing() -> None:
    step = PlanStep("step_04", StepType.COMPARE_CASES, "比较")
    result = ExecutionResult("step_04", step.step_type, {}, "完成")

    assert evaluate_step(step, result).decision is AgentDecision.REPLAN


def test_replanner_inserts_human_input_without_rewriting_completed_steps() -> None:
    plan = build_default_plan("审查案例")
    result = replan(
        plan,
        {"completed_steps": ["step_01"], "replan_count": 0},
        decision=AgentDecision.NEED_HUMAN_INPUT,
        reason="事实不足",
    )

    assert result.replan_count == 1
    assert result.plan[0].status is PlanStepStatus.COMPLETED
    assert result.plan[1].step_type is StepType.REQUEST_HUMAN_INPUT


def test_replanner_stops_at_hard_limit() -> None:
    plan = build_default_plan("审查案例")
    result = replan(
        plan,
        {"completed_steps": [], "replan_count": 2},
        decision=AgentDecision.REPLAN,
        reason="再次失败",
    )

    assert result.stopped is True
    assert result.replan_count == 2


def test_agent_graph_runs_continue_and_finish_routes() -> None:
    def fake_planner(messages, config):
        return {"plan": [step.to_dict() for step in build_default_plan("审查案例")], "api_meta": {}}

    handlers = {
        "structure_new_case": lambda state: {"structured_new_case": {"facts": [1]}},
        "search_similar_cases": lambda state: {"retrieval_query": "查询", "candidate_cases": [{"case_id": "H1"}]},
        "load_case_details": lambda state: {"loaded_cases": [{"case_id": "H1"}]},
        "compare_cases": lambda state: {"comparisons": [{"case_id": "H1"}]},
        "inspect_rule_hypotheses": lambda state: {"historical_rule_references": [{"rule_id": "R1"}]},
        "generate_review_questions": lambda state: {"review_questions": [{"question_id": "Q1"}]},
        "synthesize_report": lambda state: {"final_report": {"disclaimer": "辅助"}},
    }
    graph = build_agent_graph(
        planner_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        services=ExecutorServices(handlers),
        planner_caller=fake_planner,
    )

    result = graph.invoke({"user_request": "审查案例", "completed_steps": [], "trace": []})

    assert result["agent_status"] == "completed"
    assert result["next_action"] == AgentDecision.FINISH.value
    assert result["completed_steps"] == [f"step_{index:02d}" for index in range(1, 8)]
    assert result["final_report"]["disclaimer"] == "辅助"
    assert any(item["event"] == "evaluation" for item in result["trace"])


def test_agent_graph_replans_failed_step_and_retries() -> None:
    calls = {"compare": 0}

    def fake_planner(messages, config):
        return {"plan": [step.to_dict() for step in build_default_plan("审查案例")], "api_meta": {}}

    def compare_handler(state):
        calls["compare"] += 1
        return {} if calls["compare"] == 1 else {"comparisons": [{"case_id": "H1"}]}

    handlers = {
        "structure_new_case": lambda state: {"structured_new_case": {"facts": [1]}},
        "search_similar_cases": lambda state: {"candidate_cases": [{"case_id": "H1"}]},
        "load_case_details": lambda state: {"loaded_cases": [{"case_id": "H1"}]},
        "compare_cases": compare_handler,
        "inspect_rule_hypotheses": lambda state: {"historical_rule_references": [{"rule_id": "R1"}]},
        "generate_review_questions": lambda state: {"review_questions": [{"question_id": "Q1"}]},
        "synthesize_report": lambda state: {"final_report": {"disclaimer": "辅助"}},
    }
    graph = build_agent_graph(
        planner_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        services=ExecutorServices(handlers),
        planner_caller=fake_planner,
    )

    result = graph.invoke({"user_request": "审查案例", "completed_steps": [], "trace": []})

    assert calls["compare"] == 2
    assert result["replan_count"] == 1
    assert result["agent_status"] == "completed"


def test_agent_graph_pauses_and_resumes_with_human_text() -> None:
    def fake_planner(messages, config):
        steps = [
            PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "结构化"),
            PlanStep("human", StepType.REQUEST_HUMAN_INPUT, "补充事实"),
            PlanStep("step_02", StepType.SEARCH_SIMILAR_CASES, "检索"),
            PlanStep("step_03", StepType.LOAD_CASE_DETAILS, "加载"),
            PlanStep("step_04", StepType.COMPARE_CASES, "比较"),
            PlanStep("step_05", StepType.INSPECT_RULE_HYPOTHESES, "规则"),
            PlanStep("step_06", StepType.GENERATE_REVIEW_QUESTIONS, "问题"),
            PlanStep("step_07", StepType.SYNTHESIZE_REPORT, "报告"),
        ]
        return {"plan": [step.to_dict() for step in steps], "api_meta": {}}

    handlers = {
        "structure_new_case": lambda state: {"structured_new_case": {"facts": [1]}},
        "request_human_input": lambda state: {},
        "search_similar_cases": lambda state: {"candidate_cases": [{"case_id": "H1"}]},
        "load_case_details": lambda state: {"loaded_cases": [{"case_id": "H1"}]},
        "compare_cases": lambda state: {"comparisons": [{"case_id": "H1"}]},
        "inspect_rule_hypotheses": lambda state: {"historical_rule_references": [{"rule_id": "R1"}]},
        "generate_review_questions": lambda state: {"review_questions": [{"question_id": "Q1"}]},
        "synthesize_report": lambda state: {"final_report": {"disclaimer": "辅助"}},
    }
    graph = build_agent_graph(
        planner_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        services=ExecutorServices(handlers),
        planner_caller=fake_planner,
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "agent-human"}}

    paused = graph.invoke({"user_request": "审查案例", "trace": []}, config)
    assert "__interrupt__" in paused

    completed = graph.invoke(Command(resume="补充：企业与关联方存在共同控制关系。"), config)

    assert completed["agent_status"] == "completed"
    assert completed["human_input"].startswith("补充：")


def test_agent_graph_failure_routes_to_failure_node() -> None:
    def fake_planner(messages, config):
        return {"plan": [step.to_dict() for step in build_default_plan("审查案例")], "api_meta": {}}

    graph = build_agent_graph(
        planner_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        services=ExecutorServices({}),
        planner_caller=fake_planner,
    )

    result = graph.invoke({"user_request": "审查案例", "trace": []})

    assert result["agent_status"] == "failed"
    assert result["next_action"] == AgentDecision.FAIL.value


def test_agent_graph_falls_back_to_fixed_flow_on_failure() -> None:
    def fake_planner(messages, config):
        return {"plan": [step.to_dict() for step in build_default_plan("审查案例")], "api_meta": {}}

    def fallback(state):
        return {
            "final_report": {"limitations": ["Agent 失败，已回退固定流程"]},
            "errors": [{"code": "agent_error", "message": "测试失败"}],
        }

    graph = build_agent_graph(
        planner_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        services=ExecutorServices({}),
        planner_caller=fake_planner,
        fixed_flow_fallback=fallback,
    )

    result = graph.invoke({"user_request": "审查案例", "trace": []})

    assert result["agent_status"] == "limited"
    assert result["degraded"] is True
    assert result["final_report"]["limitations"]
    assert any(item["event"] == "fixed_flow_fallback" for item in result["trace"])
