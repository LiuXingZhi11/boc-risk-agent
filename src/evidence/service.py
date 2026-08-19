"""供企业画像、行业背景和风险评级流程共同使用的证据查询服务。"""

from __future__ import annotations

from typing import Any

from .models import EvidenceUnit
from .repository import EvidenceRepository
from src.sources.models import SourceAsset


class EvidenceQueryService:
    """只提供受控查询，不允许调用方直接执行 SQL。"""

    def __init__(self, repository: EvidenceRepository) -> None:
        self.repository = repository

    def list_sources(self, *, case_id: str) -> list[SourceAsset]:
        return self.repository.list_sources(case_id=case_id)

    def list_source_structure(self, *, source_id: str) -> list[dict[str, Any]]:
        units = self.repository.list_units(source_id=source_id)
        return [
            {
                "evidence_unit_id": unit.evidence_unit_id,
                "location": dict(unit.location),
                "section_path": unit.metadata.get("section_path", []),
                "page": unit.metadata.get("page"),
            }
            for unit in units
        ]

    def list_evidence(self, *, case_id: str) -> list[EvidenceUnit]:
        """按原始顺序列出案例证据，供需要完整局部结构的领域组包。"""
        return self.repository.list_units(case_id=case_id)

    def search_evidence(
        self,
        query: str,
        *,
        case_id: str,
        source_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        top_k: int = 20,
    ) -> list[EvidenceUnit]:
        candidates = self.repository.search(query, case_id=case_id, limit=max(top_k * 3, top_k))
        if source_ids:
            allowed = set(source_ids)
            candidates = [unit for unit in candidates if unit.source_id in allowed]
        if source_types:
            allowed = set(source_types)
            source_types_by_id = {source.source_id: source.source_type for source in self.list_sources(case_id=case_id)}
            candidates = [unit for unit in candidates if source_types_by_id.get(unit.source_id) in allowed]
        return candidates[:top_k]

    def read_evidence(self, evidence_unit_id: str) -> EvidenceUnit | None:
        return self.repository.get(evidence_unit_id)

    def read_related_evidence(self, evidence_unit_id: str, *, radius: int = 1) -> list[EvidenceUnit]:
        unit = self.repository.get(evidence_unit_id)
        if unit is None:
            return []
        units = self.repository.list_units(source_id=unit.source_id)
        position = next(index for index, item in enumerate(units) if item.evidence_unit_id == evidence_unit_id)
        start = max(0, position - radius)
        return units[start : position + radius + 1]

    def read_continuation_evidence(
        self,
        evidence_unit_id: str,
        *,
        radius: int = 1,
    ) -> list[EvidenceUnit]:
        """读取同来源、同章节、相邻切片，避免表格跨切片遗漏。"""
        unit = self.repository.get(evidence_unit_id)
        if unit is None:
            return []
        section_path = tuple(unit.metadata.get("section_path", ()))
        chunk_index = unit.metadata.get("chunk_index_in_section")
        if not section_path or chunk_index is None:
            return []
        try:
            chunk_index = int(chunk_index)
            radius = max(int(radius), 0)
        except (TypeError, ValueError):
            return []
        units = [
            candidate
            for candidate in self.repository.list_units(source_id=unit.source_id)
            if tuple(candidate.metadata.get("section_path", ())) == section_path
            and candidate.metadata.get("chunk_index_in_section") is not None
            and abs(int(candidate.metadata["chunk_index_in_section"]) - chunk_index) <= radius
        ]
        return sorted(
            units,
            key=lambda candidate: int(candidate.metadata["chunk_index_in_section"]),
        )
