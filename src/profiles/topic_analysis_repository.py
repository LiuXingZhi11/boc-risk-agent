"""企业画像主题分析的轻量 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.storage.database import connect_database, init_database


class ProfileTopicAnalysisRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save(
        self,
        *,
        profile_id: str,
        dimension_id: str,
        result: dict[str, Any],
        status: str,
        model: str | None = None,
        api_meta: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        react_trace: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> None:
        if status not in {"completed", "failed", "pending"}:
            raise ValueError("主题分析状态非法。")
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO profile_topic_analyses (
                    profile_id, dimension_id, result_json, status,
                    model, api_meta_json, react_trace_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, dimension_id) DO UPDATE SET
                    result_json = excluded.result_json,
                    status = excluded.status,
                    model = excluded.model,
                    api_meta_json = excluded.api_meta_json,
                    react_trace_json = excluded.react_trace_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    profile_id,
                    dimension_id,
                    json.dumps(result, ensure_ascii=False),
                    status,
                    model,
                    json.dumps(list(api_meta), ensure_ascii=False),
                    json.dumps(list(react_trace), ensure_ascii=False),
                ),
            )

    def get(self, profile_id: str, dimension_id: str) -> dict[str, Any] | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT profile_id, dimension_id, result_json, status,
                       model, api_meta_json, react_trace_json, created_at
                FROM profile_topic_analyses
                WHERE profile_id = ? AND dimension_id = ?
                """,
                (profile_id, dimension_id),
            ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_for_profile(self, profile_id: str) -> list[dict[str, Any]]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT profile_id, dimension_id, result_json, status,
                       model, api_meta_json, react_trace_json, created_at
                FROM profile_topic_analyses
                WHERE profile_id = ?
                ORDER BY dimension_id
                """,
                (profile_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "profile_id": row["profile_id"],
        "dimension_id": row["dimension_id"],
        "result": json.loads(row["result_json"]),
        "status": row["status"],
        "model": row["model"],
        "api_meta": json.loads(row["api_meta_json"]),
        "react_trace": json.loads(row["react_trace_json"]),
        "created_at": row["created_at"],
    }

