"""从正式企业画像确定性生成面向阅读的企业画像卡。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from src.evidence.models import EvidenceUnit
from src.ontology.loader import load_manifest

from .models import EnterpriseProfile, ProfileItem


CARD_DIMENSIONS = (
    ("enterprise_and_team", "企业治理与团队", ("basic_information", "ownership_governance_team")),
    ("technology_and_ip", "技术与知识产权", ("technology_ip",)),
    (
        "product_and_commercialization",
        "产品、研发与商业化",
        ("product_research_commercialization", "market_competition", "operations_delivery"),
    ),
    ("customer_supplier", "客户、供应商与合作方", ("customer_supplier_partners",)),
    ("finance_and_funding", "财务与融资", ("finance_capital",)),
    ("risk_and_compliance", "风险、合规与证据质量", ("compliance_legal_risk", "evidence_quality_gaps")),
)

ROLE_LABELS = {
    "enterprise_claim": "企业陈述",
    "business_record": "业务记录",
    "audited_information": "审计信息",
    "external_observation": "外部观察",
    "regulatory_finding": "监管认定",
    "judicial_finding": "司法认定",
    "internal_assessment": "内部判断",
    "outcome": "历史结果",
}
STATUS_LABELS = {
    "claimed": "已陈述",
    "supported": "有证据支持",
    "confirmed": "已确认",
    "disputed": "存在争议",
    "contradicted": "存在反证",
    "pending_verification": "待核实",
    "insufficient_evidence": "证据不足",
    "unknown": "未知",
    "not_disclosed": "未披露",
    "not_applicable": "不适用",
}
AUTHORITY_ROLES = frozenset({"audited_information", "regulatory_finding", "judicial_finding", "outcome"})


@dataclass(frozen=True)
class CardEvidence:
    evidence_unit_id: str
    source_title: str
    location: str
    excerpt: str


@dataclass(frozen=True)
class CardFact:
    item_id: str
    field_id: str
    field_label: str
    value: str
    role: str
    role_label: str
    status: str
    status_label: str
    context: str | None
    evidence: tuple[CardEvidence, ...] = field(default_factory=tuple)
    subject: str | None = None
    reporting_period: str | None = None
    value_scope: str | None = None


@dataclass(frozen=True)
class CardDimension:
    dimension_id: str
    label: str
    facts: tuple[CardFact, ...]
    claim_count: int
    authority_count: int
    topics: tuple["CardTopic", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CardTopic:
    topic_id: str
    title: str
    summary: str
    facts: tuple[CardFact, ...]
    claim_count: int
    authority_count: int
    records: tuple[dict[str, str], ...] = field(default_factory=tuple)
    analysis: str = ""
    key_signals: tuple[str, ...] = field(default_factory=tuple)
    information_boundaries: tuple[str, ...] = field(default_factory=tuple)
    analysis_evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    analysis_status: str = "not_generated"


TOPIC_DEFINITIONS = {
    "enterprise_and_team": (
        ("enterprise_overview", "企业定位与发展阶段", ("enterprise.",), ()),
        ("control_governance", "控制权与治理机制", ("ownership.", "governance."), ()),
        ("core_team", "核心团队与人员结构", ("team.",), ()),
    ),
    "technology_and_ip": (
        ("technology_system", "核心技术体系与来源", ("technology.name", "technology.source"), ()),
        ("technology_maturity", "技术成熟度与转化", ("technology.maturity_stage",), ()),
        ("ip_protection", "知识产权与权利状态", ("intellectual_property.", "technology.ownership_status"), ()),
    ),
    "product_and_commercialization": (
        ("product_matrix", "产品与服务布局", ("product.name",), ()),
        ("commercialization", "商业化阶段与交付", ("product.commercialization_stage",), ()),
    ),
    "customer_supplier": (
        ("customer_structure", "客户结构与集中度", ("customer_supplier.customer_concentration", "customer_supplier.counterparty_name", "customer_supplier.related_party_status"), ("customer",)),
        ("customer_transactions", "主要客户交易与依赖", ("customer_supplier.transaction_",), ("customer",)),
        ("supplier_structure", "供应商结构与采购依赖", ("customer_supplier.supplier_concentration", "customer_supplier.counterparty_name", "customer_supplier.related_party_status"), ("supplier",)),
        ("supplier_transactions", "主要供应商交易与依赖", ("customer_supplier.transaction_",), ("supplier",)),
    ),
    "finance_and_funding": (
        ("scale_profit", "收入与盈利表现", ("finance.operating_revenue", "finance.net_profit", "finance.net_profit_attributable_to_parent", "finance.adjusted_net_profit_attributable_to_parent"), ()),
        ("cash_debt", "现金流与偿债基础", ("finance.operating_cash_flow", "finance.cash_balance", "finance.interest_bearing_debt"), ()),
        ("rd_investment", "研发投入", ("finance.research_expense", "finance.research_expense_ratio"), ()),
        ("finance_concentration", "财务口径客户集中度", ("finance.customer_concentration",), ()),
    ),
    "risk_and_compliance": (
        ("risk_matters", "已披露风险事项", ("risk.",), ()),
        ("evidence_boundaries", "材料缺口与判断边界", ("evidence.",), ()),
    ),
}


@dataclass(frozen=True)
class EnterpriseVisualCard:
    profile_id: str
    case_id: str
    enterprise_name: str
    profile_type: str
    review_status: str
    dimensions: tuple[CardDimension, ...]
    historical_outcomes: tuple[CardFact, ...]
    information_gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    item_count: int
    relation_count: int
    evidence_count: int
    authority_fact_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_enterprise_visual_card(
    profile: EnterpriseProfile,
    *,
    evidence_by_id: dict[str, EvidenceUnit] | None = None,
) -> EnterpriseVisualCard:
    """不调用模型；仅把已审核画像按 Ontology 板块重组为阅读卡片。"""
    evidence_by_id = evidence_by_id or {}
    manifest = load_manifest()
    field_labels = {item["id"]: item["label"] for item in manifest["fields"]}
    items_by_section: dict[str, list[ProfileItem]] = {}
    for item in profile.items:
        if item.review_status != "rejected":
            items_by_section.setdefault(item.section_id, []).append(item)

    dimensions = tuple(
        _build_dimension(
            dimension_id,
            label,
            section_ids,
            items_by_section,
            field_labels,
            evidence_by_id,
        )
        for dimension_id, label, section_ids in CARD_DIMENSIONS
    )
    visible_items = tuple(item for item in profile.items if item.review_status != "rejected")
    outcomes = ()
    if profile.profile_type == "historical":
        outcomes = tuple(
            _to_fact(item, field_labels, evidence_by_id)
            for item in visible_items
            if item.content_role == "outcome"
        )
    evidence_ids = {
        ref.evidence_unit_id
        for item in visible_items
        for ref in item.evidence_refs
    }
    return EnterpriseVisualCard(
        profile_id=profile.profile_id,
        case_id=profile.case_id,
        enterprise_name=profile.enterprise_name,
        profile_type=profile.profile_type,
        review_status=profile.review_status,
        dimensions=dimensions,
        historical_outcomes=outcomes,
        information_gaps=profile.information_gaps,
        conflicts=profile.conflicts,
        item_count=len(visible_items),
        relation_count=len([relation for relation in profile.relations if relation.review_status != "rejected"]),
        evidence_count=len(evidence_ids),
        authority_fact_count=sum(item.content_role in AUTHORITY_ROLES for item in visible_items),
    )


def _build_dimension(
    dimension_id: str,
    label: str,
    section_ids: tuple[str, ...],
    items_by_section: dict[str, list[ProfileItem]],
    field_labels: dict[str, str],
    evidence_by_id: dict[str, EvidenceUnit],
) -> CardDimension:
    facts = tuple(
        _to_fact(item, field_labels, evidence_by_id)
        for section_id in section_ids
        for item in items_by_section.get(section_id, ())
    )
    topics = _build_topics(dimension_id, facts)
    return CardDimension(
        dimension_id=dimension_id,
        label=label,
        facts=facts,
        claim_count=sum(fact.role == "enterprise_claim" for fact in facts),
        authority_count=sum(fact.role in AUTHORITY_ROLES for fact in facts),
        topics=topics,
    )


def _build_topics(dimension_id: str, facts: tuple[CardFact, ...]) -> tuple[CardTopic, ...]:
    definitions = TOPIC_DEFINITIONS.get(dimension_id, ())
    topics: list[CardTopic] = []
    used: set[str] = set()
    for topic_id, title, field_prefixes, item_prefixes in definitions:
        selected = tuple(
            fact
            for fact in facts
            if fact.item_id not in used
            and any(fact.field_id.startswith(prefix) for prefix in field_prefixes)
            and (not item_prefixes or any(_topic_item_matches(fact.item_id, prefix) for prefix in item_prefixes))
        )
        if not selected:
            continue
        topics.append(_build_topic(topic_id, title, selected))
        used.update(fact.item_id for fact in selected)
    remaining = tuple(fact for fact in facts if fact.item_id not in used)
    if remaining:
        topics.append(_build_topic(f"{dimension_id}_other", "其他已披露信息", remaining))
    return tuple(topics)


def _topic_item_matches(item_id: str, group: str) -> bool:
    """按关系主体识别客户/供应商，兼容不同批次生成的 item_id 命名。"""
    tail = item_id.split(":", 1)[-1].lower()
    return group in tail


def _build_topic(topic_id: str, title: str, facts: tuple[CardFact, ...]) -> CardTopic:
    return CardTopic(
        topic_id=topic_id,
        title=title,
        summary=_topic_summary(topic_id, facts),
        facts=facts,
        claim_count=sum(fact.role == "enterprise_claim" for fact in facts),
        authority_count=sum(fact.role in AUTHORITY_ROLES for fact in facts),
        records=_topic_records(facts),
    )


def _topic_records(facts: tuple[CardFact, ...]) -> tuple[dict[str, str], ...]:
    grouped: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for fact in facts:
        subject = _subject_label(fact.subject)
        key = fact.field_label
        if fact.reporting_period:
            key = f"{key}（{fact.reporting_period}）"
        if fact.value_scope:
            key = f"{key} · {fact.value_scope}"
        if fact.value not in grouped[subject][key]:
            grouped[subject][key].append(fact.value)
    records: list[dict[str, str]] = []
    for subject, values in grouped.items():
        record = {"主体": subject}
        for key, entries in values.items():
            record[key] = "；".join(entries)
        records.append(record)
    return tuple(records)


def _topic_summary(topic_id: str, facts: tuple[CardFact, ...]) -> str:
    if topic_id.endswith("structure") or topic_id in {"customer_structure", "supplier_structure"}:
        return _structure_summary(facts)
    if topic_id.endswith("transactions"):
        return _transaction_summary(facts)
    if topic_id in {"finance_concentration"}:
        return _trend_summary(facts)
    if topic_id == "risk_matters":
        return _risk_summary(facts)
    if topic_id == "evidence_boundaries":
        return _boundary_summary(facts)
    return _field_summary(facts)


def _structure_summary(facts: tuple[CardFact, ...]) -> str:
    names = _unique_values(
        tuple(fact for fact in facts if fact.field_id == "customer_supplier.counterparty_name"),
        "材料披露的交易对手名称或代称",
    )
    concentration = [fact for fact in facts if "集中度" in fact.field_label]
    parts: list[str] = []
    if names:
        shown = "、".join(names[:8])
        suffix = f"等共 {len(names)} 个" if len(names) > 8 else f"共 {len(names)} 个"
        parts.append(f"材料披露的交易对手包括{shown}，{suffix}主体")
    if concentration:
        parts.append(_trend_summary(tuple(concentration)))
    if not parts:
        return f"该主题已披露 {len(facts)} 条相关事实，具体记录按主体和报告期归并展示。"
    return "；".join(parts) + "。"


def _transaction_summary(facts: tuple[CardFact, ...]) -> str:
    subjects = {_subject_label(fact.subject) for fact in facts if fact.subject and fact.subject != "the_enterprise"}
    periods = {fact.reporting_period for fact in facts if fact.reporting_period}
    amount_facts = [fact for fact in facts if fact.field_id.endswith("transaction_amount")]
    highest = max(amount_facts, key=lambda fact: _number(fact.value), default=None)
    parts = [f"交易金额、占比和交易内容已按 {len(subjects)} 个主体归并"]
    if periods:
        parts.append(f"覆盖 {', '.join(sorted(periods))} 等报告期")
    if highest and highest.subject:
        parts.append(f"已披露金额最高的主体为{_subject_label(highest.subject)}（{highest.value}）")
    return "，".join(parts) + "。"


def _field_summary(facts: tuple[CardFact, ...]) -> str:
    by_field: dict[str, list[CardFact]] = defaultdict(list)
    for fact in facts:
        by_field[fact.field_label].append(fact)
    sentences = []
    for label, entries in by_field.items():
        if _has_scoped_numeric(entries):
            sentences.append(_scoped_metric_summary(tuple(entries)))
            continue
        periods = [entry for entry in entries if entry.reporting_period]
        if periods and len(periods) == len(entries):
            sentences.append(_trend_summary(tuple(entries)))
        else:
            values = _unique_values(tuple(entries), label)
            if values:
                shown = "、".join(_shorten(value, 100) for value in values[:6])
                suffix = "等" if len(values) > 6 else ""
                sentences.append(f"{label}包括{shown}{suffix}")
    if not sentences:
        return f"该主题已披露 {len(facts)} 条相关事实，具体记录按主体归并展示。"
    return "；".join(sentences) + "。"


def _has_scoped_numeric(facts: list[CardFact]) -> bool:
    return any(fact.value_scope and _number(fact.value) is not None for fact in facts)


def _scoped_metric_summary(facts: tuple[CardFact, ...]) -> str:
    label = facts[0].field_label
    by_period: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for fact in facts:
        period = fact.reporting_period or "当前"
        scope = fact.value_scope or "未说明范围"
        if fact.value not in by_period[period][scope]:
            by_period[period][scope].append(fact.value)

    sentences: list[str] = []
    warnings: list[str] = []
    for period in sorted(by_period):
        scoped_values = by_period[period]
        scopes = tuple(scoped_values)
        total_scope = next((scope for scope in scopes if _is_total_scope(scope)), None)
        non_total = tuple(scope for scope in scopes if scope != total_scope)
        top_scopes = tuple(
            scope for scope in non_total
            if not any(_is_child_scope(other, scope) for other in non_total if other != scope)
        )
        if total_scope:
            total = _format_metric_values(label, scoped_values[total_scope])
            sentence = f"{period}，{label}总计{total}"
            if top_scopes:
                sentence += "，其中" + "、".join(
                    _render_scope(scope, scoped_values, non_total, label)
                    for scope in top_scopes
                )
            sentences.append(sentence)
            if len(top_scopes) > 1 and _sum_matches(
                scoped_values[total_scope], [scoped_values[scope] for scope in top_scopes]
            ) is False:
                warnings.append(f"{period}{label}一级分项与总数不一致，需核实")
        else:
            parts = "、".join(
                _render_scope(scope, scoped_values, non_total, label)
                for scope in top_scopes or scopes
            )
            sentences.append(f"{period}，{label}按统计范围为{parts}")

    result = "；".join(sentences)
    if warnings:
        result += "；" + "；".join(warnings)
    return result


def _render_scope(
    scope: str,
    scoped_values: dict[str, list[str]],
    all_scopes: tuple[str, ...],
    label: str,
) -> str:
    values = _format_metric_values(label, scoped_values[scope])
    children = tuple(
        child for child in all_scopes
        if _is_child_scope(scope, child)
        and not any(
            other != scope
            and other != child
            and _is_child_scope(scope, other)
            and _is_child_scope(other, child)
            for other in all_scopes
        )
    )
    result = f"{scope}{values}"
    if children:
        result += "（包括" + "、".join(
            _render_scope(child, scoped_values, all_scopes, label) for child in children
        ) + "）"
    return result


def _is_total_scope(scope: str) -> bool:
    normalized = _normalize_scope(scope)
    return any(token in normalized for token in ("全部", "合计", "总计", "总量"))


def _is_child_scope(parent: str, child: str) -> bool:
    parent_normalized = _normalize_scope(parent)
    child_normalized = _normalize_scope(child)
    return (
        parent_normalized != child_normalized
        and bool(parent_normalized)
        and child_normalized.startswith(parent_normalized)
    )


def _normalize_scope(scope: str) -> str:
    return re.sub(r"[\\s、,，()（）]", "", scope)


def _format_metric_values(label: str, values: list[str]) -> str:
    suffix = "项" if any(token in label for token in ("数量", "专利", "人数")) else ""
    rendered = [value if value.endswith(("%", "元", "万元", "项", "人")) else f"{value}{suffix}" for value in values]
    return "、".join(rendered) if len(rendered) > 1 else (rendered[0] if rendered else "")


def _sum_matches(total_values: list[str], parts: list[list[str]]) -> bool | None:
    if len(total_values) != 1 or any(len(values) != 1 for values in parts):
        return None
    total = _number(total_values[0])
    values = [_number(items[0]) for items in parts]
    if total is None or any(value is None for value in values):
        return None
    return abs(total - sum(value for value in values if value is not None)) < 1e-6


def _risk_summary(facts: tuple[CardFact, ...]) -> str:
    values = _unique_values(facts, "风险事项")
    if not values:
        return "材料中未形成可归纳的风险事项记录。"
    shown = "；".join(_shorten(value, 90) for value in values[:4])
    suffix = "；其余事项见支撑事实" if len(values) > 4 else ""
    return f"材料披露 {len(values)} 项风险或合规事项，主要涉及：{shown}{suffix}。"


def _boundary_summary(facts: tuple[CardFact, ...]) -> str:
    values = _unique_values(facts, "缺失材料")
    if not values:
        return "当前画像未记录额外材料缺口。"
    shown = "；".join(_shorten(value, 90) for value in values[:5])
    suffix = "；其余缺口见支撑事实" if len(values) > 5 else ""
    return f"当前记录 {len(values)} 项材料缺口，主要包括：{shown}{suffix}。"


def _trend_summary(facts: tuple[CardFact, ...]) -> str:
    if not facts:
        return "未披露相关趋势。"
    label = facts[0].field_label
    entries = sorted(
        (fact for fact in facts if fact.reporting_period),
        key=lambda fact: fact.reporting_period or "",
    )
    if not entries:
        values = _unique_values(facts, label)
        return f"{label}包括{'、'.join(values[:6])}。" if values else f"已披露{label}信息。"
    by_period: dict[str, list[str]] = defaultdict(list)
    for fact in entries:
        period = _period_label(fact.reporting_period or "")
        if fact.value not in by_period[period]:
            by_period[period].append(fact.value)
    values = "、".join(
        f"{period}{'为' if len(period_values) == 1 else '包括'}{'、'.join(period_values)}"
        for period, period_values in by_period.items()
    )
    direction = ""
    trend_values = [values[0] for values in by_period.values() if len(values) == 1]
    if len(trend_values) >= 2:
        first = _number(trend_values[0])
        last = _number(trend_values[-1])
        if first is not None and last is not None:
            direction = "，整体上升" if last > first else "，整体下降" if last < first else "，总体持平"
    return f"{label}：{values}{direction}"


def _unique_values(facts: tuple[CardFact, ...], label: str) -> list[str]:
    values: list[str] = []
    for fact in facts:
        if fact.value not in values:
            values.append(fact.value)
    return values


def _subject_label(subject: str | None) -> str:
    if not subject or subject == "the_enterprise":
        return "企业"
    return subject


def _shorten(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[:limit]}…"


def _period_label(period: str) -> str:
    if re.fullmatch(r"\d{4}", period):
        return f"{period}年"
    return period


def _number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\\-]", "", value.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _to_fact(
    item: ProfileItem,
    field_labels: dict[str, str],
    evidence_by_id: dict[str, EvidenceUnit],
) -> CardFact:
    context_parts = []
    if item.subject:
        context_parts.append(f"主体：{item.subject}")
    if item.value_scope:
        context_parts.append(f"范围：{item.value_scope}")
    if item.reporting_period:
        context_parts.append(f"期间：{item.reporting_period}")
    if item.event_date:
        context_parts.append(f"事件日期：{item.event_date}")
    if item.effective_date:
        context_parts.append(f"生效日期：{item.effective_date}")
    evidence = tuple(
        _to_evidence(ref.evidence_unit_id, ref.excerpt, evidence_by_id.get(ref.evidence_unit_id))
        for ref in item.evidence_refs
    )
    return CardFact(
        item_id=item.item_id,
        field_id=item.field_id,
        field_label=field_labels.get(item.field_id, item.field_id),
        value=_format_value(item),
        role=item.content_role,
        role_label=ROLE_LABELS.get(item.content_role, item.content_role),
        status=item.information_status,
        status_label=STATUS_LABELS.get(item.information_status, item.information_status),
        context="；".join(context_parts) or None,
        evidence=evidence,
        subject=item.subject,
        reporting_period=item.reporting_period,
        value_scope=item.value_scope,
    )


def _format_value(item: ProfileItem) -> str:
    value = item.value
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False)
    else:
        rendered = str(value)
    if item.value_type == "ratio" and isinstance(value, (int, float)) and 0 <= value <= 1:
        rendered = f"{value:.2%}"
    if item.unit and not rendered.endswith(item.unit):
        rendered = f"{rendered} {item.unit}"
    return rendered


def _to_evidence(
    evidence_unit_id: str,
    reference_excerpt: str | None,
    unit: EvidenceUnit | None,
) -> CardEvidence:
    if unit is None:
        return CardEvidence(evidence_unit_id, "证据原文暂未加载", "", reference_excerpt or "")
    title = str(unit.metadata.get("title") or unit.metadata.get("source_title") or unit.source_id)
    return CardEvidence(
        evidence_unit_id=evidence_unit_id,
        source_title=title,
        location=_format_location(unit.location),
        excerpt=reference_excerpt or unit.content[:280],
    )


def _format_location(location: Any) -> str:
    if not isinstance(location, dict):
        return ""
    if location.get("kind") == "pdf":
        start = location.get("page_start")
        end = location.get("page_end")
        if start and end:
            return f"PDF 第 {start} 页" if start == end else f"PDF 第 {start}-{end} 页"
    return ""
