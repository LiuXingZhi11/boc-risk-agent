"""受约束 Plan-and-Execute 图。

图只负责状态流转；具体业务能力通过 ExecutorServices 显式注入。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agent.executor import ExecutionResult, ExecutorServices, execute_step
from src.agent.evaluator import evaluate_step
from src.agent.planner import plan_review
from src.agent.replanner import replan
from src.agent.state import AgentDecision, PlanStep, PlanStepStatus, ReviewState, StepType
from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig


PlannerCaller = Callable[[list[dict[str, str]], GenerationConfig], dict[str, Any]]
FallbackHandler = Callable[[ReviewState], dict[str, Any]]


def _trace(state: ReviewState, event: str, **payload: Any) -> list[dict[str, Any]]:
    return state.get("trace", []) + [{"event": event, **payload}]


def _error(state: ReviewState, code: str, message: str) -> list[dict[str, str]]:
    return state.get("errors", []) + [{"code": code, "message": message}]


def _step_at(state: ReviewState) -> tuple[int, PlanStep] | None:
    plan = state.get("plan", [])
    index = state.get("current_step_index", 0)
    if index < 0 or index >= len(plan):
        return None
    return index, PlanStep.from_dict(plan[index])


def _replace_plan_step(
    state: ReviewState,
    step_id: str,
    *,
    status: PlanStepStatus,
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for item in state.get("plan", []):
        step = PlanStep.from_dict(item)
        if step.step_id == step_id:
            step = replace(step, status=status)
        updated.append(step.to_dict())
    return updated


def _first_uncompleted_index(plan: list[dict[str, Any]], completed_steps: list[str]) -> int:
    completed = set(completed_steps)
    for index, item in enumerate(plan):
        if item.get("step_id") not in completed and item.get("status") not in {
            PlanStepStatus.COMPLETED.value,
            PlanStepStatus.SKIPPED.value,
        }:
            return index
    return len(plan)


def build_agent_graph(
    *,
    planner_config: GenerationConfig,
    services: ExecutorServices,
    planner_caller: PlannerCaller = call_deepseek,
    fixed_flow_fallback: FallbackHandler | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    """构建 Agent 图；不在图内创建数据库、网络或任意工具。"""
    graph = StateGraph(ReviewState)

    def planner_node(state: ReviewState) -> dict[str, Any]:
        try:
            response = plan_review(
                state.get("user_request", ""),
                state,
                planner_config,
                caller=planner_caller,
            )
            updates: dict[str, Any] = {
                "plan": [step.to_dict() for step in response.plan],
                "current_step_index": _first_uncompleted_index(
                    [step.to_dict() for step in response.plan],
                    state.get("completed_steps", []),
                ),
                "iteration_count": state.get("iteration_count", 0) + 1,
                "next_action": AgentDecision.CONTINUE.value,
                "agent_status": "running",
                "degraded": state.get("degraded", False) or response.degraded,
                "trace": _trace(
                    state,
                    "planner",
                    degraded=response.degraded,
                    plan=[step.to_dict() for step in response.plan],
                    error=response.error,
                ),
            }
            if response.degraded and response.error:
                updates["errors"] = _error(state, "planner_degraded", response.error)
            return updates
        except Exception as exc:
            return {
                "next_action": AgentDecision.FAIL.value,
                "agent_status": "failed",
                "errors": _error(state, "planner_error", str(exc)),
                "trace": _trace(state, "planner_failed", error=str(exc)),
            }

    def executor_node(state: ReviewState) -> dict[str, Any]:
        selected = _step_at(state)
        if selected is None:
            return {
                "next_action": AgentDecision.FINISH.value,
                "trace": _trace(state, "executor_skipped", reason="计划已无未完成步骤"),
            }
        _, step = selected
        try:
            result = execute_step(step, state, services)
            return {
                **dict(result.updates),
                "last_execution_result": result.to_dict(),
                "next_action": AgentDecision.CONTINUE.value,
                "trace": _trace(state, "step_finished", **result.to_dict()),
            }
        except Exception as exc:
            return {
                "next_action": AgentDecision.FAIL.value,
                "agent_status": "failed",
                "errors": _error(state, "executor_error", str(exc)),
                "trace": _trace(state, "step_failed", step_id=step.step_id, error=str(exc)),
            }

    def evaluator_node(state: ReviewState) -> dict[str, Any]:
        selected = _step_at(state)
        raw_result = state.get("last_execution_result")
        if selected is None or not isinstance(raw_result, dict):
            return {
                "next_action": AgentDecision.FAIL.value,
                "agent_status": "failed",
                "errors": _error(state, "evaluator_error", "缺少当前步骤或执行结果"),
            }
        _, step = selected
        try:
            result = ExecutionResult(
                raw_result["step_id"],
                StepType(raw_result["step_type"]),
                raw_result.get("updates", {}),
                raw_result.get("summary", ""),
            )
            evaluation = evaluate_step(step, result)
            updates: dict[str, Any] = {
                "last_evaluation": evaluation.to_dict(),
                "next_action": evaluation.decision.value,
                "trace": _trace(state, "evaluation", **evaluation.to_dict()),
            }
            if evaluation.decision in {AgentDecision.CONTINUE, AgentDecision.FINISH}:
                completed = list(state.get("completed_steps", []))
                if step.step_id not in completed:
                    completed.append(step.step_id)
                updated_plan = _replace_plan_step(
                    state, step.step_id, status=PlanStepStatus.COMPLETED
                )
                updates.update(
                    {
                        "completed_steps": completed,
                        "plan": updated_plan,
                        "current_step_index": state.get("current_step_index", 0) + 1,
                    }
                )
            elif evaluation.decision in {AgentDecision.REPLAN, AgentDecision.NEED_HUMAN_INPUT}:
                updates["plan"] = _replace_plan_step(
                    state, step.step_id, status=PlanStepStatus.FAILED
                )
            if evaluation.decision == AgentDecision.FAIL:
                updates["agent_status"] = "failed"
                updates["errors"] = _error(state, "evaluation_failed", evaluation.reason)
            return updates
        except Exception as exc:
            return {
                "next_action": AgentDecision.FAIL.value,
                "agent_status": "failed",
                "errors": _error(state, "evaluator_error", str(exc)),
                "trace": _trace(state, "evaluator_failed", error=str(exc)),
            }

    def replanner_node(state: ReviewState) -> dict[str, Any]:
        try:
            decision = AgentDecision(state.get("next_action", ""))
            reason = (state.get("last_evaluation") or {}).get("reason", "需要重新规划")
            result = replan(
                state.get("plan", []),
                state,
                decision=decision,
                reason=reason,
            )
            updates: dict[str, Any] = {
                "plan": [step.to_dict() for step in result.plan],
                "replan_count": result.replan_count,
                "current_step_index": _first_uncompleted_index(
                    [step.to_dict() for step in result.plan],
                    state.get("completed_steps", []),
                ),
                "next_action": (
                    AgentDecision.FINISH.value if result.stopped else AgentDecision.CONTINUE.value
                ),
                "degraded": state.get("degraded", False) or result.stopped,
                "trace": _trace(state, "replanned", **result.to_dict()),
            }
            if result.stopped:
                updates["errors"] = _error(state, "replan_limit", result.reason)
            return updates
        except Exception as exc:
            return {
                "next_action": AgentDecision.FINISH.value,
                "agent_status": "limited",
                "degraded": True,
                "errors": _error(state, "replanner_error", str(exc)),
                "trace": _trace(state, "replanner_failed", error=str(exc)),
            }

    def human_input_node(state: ReviewState) -> dict[str, Any]:
        payload = {
            "type": "request_human_input",
            "reason": (state.get("last_evaluation") or {}).get("reason", "需要补充材料"),
            "missing_information": (state.get("last_evaluation") or {}).get(
                "missing_information", []
            ),
        }
        response = interrupt(payload)
        if isinstance(response, str) and response.strip():
            value = response.strip()
        elif isinstance(response, dict) and isinstance(response.get("human_input"), str):
            value = response["human_input"].strip()
        else:
            return {
                "next_action": AgentDecision.FAIL.value,
                "agent_status": "failed",
                "errors": _error(state, "human_input_error", "人工补充必须是非空文本。"),
            }
        selected = _step_at(state)
        completed = list(state.get("completed_steps", []))
        plan = state.get("plan", [])
        current_index = state.get("current_step_index", 0)
        if selected is not None:
            current_index, human_step = selected
            if human_step.step_id not in completed:
                completed.append(human_step.step_id)
            plan = _replace_plan_step(state, human_step.step_id, status=PlanStepStatus.COMPLETED)
        return {
            "human_input": value,
            "completed_steps": completed,
            "plan": plan,
            "current_step_index": current_index + 1,
            "next_action": AgentDecision.REPLAN.value,
            "trace": _trace(state, "human_input", text_length=len(value)),
        }

    def synthesize_report_node(state: ReviewState) -> dict[str, Any]:
        # 默认计划已由 Executor 执行报告步骤；此节点作为图的统一终点。
        return {
            "next_action": AgentDecision.FINISH.value,
            "agent_status": "completed" if state.get("final_report") else "limited",
            "trace": _trace(state, "synthesize_report", existing_report=bool(state.get("final_report"))),
        }

    def failure_node(state: ReviewState) -> dict[str, Any]:
        return {
            "agent_status": "failed",
            "next_action": AgentDecision.FAIL.value,
            "trace": _trace(state, "failure"),
        }

    def fixed_flow_fallback_node(state: ReviewState) -> dict[str, Any]:
        if fixed_flow_fallback is None:
            return failure_node(state)
        try:
            result = fixed_flow_fallback(state)
            if not isinstance(result, dict):
                raise TypeError("固定流程降级回调必须返回对象。")
            return {
                **result,
                "agent_status": "limited",
                "degraded": True,
                "next_action": AgentDecision.FINISH.value,
                "trace": _trace(state, "fixed_flow_fallback", result_keys=sorted(result)),
            }
        except Exception as exc:
            return {
                "agent_status": "failed",
                "next_action": AgentDecision.FAIL.value,
                "degraded": True,
                "errors": _error(state, "fixed_flow_fallback_error", str(exc)),
                "trace": _trace(state, "fixed_flow_fallback_failed", error=str(exc)),
            }

    def route_after_planner(state: ReviewState) -> str:
        return (
            "fallback"
            if state.get("next_action") == AgentDecision.FAIL.value and fixed_flow_fallback
            else "failure"
            if state.get("next_action") == AgentDecision.FAIL.value
            else "executor"
        )

    def route_after_evaluator(state: ReviewState) -> str:
        return state.get("next_action", AgentDecision.FAIL.value)

    def route_after_replanner(state: ReviewState) -> str:
        return "synthesize_report" if state.get("next_action") == AgentDecision.FINISH.value else "executor"

    def route_after_human(state: ReviewState) -> str:
        return (
            "fallback"
            if state.get("next_action") == AgentDecision.FAIL.value and fixed_flow_fallback
            else "failure"
            if state.get("next_action") == AgentDecision.FAIL.value
            else "replanner"
        )

    def route_after_evaluator_with_fallback(state: ReviewState) -> str:
        if state.get("next_action") == AgentDecision.FAIL.value:
            return "fallback" if fixed_flow_fallback else AgentDecision.FAIL.value
        return route_after_evaluator(state)

    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("replanner", replanner_node)
    graph.add_node("human_input", human_input_node)
    graph.add_node("synthesize_report", synthesize_report_node)
    graph.add_node("failure", failure_node)
    graph.add_node("fallback", fixed_flow_fallback_node)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"executor": "executor", "failure": "failure", "fallback": "fallback"},
    )
    graph.add_edge("executor", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        route_after_evaluator_with_fallback,
        {
            AgentDecision.CONTINUE.value: "executor",
            AgentDecision.REPLAN.value: "replanner",
            AgentDecision.NEED_HUMAN_INPUT.value: "human_input",
            AgentDecision.FINISH.value: "synthesize_report",
            AgentDecision.FAIL.value: "failure",
            "fallback": "fallback",
        },
    )
    graph.add_conditional_edges(
        "replanner",
        route_after_replanner,
        {"executor": "executor", "synthesize_report": "synthesize_report"},
    )
    graph.add_conditional_edges(
        "human_input",
        route_after_human,
        {"replanner": "replanner", "failure": "failure", "fallback": "fallback"},
    )
    graph.add_edge("fallback", END)
    graph.add_edge("synthesize_report", END)
    graph.add_edge("failure", END)
    return graph.compile(checkpointer=checkpointer)
