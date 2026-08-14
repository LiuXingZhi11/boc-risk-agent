"""受硬限制保护的确定性 Replanner。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .planner import MAX_PLAN_STEPS, PlanValidationError, validate_plan
from .state import AgentDecision, PlanStep, PlanStepStatus, ReviewState, StepType

MAX_REPLANS = 2


@dataclass(frozen=True)
class ReplanResult:
    plan: tuple[PlanStep, ...]
    replan_count: int
    stopped: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": [step.to_dict() for step in self.plan],
            "replan_count": self.replan_count,
            "stopped": self.stopped,
            "reason": self.reason,
        }


def _coerce_plan(plan: Iterable[PlanStep | Mapping[str, Any]]) -> tuple[PlanStep, ...]:
    return validate_plan(plan)


def replan(
    plan: Iterable[PlanStep | Mapping[str, Any]],
    state: ReviewState,
    *,
    decision: AgentDecision,
    reason: str,
    max_replans: int = MAX_REPLANS,
) -> ReplanResult:
    """只调整未完成步骤；达到上限时停止并交由受限报告处理。"""
    if decision not in {AgentDecision.REPLAN, AgentDecision.NEED_HUMAN_INPUT}:
        raise PlanValidationError("Replanner 只接受 replan 或 need_human_input。")
    if not isinstance(reason, str) or not reason.strip():
        raise PlanValidationError("Replanner reason 不能为空。")
    if not isinstance(max_replans, int) or max_replans < 0:
        raise PlanValidationError("max_replans 必须是非负整数。")

    current_plan = _coerce_plan(plan)
    current_count = int(state.get("replan_count", 0))
    if current_count >= max_replans:
        return ReplanResult(
            current_plan,
            current_count,
            True,
            f"已达到最大重规划次数 {max_replans}，停止继续循环：{reason.strip()}",
        )

    completed_ids = set(state.get("completed_steps", []))
    next_plan: list[PlanStep] = []
    human_step_exists = any(
        step.step_type == StepType.REQUEST_HUMAN_INPUT and step.step_id not in completed_ids
        for step in current_plan
    )
    for step in current_plan:
        if step.step_id in completed_ids:
            next_plan.append(
                step
                if step.status in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED}
                else PlanStep(
                    step.step_id,
                    step.step_type,
                    step.reason,
                    status=PlanStepStatus.COMPLETED,
                    input_refs=step.input_refs,
                    result_ref=step.result_ref,
                )
            )
        elif step.status == PlanStepStatus.FAILED:
            next_plan.append(
                PlanStep(
                    step.step_id,
                    step.step_type,
                    step.reason,
                    status=PlanStepStatus.PENDING,
                    input_refs=step.input_refs,
                    result_ref=step.result_ref,
                )
            )
        else:
            next_plan.append(step)

    if decision == AgentDecision.NEED_HUMAN_INPUT and not human_step_exists:
        insert_at = next(
            (index for index, step in enumerate(next_plan) if step.step_id not in completed_ids),
            len(next_plan),
        )
        next_plan.insert(
            insert_at,
            PlanStep(
                f"replan_{current_count + 1:02d}_human_input",
                StepType.REQUEST_HUMAN_INPUT,
                "材料不足，先请求人工补充文本事实。",
            ),
        )

    validated = validate_plan(
        next_plan,
        completed_steps=completed_ids,
        max_steps=MAX_PLAN_STEPS,
    )
    return ReplanResult(
        validated,
        current_count + 1,
        False,
        reason.strip(),
    )
