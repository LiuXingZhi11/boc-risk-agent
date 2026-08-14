"""构造临时新案例并加载历史案例完整详情。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from src.models import Case, CaseBundle, Fact, TargetEvent
from src.storage.repository import CaseRepository
from src.validators.structure_validator import validate_structured_cases


class NewCaseBuildError(ValueError):
    """新案例结构化结果无法构造成临时案例包。"""


class HistoricalCaseLoadError(LookupError):
    """历史案例详情无法按要求加载。"""


def build_new_case_bundle(
    structured_case: Mapping[str, Any],
    *,
    raw_text: str,
    new_case_id: str | None = None,
) -> CaseBundle:
    """把结构化结果转换为不入库的临时 ``CaseBundle``。

    模型产生的 case/fact ID 不直接复用，统一改成当前运行的 NEW_CASE 前缀，
    避免与历史案例证据引用混淆。
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise NewCaseBuildError("raw_text 不能为空")
    try:
        validate_structured_cases(dict(structured_case))
    except (TypeError, ValueError) as exc:
        raise NewCaseBuildError(f"结构化新案例校验失败：{exc}") from exc

    case_records = structured_case.get("case_records")
    if not isinstance(case_records, list) or len(case_records) != 1:
        raise NewCaseBuildError("新案例流程一次只能处理一个 case_record")

    case_record = case_records[0]
    case_id = new_case_id or f"NEW_CASE_{uuid.uuid4().hex[:12].upper()}"
    if not isinstance(case_id, str) or not case_id.startswith("NEW_CASE_"):
        raise NewCaseBuildError("new_case_id 必须以 NEW_CASE_ 开头")

    old_to_new_fact_id: dict[str, str] = {}
    facts: list[Fact] = []
    for index, fact_data in enumerate(case_record["facts"], start=1):
        old_fact_id = fact_data["fact_id"]
        fact_id = f"{case_id}_F{index:03d}"
        old_to_new_fact_id[old_fact_id] = fact_id
        facts.append(
            Fact(
                fact_id=fact_id,
                statement=fact_data["statement"],
                source_excerpt=fact_data["source_excerpt"],
                category=fact_data["category"],
                assertion_type=fact_data["assertion_type"],
                event_time=fact_data.get("event_time"),
                knowledge_status=fact_data["knowledge_status"],
                uncertainty=fact_data.get("uncertainty"),
            )
        )

    target_data = case_record["target_event"]
    target_fact_id = old_to_new_fact_id[target_data["target_fact_id"]]
    now = datetime.now(timezone.utc).isoformat()
    case = Case(
        case_id=case_id,
        case_name=case_record["case_name"],
        raw_text=raw_text.strip(),
        source="new_case",
        case_type="new_case_review",
        target_event=TargetEvent(target_fact_id, target_data.get("uncertainty")),
        review_status="pending",
        created_at=now,
        updated_at=now,
    )
    return CaseBundle(
        case=case,
        facts=tuple(facts),
        rule_hypotheses=(),
        processing_runs=(),
        api_meta=structured_case.get("api_meta"),
    )


def load_historical_case_details(
    repository: CaseRepository,
    case_ids: Iterable[str],
    *,
    require_approved: bool = True,
) -> tuple[CaseBundle, ...]:
    """按候选顺序加载历史案例完整详情，不改变数据库。"""
    requested_ids = tuple(case_ids)
    if len(requested_ids) != len(set(requested_ids)):
        raise HistoricalCaseLoadError("历史候选 case_id 不得重复")

    bundles: list[CaseBundle] = []
    for case_id in requested_ids:
        if not isinstance(case_id, str) or not case_id.strip():
            raise HistoricalCaseLoadError("历史候选 case_id 不能为空")
        bundle = repository.get_case_bundle(case_id)
        if bundle is None:
            raise HistoricalCaseLoadError(f"历史案例不存在：{case_id}")
        if require_approved and bundle.case.review_status != "approved":
            raise HistoricalCaseLoadError(f"历史案例尚未审核通过：{case_id}")
        bundles.append(bundle)
    return tuple(bundles)
