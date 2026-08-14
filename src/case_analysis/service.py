"""Generate a reviewable case analysis from an approved historical profile."""

from __future__ import annotations

import json
from typing import Any, Iterable

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.ontology.schema import COMPARISON_DIMENSION_SECTIONS
from src.profiles.comparison_cards import profile_content_hash
from src.profiles.material_context import build_profile_material_context
from src.profiles.models import EvidenceReference, HistoricalEnterpriseProfile, ProfileItem, ProfileRelation

from .models import CaseAnalysisFactor, CaseOutcome, CaseReviewDirection, HistoricalCaseAnalysis, FACTOR_ROLES, OUTCOME_STATUSES, OUTCOME_TYPES

AUTHORITY_ROLES = {"outcome", "regulatory_finding", "judicial_finding"}
OUTCOME_TYPE_ALIASES = {
    "强制退市": "restructuring_or_exit",
    "终止上市": "restructuring_or_exit",
    "投资者获赔": "other",
    "投资者赔偿": "other",
    "行政处罚": "regulatory_action",
    "司法结果": "judicial_outcome",
}


def _profile_payload(profile: HistoricalEnterpriseProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "case_id": profile.case_id,
        "enterprise_name": profile.enterprise_name,
        "ontology_version": profile.ontology_version,
        "profile_items": [
            {"item_id": item.item_id, "section_id": item.section_id, "field_id": item.field_id, "value": item.value, "value_type": item.value_type, "unit": item.unit, "source_date": item.source_date, "reporting_period": item.reporting_period, "event_date": item.event_date, "effective_date": item.effective_date, "information_status": item.information_status, "content_role": item.content_role}
            for item in profile.items if item.review_status != "rejected"
        ],
        "profile_relations": [
            {"relation_id": item.relation_id, "relation_type": item.relation_type, "source_type": item.source_type, "target_type": item.target_type, "information_status": item.information_status, "content_role": item.content_role}
            for item in profile.relations if item.review_status != "rejected"
        ],
        "information_gaps": list(profile.information_gaps),
        "conflicts": list(profile.conflicts),
    }


def build_case_analysis_messages(
    profile: HistoricalEnterpriseProfile,
    *,
    guide_text: str = "",
    material_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if profile.review_status != "approved" or profile.profile_type != "historical":
        raise ValueError("只有审核通过的历史企业画像才能生成案例分析。")
    system = f"{guide_text}\n\n你负责从已审核历史企业画像生成证据化案例分析。只输出合法 JSON，不输出 Markdown。不得把信息缺失写成负面事实，不得补充画像之外的事实。所有自然语言字段必须使用简体中文。"
    dimensions = ", ".join(COMPARISON_DIMENSION_SECTIONS)
    outcome_types = ", ".join(sorted(OUTCOME_TYPES))
    outcome_statuses = ", ".join(sorted(OUTCOME_STATUSES))
    context = material_context or build_profile_material_context(profile)
    user = f"""===== 企业与来源材料基本信息 =====
{json.dumps(context, ensure_ascii=False, indent=2)}
这里只提供主体、报告期和来源文档标题；分析事实仍只能来自下方已审核画像。
===== 企业与来源材料基本信息结束 =====

输出 case_summary、outcome_status、outcomes、factors、review_directions、applicability_limits。
outcome_status 只能逐字使用：{outcome_statuses}。
outcomes 每项：outcome_id、outcome_type、description、source_item_ids、source_relation_ids；outcome_type 只能逐字使用：{outcome_types}；只可引用 content_role 为 outcome、regulatory_finding、judicial_finding 的来源。
factors 每项：factor_id、dimension_id、title、finding、factor_role、source_item_ids、source_relation_ids。factor_role 只能是 explicit_reason、evidence_supported_factor、analyst_hypothesis；explicit_reason 必须引用权威结果来源，analyst_hypothesis 必须明确写成待核实假设。
dimension_id 只能逐字使用以下值之一：{dimensions}。
review_directions 每项：direction_id、title、rationale、related_factor_ids、verification_questions。引用 ID 只能来自输入，无法确认的结果应使用 not_disclosed。\n输入画像：\n""" + json.dumps(_profile_payload(profile), ensure_ascii=False)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(item.strip() for item in value if isinstance(item, str) and item.strip()))


def _ids(value: Any, allowed: dict[str, Any]) -> tuple[str, ...]:
    return tuple(item for item in _strings(value) if item in allowed)


def _refs(sources: Iterable[ProfileItem | ProfileRelation]) -> tuple[EvidenceReference, ...]:
    refs: dict[str, EvidenceReference] = {}
    for source in sources:
        for ref in source.evidence_refs:
            refs.setdefault(ref.evidence_unit_id, ref)
    return tuple(refs.values())


def _sources(raw: dict[str, Any], items: dict[str, ProfileItem], relations: dict[str, ProfileRelation]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[ProfileItem | ProfileRelation, ...]]:
    item_ids = _ids(raw.get("source_item_ids"), items)
    relation_ids = _ids(raw.get("source_relation_ids"), relations)
    selected: tuple[ProfileItem | ProfileRelation, ...] = tuple(items[item_id] for item_id in item_ids) + tuple(relations[relation_id] for relation_id in relation_ids)
    return item_ids, relation_ids, selected


def _text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    return value.strip() if isinstance(value, str) else ""


def _raw_entries(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _build_outcomes(raw: Any, items: dict[str, ProfileItem], relations: dict[str, ProfileRelation], rejected: list[dict[str, Any]]) -> tuple[CaseOutcome, ...]:
    output: list[CaseOutcome] = []
    seen: set[str] = set()
    for entry in _raw_entries(raw):
        item_ids, relation_ids, sources = _sources(entry, items, relations)
        outcome_id, outcome_type, description = _text(entry, "outcome_id"), _text(entry, "outcome_type"), _text(entry, "description")
        outcome_type = OUTCOME_TYPE_ALIASES.get(outcome_type, outcome_type)
        valid = outcome_id and outcome_id not in seen and outcome_type in OUTCOME_TYPES and description and any(source.content_role in AUTHORITY_ROLES for source in sources)
        if not valid:
            rejected.append({"kind": "outcome", "value": entry, "reason": "缺少合法字段、权威结果来源或引用了不存在的 ID"})
            continue
        output.append(CaseOutcome(outcome_id, outcome_type, description, item_ids, relation_ids, _refs(sources)))
        seen.add(outcome_id)
    return tuple(output)


def _build_factors(raw: Any, items: dict[str, ProfileItem], relations: dict[str, ProfileRelation], rejected: list[dict[str, Any]]) -> tuple[CaseAnalysisFactor, ...]:
    output: list[CaseAnalysisFactor] = []
    seen: set[str] = set()
    for entry in _raw_entries(raw):
        item_ids, relation_ids, sources = _sources(entry, items, relations)
        factor_id = _text(entry, "factor_id")
        dimension_id = _text(entry, "dimension_id")
        if dimension_id not in COMPARISON_DIMENSION_SECTIONS:
            matched = {
                dimension
                for source in sources
                if isinstance(source, ProfileItem)
                for dimension, sections in COMPARISON_DIMENSION_SECTIONS.items()
                if source.section_id in sections
            }
            dimension_id = next(iter(matched)) if len(matched) == 1 else ""
        title, finding, role = _text(entry, "title"), _text(entry, "finding"), _text(entry, "factor_role")
        valid = factor_id and factor_id not in seen and dimension_id in COMPARISON_DIMENSION_SECTIONS and title and finding and role in FACTOR_ROLES and bool(sources)
        if role == "explicit_reason" and not any(source.content_role in AUTHORITY_ROLES for source in sources):
            valid = False
        if not valid:
            rejected.append({"kind": "factor", "value": entry, "reason": "字段、来源引用或因素性质不合法"})
            continue
        output.append(CaseAnalysisFactor(factor_id, dimension_id, title, finding, role, item_ids, relation_ids, _refs(sources)))
        seen.add(factor_id)
    return tuple(output)


def _build_directions(raw: Any, factor_ids: set[str], rejected: list[dict[str, Any]]) -> tuple[CaseReviewDirection, ...]:
    output: list[CaseReviewDirection] = []
    seen: set[str] = set()
    for entry in _raw_entries(raw):
        direction_id, title, rationale = _text(entry, "direction_id"), _text(entry, "title"), _text(entry, "rationale")
        questions = _strings(entry.get("verification_questions"))
        related = tuple(item for item in _strings(entry.get("related_factor_ids")) if item in factor_ids)
        if not direction_id or direction_id in seen or not title or not rationale or not questions:
            rejected.append({"kind": "review_direction", "value": entry, "reason": "字段不完整或引用非法"})
            continue
        output.append(CaseReviewDirection(direction_id, title, rationale, related, questions))
        seen.add(direction_id)
    return tuple(output)


def generate_historical_case_analysis(profile: HistoricalEnterpriseProfile, *, config: GenerationConfig, guide_text: str = "", analysis_id: str | None = None, material_context: dict[str, Any] | None = None) -> HistoricalCaseAnalysis:
    result = call_deepseek(build_case_analysis_messages(profile, guide_text=guide_text, material_context=material_context), config)
    item_map = {item.item_id: item for item in profile.items if item.review_status != "rejected"}
    relation_map = {item.relation_id: item for item in profile.relations if item.review_status != "rejected"}
    rejected: list[dict[str, Any]] = []
    outcomes = _build_outcomes(result.get("outcomes"), item_map, relation_map, rejected)
    factors = _build_factors(result.get("factors"), item_map, relation_map, rejected)
    directions = _build_directions(result.get("review_directions"), {item.factor_id for item in factors}, rejected)
    summary = _text(result, "case_summary") or f"现有材料仅形成了{profile.enterprise_name}的有限历史画像，尚不足以给出完整案件结论。"
    requested_status = _text(result, "outcome_status")
    if outcomes:
        outcome_status = requested_status if requested_status in {"disclosed", "partially_disclosed"} else "disclosed"
    else:
        outcome_status = "not_disclosed"
    return HistoricalCaseAnalysis(
        analysis_id=analysis_id or f"{profile.profile_id}:case-analysis",
        profile_id=profile.profile_id, case_id=profile.case_id, enterprise_name=profile.enterprise_name,
        ontology_version=profile.ontology_version, profile_hash=profile_content_hash(profile),
        case_summary=summary, outcome_status=outcome_status, outcomes=outcomes, factors=factors,
        review_directions=directions, applicability_limits=_strings(result.get("applicability_limits")),
        information_gaps=tuple(dict.fromkeys(profile.information_gaps)), model=config.model,
        api_meta=result.get("api_meta") if isinstance(result.get("api_meta"), dict) else {},
        debug_data={"raw_model_output": {key: value for key, value in result.items() if key != "api_meta"}, "rejected_candidates": rejected},
    )
