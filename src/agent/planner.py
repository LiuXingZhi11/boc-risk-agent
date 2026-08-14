"""固定步骤白名单和计划校验。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig

from .state import PlanStep, PlanStepStatus, ReviewState, StepType

MAX_PLAN_STEPS = 8
ALLOWED_STEP_TYPES = frozenset(StepType)

_REPORT_PREREQUISITES = frozenset(
    {
        StepType.STRUCTURE_NEW_CASE,
        StepType.SEARCH_SIMILAR_CASES,
        StepType.LOAD_CASE_DETAILS,
        StepType.COMPARE_CASES,
        StepType.INSPECT_RULE_HYPOTHESES,
        StepType.GENERATE_REVIEW_QUESTIONS,
    }
)


class PlanValidationError(ValueError):
    """Planner 输出不符合固定协议。"""


class PlannerResponse:
    """Planner 的可展示结果，不包含模型思维链。"""

    def __init__(
        self,
        plan: tuple[PlanStep, ...],
        *,
        degraded: bool,
        error: str | None = None,
        api_meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.plan = plan
        self.degraded = degraded
        self.error = error
        self.api_meta = dict(api_meta or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": [step.to_dict() for step in self.plan],
            "degraded": self.degraded,
            "error": self.error,
            "api_meta": self.api_meta,
        }


def _coerce_steps(plan: Iterable[PlanStep | Mapping[str, Any]]) -> tuple[PlanStep, ...]:
    steps: list[PlanStep] = []
    for item in plan:
        if isinstance(item, PlanStep):
            steps.append(item)
        elif isinstance(item, Mapping):
            steps.append(PlanStep.from_dict(dict(item)))
        else:
            raise PlanValidationError("计划步骤必须是 PlanStep 或对象。")
    return tuple(steps)


def validate_plan(
    plan: Iterable[PlanStep | Mapping[str, Any]],
    *,
    completed_steps: Iterable[str] = (),
    max_steps: int = MAX_PLAN_STEPS,
) -> tuple[PlanStep, ...]:
    """校验计划并返回规范化的不可变步骤集合。"""
    if not isinstance(max_steps, int) or max_steps <= 0:
        raise PlanValidationError("max_steps 必须是正整数。")
    try:
        steps = _coerce_steps(plan)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, PlanValidationError):
            raise
        raise PlanValidationError(str(exc)) from exc
    if not steps:
        raise PlanValidationError("计划不能为空。")
    if len(steps) > max_steps:
        raise PlanValidationError(f"计划步骤数不得超过 {max_steps}。")

    step_ids = [step.step_id for step in steps]
    if len(step_ids) != len(set(step_ids)):
        raise PlanValidationError("step_id 不得重复。")
    step_types = [step.step_type for step in steps]
    if len(step_types) != len(set(step_types)):
        raise PlanValidationError("同一计划不得重复执行相同步骤。")
    completed = set(completed_steps)
    if any(not isinstance(step_id, str) or not step_id.strip() for step_id in completed):
        raise PlanValidationError("completed_steps 必须是非空字符串集合。")
    if step_types[0] != StepType.STRUCTURE_NEW_CASE:
        raise PlanValidationError("首次分析的第一步必须是 structure_new_case。")

    planned_types = set(step_types)
    if StepType.SYNTHESIZE_REPORT in planned_types:
        missing = _REPORT_PREREQUISITES - planned_types
        if missing:
            missing_names = ", ".join(sorted(step.value for step in missing))
            raise PlanValidationError(f"synthesize_report 缺少前置步骤：{missing_names}。")
        report_index = step_types.index(StepType.SYNTHESIZE_REPORT)
        if any(step_type not in set(step_types[:report_index]) for step_type in _REPORT_PREREQUISITES):
            raise PlanValidationError("synthesize_report 必须位于全部必要前置步骤之后。")

    for step in steps:
        if step.step_id in completed and step.status not in {
            PlanStepStatus.COMPLETED,
            PlanStepStatus.SKIPPED,
        }:
            raise PlanValidationError(f"已完成步骤 {step.step_id} 不得被重新置为 {step.status.value}。")
    return steps


def build_default_plan(
    user_request: str,
    *,
    state: ReviewState | None = None,
) -> tuple[PlanStep, ...]:
    """生成不调用模型的安全默认计划，供首轮 Planner 和降级使用。"""
    if not isinstance(user_request, str) or not user_request.strip():
        raise PlanValidationError("user_request 不能为空。")
    completed = set((state or {}).get("completed_steps", []))
    steps = (
        PlanStep("step_01", StepType.STRUCTURE_NEW_CASE, "先将新案例转为可追溯事实.", status=PlanStepStatus.COMPLETED if "step_01" in completed else PlanStepStatus.PENDING),
        PlanStep("step_02", StepType.SEARCH_SIMILAR_CASES, "基于结构化案例检索历史参考.", status=PlanStepStatus.COMPLETED if "step_02" in completed else PlanStepStatus.PENDING),
        PlanStep("step_03", StepType.LOAD_CASE_DETAILS, "加载候选历史案例的完整详情.", status=PlanStepStatus.COMPLETED if "step_03" in completed else PlanStepStatus.PENDING),
        PlanStep("step_04", StepType.COMPARE_CASES, "比较新旧案例事实和风险线索.", status=PlanStepStatus.COMPLETED if "step_04" in completed else PlanStepStatus.PENDING),
        PlanStep("step_05", StepType.INSPECT_RULE_HYPOTHESES, "汇总历史规则假设作为参考.", status=PlanStepStatus.COMPLETED if "step_05" in completed else PlanStepStatus.PENDING),
        PlanStep("step_06", StepType.GENERATE_REVIEW_QUESTIONS, "生成可核实且有证据来源的问题.", status=PlanStepStatus.COMPLETED if "step_06" in completed else PlanStepStatus.PENDING),
        PlanStep("step_07", StepType.SYNTHESIZE_REPORT, "汇总已校验结果并保留证据引用.", status=PlanStepStatus.COMPLETED if "step_07" in completed else PlanStepStatus.PENDING),
    )
    return validate_plan(steps, completed_steps=completed)


def _planner_messages(user_request: str, state: ReviewState) -> list[dict[str, str]]:
    state_summary = {
        "completed_steps": state.get("completed_steps", []),
        "current_step_index": state.get("current_step_index", 0),
        "candidate_case_count": len(state.get("candidate_cases", [])),
        "loaded_case_count": len(state.get("loaded_cases", [])),
        "comparison_count": len(state.get("comparisons", [])),
        "question_count": len(state.get("review_questions", [])),
        "has_final_report": state.get("final_report") is not None,
        "iteration_count": state.get("iteration_count", 0),
        "replan_count": state.get("replan_count", 0),
        "errors": state.get("errors", []),
        "human_input_present": bool(state.get("human_input")),
    }
    system_prompt = (
        "你是金融风险辅助审查系统的受约束 Planner。"
        "只规划分析步骤，不执行工具、不写数据库、不做审批或风险定级。"
        "只输出 JSON 对象，格式为 {\"plan\":[...]}。"
    )
    user_prompt = (
        f"用户目标：{user_request.strip()}\n\n"
        f"当前状态摘要：{json.dumps(state_summary, ensure_ascii=False)}\n\n"
        "允许的 step_type："
        f"{json.dumps(sorted(step.value for step in ALLOWED_STEP_TYPES), ensure_ascii=False)}\n"
        f"硬限制：最多 {MAX_PLAN_STEPS} 步；第一步必须 structure_new_case；"
        "synthesize_report 必须在事实准备、检索、详情加载、比较、规则参考和待核实问题之后。\n"
        "为尚未完成的分析生成合法计划。每一个 plan 项都必须完整包含："
        "step_id（如 step_01）、step_type、reason、status（初始必须是 pending）、"
        "input_refs（数组，可为空）和 result_ref（没有时为 null）。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def plan_review(
    user_request: str,
    state: ReviewState,
    config: GenerationConfig,
    *,
    caller: Callable[[list[dict[str, str]], GenerationConfig], dict[str, Any]] = call_deepseek,
) -> PlannerResponse:
    """调用结构化 Planner；任何失败均回退到确定性默认计划。"""
    try:
        if config.mode != "thinking" or config.reasoning_effort != "high":
            raise PlanValidationError("Planner 必须使用 thinking 和 reasoning_effort=high。")
        result = caller(_planner_messages(user_request, state), config)
        raw_plan = result.get("plan")
        if not isinstance(raw_plan, list):
            raise PlanValidationError("Planner 输出的 plan 必须是数组。")
        plan = validate_plan(raw_plan, completed_steps=state.get("completed_steps", []))
        return PlannerResponse(
            plan,
            degraded=False,
            api_meta=result.get("api_meta"),
        )
    except Exception as exc:
        fallback = build_default_plan(user_request, state=state)
        return PlannerResponse(
            fallback,
            degraded=True,
            error=f"Planner 已降级为默认计划：{exc}",
        )
