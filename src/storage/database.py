"""SQLite 数据库初始化和连接工具。"""

from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect_database(db_path: str | Path) -> sqlite3.Connection:
    """打开数据库连接并启用外键约束。

    调用方负责关闭连接；该函数不自动创建表。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database(db_path: str | Path) -> None:
    """幂等初始化业务数据库，不删除已有数据。"""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect_database(db_path) as connection:
        connection.executescript(schema)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(profile_items)")}
        for name, definition in (
            ("section_id", "TEXT NOT NULL DEFAULT ''"),
            ("extraction_method", "TEXT NOT NULL DEFAULT 'manual'"),
            ("ontology_version", "TEXT NOT NULL DEFAULT '0.8.0'"),
            ("subject", "TEXT"),
            ("value_scope", "TEXT"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE profile_items ADD COLUMN {name} {definition}")
        _ensure_columns(
            connection,
            "comparable_metric_definitions",
            (("value_scope", "TEXT NOT NULL DEFAULT 'not_confirmed'"),),
        )
        _ensure_columns(
            connection,
            "comparable_metric_values",
            (
                ("source_profile_id", "TEXT NOT NULL DEFAULT 'legacy_unlinked'"),
                ("source_item_id", "TEXT NOT NULL DEFAULT 'legacy_unlinked'"),
            ),
        )
        _ensure_columns(
            connection,
            "enterprise_overall_assessments",
            (
                ("recommendation", "TEXT NOT NULL DEFAULT 'conditional_proceed'"),
                ("strong_constraint_failed_count", "INTEGER NOT NULL DEFAULT 0"),
                ("weak_constraint_failed_count", "INTEGER NOT NULL DEFAULT 0"),
                ("direction_results_json", "TEXT NOT NULL DEFAULT '[]'"),
            ),
        )


def _ensure_columns(
    connection: sqlite3.Connection,
    table_name: str,
    required_columns: tuple[tuple[str, str], ...],
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    for name, definition in required_columns:
        if name not in columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")
