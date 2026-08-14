"""从少量行业 EvidenceUnit 生成并校验行业背景画像。"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.profiles.models import EvidenceReference

from .models import (
    INDUSTRY_DIMENSION_DESCRIPTIONS,
    INDUSTRY_DIMENSIONS,
    INDUSTRY_INSIGHT_TYPES,
    IndustryBackgroundProfile,
    IndustryInsight,
    IndustryProfileGeneration,
)
from .retrieval import IndustryEvidenceBundle


def build_industry_profile_messages(
    *,
    industry_name: str,
    bundle: IndustryEvidenceBundle,
    guide_text: str = "",
    allowed_dimensions: tuple[str, ...] = INDUSTRY_DIMENSIONS,
) -> list[dict[str, str]]:
    dimensions = _allowed_dimensions(allowed_dimensions)
    dimension_definitions = "\n".join(
        f"- {dimension_id}：{INDUSTRY_DIMENSION_DESCRIPTIONS[dimension_id]}"
        for dimension_id in dimensions
    )
    payload = {
        "industry_name": industry_name,
        "dimension_evidence_ids": {
            dimension_id: bundle.dimension_evidence_ids.get(dimension_id, ())
            for dimension_id in dimensions
        },
        "evidence_units": [
            {
                "evidence_unit_id": unit.evidence_unit_id,
                "source_id": unit.source_id,
                "title": unit.metadata.get("title"),
                "location": dict(unit.location),
                "content": unit.content,
            }
            for unit in bundle.evidence_units
        ],
    }
    system = (
        f"{guide_text}\n\n"
        "你负责从行业报告证据中建立行业背景画像。"
        "只复述输入材料明确表达的行业事实、预测和分析判断，"
        "不得补充外部知识，也不得把行业陈述改写成某一家企业的事实。"
        "只输出合法 JSON，不输出 Markdown 或额外解释。"
    )
    user = (
        "顶层只输出 insights 和 information_gaps。insights 是数组，每项只包含："
        "insight_id、dimension_id、statement、insight_type、time_scope、"
        "geographic_scope、evidence_unit_ids、evidence_quotes。\n"
        f"本批次 dimension_id 只能使用：{', '.join(dimensions)}。\n"
        f"当前维度定义：\n{dimension_definitions}\n"
        "只有证据直接回答对应维度定义时才生成要点；不符合当前维度的证据必须省略，"
        "不得为了使用证据而强行归类。\n"
        f"insight_type 只能使用：{', '.join(INDUSTRY_INSIGHT_TYPES)}。"
        "reported_fact 表示报告陈述的现状或历史事实，forecast 表示预测，"
        "analysis_judgment 表示报告的分析观点或建议；不得把预测标成事实，"
        "不得把‘建议、提出、可考虑’等建议性表述标成 forecast。\n"
        "statement 使用普通人可读的简体中文，并保留材料披露的时间、地域、"
        "统计口径和不确定措辞。time_scope、geographic_scope 未明确披露时填 null。\n"
        "evidence_unit_ids 只能逐字复制输入 ID。evidence_quotes 是对象数组，"
        "每项只包含 evidence_unit_id 和 excerpt；每个引用 ID 都必须至少有一条摘录。"
        "excerpt 必须逐字连续复制对应 EvidenceUnit 原文，不得拼接、改写或使用省略号。\n"
        "每条要点只表达一个核心事实，不要把多个独立技术、阶段或判断合并成一条。"
        "statement 中每个实质性结论都必须由 evidence_quotes 的连续原文直接支持。"
        "在证据充分时，优先保留不同来源或不同章节中的独立事实，不要因为已有一条概括性结论"
        "就省略其他能补充市场、技术、产业链、竞争、商业化或风险判断的直接证据。"
        "每个维度最多输出 4 条高价值要点，没有充分证据时可以不输出。"
        "同一事实不要重复输出。information_gaps 是简体中文字符串数组，只说明"
        "本次输入证据未充分覆盖的当前批次维度，不生成其他维度或企业信息缺口。\n\n"
        "===== 行业证据开始 =====\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "===== 行业证据结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_industry_background_profile(
    *,
    profile_id: str,
    industry_id: str,
    industry_name: str,
    bundle: IndustryEvidenceBundle,
    config: GenerationConfig,
    guide_text: str = "",
    allowed_dimensions: tuple[str, ...] = INDUSTRY_DIMENSIONS,
) -> IndustryProfileGeneration:
    if bundle.industry_id != industry_id:
        raise ValueError("行业证据包与 industry_id 不匹配。")
    result = call_deepseek(
        build_industry_profile_messages(
            industry_name=industry_name,
            bundle=bundle,
            guide_text=guide_text,
            allowed_dimensions=allowed_dimensions,
        ),
        config,
    )
    insights, rejected = _validate_insights(
        result.get("insights"),
        bundle,
        allowed_dimensions=_allowed_dimensions(allowed_dimensions),
    )
    used_ids = {
        reference.evidence_unit_id
        for insight in insights
        for reference in insight.evidence_refs
    }
    source_ids = tuple(
        dict.fromkeys(
            unit.source_id
            for unit in bundle.evidence_units
            if unit.evidence_unit_id in used_ids
        )
    )
    profile = IndustryBackgroundProfile(
        profile_id=profile_id,
        industry_id=industry_id,
        industry_name=industry_name,
        source_ids=source_ids,
        insights=insights,
        information_gaps=_strings(result.get("information_gaps")),
        review_status="pending",
        model=config.model,
        api_meta=result.get("api_meta") or {},
    )
    return IndustryProfileGeneration(profile, rejected)


def audit_industry_profile_generation(
    *,
    generation: IndustryProfileGeneration,
    config: GenerationConfig,
) -> IndustryProfileGeneration:
    """全局审核行业要点，只接受或拒绝，不改写内容。"""
    result = call_deepseek(
        build_industry_audit_messages(generation.profile),
        config,
    )
    raw_decisions = result.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("行业语义审核 decisions 必须是数组。")
    decisions = {
        item.get("insight_id"): item
        for item in raw_decisions
        if isinstance(item, dict) and isinstance(item.get("insight_id"), str)
    }
    accepted = []
    rejected = list(generation.rejected_candidates)
    for insight in generation.profile.insights:
        decision = decisions.get(insight.insight_id)
        if decision is not None and decision.get("accepted") is True:
            accepted.append(insight)
            continue
        reason = (
            decision.get("reason")
            if isinstance(decision, dict) and isinstance(decision.get("reason"), str)
            else "全局语义审核未返回接受决定。"
        )
        rejected.append({"insight_id": insight.insight_id, "reason": reason})
    profile = replace(
        generation.profile,
        insights=tuple(accepted),
        api_meta={
            **generation.profile.api_meta,
            "semantic_audit": result.get("api_meta") or {},
        },
    )
    return IndustryProfileGeneration(profile, tuple(rejected))


def build_industry_audit_messages(
    profile: IndustryBackgroundProfile,
) -> list[dict[str, str]]:
    payload = {
        "dimension_definitions": INDUSTRY_DIMENSION_DESCRIPTIONS,
        "insights": [
            {
                "insight_id": insight.insight_id,
                "dimension_id": insight.dimension_id,
                "statement": insight.statement,
                "insight_type": insight.insight_type,
                "evidence_quotes": [
                    {
                        "evidence_unit_id": reference.evidence_unit_id,
                        "excerpt": reference.excerpt,
                    }
                    for reference in insight.evidence_refs
                ],
            }
            for insight in profile.insights
        ],
    }
    system = (
        "你负责审核行业背景画像候选，只能根据输入候选、维度定义和原文摘录判断。"
        "不得使用外部知识，不得改写或补充行业事实。只输出合法 JSON。"
    )
    user = (
        "逐条检查：dimension_id 是否匹配；insight_type 是否正确；statement 的全部"
        "实质结论是否被摘录直接支持；是否与其他候选实质重复。建议、提出、可考虑"
        "属于 analysis_judgment，不属于 forecast。行业风险必须是不利影响、不确定性、"
        "约束、瓶颈或安全伦理问题，不能是收益、机会或缓释措施。\n"
        "顶层只输出 decisions 数组，每项只包含 insight_id、accepted、reason。"
        "accepted 只能是 true 或 false。重复候选只接受信息更直接、维度更准确的一项。"
        "不要输出修改后的 statement 或新要点。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _validate_insights(
    raw_insights: Any,
    bundle: IndustryEvidenceBundle,
    *,
    allowed_dimensions: tuple[str, ...] = INDUSTRY_DIMENSIONS,
) -> tuple[tuple[IndustryInsight, ...], tuple[dict[str, Any], ...]]:
    if not isinstance(raw_insights, list):
        raise ValueError("insights 必须是数组。")
    evidence = {
        unit.evidence_unit_id: unit for unit in bundle.evidence_units
    }
    accepted: list[IndustryInsight] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_insights):
        try:
            insight = _build_insight(
                raw,
                evidence,
                allowed_dimensions,
                bundle.dimension_evidence_ids,
            )
            if insight.insight_id in seen_ids:
                raise ValueError("insight_id 不得重复。")
        except (TypeError, ValueError, KeyError) as exc:
            rejected.append(
                {
                    "index": index,
                    "insight_id": raw.get("insight_id") if isinstance(raw, dict) else None,
                    "reason": str(exc),
                }
            )
            continue
        accepted.append(insight)
        seen_ids.add(insight.insight_id)
    return tuple(accepted), tuple(rejected)


def _build_insight(
    raw: Any,
    evidence: dict[str, Any],
    allowed_dimensions: tuple[str, ...],
    dimension_evidence_ids: dict[str, tuple[str, ...]],
) -> IndustryInsight:
    if not isinstance(raw, dict):
        raise ValueError("行业要点必须是对象。")
    insight_id = _required_text(raw.get("insight_id"), "insight_id")
    statement = _required_text(raw.get("statement"), "statement")
    _require_chinese(statement, "statement")
    dimension_id = raw.get("dimension_id")
    insight_type = raw.get("insight_type")
    if dimension_id not in allowed_dimensions:
        raise ValueError(f"行业维度不属于当前批次：{dimension_id!r}")
    if insight_type not in INDUSTRY_INSIGHT_TYPES:
        raise ValueError(f"行业要点类型非法：{insight_type!r}")
    evidence_ids = _valid_evidence_ids(raw.get("evidence_unit_ids"), evidence)
    allowed_evidence_ids = set(dimension_evidence_ids.get(dimension_id, ()))
    if any(evidence_id not in allowed_evidence_ids for evidence_id in evidence_ids):
        raise ValueError("行业要点引用了未关联到该维度的 EvidenceUnit。")
    quotes = raw.get("evidence_quotes")
    if not isinstance(quotes, list):
        raise ValueError("evidence_quotes 必须是数组。")
    excerpts: dict[str, list[str]] = {}
    for quote in quotes:
        if not isinstance(quote, dict):
            raise ValueError("evidence_quotes 的每一项必须是对象。")
        evidence_id = quote.get("evidence_unit_id")
        excerpt = _required_text(quote.get("excerpt"), "excerpt")
        if evidence_id not in evidence_ids:
            raise ValueError("证据摘录只能引用 evidence_unit_ids 中的证据。")
        if _normalize(excerpt) not in _normalize(evidence[evidence_id].content):
            raise ValueError("证据摘录必须逐字来自对应 EvidenceUnit。")
        excerpts.setdefault(evidence_id, []).append(excerpt)
    if set(excerpts) != set(evidence_ids):
        raise ValueError("每个 evidence_unit_id 都必须提供对应摘录。")
    return IndustryInsight(
        insight_id=insight_id,
        dimension_id=dimension_id,
        statement=statement,
        insight_type=insight_type,
        time_scope=_optional_text(raw.get("time_scope")),
        geographic_scope=_optional_text(raw.get("geographic_scope")),
        evidence_refs=tuple(
            EvidenceReference(
                evidence_id,
                excerpt="\n".join(dict.fromkeys(excerpts[evidence_id])),
            )
            for evidence_id in evidence_ids
        ),
    )


def _valid_evidence_ids(
    raw_ids: Any,
    evidence: dict[str, Any],
) -> tuple[str, ...]:
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("evidence_unit_ids 必须是非空数组。")
    if any(not isinstance(value, str) or value not in evidence for value in raw_ids):
        raise ValueError("行业要点引用了输入中不存在的 EvidenceUnit。")
    return tuple(dict.fromkeys(raw_ids))


def _strings(raw_values: Any) -> tuple[str, ...]:
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
        _require_chinese(value, "information_gaps")
    return values


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 不能为空。")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize(value: str) -> str:
    return "".join(value.split())


def _require_chinese(value: str, field_name: str) -> None:
    if not re.search(r"[\u4e00-\u9fff]", value):
        raise ValueError(f"行业画像字段 {field_name} 必须使用简体中文。")


def _allowed_dimensions(values: tuple[str, ...]) -> tuple[str, ...]:
    dimensions = tuple(dict.fromkeys(values))
    if not dimensions or any(value not in INDUSTRY_DIMENSIONS for value in dimensions):
        raise ValueError("allowed_dimensions 必须使用固定行业维度。")
    return dimensions
