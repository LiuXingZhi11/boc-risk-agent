import sqlite3

from src.storage.database import connect_database, init_database


def test_init_database_creates_schema_and_enables_foreign_keys(tmp_path) -> None:
    database_path = tmp_path / "nested" / "project.db"

    init_database(database_path)

    with connect_database(database_path) as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert foreign_keys == 1
        assert {"sources", "evidence_units", "profiles", "profile_items"} <= tables


def test_init_database_is_idempotent_and_does_not_delete_data(tmp_path) -> None:
    database_path = tmp_path / "project.db"
    init_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO sources (
                source_id, case_id, source_type, path, title, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("SOURCE_001", "CASE_001", "pdf", "report.pdf", "测试报告", "hash"),
        )

    init_database(database_path)

    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT title FROM sources WHERE source_id = ?", ("SOURCE_001",)
        ).fetchone()
        assert row[0] == "测试报告"


def test_foreign_key_rejects_evidence_without_source(tmp_path) -> None:
    database_path = tmp_path / "project.db"
    init_database(database_path)

    with connect_database(database_path) as connection:
        try:
            connection.execute(
                """
                INSERT INTO evidence_units (
                    evidence_unit_id, source_id, case_id, content_type, content,
                    location_json, metadata_json, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "EVIDENCE_001",
                    "MISSING_SOURCE",
                    "MISSING_CASE",
                    "text",
                    "原文",
                    "{}",
                    "{}",
                    "hash",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("缺少父来源时应触发外键约束")
