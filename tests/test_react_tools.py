from __future__ import annotations

import json
from dataclasses import replace

from src.evidence.models import EvidenceUnit
from src.profiles.react_models import ReactLimits, ReactToolSession
from src.profiles.react_tools import create_react_tools


class FakeEvidenceService:
    def __init__(self, units: list[EvidenceUnit]) -> None:
        self.units = units
        self.case_ids: list[str] = []
        self.queries: list[str] = []

    def search_evidence(self, query: str, *, case_id: str, top_k: int):
        self.case_ids.append(case_id)
        self.queries.append(query)
        return self.units[:top_k]


def _unit(index: int) -> EvidenceUnit:
    return EvidenceUnit(
        evidence_unit_id=f"src:eu_{index:05d}",
        source_id="src",
        case_id="CASE-1",
        content_type="document_chunk",
        content=f"柔性显示核心技术证据正文 {index}",
        location={"page": index},
        metadata={"title": f"核心技术 {index}", "section_path": ["核心技术"]},
        content_hash=f"hash-{index}",
    )


def _tools(session: ReactToolSession):
    return {item.name: item for item in create_react_tools(session)}


def test_search_evidence_returns_catalog_without_content_and_uses_session_case_id():
    service = FakeEvidenceService([_unit(1), _unit(2)])
    session = ReactToolSession(
        case_id="CASE-1",
        domain="technology_and_ip",
        evidence_service=service,
        limits=ReactLimits(max_catalog_items=1),
    )

    result = json.loads(_tools(session)["search_evidence"].invoke({"query": "柔性显示"}))

    assert len(result["catalog"]) == 1
    assert "content" not in result["catalog"][0]
    assert "证据正文" not in json.dumps(result, ensure_ascii=False)
    assert set(service.case_ids) == {"CASE-1"}
    assert "柔性显示" in service.queries
    assert list(session.discovered_units) == ["src:eu_00001"]


def test_search_evidence_splits_agent_query_into_independent_terms():
    service = FakeEvidenceService([_unit(1)])
    session = ReactToolSession(
        case_id="CASE-1",
        domain="customer_and_supplier",
        evidence_service=service,
        limits=ReactLimits(max_catalog_items=3),
    )

    _tools(session)["search_evidence"].invoke(
        {"query": "主要客户、前五大客户 主要供应商，采购占比"}
    )

    assert {"主要客户", "前五大客户", "主要供应商", "采购占比"} <= set(
        service.queries
    )


def test_read_evidence_only_reads_discovered_ids_and_honors_total_limit():
    session = ReactToolSession(
        case_id="CASE-1",
        domain="technology_and_ip",
        evidence_service=FakeEvidenceService([_unit(1), _unit(2)]),
        limits=ReactLimits(max_catalog_items=2, max_read_units=1),
    )
    tools = _tools(session)
    tools["search_evidence"].invoke({"query": "核心技术"})

    result = json.loads(
        tools["read_evidence"].invoke(
            {"evidence_unit_ids": ["src:eu_00001", "unknown", "src:eu_00002"]}
        )
    )

    assert [item["evidence_unit_id"] for item in result["evidence"]] == ["src:eu_00001"]
    assert result["unknown_evidence_unit_ids"] == ["unknown"]
    assert result["not_read_due_to_limit"] == ["src:eu_00002"]
    assert list(session.read_units) == ["src:eu_00001"]
    assert "证据正文" not in json.dumps(session.trace, ensure_ascii=False, default=str)


def test_agent_exposes_only_search_and_read_tools():
    session = ReactToolSession(
        case_id="CASE-1",
        domain="technology_and_ip",
        evidence_service=FakeEvidenceService([_unit(1)]),
        limits=ReactLimits(),
    )

    assert set(_tools(session)) == {"search_evidence", "read_evidence"}


def test_read_evidence_includes_same_section_continuation_unit():
    units = [
        replace(
            _unit(index),
            metadata={
                "title": "连续表格",
                "section_path": ["连续表格"],
                "chunk_index_in_section": index - 1,
            },
        )
        for index in (1, 2)
    ]

    class ContinuationService(FakeEvidenceService):
        def read_continuation_evidence(self, evidence_unit_id: str, *, radius: int = 1):
            current = next(unit for unit in self.units if unit.evidence_unit_id == evidence_unit_id)
            current_index = current.metadata["chunk_index_in_section"]
            return [
                unit
                for unit in self.units
                if abs(unit.metadata["chunk_index_in_section"] - current_index) <= radius
            ]

    session = ReactToolSession(
        case_id="CASE-1",
        domain="technology_and_ip",
        evidence_service=ContinuationService(units),
        limits=ReactLimits(max_catalog_items=2, max_read_units=2),
    )
    tools = _tools(session)
    tools["search_evidence"].invoke({"query": "连续表格"})
    result = json.loads(tools["read_evidence"].invoke({"evidence_unit_ids": [units[0].evidence_unit_id]}))

    assert [item["evidence_unit_id"] for item in result["evidence"]] == [
        units[0].evidence_unit_id,
        units[1].evidence_unit_id,
    ]
    assert result["continuation_evidence_unit_ids"] == [units[1].evidence_unit_id]
