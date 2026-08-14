"""计划式 Agent 的可持久化状态和计划步骤类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict


class StepType(str, Enum):
    """Planner 可以生成的固定步骤类型。"""

    STRUCTURE_NEW_CASE = "structure_new_case"
    SEARCH_SIMILAR_CASES = "search_similar_cases"
    LOAD_CASE_DETAILS = "load_case_details"
    COMPARE_CASES = "compare_cases"
    INSPECT_RULE_HYPOTHESES = "inspect_rule_hypotheses"
    GENERATE_REVIEW_QUESTIONS = "generate_review_questions"
    SYNTHESIZE_REPORT = "synthesize_report"
    REQUEST_HUMAN_INPUT = "request_human_input"


class PlanStepStatus(str, Enum):
    """计划步骤状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentDecision(str, Enum):
    """Evaluator 允许返回的有限决策集合。"""

    CONTINUE = "continue"
    REPLAN = "replan"
    NEED_HUMAN_INPUT = "need_human_input"
    FINISH = "finish"
    FAIL = "fail"


@dataclass(frozen=True)
class PlanStep:
    """一个不包含任意工具名的计划步骤。"""

    step_id: str
    step_type: StepType
    reason: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    result_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not self.step_id.strip():
            raise ValueError("step_id 必须是非空字符串。")
        if not isinstance(self.step_type, StepType):
            raise ValueError("step_type 必须是 StepType 枚举值。")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason 必须是非空字符串。")
        if not isinstance(self.status, PlanStepStatus):
            raise ValueError("status 必须是 PlanStepStatus 枚举值。")
        refs = tuple(self.input_refs)
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            raise ValueError("input_refs 中的引用必须是非空字符串。")
        if len(refs) != len(set(refs)):
            raise ValueError("input_refs 不得重复。")
        object.__setattr__(self, "step_id", self.step_id.strip())
        object.__setattr__(self, "reason", self.reason.strip())
        object.__setattr__(self, "input_refs", refs)
        if self.result_ref is not None:
            if not isinstance(self.result_ref, str) or not self.result_ref.strip():
                raise ValueError("result_ref 必须是非空字符串或 None。")
            object.__setattr__(self, "result_ref", self.result_ref.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "reason": self.reason,
            "status": self.status.value,
            "input_refs": list(self.input_refs),
            "result_ref": self.result_ref,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanStep":
        if not isinstance(data, dict):
            raise ValueError("计划步骤必须是对象。")
        try:
            step_type = StepType(data.get("step_type"))
            status = PlanStepStatus(data.get("status", PlanStepStatus.PENDING.value))
        except ValueError as exc:
            raise ValueError(f"计划步骤枚举值非法：{exc}") from exc
        input_refs = data.get("input_refs", ())
        if not isinstance(input_refs, (list, tuple)):
            raise ValueError("input_refs 必须是数组。")
        return cls(
            step_id=data.get("step_id"),
            step_type=step_type,
            reason=data.get("reason"),
            status=status,
            input_refs=tuple(input_refs),
            result_ref=data.get("result_ref"),
        )


class ReviewState(TypedDict, total=False):
    """Agent 图使用的状态；只保存可展示结果，不保存思维链。"""

    thread_id: str
    run_id: str
    user_request: str
    raw_case_text: str
    structured_new_case: dict[str, Any] | None
    new_case_bundle: dict[str, Any] | None
    plan: list[dict[str, Any]]
    current_step_index: int
    completed_steps: list[str]
    retrieval_query: str | None
    candidate_cases: list[dict[str, Any]]
    rerank: dict[str, Any] | None
    loaded_cases: list[dict[str, Any]]
    comparisons: list[dict[str, Any]]
    historical_rule_references: list[dict[str, Any]]
    review_questions: list[dict[str, Any]]
    final_report: dict[str, Any] | None
    next_action: str | None
    agent_status: str | None
    degraded: bool
    last_execution_result: dict[str, Any] | None
    last_evaluation: dict[str, Any] | None
    iteration_count: int
    replan_count: int
    errors: list[dict[str, str]]
    human_input: str | None
    trace: list[dict[str, Any]]
