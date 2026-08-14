"""行业背景 ReAct 使用的搜索与正文读取工具。"""

from __future__ import annotations

import json
import re

from langchain_core.tools import BaseTool, tool

from src.profiles.evidence_discovery import search_balanced_evidence
from src.profiles.extraction import build_evidence_catalog
from src.profiles.react_models import ReactTraceEntry

from .models import INDUSTRY_DIMENSIONS
from .react_models import IndustryReactSession
from .retrieval import INDUSTRY_SEARCH_TERMS, industry_scope_id


def create_industry_react_tools(
    session: IndustryReactSession,
) -> list[BaseTool]:
    @tool
    def search_industry_evidence(query: str, dimension_ids: list[str]) -> str:
        """搜索当前行业集合的轻量证据目录；不返回正文。"""
        dimensions = tuple(
            dict.fromkeys(
                value for value in dimension_ids if value in INDUSTRY_DIMENSIONS
            )
        )
        if len(dimensions) != 1:
            return _json(
                {
                    "error": "每次搜索必须且只能指定一个固定行业维度。",
                    "catalog": [],
                }
            )
        query_terms = _distinct_search_terms(
            _split_query_terms(query),
            industry_name=session.industry_name,
        )
        if not query_terms:
            return _json(
                {
                    "error": "query 必须包含行业名称以外的具体主题词。",
                    "catalog": [],
                }
            )
        terms = _distinct_search_terms(
            (*query_terms, *INDUSTRY_SEARCH_TERMS[dimensions[0]]),
            industry_name=session.industry_name,
        )
        units = tuple(
            search_balanced_evidence(
                session.evidence_service,
                case_id=industry_scope_id(session.industry_id),
                keywords=terms,
                limit=session.limits.max_catalog_items,
            )
        )
        catalog = build_evidence_catalog(units, keywords=terms)
        for unit, item in zip(units, catalog, strict=True):
            session.discovered_units[unit.evidence_unit_id] = unit
            session.catalog_items[unit.evidence_unit_id] = item
            session.evidence_dimensions.setdefault(
                unit.evidence_unit_id, set()
            ).update(dimensions)
        session.trace.append(
            ReactTraceEntry(
                tool_name="search_industry_evidence",
                input_summary={
                    "query": query,
                    "dimension_ids": list(dimensions),
                    "keyword_count": len(terms),
                    "search_terms": list(terms),
                },
                output_summary={
                    "catalog_count": len(catalog),
                    "evidence_unit_ids": [
                        item["evidence_unit_id"] for item in catalog
                    ],
                },
            )
        )
        return _json({"catalog": catalog})

    @tool
    def read_industry_evidence(evidence_unit_ids: list[str]) -> str:
        """分批读取本轮搜索已经发现的行业 EvidenceUnit 正文。"""
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
        remaining = max(
            session.limits.max_read_units - len(session.read_units), 0
        )
        selected_ids = available_ids[:remaining]
        for evidence_id in selected_ids:
            session.read_units[evidence_id] = session.discovered_units[evidence_id]
        evidence = [
            _evidence_payload(session.read_units[evidence_id])
            for evidence_id in selected_ids
        ]
        session.trace.append(
            ReactTraceEntry(
                tool_name="read_industry_evidence",
                input_summary={"evidence_unit_ids": requested_ids},
                output_summary={
                    "read_evidence_unit_ids": selected_ids,
                    "unknown_evidence_unit_ids": unknown_ids,
                    "content_chars": sum(
                        len(item["content"]) for item in evidence
                    ),
                },
            )
        )
        return _json(
            {
                "evidence": evidence,
                "unknown_evidence_unit_ids": unknown_ids,
                "not_read_due_to_limit": available_ids[remaining:],
            }
        )

    return [search_industry_evidence, read_industry_evidence]


def _evidence_payload(unit) -> dict:
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


def _split_query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            term.strip()
            for term in re.split(r"[\s,，、;；]+", query)
            if term.strip()
        )
    )


def _distinct_search_terms(
    terms: tuple[str, ...],
    *,
    industry_name: str,
) -> tuple[str, ...]:
    normalized_name = _normalize_term(industry_name)
    return tuple(
        term for term in terms if _normalize_term(term) != normalized_name
    )


def _normalize_term(value: str) -> str:
    return "".join(value.split()).casefold()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False)
