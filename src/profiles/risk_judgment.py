"""基于已审核企业画像生成证据化的自然语言核心风险判断。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.industry.models import IndustryBackgroundProfile

from .candidates import is_cross_domain_legal_name_gap
from .detailed_comparison import DetailedComparisonRun
from .models import CurrentEnterpriseProfile


@dataclass(frozen=True)
class RiskJudgmentPoint:
    title: str
    explanation: str
    current_item_ids: tuple[str, ...]
    current_relation_ids: tuple[str, ...]
    supporting_information_gaps: tuple[str, ...]
    supporting_conflicts: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    industry_insight_ids: tuple[str, ...] = ()
    industry_evidence_unit_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoreRiskJudgment:
    current_profile_id: str
    overall_judgment: str
    key_risks: tuple[RiskJudgmentPoint, ...]
    mitigating_factors: tuple[RiskJudgmentPoint, ...]
    uncertainties: tuple[str, ...]
    verification_priorities: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    api_meta: dict[str, Any]
    industry_profile_id: str | None = None
    industry_name: str | None = None
    industry_evidence_unit_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_core_risk_judgment_messages(
    current: CurrentEnterpriseProfile,
    comparison_run: DetailedComparisonRun,
    *,
    guide_text: str = "",
    industry_profile: IndustryBackgroundProfile | None = None,
) -> list[dict[str, str]]:
    information_gaps = _information_gaps(current)
    payload = {
        "current_profile": _current_profile_payload(current),
        "information_gaps": [
            {"number": number, "text": value}
            for number, value in enumerate(information_gaps, start=1)
        ],
        "conflicts": [
            {"number": number, "text": value}
            for number, value in enumerate(current.conflicts, start=1)
        ],
        "validated_historical_comparisons": [
            asdict(comparison) for comparison in comparison_run.comparisons
        ],
        "industry_context": (
            _industry_profile_payload(industry_profile)
            if industry_profile is not None
            else None
        ),
    }
    system = (
        f"{guide_text}\n\n"
        "你负责形成当前科技型企业的核心风险判断。"
        "结论必须让不熟悉数据结构的审查人员直接读懂，并严格限于输入。"
        "当前企业风险事实只能来自 current_profile、information_gaps 和 conflicts；"
        "历史比较只用于理解关注方向、适用限制和核实优先级，不能把历史企业结果写成当前企业事实。"
        "industry_context 只用于解释行业环境，不能单独证明当前企业存在某项风险。"
        "只输出合法 JSON，不输出 Markdown、解释、风险分数或授信审批意见。"
    )
    user = (
        "只输出以下顶层字段：overall_judgment、key_risks、mitigating_factors、"
        "uncertainties、verification_priorities。\n"
        "overall_judgment 是一段简体中文综合判断，直接说明最需要关注的风险及现有材料的判断边界。\n"
        "key_risks 和 mitigating_factors 都是数组，每项只包含 title、explanation、"
        "current_item_ids、current_relation_ids、information_gap_numbers、conflict_numbers、"
        "industry_insight_ids。"
        "每个 key_risks 项至少引用一个当前画像项、当前关系、信息缺口或冲突；"
        "mitigating_factors 每项必须引用当前画像项或当前关系。"
        "所有 ID 和编号必须逐字复制输入，不得编造。"
        "行业要点只能补充说明企业风险为什么值得关注；即使引用行业要点，"
        "key_risks 仍必须同时引用当前企业依据。mitigating_factors 不得由行业要点推断。"
        "按重要程度排序，核心风险最多五项，缓释因素最多三项。"
        "explanation 要说明依据及其为什么值得关注，不能只重复标题。\n"
        "uncertainties 和 verification_priorities 是简体中文字符串数组，"
        "分别说明影响判断可靠性的主要不确定性和下一步优先核实事项。"
        "如果材料不足，应直接说明不足，不得用行业常识或外部知识补全。"
        "所有面向读者的文字都使用清楚、克制的简体中文；内部 ID 不得写入自然语言正文。\n\n"
        "===== 已审核输入开始 =====\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "===== 已审核输入结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_core_risk_judgment(
    current: CurrentEnterpriseProfile,
    comparison_run: DetailedComparisonRun,
    *,
    config: GenerationConfig,
    guide_text: str = "",
    industry_profile: IndustryBackgroundProfile | None = None,
) -> CoreRiskJudgment:
    if current.review_status != "approved":
        raise ValueError("当前企业画像必须先完成审核。")
    if comparison_run.current_profile_id != current.profile_id:
        raise ValueError("详细比较结果与当前企业画像不匹配。")
    if industry_profile is not None and industry_profile.review_status != "approved":
        raise ValueError("核心风险判断只能使用 approved 行业画像。")
    result = call_deepseek(
        build_core_risk_judgment_messages(
            current,
            comparison_run,
            guide_text=guide_text,
            industry_profile=industry_profile,
        ),
        config,
    )
    return _validate_core_risk_judgment(current, result, industry_profile)


def _validate_core_risk_judgment(
    current: CurrentEnterpriseProfile,
    raw: dict[str, Any],
    industry_profile: IndustryBackgroundProfile | None = None,
) -> CoreRiskJudgment:
    overall_judgment = _required_chinese_text(
        raw.get("overall_judgment"), "overall_judgment"
    )
    information_gaps = _information_gaps(current)
    key_risks = _points(
        raw.get("key_risks"),
        current,
        information_gaps,
        current.conflicts,
        require_profile_source=False,
        limit=5,
        industry_profile=industry_profile,
    )
    mitigating_factors = _points(
        raw.get("mitigating_factors"),
        current,
        information_gaps,
        current.conflicts,
        require_profile_source=True,
        limit=3,
        industry_profile=industry_profile,
    )
    evidence_unit_ids = tuple(
        dict.fromkeys(
            evidence_id
            for point in (*key_risks, *mitigating_factors)
            for evidence_id in point.evidence_unit_ids
        )
    )
    industry_evidence_unit_ids = tuple(
        dict.fromkeys(
            evidence_id
            for point in (*key_risks, *mitigating_factors)
            for evidence_id in point.industry_evidence_unit_ids
        )
    )
    return CoreRiskJudgment(
        current_profile_id=current.profile_id,
        overall_judgment=overall_judgment,
        key_risks=key_risks,
        mitigating_factors=mitigating_factors,
        uncertainties=_strings(raw.get("uncertainties"), "uncertainties"),
        verification_priorities=_strings(
            raw.get("verification_priorities"), "verification_priorities"
        ),
        evidence_unit_ids=evidence_unit_ids,
        api_meta=raw.get("api_meta") or {},
        industry_profile_id=(
            industry_profile.profile_id if industry_profile is not None else None
        ),
        industry_name=(
            industry_profile.industry_name if industry_profile is not None else None
        ),
        industry_evidence_unit_ids=industry_evidence_unit_ids,
    )


def _current_profile_payload(current: CurrentEnterpriseProfile) -> dict[str, Any]:
    return {
        "profile_id": current.profile_id,
        "enterprise_name": current.enterprise_name,
        "items": [
            {
                "item_id": item.item_id,
                "section_id": item.section_id,
                "field_id": item.field_id,
                "value": item.value,
                "unit": item.unit,
                "reporting_period": item.reporting_period,
                "information_status": item.information_status,
                "content_role": item.content_role,
                "evidence_unit_ids": [
                    reference.evidence_unit_id for reference in item.evidence_refs
                ],
            }
            for item in current.items
            if item.review_status != "rejected"
        ],
        "relations": [
            {
                "relation_id": relation.relation_id,
                "relation_type": relation.relation_type,
                "source_id": relation.source_id,
                "target_id": relation.target_id,
                "information_status": relation.information_status,
                "content_role": relation.content_role,
                "evidence_unit_ids": [
                    reference.evidence_unit_id
                    for reference in relation.evidence_refs
                ],
            }
            for relation in current.relations
            if relation.review_status != "rejected"
        ],
    }


def _points(
    raw_points: Any,
    current: CurrentEnterpriseProfile,
    information_gaps: tuple[str, ...],
    conflicts: tuple[str, ...],
    *,
    require_profile_source: bool,
    limit: int,
    industry_profile: IndustryBackgroundProfile | None,
) -> tuple[RiskJudgmentPoint, ...]:
    if not isinstance(raw_points, list):
        return ()
    items = {
        item.item_id: item for item in current.items if item.review_status != "rejected"
    }
    relations = {
        relation.relation_id: relation
        for relation in current.relations
        if relation.review_status != "rejected"
    }
    industry_insights = {
        insight.insight_id: insight
        for insight in industry_profile.insights
    } if industry_profile is not None else {}
    points: list[RiskJudgmentPoint] = []
    for raw in raw_points:
        if not isinstance(raw, dict):
            continue
        title = _optional_chinese_text(raw.get("title"), "title")
        explanation = _optional_chinese_text(raw.get("explanation"), "explanation")
        if not title or not explanation:
            continue
        item_ids = _ids(raw.get("current_item_ids"), items)
        relation_ids = _ids(raw.get("current_relation_ids"), relations)
        selected_gaps = _numbered_values(
            raw.get("information_gap_numbers"), information_gaps
        )
        selected_conflicts = _numbered_values(
            raw.get("conflict_numbers"), conflicts
        )
        industry_insight_ids = _ids(
            raw.get("industry_insight_ids"), industry_insights
        )
        if require_profile_source and not (item_ids or relation_ids):
            continue
        if not (item_ids or relation_ids or selected_gaps or selected_conflicts):
            continue
        sources = [
            *(items[item_id] for item_id in item_ids),
            *(relations[relation_id] for relation_id in relation_ids),
        ]
        evidence_unit_ids = tuple(
            dict.fromkeys(
                reference.evidence_unit_id
                for source in sources
                for reference in source.evidence_refs
            )
        )
        industry_evidence_unit_ids = tuple(
            dict.fromkeys(
                reference.evidence_unit_id
                for insight_id in industry_insight_ids
                for reference in industry_insights[insight_id].evidence_refs
            )
        )
        points.append(
            RiskJudgmentPoint(
                title=title,
                explanation=explanation,
                current_item_ids=item_ids,
                current_relation_ids=relation_ids,
                supporting_information_gaps=selected_gaps,
                supporting_conflicts=selected_conflicts,
                evidence_unit_ids=evidence_unit_ids,
                industry_insight_ids=industry_insight_ids,
                industry_evidence_unit_ids=industry_evidence_unit_ids,
            )
        )
        if len(points) == limit:
            break
    return tuple(points)


def _information_gaps(current: CurrentEnterpriseProfile) -> tuple[str, ...]:
    return tuple(
        gap
        for gap in current.information_gaps
        if not is_cross_domain_legal_name_gap(gap)
    )


def _industry_profile_payload(
    profile: IndustryBackgroundProfile,
) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "industry_name": profile.industry_name,
        "insights": [
            {
                "insight_id": insight.insight_id,
                "dimension_id": insight.dimension_id,
                "statement": insight.statement,
                "insight_type": insight.insight_type,
                "time_scope": insight.time_scope,
                "geographic_scope": insight.geographic_scope,
                "evidence_unit_ids": [
                    reference.evidence_unit_id
                    for reference in insight.evidence_refs
                ],
            }
            for insight in profile.insights
            if insight.review_status != "rejected"
        ],
        "information_gaps": list(profile.information_gaps),
    }


def _ids(raw_ids: Any, allowed: dict[str, Any]) -> tuple[str, ...]:
    if not isinstance(raw_ids, list):
        return ()
    return tuple(
        dict.fromkeys(value for value in raw_ids if isinstance(value, str) and value in allowed)
    )


def _numbered_values(raw_numbers: Any, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(raw_numbers, list):
        return ()
    return tuple(
        dict.fromkeys(
            values[number - 1]
            for number in raw_numbers
            if isinstance(number, int)
            and not isinstance(number, bool)
            and 1 <= number <= len(values)
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


def _required_chinese_text(value: Any, field_name: str) -> str:
    text = _optional_chinese_text(value, field_name)
    if not text:
        raise ValueError(f"核心风险判断字段 {field_name} 不能为空。")
    return text


def _optional_chinese_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    _require_chinese(text, field_name)
    return text


def _require_chinese(value: str, field_name: str) -> None:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", value))
    english_words = len(re.findall(r"[A-Za-z]{2,}", value))
    if chinese_chars == 0 or chinese_chars < english_words:
        raise ValueError(f"核心风险判断字段 {field_name} 必须使用简体中文。")
