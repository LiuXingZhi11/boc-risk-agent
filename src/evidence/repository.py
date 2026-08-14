"""证据单元 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path

from src.sources.models import SourceAsset
from src.storage.database import connect_database, init_database

from .models import EvidenceUnit


class EvidenceRepository:
    """保存数据源和证据单元，不参与模型调用。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save_source(self, source: SourceAsset, *, replace: bool = True) -> None:
        with connect_database(self.db_path) as connection:
            if replace:
                connection.execute("DELETE FROM evidence_units WHERE source_id = ?", (source.source_id,))
                connection.execute("DELETE FROM sources WHERE source_id = ?", (source.source_id,))
            connection.execute(
                """
                INSERT INTO sources (
                    source_id, case_id, source_type, path, title, source_date,
                    content_hash, ingestion_status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.case_id,
                    source.source_type,
                    source.path,
                    source.title,
                    source.source_date,
                    source.content_hash,
                    source.ingestion_status,
                    json.dumps(dict(source.metadata), ensure_ascii=False),
                ),
            )

    def save_units(self, units: list[EvidenceUnit] | tuple[EvidenceUnit, ...]) -> None:
        with connect_database(self.db_path) as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO evidence_units (
                    evidence_unit_id, source_id, case_id, content_type, content,
                    location_json, metadata_json, source_date, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        unit.evidence_unit_id,
                        unit.source_id,
                        unit.case_id,
                        unit.content_type,
                        unit.content,
                        json.dumps(dict(unit.location), ensure_ascii=False),
                        json.dumps(dict(unit.metadata), ensure_ascii=False),
                        unit.source_date,
                        unit.content_hash,
                    )
                    for unit in units
                ],
            )

    def list_sources(self, *, case_id: str | None = None) -> list[SourceAsset]:
        query = "SELECT * FROM sources"
        params: tuple[str, ...] = ()
        if case_id:
            query += " WHERE case_id = ?"
            params = (case_id,)
        query += " ORDER BY source_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            SourceAsset(
                source_id=row["source_id"],
                case_id=row["case_id"],
                source_type=row["source_type"],
                path=row["path"],
                title=row["title"],
                source_date=row["source_date"],
                content_hash=row["content_hash"],
                ingestion_status=row["ingestion_status"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def search(self, query: str, *, case_id: str | None = None, limit: int = 20) -> list[EvidenceUnit]:
        sql = "SELECT * FROM evidence_units WHERE content LIKE ?"
        params: list[object] = [f"%{query}%"]
        if case_id:
            sql += " AND case_id = ?"
            params.append(case_id)
        sql += " ORDER BY evidence_unit_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        units = [_unit_from_row(row) for row in rows]
        normalized_query = query.casefold()
        units.sort(
            key=lambda unit: (-_match_score(unit, normalized_query), unit.evidence_unit_id)
        )
        return units[:limit]

    def get(self, evidence_unit_id: str) -> EvidenceUnit | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM evidence_units WHERE evidence_unit_id = ?",
                (evidence_unit_id,),
            ).fetchone()
        return _unit_from_row(row) if row else None

    def list_units(self, *, source_id: str | None = None, case_id: str | None = None) -> list[EvidenceUnit]:
        query = "SELECT * FROM evidence_units WHERE 1 = 1"
        params: list[str] = []
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if case_id:
            query += " AND case_id = ?"
            params.append(case_id)
        query += " ORDER BY evidence_unit_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_unit_from_row(row) for row in rows]


def _unit_from_row(row) -> EvidenceUnit:
    return EvidenceUnit(
        evidence_unit_id=row["evidence_unit_id"],
        source_id=row["source_id"],
        case_id=row["case_id"],
        content_type=row["content_type"],
        content=row["content"],
        location=json.loads(row["location_json"]),
        metadata=json.loads(row["metadata_json"]),
        source_date=row["source_date"],
        content_hash=row["content_hash"],
    )


def _match_score(unit: EvidenceUnit, query: str) -> int:
    """按命中次数排序，避免 LIKE 查询固定返回文档开头页面。"""
    if not query:
        return 0
    content = unit.content.casefold()
    score = content.count(query) * 100
    if len(unit.content) >= 200:
        score += 1
    if "目录" in unit.content and len(unit.content) < 120:
        score -= 100
    return score
