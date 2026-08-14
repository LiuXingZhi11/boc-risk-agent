"""企业画像候选人工审核服务。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from .candidates import build_profile_from_candidates, validate_profile_candidates
from .models import EnterpriseProfile
from .repository import ProfileRepository


def finalize_profile_review(
    candidates: dict[str, Any],
    *,
    evidence_unit_ids: Iterable[str],
    decision: str,
    profile_id: str,
    case_id: str,
    enterprise_name: str,
    profile_type: str,
    edited_candidates: dict[str, Any] | None = None,
) -> EnterpriseProfile | None:
    """审核并生成正式画像；reject 返回 None。"""
    if decision not in {"accept", "edit_and_accept", "reject"}:
        raise ValueError("审核决定必须为 accept、edit_and_accept 或 reject。")
    if decision == "reject":
        return None
    selected = edited_candidates if decision == "edit_and_accept" else candidates
    if selected is None:
        raise ValueError("edit_and_accept 必须提供 edited_candidates。")
    available_ids = tuple(evidence_unit_ids)
    validate_profile_candidates(
        selected,
        evidence_unit_ids=available_ids,
        profile_type=profile_type,
    )
    profile = build_profile_from_candidates(
        selected,
        profile_id=profile_id,
        case_id=case_id,
        enterprise_name=enterprise_name,
        profile_type=profile_type,
    )
    reviewed_items = tuple(replace(item, review_status="accepted") for item in profile.items)
    reviewed_relations = tuple(replace(relation, review_status="accepted") for relation in profile.relations)
    return profile.__class__(
        profile_id=profile.profile_id,
        case_id=profile.case_id,
        enterprise_name=profile.enterprise_name,
        ontology_version=profile.ontology_version,
        items=reviewed_items,
        relations=reviewed_relations,
        information_gaps=profile.information_gaps,
        conflicts=profile.conflicts,
        review_status="approved",
    )


def finalize_and_save_profile_review(
    candidates: dict[str, Any],
    *,
    repository: ProfileRepository,
    evidence_unit_ids: Iterable[str],
    decision: str,
    profile_id: str,
    case_id: str,
    enterprise_name: str,
    profile_type: str,
    edited_candidates: dict[str, Any] | None = None,
) -> EnterpriseProfile | None:
    """审核通过后写入 ProfileRepository；拒绝时不产生正式画像。"""
    profile = finalize_profile_review(
        candidates,
        evidence_unit_ids=evidence_unit_ids,
        decision=decision,
        profile_id=profile_id,
        case_id=case_id,
        enterprise_name=enterprise_name,
        profile_type=profile_type,
        edited_candidates=edited_candidates,
    )
    if profile is not None:
        repository.save(profile)
    return profile
