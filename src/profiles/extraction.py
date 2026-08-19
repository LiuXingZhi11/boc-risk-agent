"""企业画像候选事实抽取服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from src.evidence.models import EvidenceUnit
from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.ontology.registry import REGISTRY
from src.ontology.schema import CONTENT_ROLES, INFORMATION_STATUSES, RELATION_TYPES
from src.prompts import (
    load_profile_dimension_mapping,
    load_profile_domain_rules,
    load_prompt_section,
)

from .candidates import filter_profile_candidates


@dataclass(frozen=True)
class EvidenceSelectionResult:
    selected_evidence_unit_ids: tuple[str, ...]
    api_meta: dict[str, Any]


_PROFILE_MAPPING = load_profile_dimension_mapping()
_EXTRACTION_DOMAINS = _PROFILE_MAPPING["extraction_domains"]
PROFILE_DOMAINS = tuple(item["id"] for item in _EXTRACTION_DOMAINS)
PROFILE_DOMAIN_FIELDS = {
    item["id"]: frozenset(item["field_ids"])
    for item in _EXTRACTION_DOMAINS
}
PROFILE_DOMAIN_RELATIONS = {
    item["id"]: frozenset(item["relation_types"])
    for item in _EXTRACTION_DOMAINS
}
PROFILE_DOMAIN_PURPOSES = {
    item["id"]: item["purpose"]
    for item in _EXTRACTION_DOMAINS
}


def build_evidence_catalog(
    evidence_units: Iterable[EvidenceUnit],
    *,
    keywords: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """构造给证据发现阶段使用的轻量目录，不包含正文。"""
    keyword_list = tuple(keyword for keyword in keywords if keyword)
    catalog: list[dict[str, Any]] = []
    for unit in evidence_units:
        catalog.append(
            {
                "evidence_unit_id": unit.evidence_unit_id,
                "source_id": unit.source_id,
                "case_id": unit.case_id,
                "source_title": unit.metadata.get("source_title", ""),
                "source_date": unit.source_date,
                "reporting_period_hint": unit.metadata.get("reporting_period")
                or unit.metadata.get("report_period"),
                "title": unit.metadata.get("title", ""),
                "section_path": list(unit.metadata.get("section_path", [])),
                "location": dict(unit.location),
                "content_type": unit.content_type,
                "block_type": unit.metadata.get("block_type"),
                "person_name": unit.metadata.get("person_name"),
                "keyword_hits": [keyword for keyword in keyword_list if keyword in unit.content],
                "content_chars": len(unit.content),
            }
        )
    return catalog


def _catalog_material_context(catalog: list[dict[str, Any]]) -> str:
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in catalog:
        source_id = str(item.get("source_id") or "")
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        materials.append(
            {
                "source_id": source_id,
                "case_id": item.get("case_id"),
                "document_title": item.get("source_title") or item.get("title"),
                "source_date": item.get("source_date"),
                "reporting_period_hint": item.get("reporting_period_hint"),
            }
        )
    return json.dumps(materials, ensure_ascii=False, indent=2)


def _profile_material_context(
    units: tuple[EvidenceUnit, ...], *, domain: str, profile_type: str
) -> str:
    materials: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        if unit.source_id in seen:
            continue
        seen.add(unit.source_id)
        materials.append(
            {
                "source_id": unit.source_id,
                "case_id": unit.case_id,
                "document_title": unit.metadata.get("source_title")
                or unit.metadata.get("document_title")
                or unit.metadata.get("title")
                or unit.source_id,
                "source_date": unit.source_date,
                "reporting_period_hint": unit.metadata.get("reporting_period")
                or unit.metadata.get("report_period"),
            }
        )
    context = {
        "profile_type": profile_type,
        "investigation_domain": domain,
        "case_id": units[0].case_id if units else None,
        "materials": materials,
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


def _evidence_text(unit: EvidenceUnit) -> str:
    header = {
        "source_id": unit.source_id,
        "document_title": unit.metadata.get("source_title")
        or unit.metadata.get("document_title")
        or unit.source_id,
        "section_title": unit.metadata.get("title"),
        "section_path": list(unit.metadata.get("section_path", [])),
        "location": dict(unit.location),
        "source_date": unit.source_date,
    }
    return (
        f"[EvidenceUnit {unit.evidence_unit_id}]\n"
        f"证据元数据：{json.dumps(header, ensure_ascii=False)}\n"
        f"正文：\n{unit.content}"
    )


def build_evidence_selection_messages(
    catalog: list[dict[str, Any]],
    *,
    domain: str,
    max_selected: int,
    guide_text: str = "",
) -> list[dict[str, str]]:
    """构造证据发现提示词；这里禁止携带 EvidenceUnit 正文。"""
    if domain not in PROFILE_DOMAINS:
        raise ValueError(f"调查领域非法：{domain!r}")
    if max_selected <= 0:
        raise ValueError("max_selected 必须是正整数。")
    system = load_prompt_section("data/企业画像数据规则.md", "固定流程证据选择")
    if guide_text:
        system = f"{system}\n\n{guide_text}"
    user = (
        "===== 材料基本信息 =====\n"
        f"{_catalog_material_context(catalog)}\n"
        "文档标题可以提供企业和报告年度线索；source_date 是材料日期，不等同于报告期。\n"
        "===== 材料基本信息结束 =====\n\n"
        f"调查领域：{domain}\n"
        f"本领域目标：{PROFILE_DOMAIN_PURPOSES[domain]}\n"
        f"最多选择：{max_selected} 个 EvidenceUnit\n"
        "输出字段：selected_evidence_unit_ids（字符串数组）。"
        "如果目录中没有足够相关证据，可以少选或输出空数组。\n\n"
        "===== 证据目录开始 =====\n"
        f"{json.dumps(catalog, ensure_ascii=False, indent=2)}\n"
        "===== 证据目录结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def select_evidence_units(
    catalog: list[dict[str, Any]],
    *,
    domain: str,
    config: GenerationConfig,
    max_selected: int = 5,
    guide_text: str = "",
) -> EvidenceSelectionResult:
    """调用模型从目录中选择 EvidenceUnit，并保留本次调用元数据。"""
    result = call_deepseek(
        build_evidence_selection_messages(
            catalog,
            domain=domain,
            max_selected=max_selected,
            guide_text=guide_text,
        ),
        config,
    )
    selected = result.get("selected_evidence_unit_ids", [])
    if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
        raise ValueError("证据选择结果的 selected_evidence_unit_ids 必须是字符串数组。")
    allowed = {item["evidence_unit_id"] for item in catalog}
    if any(item not in allowed for item in selected):
        raise ValueError("证据选择结果包含目录中不存在的 EvidenceUnit ID。")
    return EvidenceSelectionResult(
        selected_evidence_unit_ids=tuple(dict.fromkeys(selected))[:max_selected],
        api_meta=result.get("api_meta") or {},
    )


def build_profile_messages(
    evidence_units: tuple[EvidenceUnit, ...] | list[EvidenceUnit],
    *,
    domain: str,
    profile_type: str,
    guide_text: str = "",
    focus_instructions: str = "",
) -> list[dict[str, str]]:
    if domain not in PROFILE_DOMAINS:
        raise ValueError(f"调查领域非法：{domain!r}")
    if profile_type not in {"historical", "current"}:
        raise ValueError("profile_type 必须是 historical 或 current。")
    units = tuple(evidence_units)
    evidence_text = "\n\n".join(
        _evidence_text(unit) for unit in units
    )
    evidence_id_allowlist = "\n".join(
        f"- {unit.evidence_unit_id}" for unit in units
    )
    allowed_fields = PROFILE_DOMAIN_FIELDS[domain]
    allowed_relations = PROFILE_DOMAIN_RELATIONS[domain]
    field_schema = "\n".join(
        f"- {field.field_id}（{field.label}）: section_id={field.section_id}, value_type={field.value_type}"
        + (", reporting_period_required=true" if field.reporting_period_required else "")
        + (", unit_required=true" if field.currency_required else "")
        + (", value_scope_required=true" if field.value_scope_required else "")
        + (
            f", allowed_values={','.join(field.allowed_values)}"
            if field.allowed_values
            else ""
        )
        for field in REGISTRY.fields.values()
        if field.field_id in allowed_fields
    )
    relation_schema = "\n".join(
        f"- {relation}: source_type={','.join(sources)}; target_type={','.join(targets)}"
        for relation, (sources, targets) in RELATION_TYPES.items()
        if relation in allowed_relations
    )
    system = load_prompt_section("data/企业画像数据规则.md", "结构化事实抽取")
    if guide_text:
        system = f"{system}\n\n{guide_text}"
    domain_rule = load_profile_domain_rules(domain, allowed_fields)
    user = (
        f"{load_prompt_section('data/企业画像数据规则.md', '结构化事实抽取')}\n\n"
        f"画像类型：{profile_type}\n调查领域：{domain}\n"
        f"{domain_rule}\n"
        "输出字段：profile_items、profile_relations、information_gaps、conflicts、unmapped_items。\n"
        "profile_items 每项包含 item_id、subject、section_id、field_id、value、value_type、information_status、content_role、"
        "evidence_unit_ids、evidence_quotes、extraction_method，以及可选的 value_scope、unit、"
        "source_date、reporting_period、event_date、effective_date。\n"
        "subject 表示该属性属于谁，必须使用证据中的明确对象名称；企业整体属性统一使用 the_enterprise。"
        "同一技术、产品、人员或知识产权的各项属性必须使用完全相同的 subject，"
        "不同对象即使属性值相同也要分别保留。主体、field_id、value 和时间等限定条件都相同的事实只输出一次，"
        "如有多条证据，将 evidence_unit_ids 合并到同一画像项。\n"
        "evidence_quotes 是对象数组，每项包含 evidence_unit_id 和 excerpt。每个 evidence_unit_ids 中的 ID"
        " 都必须至少有一条对应摘录；excerpt 必须从对应 EvidenceUnit 连续复制，保留原文用词和标点，"
        "不得拼接句子、补写标点或改写为摘要。"
        "引用多条证据形成汇总时逐条提供摘录，不要用一条摘录代替其他证据，也不要用模型概括代替原文。\n"
        "表格指标同时依赖表头或表前定义与数据行时，分别提供定义摘录和对应数据行摘录；"
        "同一 EvidenceUnit 可以提供多条 evidence_quotes。"
        "多年度表格的每个年度候选都必须重复引用口径定义。\n"
        "每个 profile_item 的 item_id 必须唯一；同一对象的名称、数量、状态等不同属性也必须使用不同 item_id。"
        "每个 profile_relation 的 relation_id 同样必须唯一；关系引用画像项的 item_id 时，必须同时输出"
        "该画像项，不得引用未输出或不满足证据要求的候选项。\n"
        f"information_status 只能使用：{', '.join(sorted(INFORMATION_STATUSES))}。\n"
        f"content_role 只能使用：{', '.join(sorted(CONTENT_ROLES))}。\n"
        "value_type 为 enum 时只能填写证据能够支持的明确状态；不能确定时不要猜测，"
        "应写入 information_gaps。text 和 entity_ref 保留原始业务含义，不强制套用预设词表。\n"
        "value_type 为 integer 时必须输出非负 JSON 整数，不能输出带逗号、单位或说明文字的字符串；"
        "数量口径和截止日期写入 reporting_period。\n"
        "value_type 为 money 时必须输出不带千分位和单位的 JSON 数值，unit 单独保存；"
        "表格单位为万元时保留万元和表中原数值，不得自行换算为元。"
        "value_type 为 ratio 时将百分比转换为 0 至 1 的 JSON 小数。\n"
        "同一对象的同一属性如果仍需核实，不得一边填写 self_owned、commercial 等明确状态，"
        "一边又在 information_gaps 中说明该属性缺少证明；应省略该属性候选，或使用"
        " pending_verification/insufficient_evidence 表达证据状态。\n"
        "enterprise.legal_name 必须是证据中出现的完整法定名称；发行人、本公司、公司、企业等指代词不得作为名称。\n"
        "field_id、section_id、value_type 必须严格从以下 Ontology 字段表中选择，不得自行改名：\n"
        f"{field_schema}\n"
        "relation_type 以及 source_type/target_type 必须严格从以下关系表中选择，不得自行改名：\n"
        f"{relation_schema}\n"
        "evidence_unit_ids 只能逐字复制以下白名单中的 ID；不得使用目录阶段未被选中的 ID，"
        "不得缩写、改写或自行生成 ID：\n"
        f"{evidence_id_allowlist}\n"
        "profile_relations 每项包含 relation_id、relation_type、source_id、source_type、target_id、"
        "target_type、information_status、content_role、evidence_unit_ids、evidence_quotes。\n\n"
        f"information_gaps 只能描述 {domain} 领域，并且每条必须以“{domain}: ”开头；"
        "不得列举其他领域在当前证据中未出现的字段。conflicts 同样只记录当前领域的明确冲突。\n"
        "除 enterprise_and_control 领域外，不得把缺少企业法定名称列为信息缺口；"
        "关系中可使用 the_enterprise 指代当前企业。\n"
        "不要输出企业总结、比较关键词、相似案例判断或 comparison card；"
        "这些内容在画像审核通过后由独立步骤生成。\n\n"
        "===== 材料基本信息 =====\n"
        f"{_profile_material_context(units, domain=domain, profile_type=profile_type)}\n"
        "文档标题中明确出现的企业名称和报告年度可以作为主体与 reporting_period 线索；"
        "source_date 仅表示材料日期，不得自动当作报告期。\n"
        "===== 材料基本信息结束 =====\n\n"
        "===== 证据开始 =====\n"
        f"{evidence_text}\n"
        "===== 证据结束 ====="
    )
    if focus_instructions:
        user += (
            "\n\n===== 本轮补充抽取范围 =====\n"
            f"{focus_instructions}\n"
            "只补充这些失败候选需要的字段或关系；首轮已通过的其他事实不要重复生成。\n"
            "===== 本轮补充抽取范围结束 ====="
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_relation_repair_messages(
    evidence_units: tuple[EvidenceUnit, ...] | list[EvidenceUnit],
    *,
    requests: list[dict[str, Any]],
    domain: str,
) -> list[dict[str, str]]:
    """构造只处理失败关系的窄范围抽取提示词。"""
    evidence_text = "\n\n".join(_evidence_text(unit) for unit in evidence_units)
    system = load_prompt_section("data/企业画像数据规则.md", "关系核验")
    user = (
        f"调查领域：{domain}\n"
        "失败关系请求：\n"
        f"{json.dumps(requests, ensure_ascii=False, indent=2)}\n\n"
        "输出的每条判定必须包含 candidate_id、supported、evidence_unit_ids、evidence_quotes。\n"
        "===== 输入证据开始 =====\n"
        f"{evidence_text}\n"
        "===== 输入证据结束 ====="
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_profile_candidates(
    evidence_units: tuple[EvidenceUnit, ...] | list[EvidenceUnit],
    *,
    domain: str,
    profile_type: str,
    config: GenerationConfig,
    guide_text: str = "",
    focus_instructions: str = "",
) -> dict[str, Any]:
    units = tuple(evidence_units)
    if not units:
        raise ValueError("至少需要一个 EvidenceUnit。")
    batches = _profile_extraction_batches(units, domain=domain)
    batch_results: list[dict[str, Any]] = []
    api_records: list[dict[str, Any]] = []
    for batch_index, (batch_name, batch_units) in enumerate(batches, start=1):
        batch_focus = focus_instructions
        if domain == "customer_and_supplier" and batch_name in {"customer", "supplier"}:
            role_label = "客户" if batch_name == "customer" else "供应商"
            batch_focus = (
                f"本轮只提取{role_label}信息，不要输出另一侧表格的事实。"
                f"所有画像项 item_id 使用 {batch_name}:item_... 前缀，关系使用 {batch_name}:rel_... 前缀。"
                + (f"\n{focus_instructions}" if focus_instructions else "")
            )
        result = call_deepseek(
            build_profile_messages(
                batch_units,
                domain=domain,
                profile_type=profile_type,
                guide_text=guide_text,
                focus_instructions=batch_focus,
            ),
            config,
        )
        clean_result = {
            key: value for key, value in result.items() if key != "api_meta"
        }
        if domain == "customer_and_supplier" and len(batches) > 1:
            clean_result = _normalize_party_batch_ids(clean_result)
        elif len(batches) > 1:
            clean_result = _prefix_batch_candidate_ids(
                clean_result,
                prefix=batch_name,
            )
        batch_results.append(clean_result)
        api_records.append(
            {
                **(result.get("api_meta") or {}),
                "batch_index": batch_index,
                "batch_name": batch_name,
                "evidence_unit_ids": [
                    unit.evidence_unit_id for unit in batch_units
                ],
            }
        )
    clean = _merge_profile_candidate_batches(batch_results)
    evidence_contents = {
        unit.evidence_unit_id: unit.content
        for unit in units
    }
    filtered = filter_domain_candidates(
        clean,
        evidence_unit_ids=evidence_contents,
        domain=domain,
        profile_type=profile_type,
        evidence_contents=evidence_contents,
    )
    filtered["api_meta"] = {
        "stage": "profile_extraction",
        "domain": domain,
        "batch_count": len(batches),
        "batch_calls": api_records,
        "prompt_tokens": sum(
            int(record.get("prompt_tokens") or record.get("input_tokens") or 0)
            for record in api_records
        ),
        "completion_tokens": sum(
            int(record.get("completion_tokens") or record.get("output_tokens") or 0)
            for record in api_records
        ),
        "total_tokens": sum(
            int(record.get("total_tokens") or 0) for record in api_records
        ),
    }
    return filtered


def _normalize_party_batch_ids(data: dict[str, Any]) -> dict[str, Any]:
    """统一客户/供应商候选项的角色前缀，避免同一表格跨批次错挂。"""
    normalized = dict(data)
    item_mapping: dict[str, str] = {}
    for item in data.get("profile_items", []):
        if not isinstance(item, dict) or not isinstance(item.get("item_id"), str):
            continue
        role = _candidate_party_role(item)
        if not role:
            continue
        suffix = _party_item_suffix(item["item_id"])
        item_mapping[item["item_id"]] = f"{role}:{suffix}"
    normalized["profile_items"] = [
        {**item, "item_id": item_mapping.get(item.get("item_id"), item.get("item_id"))}
        if isinstance(item, dict)
        else item
        for item in data.get("profile_items", [])
    ]
    relations: list[Any] = []
    for relation in data.get("profile_relations", []):
        if not isinstance(relation, dict):
            relations.append(relation)
            continue
        role = "customer" if relation.get("relation_type") == "sells_to" else (
            "supplier" if relation.get("relation_type") == "purchases_from" else None
        )
        relation_id = relation.get("relation_id")
        if role and isinstance(relation_id, str):
            relation_id = f"{role}:{_party_item_suffix(relation_id)}"
        relations.append(
            {
                **relation,
                "relation_id": relation_id,
                "source_id": item_mapping.get(relation.get("source_id"), relation.get("source_id")),
                "target_id": item_mapping.get(relation.get("target_id"), relation.get("target_id")),
            }
        )
    normalized["profile_relations"] = relations
    return normalized


def _party_item_suffix(item_id: str) -> str:
    parts = [part for part in item_id.split(":") if part]
    for part in reversed(parts):
        if part.startswith("item_") or part.startswith("rel_"):
            return part
    return parts[-1] if parts else item_id


def _candidate_party_role(candidate: dict[str, Any]) -> str | None:
    item_id = str(candidate.get("item_id") or "")
    lowered = item_id.casefold()
    if "item_supplier" in lowered or ":supplier:" in lowered:
        return "supplier"
    if "item_customer" in lowered or ":customer:" in lowered:
        return "customer"
    scope = " ".join(
        str(candidate.get(key) or "")
        for key in ("value_scope", "subject", "value")
    )
    if any(term in scope for term in ("供应商", "采购", "原材料")):
        return "supplier"
    if any(term in scope for term in ("客户", "销售", "营业收入")):
        return "customer"
    return None


def _profile_extraction_batches(
    units: tuple[EvidenceUnit, ...],
    *,
    domain: str,
) -> tuple[tuple[str, tuple[EvidenceUnit, ...]], ...]:
    if domain != "customer_and_supplier":
        return (("all", units),)
    customer_units = tuple(
        unit
        for unit in units
        if "合计" in unit.content
        and any(
            term in unit.content
            for term in (
                "主要客户",
                "主要销售客户",
                "前五大客户",
                "前五名客户",
                "前五名销售客户",
            )
        )
        and any(
            term in unit.content
            for term in ("销售金额", "销售收入", "销售额")
        )
        and any(
            term in unit.content
            for term in ("收入占比", "占营业收入", "占年度销售总额", "销售总额")
        )
    )
    supplier_units = tuple(
        unit
        for unit in units
        if "合计" in unit.content
        and any(
            term in unit.content
            for term in (
                "主要供应商",
                "前五大供应商",
                "前五名供应商",
                "前五大原材料供应商",
            )
        )
        and any(term in unit.content for term in ("采购金额", "采购额", "采购总额"))
    )
    if customer_units and supplier_units:
        return (
            ("customer", customer_units),
            ("supplier", supplier_units),
        )
    return (("all", units),)


def _prefix_batch_candidate_ids(
    data: dict[str, Any],
    *,
    prefix: str,
) -> dict[str, Any]:
    normalized = dict(data)
    items = data.get("profile_items", [])
    item_ids = {
        item["item_id"]: f"{prefix}:{item['item_id']}"
        for item in items
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    }
    normalized["profile_items"] = [
        {**item, "item_id": item_ids.get(item.get("item_id"), item.get("item_id"))}
        if isinstance(item, dict)
        else item
        for item in items
    ]
    normalized["profile_relations"] = [
        {
            **relation,
            "relation_id": (
                f"{prefix}:{relation['relation_id']}"
                if isinstance(relation.get("relation_id"), str)
                else relation.get("relation_id")
            ),
            "source_id": item_ids.get(
                relation.get("source_id"), relation.get("source_id")
            ),
            "target_id": item_ids.get(
                relation.get("target_id"), relation.get("target_id")
            ),
        }
        if isinstance(relation, dict)
        else relation
        for relation in data.get("profile_relations", [])
    ]
    return normalized


def _merge_profile_candidate_batches(
    batches: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = {
        "profile_items": [],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    for batch in batches:
        for key in merged:
            values = batch.get(key, [])
            if isinstance(values, list):
                merged[key].extend(values)
    for key in ("information_gaps", "conflicts"):
        # The model may return either strings or structured objects.  Use a
        # stable serialized representation for de-duplication so object
        # entries do not raise ``TypeError: unhashable type: 'dict'``.
        seen: set[str] = set()
        unique: list[Any] = []
        for value in merged[key]:
            marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if marker not in seen:
                seen.add(marker)
                unique.append(value)
        merged[key] = unique
    return merged


def filter_domain_candidates(
    data: dict[str, Any],
    *,
    evidence_unit_ids: Iterable[str],
    domain: str,
    profile_type: str,
    evidence_contents: dict[str, str] | None = None,
) -> dict[str, Any]:
    """按调查领域过滤画像候选，并返回逐条拒绝记录。"""
    if domain not in PROFILE_DOMAINS:
        raise ValueError(f"调查领域非法：{domain!r}")
    filtered, rejected = filter_profile_candidates(
        data,
        evidence_unit_ids=evidence_unit_ids,
        profile_type=profile_type,
        allowed_field_ids=PROFILE_DOMAIN_FIELDS[domain],
        allowed_relation_types=PROFILE_DOMAIN_RELATIONS[domain],
        information_gap_prefix=f"{domain}:",
        require_subject=True,
        evidence_contents=evidence_contents,
        require_evidence_quote=evidence_contents is not None,
    )
    expected_roles = {
        "risk_matters": {
            "enterprise_claim",
            "business_record",
            "external_observation",
            "internal_assessment",
            "audited_information",
        },
        "authoritative_findings": {"regulatory_finding", "judicial_finding"},
        "outcome_and_resolution": {"outcome"},
    }.get(domain)
    if expected_roles:
        for key in ("profile_items", "profile_relations"):
            accepted = []
            for candidate in filtered[key]:
                if candidate.get("content_role") in expected_roles:
                    if (
                        domain == "risk_matters"
                        and key == "profile_items"
                        and _is_resolved_legal_case(candidate, evidence_contents)
                    ):
                        rejected.append(
                            {
                                "kind": key,
                                "value": candidate,
                                "reason": "已由法院判决或裁判结案的具体诉讼不属于风险事项，应转入权威认定或结果领域",
                            }
                        )
                        continue
                    accepted.append(candidate)
                else:
                    rejected.append(
                        {"kind": key, "value": candidate, "reason": f"{domain} 的 content_role 不合法"}
                    )
            filtered[key] = accepted
    filtered["rejected_candidates"] = rejected
    return filtered


def _is_resolved_legal_case(
    candidate: dict[str, Any],
    evidence_contents: dict[str, str] | None,
) -> bool:
    """识别已经有裁判结论的具体诉讼，避免混入风险事项。"""
    value = str(candidate.get("value") or "")
    if not any(term in value for term in ("诉", "侵权案", "诉讼")):
        return False
    if evidence_contents is None:
        return False
    context = "\n".join(
        evidence_contents.get(evidence_id, "")
        for evidence_id in candidate.get("evidence_unit_ids", [])
    )
    return any(term in context for term in ("判决书", "驳回上诉", "维持原判", "判决") )
