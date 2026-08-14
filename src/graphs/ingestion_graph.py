"""历史案例入库固定工作流。

图只负责节点编排和状态流转；模型调用、校验、案例包组装和持久化
分别复用已有的普通 Python 服务、校验器和 Repository。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.llm.generation_config import GenerationConfig
from src.models import ProcessingRun
from src.services.rule_service import extract_rule_hypotheses
from src.services.structure_service import structure_case
from src.storage.bundle_builder import build_case_bundles
from src.storage.repository import CaseRepository
from src.validators.rule_validator import validate_rule_hypotheses
from src.validators.structure_validator import validate_structured_cases


class IngestionState(TypedDict, total=False):
    thread_id: str
    case_id: str
    case_name: str
    raw_case_text: str
    source: str | None
    structured_case: dict[str, Any]
    rule_hypotheses: dict[str, Any]
    structure_valid: bool
    rules_valid: bool
    validation_errors: list[str]
    human_review_payload: dict[str, Any]
    human_decision: str
    saved_case_id: str | None
    processing_runs: list[dict[str, Any]]
    current_stage: str
    error: dict[str, str] | None


def build_ingestion_graph(
    *,
    structure_guide: str,
    rule_guide: str,
    structure_config: GenerationConfig,
    rule_config: GenerationConfig,
    database_path: str,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    """构建并编译历史案例入库图。"""
    repository = CaseRepository(database_path)
    graph = StateGraph(IngestionState)

    def prepare_input_node(state: IngestionState) -> dict[str, Any]:
        try:
            raw_text = state.get("raw_case_text", "")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError("raw_case_text 不能为空。")
            source = state.get("source")
            if source is not None and not isinstance(source, str):
                raise ValueError("source 必须是字符串或 None。")
            return {
                "raw_case_text": raw_text.strip(),
                "validation_errors": [],
                "processing_runs": [],
                "current_stage": "prepare_input",
                "error": None,
            }
        except Exception as exc:
            return {
                **_failure_update("input_error", str(exc), "prepare_input"),
                "processing_runs": _append_state_run(
                    state, stage="prepare_input", status="failed", error_message=str(exc)
                ),
            }

    def structure_case_node(state: IngestionState) -> dict[str, Any]:
        stage = "structure_case"
        try:
            result = structure_case(
                state["raw_case_text"], structure_guide, structure_config
            )
            return {
                "structured_case": result,
                "current_stage": stage,
                "processing_runs": _append_run(
                    state, stage="structure", status="succeeded", meta=result.get("api_meta")
                ),
                "error": None,
            }
        except Exception as exc:
            return _failure_update(
                "structure_error",
                str(exc),
                stage,
                state=state,
                run_stage="structure",
            )

    def validate_structure_node(state: IngestionState) -> dict[str, Any]:
        stage = "validate_structure"
        try:
            validate_structured_cases(state["structured_case"])
            return {
                "structure_valid": True,
                "current_stage": stage,
                "error": None,
            }
        except Exception as exc:
            message = str(exc)
            return {
                **_failure_update("structure_validation_error", message, stage),
                "structure_valid": False,
                "validation_errors": state.get("validation_errors", []) + [message],
                "processing_runs": _append_state_run(
                    state, stage=stage, status="failed", error_message=message
                ),
            }

    def extract_rules_node(state: IngestionState) -> dict[str, Any]:
        stage = "extract_rules"
        try:
            result = extract_rule_hypotheses(
                state["structured_case"], rule_guide, rule_config
            )
            return {
                "rule_hypotheses": result,
                "current_stage": stage,
                "processing_runs": _append_run(
                    state, stage="rules", status="succeeded", meta=result.get("api_meta")
                ),
                "error": None,
            }
        except Exception as exc:
            return _failure_update(
                "rules_error",
                str(exc),
                stage,
                state=state,
                run_stage="rules",
            )

    def validate_rules_node(state: IngestionState) -> dict[str, Any]:
        stage = "validate_rules"
        try:
            validate_rule_hypotheses(
                state["rule_hypotheses"], state["structured_case"]
            )
            return {
                "rules_valid": True,
                "current_stage": stage,
                "error": None,
            }
        except Exception as exc:
            message = str(exc)
            return {
                **_failure_update("rules_validation_error", message, stage),
                "rules_valid": False,
                "validation_errors": state.get("validation_errors", []) + [message],
                "processing_runs": _append_state_run(
                    state, stage=stage, status="failed", error_message=message
                ),
            }

    def human_review_node(state: IngestionState) -> dict[str, Any]:
        payload = {
            "structured_case": state.get("structured_case"),
            "rule_hypotheses": state.get("rule_hypotheses"),
            "structure_valid": state.get("structure_valid", False),
            "rules_valid": state.get("rules_valid", False),
            "options": ["accept", "reject", "accept_with_edits"],
        }
        decision_payload = interrupt(payload)
        try:
            if isinstance(decision_payload, str):
                decision = decision_payload
                updates: dict[str, Any] = {}
            elif isinstance(decision_payload, dict):
                decision = decision_payload.get("decision")
                updates = {
                    key: decision_payload[key]
                    for key in ("structured_case", "rule_hypotheses")
                    if key in decision_payload
                }
            else:
                raise ValueError("人工审核输入必须是决定字符串或对象。")
            if decision not in {"accept", "reject", "accept_with_edits"}:
                raise ValueError("人工审核决定必须为 accept、reject 或 accept_with_edits。")
            return {
                **updates,
                "human_review_payload": payload,
                "human_decision": decision,
                "current_stage": "human_review",
                "processing_runs": _append_state_run(
                    state,
                    stage="human_review",
                    status="rejected" if decision == "reject" else "succeeded",
                    error_message="人工拒绝保存。" if decision == "reject" else None,
                ),
                "error": (
                    {"code": "human_rejected", "message": "人工拒绝保存。"}
                    if decision == "reject"
                    else None
                ),
            }
        except Exception as exc:
            return {
                "human_review_payload": payload,
                **_failure_update("human_review_error", str(exc), "human_review"),
            }

    def revalidate_edited_node(state: IngestionState) -> dict[str, Any]:
        errors: list[str] = []
        try:
            validate_structured_cases(state["structured_case"])
        except Exception as exc:
            errors.append(str(exc))
        if not errors:
            try:
                validate_rule_hypotheses(
                    state["rule_hypotheses"], state["structured_case"]
                )
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            return {
                "structure_valid": not any("结构化" in error for error in errors),
                "rules_valid": False,
                "validation_errors": state.get("validation_errors", []) + errors,
                "current_stage": "revalidate_edited",
                "processing_runs": _append_state_run(
                    state,
                    stage="revalidate_edited",
                    status="failed",
                    error_message="；".join(errors),
                ),
                "error": {
                    "code": "edited_validation_error",
                    "message": "；".join(errors),
                },
            }
        return {
            "structure_valid": True,
            "rules_valid": True,
            "current_stage": "revalidate_edited",
            "error": None,
        }

    def save_case_node(state: IngestionState) -> dict[str, Any]:
        stage = "save_case"
        try:
            bundles = build_case_bundles(
                state["structured_case"],
                state["rule_hypotheses"],
                raw_text=state["raw_case_text"],
                source=state.get("source"),
            )
            if len(bundles) != 1:
                raise ValueError("历史案例入库一次只能保存一个案例。")
            bundle = bundles[0]
            save_run = ProcessingRun(
                run_id=f"{bundle.case.case_id}_save",
                case_id=bundle.case.case_id,
                stage="save_case",
                model=None,
                generation_mode=None,
                reasoning_effort=None,
                temperature=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                status="succeeded",
                error_message=None,
                created_at=bundle.case.created_at,
            )
            repository.save_case_bundle(
                replace(bundle, processing_runs=bundle.processing_runs + (save_run,))
            )
            return {
                "case_id": bundle.case.case_id,
                "saved_case_id": bundle.case.case_id,
                "current_stage": stage,
                "processing_runs": _append_state_run(
                    state, stage=stage, status="succeeded", error_message=None
                ),
                "error": None,
            }
        except Exception as exc:
            return _failure_update(
                "save_error",
                str(exc),
                stage,
                state=state,
                run_stage=stage,
            )

    def failure_node(state: IngestionState) -> dict[str, Any]:
        return {"current_stage": "failure"}

    graph.add_node("prepare_input", prepare_input_node)
    graph.add_node("structure_case", structure_case_node)
    graph.add_node("validate_structure", validate_structure_node)
    graph.add_node("extract_rules", extract_rules_node)
    graph.add_node("validate_rules", validate_rules_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("revalidate_edited", revalidate_edited_node)
    graph.add_node("save_case", save_case_node)
    graph.add_node("failure", failure_node)
    graph.add_edge(START, "prepare_input")
    graph.add_conditional_edges("prepare_input", _route_error, {"failure": "failure", "next": "structure_case"})
    graph.add_conditional_edges("structure_case", _route_error, {"failure": "failure", "next": "validate_structure"})
    graph.add_conditional_edges("validate_structure", _route_error, {"failure": "failure", "next": "extract_rules"})
    graph.add_conditional_edges("extract_rules", _route_error, {"failure": "failure", "next": "validate_rules"})
    graph.add_conditional_edges("validate_rules", _route_error, {"failure": "failure", "next": "human_review"})
    graph.add_conditional_edges(
        "human_review",
        _route_review,
        {"failure": "failure", "revalidate": "revalidate_edited", "save": "save_case"},
    )
    graph.add_conditional_edges("revalidate_edited", _route_error, {"failure": "failure", "next": "save_case"})
    graph.add_conditional_edges("save_case", _route_error, {"failure": "failure", "next": END})
    graph.add_edge("failure", END)
    return graph.compile(checkpointer=checkpointer)


def _route_error(state: IngestionState) -> str:
    return "failure" if state.get("error") else "next"


def _route_review(state: IngestionState) -> str:
    if state.get("error"):
        return "failure"
    if state.get("human_decision") == "accept_with_edits":
        return "revalidate"
    return "save"


def _failure_update(
    code: str,
    message: str,
    stage: str,
    *,
    state: IngestionState | None = None,
    run_stage: str | None = None,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "current_stage": stage,
        "error": {"code": code, "message": message},
    }
    if state is not None and run_stage is not None:
        update["processing_runs"] = _append_state_run(
            state, stage=run_stage, status="failed", error_message=message
        )
    return update


def _append_run(
    state: IngestionState,
    *,
    stage: str,
    status: str,
    meta: Any,
) -> list[dict[str, Any]]:
    run = {
        "stage": stage,
        "status": status,
        "error_message": None,
        "api_meta": meta if isinstance(meta, dict) else None,
    }
    return state.get("processing_runs", []) + [run]


def _append_state_run(
    state: IngestionState,
    *,
    stage: str,
    status: str,
    error_message: str | None,
) -> list[dict[str, Any]]:
    return state.get("processing_runs", []) + [
        {"stage": stage, "status": status, "error_message": error_message}
    ]
