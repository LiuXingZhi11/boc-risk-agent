"""材料管理工作区的页面服务。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from src.evidence import EvidenceRepository
from src.industry import industry_scope_id
from src.sources import ingest_source


def ingest_uploaded_source(
    *,
    database: str | Path,
    case_id: str,
    upload_root: str | Path,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    target = Path(upload_root) / case_id / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    source, units = ingest_source(target, case_id=case_id)
    repository = EvidenceRepository(database)
    repository.save_source(source)
    repository.save_units(list(units))
    return {"source_id": source.source_id, "path": str(target), "evidence_units": len(units)}


def source_rows(database: str | Path, case_id: str = "") -> list[dict[str, Any]]:
    repository = EvidenceRepository(database)
    sources = repository.list_sources(case_id=case_id or None)
    return [
        {
            "case_id": source.case_id,
            "source_id": source.source_id,
            "type": source.source_type,
            "title": source.title,
            "evidence_units": len(repository.list_units(source_id=source.source_id)),
            "path": source.path,
        }
        for source in sources
    ]


def ingest_industry_source(
    *,
    database: str | Path,
    industry_id: str,
    industry_name: str,
    upload_root: str | Path,
    filename: str,
    content: bytes,
    source_date: str | None = None,
) -> dict[str, Any]:
    scope_id = industry_scope_id(industry_id)
    target = Path(upload_root) / "industry" / industry_id / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    source, units = ingest_source(target, case_id=scope_id, source_date=source_date)
    source = replace(
        source,
        metadata={
            "material_role": "industry_report",
            "industry_id": industry_id,
            "industry_name": industry_name,
        },
    )
    repository = EvidenceRepository(database)
    repository.save_source(source)
    repository.save_units(list(units))
    return {
        "source_id": source.source_id,
        "industry_id": industry_id,
        "path": str(target),
        "evidence_units": len(units),
    }


def industry_source_rows(
    database: str | Path,
    industry_id: str = "",
) -> list[dict[str, Any]]:
    repository = EvidenceRepository(database)
    sources = repository.list_sources(
        case_id=industry_scope_id(industry_id) if industry_id.strip() else None
    )
    return [
        {
            "source_id": source.source_id,
            "industry_id": source.metadata.get("industry_id"),
            "industry_name": source.metadata.get("industry_name"),
            "title": source.title,
            "source_date": source.source_date,
            "evidence_units": len(repository.list_units(source_id=source.source_id)),
            "path": source.path,
        }
        for source in sources
        if source.metadata.get("material_role") == "industry_report"
    ]


__all__ = [
    "industry_source_rows",
    "ingest_industry_source",
    "ingest_uploaded_source",
    "source_rows",
]
