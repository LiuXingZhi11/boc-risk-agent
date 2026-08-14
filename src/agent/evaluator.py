"""基于确定性完成条件的 Agent Evaluator。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .executor import ExecutionResult
from .state import AgentDecision, PlanStep, StepType


@dataclass(frozen=True)
class EvaluationResult:
    decision: AgentDecision
    reason: str
    missing_information: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "missing_information": list(self.missing_information),
        }


def _has_non_empty_value(updates: Mapping[str, Any], field_name: str) -> bool:
    value = updates.get(field_name)
    return value is not None and value != [] and value != {}


def evaluate_step(step: PlanStep, result: ExecutionResult | None) -> EvaluationResult:
    """只依据已返回的状态更新判断下一动作，不调用模型。"""
    if result is None:
        return EvaluationResult(AgentDecision.FAIL, "步骤没有返回执行结果。")

    if step.step_type == StepType.REQUEST_HUMAN_INPUT:
        if _has_non_empty_value(result.updates, "human_input"):
            return EvaluationResult(AgentDecision.CONTINUE, "已收到人工补充，可继续执行剩余计划。")
        return EvaluationResult(
            AgentDecision.NEED_HUMAN_INPUT,
            "案例材料仍不足，需要人工补充文本信息。",
            ("请补充与当前风险事件、主体关系、时间或金额有关的事实。",),
        )

    expected_field = {
        StepType.STRUCTURE_NEW_CASE: "structured_new_case",
        StepType.SEARCH_SIMILAR_CASES: "candidate_cases",
        StepType.LOAD_CASE_DETAILS: "loaded_cases",
        StepType.COMPARE_CASES: "comparisons",
        StepType.INSPECT_RULE_HYPOTHESES: "historical_rule_references",
        StepType.GENERATE_REVIEW_QUESTIONS: "review_questions",
        StepType.SYNTHESIZE_REPORT: "final_report",
    }[step.step_type]
    if not _has_non_empty_value(result.updates, expected_field):
        if step.step_type == StepType.SEARCH_SIMILAR_CASES:
            return EvaluationResult(
                AgentDecision.CONTINUE,
                "没有检索候选，继续生成带限制说明的辅助结果。",
            )
        return EvaluationResult(
            AgentDecision.REPLAN,
            f"步骤未产生预期结果字段：{expected_field}。",
        )
    if step.step_type == StepType.SYNTHESIZE_REPORT:
        return EvaluationResult(AgentDecision.FINISH, "最终报告已生成。")
    return EvaluationResult(AgentDecision.CONTINUE, f"步骤 {step.step_type.value} 已产生可用结果。")
