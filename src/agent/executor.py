"""固定白名单的计划步骤执行器。"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .state import PlanStep, ReviewState, StepType

StepHandler = Callable[[ReviewState], Mapping[str, Any]]

# 这是静态白名单，不接受模型生成的函数名，也不执行动态 import 或 shell。
STEP_EXECUTORS: Mapping[StepType, str] = MappingProxyType(
    {
        StepType.STRUCTURE_NEW_CASE: "structure_new_case",
        StepType.SEARCH_SIMILAR_CASES: "search_similar_cases",
        StepType.LOAD_CASE_DETAILS: "load_case_details",
        StepType.COMPARE_CASES: "compare_cases",
        StepType.INSPECT_RULE_HYPOTHESES: "inspect_rule_hypotheses",
        StepType.GENERATE_REVIEW_QUESTIONS: "generate_review_questions",
        StepType.SYNTHESIZE_REPORT: "synthesize_report",
        StepType.REQUEST_HUMAN_INPUT: "request_human_input",
    }
)

_ALLOWED_UPDATES: Mapping[StepType, frozenset[str]] = MappingProxyType(
    {
        StepType.STRUCTURE_NEW_CASE: frozenset({"structured_new_case", "new_case_bundle"}),
        StepType.SEARCH_SIMILAR_CASES: frozenset({"retrieval_query", "candidate_cases", "rerank"}),
        StepType.LOAD_CASE_DETAILS: frozenset({"loaded_cases"}),
        StepType.COMPARE_CASES: frozenset({"comparisons"}),
        StepType.INSPECT_RULE_HYPOTHESES: frozenset({"historical_rule_references"}),
        StepType.GENERATE_REVIEW_QUESTIONS: frozenset({"review_questions"}),
        StepType.SYNTHESIZE_REPORT: frozenset({"final_report"}),
        StepType.REQUEST_HUMAN_INPUT: frozenset({"human_input"}),
    }
)


class ExecutorError(RuntimeError):
    """计划步骤不能安全执行。"""


@dataclass(frozen=True)
class ExecutorServices:
    """由应用层显式注入的白名单服务。"""

    handlers: Mapping[str, StepHandler]

    def handler_for(self, step_type: StepType) -> StepHandler:
        service_name = STEP_EXECUTORS.get(step_type)
        if service_name is None:
            raise ExecutorError(f"步骤未在执行白名单中：{step_type!r}")
        handler = self.handlers.get(service_name)
        if handler is None or not callable(handler):
            raise ExecutorError(f"未提供步骤服务：{service_name}")
        return handler


@dataclass(frozen=True)
class ExecutionResult:
    """单步执行结果；由图节点负责合并到 ReviewState。"""

    step_id: str
    step_type: StepType
    updates: Mapping[str, Any]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "updates": dict(self.updates),
            "summary": self.summary,
        }


def execute_step(
    step: PlanStep,
    state: ReviewState,
    services: ExecutorServices,
) -> ExecutionResult:
    """执行一个已校验步骤，只返回该步骤获授权更新的状态字段。"""
    if not isinstance(step, PlanStep):
        raise ExecutorError("待执行对象必须是 PlanStep。")
    if step.step_id in set(state.get("completed_steps", [])):
        raise ExecutorError(f"步骤已完成，不得重复执行：{step.step_id}")

    handler = services.handler_for(step.step_type)
    updates = handler(state)
    if not isinstance(updates, Mapping):
        raise ExecutorError(f"步骤服务必须返回状态更新对象：{step.step_type.value}")
    allowed = _ALLOWED_UPDATES[step.step_type]
    unexpected = set(updates) - allowed
    if unexpected:
        names = ", ".join(sorted(str(key) for key in unexpected))
        raise ExecutorError(f"步骤 {step.step_type.value} 返回未授权状态字段：{names}")
    return ExecutionResult(
        step_id=step.step_id,
        step_type=step.step_type,
        updates=dict(updates),
        summary=f"已执行白名单步骤：{step.step_type.value}",
    )
