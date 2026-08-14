"""由正式企业画像派生、用于相似案例召回的分维度比较卡。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.ontology.schema import COMPARISON_DIMENSION_SECTIONS

from .models import EnterpriseProfile, ProfileItem, ProfileRelation
from .material_context import build_profile_material_context


COMPARISON_DIMENSIONS = COMPARISON_DIMENSION_SECTIONS


@dataclass(frozen=True)
class ComparisonDimension:
    dimension_id: str
    summary: str
    comparison_terms: tuple[str, ...]
    structured_features: dict[str, str] = field(default_factory=dict)
    relation_signatures: tuple[str, ...] = field(default_factory=tuple)
    source_item_ids: tuple[str, ...] = field(default_factory=tuple)
    source_relation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_unit_ids: tuple[str, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.dimension_id not in COMPARISON_DIMENSIONS:
            raise ValueError(f"比较维度非法：{self.dimension_id!r}")
        if not self.summary.strip():
            raise ValueError("比较维度 summary 不能为空。")
        if not self.comparison_terms:
            raise ValueError("比较维度至少需要一个 comparison_term。")


@dataclass(frozen=True)
class EnterpriseComparisonCard:
    card_id: str
    profile_id: str
    case_id: str
    enterprise_name: str
    profile_type: str
    ontology_version: str
    profile_hash: str
    dimensions: tuple[ComparisonDimension, ...]
    generation_method: str = "llm"
    model: str | None = None
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if self.profile_type not in {"historical", "current"}:
            raise ValueError("profile_type 必须是 historical 或 current。")
        if self.review_status not in {"pending", "approved", "rejected"}:
            raise ValueError("review_status 必须是 pending、approved 或 rejected。")
        if not all(
            value.strip()
            for value in (
                self.card_id,
                self.profile_id,
                self.case_id,
                self.enterprise_name,
                self.ontology_version,
                self.profile_hash,
            )
        ):
            raise ValueError("比较卡标识、画像标识、案例标识、企业名称和版本信息不能为空。")
        dimension_ids = [item.dimension_id for item in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("同一比较卡的 dimension_id 不得重复。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def profile_content_hash(profile: EnterpriseProfile) -> str:
    """计算比较卡的画像版本指纹；画像发生变化时旧卡即失效。"""
    payload = {
        "profile_id": profile.profile_id,
        "case_id": profile.case_id,
        "profile_type": profile.profile_type,
        "ontology_version": profile.ontology_version,
        "items": [asdict(item) for item in profile.items],
        "relations": [asdict(relation) for relation in profile.relations],
        "information_gaps": list(profile.information_gaps),
        "conflicts": list(profile.conflicts),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_comparison_card_messages(
    profile: EnterpriseProfile,
    *,
    guide_text: str = "",
    material_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """把已审核画像交给模型凝练；不传原始长文，也不允许改写画像事实。"""
    profile_payload = {
        "profile_id": profile.profile_id,
        "enterprise_name": profile.enterprise_name,
        "profile_type": profile.profile_type,
        "ontology_version": profile.ontology_version,
        "profile_items": [
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
            }
            for item in profile.items
            if item.review_status != "rejected"
        ],
        "profile_relations": [
            {
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "source_type": relation.source_type,
                "target_type": relation.target_type,
                "information_status": relation.information_status,
                "content_role": relation.content_role,
            }
            for relation in profile.relations
            if relation.review_status != "rejected"
        ],
        "information_gaps": list(profile.information_gaps),
        "conflicts": list(profile.conflicts),
    }
    dimension_text = "\n".join(
        f"- {dimension_id}: {', '.join(section_ids)}"
        for dimension_id, section_ids in COMPARISON_DIMENSIONS.items()
    )
    system = (
        f"{guide_text}\n\n"
        "你负责把已审核的科技型企业画像凝练为分维度比较卡。"
        "比较卡只服务于历史相似案例召回，不是新的事实来源，也不是风险评分。"
        "只输出合法 JSON，不输出 Markdown、解释或额外字段。"
    )
    user = (
        "===== 企业与来源材料基本信息 =====\n"
        f"{json.dumps(material_context or build_profile_material_context(profile), ensure_ascii=False, indent=2)}\n"
        "这里只提供主体、报告期和来源文档标题；不得将标题本身扩写成画像事实。\n"
        "===== 企业与来源材料基本信息结束 =====\n\n"
        "输出顶层字段 comparison_dimensions（数组）。每项只能包含："
        "dimension_id、summary、comparison_terms、source_item_ids、"
        "source_relation_ids、information_gaps。\n"
        "summary 只概括输入画像中已有的、有区分度的事实，不得补充常识、推断或结论；"
        "不要重复固定模板标题，建议 40 至 160 个汉字。\n"
        "comparison_terms 提取 2 至 12 个可用于比较和检索的实体、技术、依赖、"
        "经营特征或风险概念，不要放“企业、风险、情况、信息不足”等通用词。\n"
        "source_item_ids 和 source_relation_ids 必须逐字复制输入中的 ID；"
        "每个维度至少引用一项来源。没有有效事实的维度可以省略。\n"
        "不得输出分数、风险等级、structured_features、relation_signatures 或 evidence_unit_ids；"
        "这些字段由程序从画像来源项确定。\n"
        f"允许的维度及对应画像板块：\n{dimension_text}\n\n"
        "===== 已审核企业画像开始 =====\n"
        f"{json.dumps(profile_payload, ensure_ascii=False, indent=2)}\n"
        "===== 已审核企业画像结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_comparison_card(
    profile: EnterpriseProfile,
    *,
    config: GenerationConfig,
    guide_text: str = "",
    card_id: str | None = None,
    material_context: dict[str, Any] | None = None,
) -> tuple[EnterpriseComparisonCard, dict[str, Any]]:
    """调用模型生成比较卡，并用画像中的来源项补齐结构化与证据字段。"""
    if profile.review_status != "approved":
        raise ValueError("只有审核通过的企业画像才能生成正式比较卡。")
    result = call_deepseek(
        build_comparison_card_messages(profile, guide_text=guide_text, material_context=material_context),
        config,
    )
    dimensions = _build_dimensions(profile, result.get("comparison_dimensions"))
    if not dimensions:
        raise ValueError("模型没有返回可用的比较维度。")
    card = EnterpriseComparisonCard(
        card_id=card_id or f"{profile.profile_id}:comparison",
        profile_id=profile.profile_id,
        case_id=profile.case_id,
        enterprise_name=profile.enterprise_name,
        profile_type=profile.profile_type,
        ontology_version=profile.ontology_version,
        profile_hash=profile_content_hash(profile),
        dimensions=dimensions,
        generation_method="llm",
        model=config.model,
        review_status="pending",
    )
    return card, result.get("api_meta") or {}


def approve_comparison_card(card: EnterpriseComparisonCard) -> EnterpriseComparisonCard:
    return EnterpriseComparisonCard(
        **{**card.to_dict(), "dimensions": card.dimensions, "review_status": "approved"}
    )


def comparison_dimension_text(dimension: ComparisonDimension) -> str:
    """仅拼接变量内容，避免固定模板文字污染 BM25/BGE。"""
    parts = [
        dimension.summary,
        " ".join(dimension.comparison_terms),
        " ".join(dimension.structured_features.values()),
        " ".join(dimension.relation_signatures),
    ]
    return "\n".join(part for part in parts if part.strip())


def _build_dimensions(
    profile: EnterpriseProfile,
    raw_dimensions: Any,
) -> tuple[ComparisonDimension, ...]:
    if not isinstance(raw_dimensions, list):
        raise ValueError("comparison_dimensions 必须是数组。")
    item_map = {
        item.item_id: item for item in profile.items if item.review_status != "rejected"
    }
    relation_map = {
        relation.relation_id: relation
        for relation in profile.relations
        if relation.review_status != "rejected"
    }
    dimensions: list[ComparisonDimension] = []
    seen: set[str] = set()
    for raw in raw_dimensions:
        if not isinstance(raw, dict):
            continue
        dimension_id = raw.get("dimension_id")
        summary = raw.get("summary")
        if (
            dimension_id not in COMPARISON_DIMENSIONS
            or dimension_id in seen
            or not isinstance(summary, str)
            or not summary.strip()
        ):
            continue
        source_item_ids = _allowed_ids(raw.get("source_item_ids"), item_map)
        source_relation_ids = _allowed_ids(
            raw.get("source_relation_ids"), relation_map
        )
        if not source_item_ids and not source_relation_ids:
            continue
        if not _sources_belong_to_dimension(
            dimension_id,
            source_item_ids,
            source_relation_ids,
            item_map,
            relation_map,
        ):
            continue
        terms = _clean_terms(raw.get("comparison_terms"))
        if not terms:
            continue
        selected_items = [item_map[item_id] for item_id in source_item_ids]
        selected_relations = [
            relation_map[relation_id] for relation_id in source_relation_ids
        ]
        evidence_ids = _evidence_ids((*selected_items, *selected_relations))
        dimensions.append(
            ComparisonDimension(
                dimension_id=dimension_id,
                summary=summary.strip(),
                comparison_terms=terms,
                structured_features=_structured_features(selected_items),
                relation_signatures=tuple(
                    sorted(
                        {
                            f"{relation.source_type}-{relation.relation_type}-{relation.target_type}"
                            for relation in selected_relations
                        }
                    )
                ),
                source_item_ids=source_item_ids,
                source_relation_ids=source_relation_ids,
                evidence_unit_ids=evidence_ids,
                information_gaps=_clean_strings(raw.get("information_gaps")),
            )
        )
        seen.add(dimension_id)
    return tuple(dimensions)


def _allowed_ids(raw_ids: Any, allowed: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(raw_ids, list):
        return ()
    return tuple(
        dict.fromkeys(
            item for item in raw_ids if isinstance(item, str) and item in allowed
        )
    )


def _sources_belong_to_dimension(
    dimension_id: str,
    item_ids: tuple[str, ...],
    relation_ids: tuple[str, ...],
    item_map: dict[str, ProfileItem],
    relation_map: dict[str, ProfileRelation],
) -> bool:
    allowed_sections = set(COMPARISON_DIMENSIONS[dimension_id])
    if any(item_map[item_id].section_id not in allowed_sections for item_id in item_ids):
        return False
    # 关系本身没有 section_id；至少有一个同维度画像项时才允许引用关系。
    return not relation_ids or bool(item_ids)


def _clean_terms(raw_terms: Any) -> tuple[str, ...]:
    if not isinstance(raw_terms, list):
        return ()
    values = []
    for term in raw_terms:
        if isinstance(term, str) and 1 < len(term.strip()) <= 40:
            values.append(term.strip())
    return tuple(dict.fromkeys(values))[:12]


def _clean_strings(raw_values: Any) -> tuple[str, ...]:
    if not isinstance(raw_values, list):
        return ()
    return tuple(
        dict.fromkeys(
            value.strip()
            for value in raw_values
            if isinstance(value, str) and value.strip()
        )
    )


def _evidence_ids(
    sources: Iterable[ProfileItem | ProfileRelation],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref.evidence_unit_id for source in sources for ref in source.evidence_refs
        )
    )


def _structured_features(items: Iterable[ProfileItem]) -> dict[str, str]:
    features: dict[str, str] = {}
    for item in items:
        if item.value_type == "enum" and isinstance(item.value, str):
            features[item.field_id] = " ".join(item.value.casefold().split())
        elif item.value_type == "ratio":
            ratio = _parse_ratio(item.value)
            if ratio is not None:
                features[item.field_id] = _ratio_bucket(ratio)
    return features


def _parse_ratio(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(%)?\s*", value)
        if not match:
            return None
        number = float(match.group(1))
        if match.group(2):
            number /= 100
    else:
        return None
    return number if 0 <= number <= 1 else None


def _ratio_bucket(value: float) -> str:
    if value <= 0.1:
        return "0-10%"
    if value <= 0.3:
        return "10-30%"
    if value <= 0.5:
        return "30-50%"
    if value <= 0.7:
        return "50-70%"
    return "70-100%"
