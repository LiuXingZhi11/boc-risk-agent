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
        _migrate_rating_levels(connection)
        _migrate_to_21_rating_levels(connection)
        _migrate_optional_cohort_ids(connection)
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


def _migrate_rating_levels(connection: sqlite3.Connection) -> None:
    """将旧 A-D 综合评定表迁移到兼容的中间评级表。"""
    legacy_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
        "AND name = 'enterprise_overall_assessments_legacy'"
    ).fetchone()
    if legacy_exists:
        current_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'enterprise_overall_assessments'"
        ).fetchone()
        current_count = (
            connection.execute(
                "SELECT count(*) FROM enterprise_overall_assessments"
            ).fetchone()[0]
            if current_exists
            else 0
        )
        if current_count:
            connection.execute("DROP TABLE enterprise_overall_assessments_legacy")
        else:
            connection.execute("DROP INDEX IF EXISTS idx_overall_assessments_lookup")
            if current_exists:
                connection.execute("DROP TABLE enterprise_overall_assessments")
            connection.execute(
                "ALTER TABLE enterprise_overall_assessments_legacy "
                "RENAME TO enterprise_overall_assessments"
            )
    row = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'enterprise_overall_assessments'"
    ).fetchone()
    table_sql = (row[0] or "") if row else ""
    if ("'AAA'" in table_sql or "'AAA1'" in table_sql) and "'proceed_with_review'" in table_sql:
        return

    connection.execute("DROP INDEX IF EXISTS idx_overall_assessments_lookup")
    connection.execute(
        "ALTER TABLE enterprise_overall_assessments "
        "RENAME TO enterprise_overall_assessments_legacy"
    )
    connection.executescript(
        """
        CREATE TABLE enterprise_overall_assessments (
            assessment_id TEXT PRIMARY KEY,
            cohort_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            rating_level TEXT NOT NULL CHECK (rating_level IN ('AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'CCC', 'CC', 'C')),
            overall_judgment TEXT NOT NULL,
            rating_rationale_json TEXT NOT NULL,
            core_risks_json TEXT NOT NULL DEFAULT '[]',
            mitigating_factors_json TEXT NOT NULL DEFAULT '[]',
            rating_boundaries_json TEXT NOT NULL DEFAULT '[]',
            verification_priorities_json TEXT NOT NULL DEFAULT '[]',
            source_direction_report_ids_json TEXT NOT NULL,
            source_direction_ranking_sections_json TEXT NOT NULL DEFAULT '[]',
            evidence_refs_json TEXT NOT NULL,
            recommendation TEXT NOT NULL DEFAULT 'conditional_proceed'
                CHECK (recommendation IN ('proceed_with_caution', 'proceed_with_review', 'conditional_proceed', 'do_not_proceed')),
            strong_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
            weak_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
            direction_results_json TEXT NOT NULL DEFAULT '[]',
            is_experimental INTEGER NOT NULL DEFAULT 0 CHECK (is_experimental IN (0, 1)),
            review_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (review_status IN ('pending', 'approved', 'rejected')),
            FOREIGN KEY (cohort_id) REFERENCES peer_cohorts(cohort_id) ON DELETE CASCADE
        );
        """
    )
    connection.execute(
        """
        INSERT INTO enterprise_overall_assessments (
            assessment_id, cohort_id, case_id, rating_level, overall_judgment,
            rating_rationale_json, core_risks_json, mitigating_factors_json,
            rating_boundaries_json, verification_priorities_json,
            source_direction_report_ids_json, source_direction_ranking_sections_json,
            evidence_refs_json, recommendation, strong_constraint_failed_count,
            weak_constraint_failed_count, direction_results_json, is_experimental,
            review_status
        )
        SELECT assessment_id, cohort_id, case_id,
            CASE rating_level WHEN 'A' THEN 'AAA' WHEN 'B' THEN 'AA'
                WHEN 'C' THEN 'CCC' WHEN 'D' THEN 'C' ELSE rating_level END,
            overall_judgment, rating_rationale_json, core_risks_json,
            mitigating_factors_json, rating_boundaries_json, verification_priorities_json,
            source_direction_report_ids_json, source_direction_ranking_sections_json,
            evidence_refs_json, recommendation, strong_constraint_failed_count,
            weak_constraint_failed_count, direction_results_json, is_experimental,
            review_status
        FROM enterprise_overall_assessments_legacy
        """
    )
    connection.execute("DROP TABLE enterprise_overall_assessments_legacy")
    connection.execute(
        "CREATE INDEX idx_overall_assessments_lookup "
        "ON enterprise_overall_assessments(cohort_id, case_id, review_status)"
    )


def _migrate_to_21_rating_levels(connection: sqlite3.Connection) -> None:
    """将旧评级表升级为 21 级，保留报告内容和方向状态。"""
    row = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'table' AND name = 'enterprise_overall_assessments'"
    ).fetchone()
    table_sql = (row[0] or "") if row else ""
    if "'AAA1'" in table_sql and "'D1'" in table_sql:
        return

    connection.execute("DROP INDEX IF EXISTS idx_overall_assessments_lookup")
    connection.execute(
        "ALTER TABLE enterprise_overall_assessments "
        "RENAME TO enterprise_overall_assessments_legacy_9_levels"
    )
    connection.executescript(
        """
        CREATE TABLE enterprise_overall_assessments (
            assessment_id TEXT PRIMARY KEY,
            cohort_id TEXT,
            case_id TEXT NOT NULL,
            rating_level TEXT NOT NULL CHECK (rating_level IN ('AAA1', 'AAA2', 'AAA3', 'AA1', 'AA2', 'AA3', 'A1', 'A2', 'A3', 'BBB1', 'BBB2', 'BBB3', 'BB1', 'BB2', 'BB3', 'B1', 'B2', 'CCC1', 'CC1', 'C1', 'D1')),
            overall_judgment TEXT NOT NULL,
            rating_rationale_json TEXT NOT NULL,
            core_risks_json TEXT NOT NULL DEFAULT '[]',
            mitigating_factors_json TEXT NOT NULL DEFAULT '[]',
            rating_boundaries_json TEXT NOT NULL DEFAULT '[]',
            verification_priorities_json TEXT NOT NULL DEFAULT '[]',
            source_direction_report_ids_json TEXT NOT NULL,
            source_direction_ranking_sections_json TEXT NOT NULL DEFAULT '[]',
            evidence_refs_json TEXT NOT NULL,
            recommendation TEXT NOT NULL DEFAULT 'conditional_proceed'
                CHECK (recommendation IN ('proceed_with_caution', 'proceed_with_review', 'conditional_proceed', 'do_not_proceed')),
            strong_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
            weak_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
            direction_results_json TEXT NOT NULL DEFAULT '[]',
            is_experimental INTEGER NOT NULL DEFAULT 0 CHECK (is_experimental IN (0, 1)),
            review_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (review_status IN ('pending', 'approved', 'rejected'))
        );
        INSERT INTO enterprise_overall_assessments (
            assessment_id, cohort_id, case_id, rating_level, overall_judgment,
            rating_rationale_json, core_risks_json, mitigating_factors_json,
            rating_boundaries_json, verification_priorities_json,
            source_direction_report_ids_json, source_direction_ranking_sections_json,
            evidence_refs_json, recommendation, strong_constraint_failed_count,
            weak_constraint_failed_count, direction_results_json, is_experimental,
            review_status
        )
        SELECT assessment_id, cohort_id, case_id,
            CASE rating_level
                WHEN 'AAA' THEN 'AAA1' WHEN 'AA' THEN 'AA1'
                WHEN 'A' THEN 'A1' WHEN 'BBB' THEN 'BBB1'
                WHEN 'BB' THEN 'BB1' WHEN 'B' THEN 'B1'
                WHEN 'CCC' THEN 'CCC1' WHEN 'CC' THEN 'CC1'
                WHEN 'C' THEN 'C1' WHEN 'D' THEN 'D1'
                ELSE 'AAA1'
            END,
            overall_judgment, rating_rationale_json, core_risks_json,
            mitigating_factors_json, rating_boundaries_json,
            verification_priorities_json, source_direction_report_ids_json,
            source_direction_ranking_sections_json, evidence_refs_json,
            recommendation, strong_constraint_failed_count,
            weak_constraint_failed_count, direction_results_json,
            is_experimental, review_status
        FROM enterprise_overall_assessments_legacy_9_levels;
        DROP TABLE enterprise_overall_assessments_legacy_9_levels;
        CREATE INDEX idx_overall_assessments_lookup
            ON enterprise_overall_assessments(cohort_id, case_id, review_status);
        """
    )


def _migrate_optional_cohort_ids(connection: sqlite3.Connection) -> None:
    """让单企业报告可以不绑定同行样本，同时保留旧报告。"""
    domain_columns = {
        row[1]: row for row in connection.execute("PRAGMA table_info(domain_approval_reports)")
    }
    if domain_columns.get("cohort_id", (None, None, None, 0))[3]:
        connection.execute("DROP INDEX IF EXISTS idx_domain_approval_reports_lookup")
        connection.execute(
            "ALTER TABLE domain_approval_reports RENAME TO domain_approval_reports_legacy_optional"
        )
        connection.executescript(
            """
            CREATE TABLE domain_approval_reports (
                report_id TEXT PRIMARY KEY,
                cohort_id TEXT,
                case_id TEXT NOT NULL,
                domain_id TEXT NOT NULL,
                one_sentence_summary TEXT NOT NULL,
                approval_points_json TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (review_status IN ('pending', 'approved', 'rejected'))
            );
            INSERT INTO domain_approval_reports (
                report_id, cohort_id, case_id, domain_id,
                one_sentence_summary, approval_points_json, review_status
            )
            SELECT report_id, cohort_id, case_id, domain_id,
                one_sentence_summary, approval_points_json, review_status
            FROM domain_approval_reports_legacy_optional;
            DROP TABLE domain_approval_reports_legacy_optional;
            CREATE INDEX idx_domain_approval_reports_lookup
                ON domain_approval_reports(cohort_id, case_id, domain_id);
            """
        )

    assessment_columns = {
        row[1]: row
        for row in connection.execute("PRAGMA table_info(enterprise_overall_assessments)")
    }
    if assessment_columns.get("cohort_id", (None, None, None, 0))[3]:
        connection.execute("DROP INDEX IF EXISTS idx_overall_assessments_lookup")
        connection.execute(
            "ALTER TABLE enterprise_overall_assessments RENAME TO enterprise_overall_assessments_legacy_optional"
        )
        connection.executescript(
            """
            CREATE TABLE enterprise_overall_assessments (
                assessment_id TEXT PRIMARY KEY,
                cohort_id TEXT,
                case_id TEXT NOT NULL,
                rating_level TEXT NOT NULL CHECK (rating_level IN ('AAA1', 'AAA2', 'AAA3', 'AA1', 'AA2', 'AA3', 'A1', 'A2', 'A3', 'BBB1', 'BBB2', 'BBB3', 'BB1', 'BB2', 'BB3', 'B1', 'B2', 'CCC1', 'CC1', 'C1', 'D1')),
                overall_judgment TEXT NOT NULL,
                rating_rationale_json TEXT NOT NULL,
                core_risks_json TEXT NOT NULL DEFAULT '[]',
                mitigating_factors_json TEXT NOT NULL DEFAULT '[]',
                rating_boundaries_json TEXT NOT NULL DEFAULT '[]',
                verification_priorities_json TEXT NOT NULL DEFAULT '[]',
                source_direction_report_ids_json TEXT NOT NULL,
                source_direction_ranking_sections_json TEXT NOT NULL DEFAULT '[]',
                evidence_refs_json TEXT NOT NULL,
                recommendation TEXT NOT NULL DEFAULT 'conditional_proceed'
                    CHECK (recommendation IN ('proceed_with_caution', 'proceed_with_review', 'conditional_proceed', 'do_not_proceed')),
                strong_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
                weak_constraint_failed_count INTEGER NOT NULL DEFAULT 0,
                direction_results_json TEXT NOT NULL DEFAULT '[]',
                is_experimental INTEGER NOT NULL DEFAULT 0 CHECK (is_experimental IN (0, 1)),
                review_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (review_status IN ('pending', 'approved', 'rejected'))
            );
            INSERT INTO enterprise_overall_assessments (
                assessment_id, cohort_id, case_id, rating_level, overall_judgment,
                rating_rationale_json, core_risks_json, mitigating_factors_json,
                rating_boundaries_json, verification_priorities_json,
                source_direction_report_ids_json, source_direction_ranking_sections_json,
                evidence_refs_json, recommendation, strong_constraint_failed_count,
                weak_constraint_failed_count, direction_results_json, is_experimental,
                review_status
            )
            SELECT assessment_id, cohort_id, case_id, rating_level, overall_judgment,
                rating_rationale_json, core_risks_json, mitigating_factors_json,
                rating_boundaries_json, verification_priorities_json,
                source_direction_report_ids_json, source_direction_ranking_sections_json,
                evidence_refs_json, recommendation, strong_constraint_failed_count,
                weak_constraint_failed_count, direction_results_json, is_experimental,
                review_status
            FROM enterprise_overall_assessments_legacy_optional;
            DROP TABLE enterprise_overall_assessments_legacy_optional;
            CREATE INDEX idx_overall_assessments_lookup
                ON enterprise_overall_assessments(cohort_id, case_id, review_status);
            """
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
