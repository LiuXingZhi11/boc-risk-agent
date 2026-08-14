"""对 ComparisonCard 召回的 Top-K 企业画像做证据化详细比较。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig

from .candidates import is_cross_domain_legal_name_gap
from .comparison_cards import COMPARISON_DIMENSIONS
from .comparison_retrieval import ComparisonCardMatch
from .models import CurrentEnterpriseProfile, HistoricalEnterpriseProfile
from .material_context import build_profile_material_context


@dataclass(frozen=True)
class ComparisonPoint:
    dimension_id: str
    explanation: str
    current_item_ids: tuple[str, ...]
    historical_item_ids: tuple[str, ...]
    current_relation_ids: tuple[str, ...]
    historical_relation_ids: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]


@dataclass(frozen=True)
class HistoricalProfileComparison:
    historical_profile_id: str
    historical_case_id: str
    historical_enterprise_name: str
    retrieval_score: float
    similarity_basis: tuple[ComparisonPoint, ...]
    key_differences: tuple[ComparisonPoint, ...]
    historical_outcomes: tuple[ComparisonPoint, ...]
    applicability_limits: tuple[str, ...]
    verification_questions: tuple[str, ...]


@dataclass(frozen=True)
class DetailedComparisonRun:
    current_profile_id: str
    comparisons: tuple[HistoricalProfileComparison, ...]
    api_meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_detailed_comparison_messages(
    current: CurrentEnterpriseProfile,
    historical_profiles: Iterable[HistoricalEnterpriseProfile],
    matches: Iterable[ComparisonCardMatch],
    *,
    guide_text: str = "",
    historical_case_analyses: dict[str, dict[str, Any]] | None = None,
    material_contexts: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    historical = tuple(historical_profiles)
    match_map = {match.historical_profile_id: match for match in matches}
    payload = {
        "current_material_context": (material_contexts or {}).get(
            current.profile_id, build_profile_material_context(current)
        ),
        "current_profile": _profile_payload(current),
        "historical_candidates": [
            {
                "retrieval": match_map[profile.profile_id].to_dict(),
                "material_context": (material_contexts or {}).get(
                    profile.profile_id, build_profile_material_context(profile)
                ),
                "profile": _profile_payload(profile),
                "approved_case_analysis": (historical_case_analyses or {}).get(profile.profile_id),
            }
            for profile in historical
            if profile.profile_id in match_map
        ],
    }
    system = (
        f"{guide_text}\n\n"
        "你负责对当前科技型企业与已召回的历史企业画像做详细比较。"
        "检索分数只表示候选顺序，不是风险结论。"
        "所有自然语言分析、适用限制和核实问题必须使用简体中文；"
        "仅技术缩写、产品名、企业名和输入 ID 可以保留原文。"
        "只输出合法 JSON，不输出 Markdown、解释或输入中没有的事实。"
    )
    user = (
        "顶层只输出 comparisons 数组。每个历史企业一项，包含："
        "historical_profile_id、similarity_basis、key_differences、"
        "historical_outcomes、applicability_limits、verification_questions。\n"
        "前三个字段是比较点数组；每个比较点只包含 dimension_id、explanation、"
        "current_item_ids、historical_item_ids、current_relation_ids、"
        "historical_relation_ids。\n"
        "所有 ID 必须逐字复制输入；相似点和差异点必须同时引用当前与历史来源。"
        "每句话只能复述所引用画像项的字段和值、关系类型、信息缺口或冲突；"
        "不得根据企业名称、技术常识或外部知识补充行业、应用场景、客户、经营表现和监管环境。"
        "历史结果只能引用历史画像中 content_role=outcome、regulatory_finding、"
        "judicial_finding 的内容；每条已披露 outcome 必须单独出现在 historical_outcomes，"
        "历史结果无需引用当前企业来源；没有就输出空数组。\n"
        "不得把历史企业结果转移为当前企业事实，不得输出综合风险分数或审批建议。\n"
        "不得因为历史企业存在欺诈、造假、退市或处罚，而将当前企业描述为存在相同风险；"
        "此类历史结果只能用于说明适用限制或提出中性的证据核实问题。\n"
        "approved_case_analysis 仅用于理解历史企业自身的案件背景、适用限制和核实方向；"
        "它不是当前企业事实，也不能替代当前画像与历史画像的双向引用。\n"
        "explanation、applicability_limits、verification_questions 必须使用简体中文，"
        "不得输出英文句子。\n"
        "核实问题只能来自当前画像已有的信息缺口、冲突或本次比较形成的差异，"
        "并且只能涉及输入画像实际出现的比较维度，不得扩展到其他领域。\n"
        f"dimension_id 只能使用：{', '.join(COMPARISON_DIMENSIONS)}。\n\n"
        "===== 当前画像与历史候选开始 =====\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "===== 当前画像与历史候选结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def compare_profile_candidates(
    current: CurrentEnterpriseProfile,
    historical_profiles: Iterable[HistoricalEnterpriseProfile],
    matches: Iterable[ComparisonCardMatch],
    *,
    config: GenerationConfig,
    guide_text: str = "",
    historical_case_analyses: dict[str, dict[str, Any]] | None = None,
    material_contexts: dict[str, dict[str, Any]] | None = None,
) -> DetailedComparisonRun:
    if current.review_status != "approved":
        raise ValueError("当前企业画像必须先完成事实映射审核。")
    historical = tuple(historical_profiles)
    if any(profile.review_status != "approved" for profile in historical):
        raise ValueError("详细比较只能使用 approved 历史画像。")
    match_values = tuple(matches)
    result = call_deepseek(
        build_detailed_comparison_messages(
            current, historical, match_values, guide_text=guide_text,
            historical_case_analyses=historical_case_analyses,
            material_contexts=material_contexts,
        ),
        config,
    )
    comparisons = _validate_comparisons(
        current,
        historical,
        match_values,
        result.get("comparisons"),
    )
    return DetailedComparisonRun(
        current_profile_id=current.profile_id,
        comparisons=comparisons,
        api_meta=result.get("api_meta") or {},
    )


def _profile_payload(profile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "case_id": profile.case_id,
        "enterprise_name": profile.enterprise_name,
        "items": [
            {
                "item_id": item.item_id,
                "subject": item.subject,
                "value_scope": item.value_scope,
                "section_id": item.section_id,
                "field_id": item.field_id,
                "value": item.value,
                "value_type": item.value_type,
                "unit": item.unit,
                "reporting_period": item.reporting_period,
                "information_status": item.information_status,
                "content_role": item.content_role,
                "evidence_unit_ids": [
                    ref.evidence_unit_id for ref in item.evidence_refs
                ],
            }
            for item in profile.items
            if item.review_status != "rejected"
        ],
        "relations": [
            {
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "source_type": relation.source_type,
                "target_type": relation.target_type,
                "information_status": relation.information_status,
                "content_role": relation.content_role,
                "evidence_unit_ids": [
                    ref.evidence_unit_id for ref in relation.evidence_refs
                ],
            }
            for relation in profile.relations
            if relation.review_status != "rejected"
        ],
        "information_gaps": list(profile.information_gaps),
        "conflicts": list(profile.conflicts),
    }


def _validate_comparisons(
    current: CurrentEnterpriseProfile,
    historical_profiles: tuple[HistoricalEnterpriseProfile, ...],
    matches: tuple[ComparisonCardMatch, ...],
    raw_comparisons: Any,
) -> tuple[HistoricalProfileComparison, ...]:
    if not isinstance(raw_comparisons, list):
        raise ValueError("comparisons 必须是数组。")
    current_items = {item.item_id: item for item in current.items}
    current_relations = {
        relation.relation_id: relation for relation in current.relations
    }
    historical_map = {
        profile.profile_id: profile for profile in historical_profiles
    }
    match_map = {match.historical_profile_id: match for match in matches}
    comparisons: list[HistoricalProfileComparison] = []
    seen: set[str] = set()
    for raw in raw_comparisons:
        if not isinstance(raw, dict):
            continue
        profile_id = raw.get("historical_profile_id")
        if (
            profile_id not in historical_map
            or profile_id not in match_map
            or profile_id in seen
        ):
            continue
        profile = historical_map[profile_id]
        historical_items = {item.item_id: item for item in profile.items}
        historical_relations = {
            relation.relation_id: relation for relation in profile.relations
        }
        comparisons.append(
            HistoricalProfileComparison(
                historical_profile_id=profile.profile_id,
                historical_case_id=profile.case_id,
                historical_enterprise_name=profile.enterprise_name,
                retrieval_score=match_map[profile_id].score,
                similarity_basis=_points(
                    raw.get("similarity_basis"),
                    current_items,
                    historical_items,
                    current_relations,
                    historical_relations,
                    require_both=True,
                ),
                key_differences=_points(
                    raw.get("key_differences"),
                    current_items,
                    historical_items,
                    current_relations,
                    historical_relations,
                    require_both=True,
                ),
                historical_outcomes=_historical_outcomes(
                    raw.get("historical_outcomes"),
                    profile,
                    current_items,
                    historical_items,
                    current_relations,
                    historical_relations,
                ),
                applicability_limits=_strings(
                    raw.get("applicability_limits"), "applicability_limits"
                ),
                verification_questions=_verification_questions(raw.get("verification_questions"), current),
            )
        )
        seen.add(profile_id)
    return tuple(comparisons)


def _historical_outcomes(
    raw_points: Any,
    profile: HistoricalEnterpriseProfile,
    current_items: dict[str, Any],
    historical_items: dict[str, Any],
    current_relations: dict[str, Any],
    historical_relations: dict[str, Any],
) -> tuple[ComparisonPoint, ...]:
    points = _points(
        raw_points,
        current_items,
        historical_items,
        current_relations,
        historical_relations,
        require_both=False,
        outcome_only=True,
    )
    if points:
        return points
    items = [item for item in profile.items if item.content_role == "outcome"]
    if not items:
        items = [
            item
            for item in profile.items
            if item.content_role in {"regulatory_finding", "judicial_finding"}
        ]
    return tuple(
        ComparisonPoint(
            dimension_id="authority_outcome_and_evidence",
            explanation=str(item.value),
            current_item_ids=(),
            historical_item_ids=(item.item_id,),
            current_relation_ids=(),
            historical_relation_ids=(),
            evidence_unit_ids=tuple(ref.evidence_unit_id for ref in item.evidence_refs),
        )
        for item in items
    )


def _verification_questions(raw_values: Any, current: CurrentEnterpriseProfile) -> tuple[str, ...]:
    values = _strings(raw_values, "verification_questions")
    current_has_authority = any(
        item.content_role in {"outcome", "regulatory_finding", "judicial_finding"}
        for item in current.items
    )
    has_legal_name_gap = any(
        "法定名称" in gap and not is_cross_domain_legal_name_gap(gap)
        for gap in current.information_gaps
    )
    blocked_history_terms = ("欺诈", "造假", "退市", "处罚")
    return tuple(
        value
        for value in values
        if not ("法定名称" in value and not has_legal_name_gap)
        and not (not current_has_authority and any(term in value for term in blocked_history_terms))
    )


def _points(
    raw_points: Any,
    current_items: dict[str, Any],
    historical_items: dict[str, Any],
    current_relations: dict[str, Any],
    historical_relations: dict[str, Any],
    *,
    require_both: bool,
    outcome_only: bool = False,
) -> tuple[ComparisonPoint, ...]:
    if not isinstance(raw_points, list):
        return ()
    points: list[ComparisonPoint] = []
    for raw in raw_points:
        if not isinstance(raw, dict):
            continue
        dimension_id = raw.get("dimension_id")
        explanation = raw.get("explanation")
        if (
            dimension_id not in COMPARISON_DIMENSIONS
            or not isinstance(explanation, str)
            or not explanation.strip()
        ):
            continue
        _require_chinese(explanation, "explanation")
        current_item_ids = _ids(raw.get("current_item_ids"), current_items)
        historical_item_ids = _ids(
            raw.get("historical_item_ids"), historical_items
        )
        current_relation_ids = _ids(
            raw.get("current_relation_ids"), current_relations
        )
        historical_relation_ids = _ids(
            raw.get("historical_relation_ids"), historical_relations
        )
        current_has_source = bool(current_item_ids or current_relation_ids)
        historical_has_source = bool(
            historical_item_ids or historical_relation_ids
        )
        if require_both and not (current_has_source and historical_has_source):
            continue
        if not require_both and not historical_has_source:
            continue
        allowed_sections = set(COMPARISON_DIMENSIONS[dimension_id])
        selected_items = [
            *(current_items[item_id] for item_id in current_item_ids),
            *(historical_items[item_id] for item_id in historical_item_ids),
        ]
        if any(item.section_id not in allowed_sections for item in selected_items):
            continue
        historical_sources = [
            *(historical_items[item_id] for item_id in historical_item_ids),
            *(
                historical_relations[relation_id]
                for relation_id in historical_relation_ids
            ),
        ]
        if outcome_only and any(
            source.content_role
            not in {"outcome", "regulatory_finding", "judicial_finding"}
            for source in historical_sources
        ):
            continue
        all_sources = [
            *(current_items[item_id] for item_id in current_item_ids),
            *(
                current_relations[relation_id]
                for relation_id in current_relation_ids
            ),
            *historical_sources,
        ]
        evidence_ids = tuple(
            dict.fromkeys(
                ref.evidence_unit_id
                for source in all_sources
                for ref in source.evidence_refs
            )
        )
        points.append(
            ComparisonPoint(
                dimension_id=dimension_id,
                explanation=explanation.strip(),
                current_item_ids=current_item_ids,
                historical_item_ids=historical_item_ids,
                current_relation_ids=current_relation_ids,
                historical_relation_ids=historical_relation_ids,
                evidence_unit_ids=evidence_ids,
            )
        )
    return tuple(points)


def _ids(raw_ids: Any, allowed: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(raw_ids, list):
        return ()
    return tuple(
        dict.fromkeys(
            item for item in raw_ids if isinstance(item, str) and item in allowed
        )
    )


def _strings(raw_values: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(raw_values, list):
        return ()
    values = tuple(
        dict.fromkeys(
            value.strip()
            for value in raw_values
            if isinstance(value, str) and value.strip()
        )
    )
    for value in values:
        _require_chinese(value, field_name)
    return values


def _require_chinese(value: str, field_name: str) -> None:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", value))
    english_words = len(re.findall(r"[A-Za-z]{2,}", value))
    if chinese_chars == 0 or chinese_chars < english_words:
        raise ValueError(f"详细比较字段 {field_name} 必须使用简体中文。")
