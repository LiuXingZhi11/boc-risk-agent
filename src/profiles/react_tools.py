"""绑定单次运行会话的 LangChain 只读调查工具。"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.tools import BaseTool, tool

from src.evidence.models import EvidenceUnit

from .evidence_discovery import search_balanced_evidence
from .extraction import build_evidence_catalog
from .historical_workflow import HISTORICAL_DOMAIN_QUERIES
from .react_models import ReactToolSession, ReactTraceEntry


_RISK_SECTION_QUERIES = (
    "可能面对的风险",
    "风险因素",
    "主要风险",
    "经营风险",
    "技术风险",
)
_RISK_EVENT_QUERIES = ("诉讼", "处罚", "担保", "合规")


def build_react_search_keywords(domain: str, query: str) -> tuple[str, ...]:
    """构造受控 ReAct 的目录检索词，风险章节优先于事件材料。"""
    domain_queries = HISTORICAL_DOMAIN_QUERIES[domain]
    if domain == "risk_matters":
        values = (
            *_RISK_SECTION_QUERIES,
            *_split_query_terms(query),
            *_RISK_EVENT_QUERIES,
            *domain_queries,
        )
    else:
        values = (*_split_query_terms(query), *domain_queries)
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def expand_risk_heading_units(
    session: ReactToolSession,
    units: list[EvidenceUnit],
) -> list[EvidenceUnit]:
    """用风险父标题后的具体子风险替换没有正文的父标题。"""
    if session.domain != "risk_matters":
        return units
    all_units = session.evidence_service.list_evidence(case_id=session.case_id)
    positions = {unit.evidence_unit_id: index for index, unit in enumerate(all_units)}
    expanded: list[EvidenceUnit] = []
    for unit in units:
        if not _is_empty_risk_heading(unit):
            expanded.append(unit)
            continue
        parent_path = tuple(unit.metadata.get("section_path", []))
        children = [
            candidate
            for candidate in all_units[positions[unit.evidence_unit_id] + 1 :]
            if tuple(candidate.metadata.get("section_path", []))[: len(parent_path)] == parent_path
            and len(tuple(candidate.metadata.get("section_path", []))) > len(parent_path)
        ]
        expanded.extend(children or [unit])
    unique: list[EvidenceUnit] = []
    seen_ids: set[str] = set()
    for unit in expanded:
        if unit.evidence_unit_id not in seen_ids:
            unique.append(unit)
            seen_ids.add(unit.evidence_unit_id)
    return unique[: session.limits.max_catalog_items]


def _is_empty_risk_heading(unit: EvidenceUnit) -> bool:
    path = " ".join(str(value) for value in unit.metadata.get("section_path", []))
    return len(unit.content.strip()) <= 80 and any(
        term in path for term in ("风险", "风险因素", "可能面对")
    )


def create_react_tools(session: ReactToolSession) -> list[BaseTool]:
    """创建绑定当前案例和领域的搜索、读取工具。"""

    @tool
    def search_evidence(query: str) -> str:
        """搜索当前案例当前领域的证据目录；需要发现材料时调用，不返回正文。"""
        keywords = build_react_search_keywords(session.domain, query)
        units = search_balanced_evidence(
            session.evidence_service,
            case_id=session.case_id,
            keywords=keywords,
            limit=session.limits.max_catalog_items,
        )
        units = expand_risk_heading_units(session, units)
        catalog = build_evidence_catalog(units, keywords=keywords)
        for unit, item in zip(units, catalog, strict=True):
            session.discovered_units[unit.evidence_unit_id] = unit
            session.catalog_items[unit.evidence_unit_id] = item
        session.trace.append(
            ReactTraceEntry(
                tool_name="search_evidence",
                input_summary={
                    "query": query,
                    "keyword_count": len(keywords),
                    "phase": session.phase,
                },
                output_summary={
                    "catalog_count": len(catalog),
                    "evidence_unit_ids": [item["evidence_unit_id"] for item in catalog],
                },
            )
        )
        return _json({"catalog": catalog})

    @tool
    def read_evidence(evidence_unit_ids: list[str]) -> str:
        """读取此前搜索发现的 EvidenceUnit；形成候选前先用它取得正文。"""
        requested_ids = list(dict.fromkeys(evidence_unit_ids))
        unknown_ids = [
            evidence_id
            for evidence_id in requested_ids
            if evidence_id not in session.discovered_units
        ]
        available_ids = [
            evidence_id
            for evidence_id in requested_ids
            if evidence_id in session.discovered_units
            and evidence_id not in session.read_units
        ]
        remaining = max(session.limits.max_read_units - len(session.read_units), 0)
        selected_ids = available_ids[:remaining]
        continuation_ids: list[str] = []
        if hasattr(session.evidence_service, "read_continuation_evidence"):
            for evidence_id in tuple(selected_ids):
                if len(selected_ids) >= remaining:
                    break
                related_units = session.evidence_service.read_continuation_evidence(
                    evidence_id,
                    radius=1,
                )
                for related in related_units:
                    related_id = related.evidence_unit_id
                    if related_id in session.read_units or related_id in selected_ids:
                        continue
                    session.discovered_units[related_id] = related
                    session.catalog_items[related_id] = build_evidence_catalog([related])[0]
                    selected_ids.append(related_id)
                    continuation_ids.append(related_id)
                    if len(selected_ids) >= remaining:
                        break
        for evidence_id in selected_ids:
            session.read_units[evidence_id] = session.discovered_units[evidence_id]
        evidence = [_evidence_payload(session.read_units[evidence_id]) for evidence_id in selected_ids]
        session.trace.append(
            ReactTraceEntry(
                tool_name="read_evidence",
                input_summary={
                    "evidence_unit_ids": requested_ids,
                    "phase": session.phase,
                },
                output_summary={
                    "read_evidence_unit_ids": selected_ids,
                    "continuation_evidence_unit_ids": continuation_ids,
                    "unknown_evidence_unit_ids": unknown_ids,
                    "content_chars": sum(len(item["content"]) for item in evidence),
                },
            )
        )
        return _json(
            {
                "evidence": evidence,
                "unknown_evidence_unit_ids": unknown_ids,
                "not_read_due_to_limit": available_ids[remaining:],
                "continuation_evidence_unit_ids": continuation_ids,
            }
        )

    return [search_evidence, read_evidence]


def _evidence_payload(unit: Any) -> dict[str, Any]:
    return {
        "evidence_unit_id": unit.evidence_unit_id,
        "source_id": unit.source_id,
        "source_title": unit.metadata.get("source_title", ""),
        "source_date": unit.source_date,
        "title": unit.metadata.get("title", ""),
        "section_path": list(unit.metadata.get("section_path", [])),
        "location": dict(unit.location),
        "content": unit.content,
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _split_query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        term.strip()
        for term in re.split(r"[\s,，、;；]+", query)
        if term.strip()
    )
