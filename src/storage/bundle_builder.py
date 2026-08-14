"""将旧版结构化与规则 JSON 组装为可保存的案例包。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from src.models import Case, CaseBundle, Fact, ProcessingRun, RuleHypothesis, TargetEvent
from src.validators.rule_validator import validate_rule_hypotheses
from src.validators.structure_validator import validate_structured_cases


CASE_HEADING_PATTERN = re.compile(r"^##\s+(CASE_[A-Za-z0-9_-]+)(?:\s*[:：].*)?$", re.MULTILINE)


def split_case_texts(raw_text: str) -> dict[str, str]:
    """按 Markdown 二级标题拆分案例原文；无法拆分时返回空映射。"""
    matches = list(CASE_HEADING_PATTERN.finditer(raw_text))
    if not matches:
        return {}
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        result[match.group(1)] = raw_text[match.start():end].strip()
    return result


def build_case_bundles(
    structured_data: Mapping[str, Any],
    rules_data: Mapping[str, Any],
    *,
    raw_text: str,
    source: str | None = None,
    case_type: str | None = None,
    review_status: str = "pending",
) -> list[CaseBundle]:
    """校验阶段输出并生成待保存的案例包。"""
    structured = dict(structured_data)
    rules = dict(rules_data)
    validate_structured_cases(structured)
    validate_rule_hypotheses(rules, structured)
    raw_text_by_case = split_case_texts(raw_text)
    now = datetime.now(timezone.utc).isoformat()
    rules_by_case: dict[str, list[Mapping[str, Any]]] = {}
    for rule in rules["single_case_rule_hypotheses"]:
        rules_by_case.setdefault(rule["case_id"], []).append(rule)

    bundles: list[CaseBundle] = []
    for case_record in structured["case_records"]:
        case_id = case_record["case_id"]
        target = TargetEvent(
            case_record["target_event"]["target_fact_id"],
            case_record["target_event"].get("uncertainty"),
        )
        case = Case(
            case_id=case_id,
            case_name=case_record["case_name"],
            raw_text=raw_text_by_case.get(case_id, raw_text),
            source=source if source is not None else case_record.get("source"),
            case_type=case_type,
            target_event=target,
            review_status=review_status,
            created_at=now,
            updated_at=now,
        )
        facts = tuple(Fact.from_dict(fact) for fact in case_record["facts"])
        rules_for_case = tuple(
            RuleHypothesis.from_dict(rule, review_status="pending")
            for rule in rules_by_case.get(case_id, [])
        )
        processing_runs = _processing_runs_for_case(
            case_id,
            structured.get("api_meta"),
            rules.get("api_meta"),
            now,
        )
        bundles.append(
            CaseBundle(
                case=case,
                facts=facts,
                rule_hypotheses=rules_for_case,
                processing_runs=processing_runs,
                api_meta={
                    "structure": structured.get("api_meta"),
                    "rules": rules.get("api_meta"),
                },
            )
        )
    return bundles


def _processing_runs_for_case(
    case_id: str,
    structure_meta: Any,
    rules_meta: Any,
    created_at: str,
) -> tuple[ProcessingRun, ...]:
    runs: list[ProcessingRun] = []
    for stage, meta in (("structure", structure_meta), ("rules", rules_meta)):
        if not isinstance(meta, Mapping):
            continue
        runs.append(
            ProcessingRun(
                run_id=f"{case_id}_{stage}_{uuid.uuid4().hex}",
                case_id=case_id,
                stage=stage,
                model=meta.get("model"),
                generation_mode=meta.get("generation_mode"),
                reasoning_effort=meta.get("reasoning_effort"),
                temperature=meta.get("temperature"),
                prompt_tokens=meta.get("prompt_tokens"),
                completion_tokens=meta.get("completion_tokens"),
                total_tokens=meta.get("total_tokens"),
                status="succeeded",
                error_message=None,
                created_at=created_at,
            )
        )
    return tuple(runs)
