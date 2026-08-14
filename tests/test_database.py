import sqlite3

from src.storage.database import connect_database, init_database


def test_init_database_creates_schema_and_enables_foreign_keys(tmp_path) -> None:
    database_path = tmp_path / "nested" / "risk_cases.db"

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
        assert {"cases", "facts", "rule_hypotheses", "processing_runs"} <= tables


def test_init_database_is_idempotent_and_does_not_delete_data(tmp_path) -> None:
    database_path = tmp_path / "risk_cases.db"
    init_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO cases (
                case_id, case_name, raw_text, review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("CASE_001", "测试案例", "案例原文", "pending", "now", "now"),
        )

    init_database(database_path)

    with connect_database(database_path) as connection:
        row = connection.execute(
            "SELECT case_name FROM cases WHERE case_id = ?", ("CASE_001",)
        ).fetchone()
        assert row[0] == "测试案例"


def test_foreign_key_rejects_fact_without_case(tmp_path) -> None:
    database_path = tmp_path / "risk_cases.db"
    init_database(database_path)

    with connect_database(database_path) as connection:
        try:
            connection.execute(
                """
                INSERT INTO facts (
                    fact_id, case_id, statement, source_excerpt, category,
                    assertion_type, knowledge_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "CASE_001_F001",
                    "MISSING_CASE",
                    "事实",
                    "原文",
                    "other",
                    "reported_fact",
                    "time_unknown",
                ),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("缺少父案例时应触发外键约束")
