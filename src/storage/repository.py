"""案例库 Repository。

本模块只负责 SQLite 持久化，不负责模型调用、检索或工作流编排。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.models import (
    CASE_REVIEW_STATUSES,
    Case,
    CaseBundle,
    Fact,
    ProcessingRun,
    RuleHypothesis,
    TargetEvent,
)

from .database import connect_database, init_database


class RepositoryError(RuntimeError):
    """案例库操作失败。"""


class DuplicateCaseError(RepositoryError):
    """案例 ID 已存在且未请求替换。"""


class CaseNotFoundError(RepositoryError):
    """请求的案例不存在。"""


class CaseRepository:
    """基于 SQLite 的案例库访问对象。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def case_exists(self, case_id: str) -> bool:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
        return row is not None

    def save_case_bundle(self, bundle: CaseBundle, *, replace: bool = False) -> None:
        """以单个事务保存案例包。

        默认拒绝重复 case_id；replace=True 时在同一事务内删除旧案例及其
        子记录后整体写入新案例包。
        """
        case = bundle.case
        with connect_database(self.db_path) as connection:
            try:
                exists = connection.execute(
                    "SELECT 1 FROM cases WHERE case_id = ?", (case.case_id,)
                ).fetchone()
                if exists and not replace:
                    raise DuplicateCaseError(f"案例已存在：{case.case_id}")
                if exists:
                    self._delete_case_rows(connection, case.case_id)

                connection.execute(
                    """
                    INSERT INTO cases (
                        case_id, case_name, raw_text, source, case_type,
                        target_fact_id, target_uncertainty, review_status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.case_id,
                        case.case_name,
                        case.raw_text,
                        case.source,
                        case.case_type,
                        case.target_event.target_fact_id if case.target_event else None,
                        case.target_event.uncertainty if case.target_event else None,
                        case.review_status,
                        case.created_at,
                        case.updated_at,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO facts (
                        fact_id, case_id, statement, source_excerpt, category,
                        assertion_type, event_time, knowledge_status, uncertainty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            fact.fact_id,
                            case.case_id,
                            fact.statement,
                            fact.source_excerpt,
                            fact.category,
                            fact.assertion_type,
                            fact.event_time,
                            fact.knowledge_status,
                            fact.uncertainty,
                        )
                        for fact in bundle.facts
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO rule_hypotheses (
                        rule_id, case_id, rule_hypothesis,
                        supporting_fact_ids_json, uncertainty,
                        generalization_status, review_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            rule.rule_id,
                            case.case_id,
                            rule.rule_hypothesis,
                            json.dumps(list(rule.supporting_fact_ids), ensure_ascii=False),
                            rule.uncertainty,
                            rule.generalization_status,
                            rule.review_status,
                        )
                        for rule in bundle.rule_hypotheses
                    ],
                )
                self._insert_processing_runs(connection, bundle.processing_runs)
            except DuplicateCaseError:
                raise
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
                raise RepositoryError(f"保存案例失败：{exc}") from exc

    def get_case_bundle(self, case_id: str) -> CaseBundle | None:
        with connect_database(self.db_path) as connection:
            case_row = connection.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            if case_row is None:
                return None
            fact_rows = connection.execute(
                "SELECT * FROM facts WHERE case_id = ? ORDER BY rowid", (case_id,)
            ).fetchall()
            rule_rows = connection.execute(
                "SELECT * FROM rule_hypotheses WHERE case_id = ? ORDER BY rowid",
                (case_id,),
            ).fetchall()
            run_rows = connection.execute(
                "SELECT * FROM processing_runs WHERE case_id = ? ORDER BY created_at, run_id",
                (case_id,),
            ).fetchall()

        target_fact_id = case_row["target_fact_id"]
        target_event = (
            TargetEvent(target_fact_id, case_row["target_uncertainty"])
            if target_fact_id
            else None
        )
        case = Case(
            case_id=case_row["case_id"],
            case_name=case_row["case_name"],
            raw_text=case_row["raw_text"],
            source=case_row["source"],
            case_type=case_row["case_type"],
            target_event=target_event,
            review_status=case_row["review_status"],
            created_at=case_row["created_at"],
            updated_at=case_row["updated_at"],
        )
        facts = tuple(
            Fact(
                fact_id=row["fact_id"],
                statement=row["statement"],
                source_excerpt=row["source_excerpt"],
                category=row["category"],
                assertion_type=row["assertion_type"],
                event_time=row["event_time"],
                knowledge_status=row["knowledge_status"],
                uncertainty=row["uncertainty"],
            )
            for row in fact_rows
        )
        rules = tuple(
            RuleHypothesis(
                rule_id=row["rule_id"],
                case_id=row["case_id"],
                rule_hypothesis=row["rule_hypothesis"],
                supporting_fact_ids=tuple(json.loads(row["supporting_fact_ids_json"])),
                uncertainty=row["uncertainty"],
                generalization_status=row["generalization_status"],
                review_status=row["review_status"],
            )
            for row in rule_rows
        )
        runs = tuple(self._processing_run_from_row(row) for row in run_rows)
        return CaseBundle(case=case, facts=facts, rule_hypotheses=rules, processing_runs=runs)

    def list_cases(self, *, review_status: str | None = None) -> list[Case]:
        if review_status is not None and review_status not in CASE_REVIEW_STATUSES:
            raise ValueError(f"review_status 非法：{review_status!r}")
        query = "SELECT * FROM cases"
        params: tuple[str, ...] = ()
        if review_status is not None:
            query += " WHERE review_status = ?"
            params = (review_status,)
        query += " ORDER BY case_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._case_from_row(row) for row in rows]

    def update_case_review_status(self, case_id: str, review_status: str) -> None:
        if review_status not in CASE_REVIEW_STATUSES:
            raise ValueError(f"review_status 非法：{review_status!r}")
        updated_at = datetime.now(timezone.utc).isoformat()
        with connect_database(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE cases SET review_status = ?, updated_at = ? WHERE case_id = ?",
                (review_status, updated_at, case_id),
            )
            if cursor.rowcount == 0:
                raise CaseNotFoundError(f"案例不存在：{case_id}")

    def delete_case(self, case_id: str) -> None:
        with connect_database(self.db_path) as connection:
            if connection.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone() is None:
                raise CaseNotFoundError(f"案例不存在：{case_id}")
            self._delete_case_rows(connection, case_id)

    def save_processing_run(self, run: ProcessingRun) -> None:
        with connect_database(self.db_path) as connection:
            try:
                self._insert_processing_runs(connection, (run,))
            except sqlite3.IntegrityError as exc:
                raise RepositoryError(f"保存运行记录失败：{exc}") from exc

    def get_processing_runs(self, case_id: str) -> list[ProcessingRun]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM processing_runs WHERE case_id = ? ORDER BY created_at, run_id",
                (case_id,),
            ).fetchall()
        return [self._processing_run_from_row(row) for row in rows]

    @staticmethod
    def _delete_case_rows(connection: sqlite3.Connection, case_id: str) -> None:
        connection.execute("DELETE FROM processing_runs WHERE case_id = ?", (case_id,))
        connection.execute("DELETE FROM cases WHERE case_id = ?", (case_id,))

    @staticmethod
    def _insert_processing_runs(
        connection: sqlite3.Connection,
        runs: tuple[ProcessingRun, ...],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO processing_runs (
                run_id, case_id, stage, model, generation_mode,
                reasoning_effort, temperature, prompt_tokens,
                completion_tokens, total_tokens, status, error_message,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run.run_id,
                    run.case_id,
                    run.stage,
                    run.model,
                    run.generation_mode,
                    run.reasoning_effort,
                    run.temperature,
                    run.prompt_tokens,
                    run.completion_tokens,
                    run.total_tokens,
                    run.status,
                    run.error_message,
                    run.created_at,
                )
                for run in runs
            ],
        )

    @staticmethod
    def _case_from_row(row: sqlite3.Row) -> Case:
        target_event = (
            TargetEvent(row["target_fact_id"], row["target_uncertainty"])
            if row["target_fact_id"]
            else None
        )
        return Case(
            case_id=row["case_id"],
            case_name=row["case_name"],
            raw_text=row["raw_text"],
            source=row["source"],
            case_type=row["case_type"],
            target_event=target_event,
            review_status=row["review_status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _processing_run_from_row(row: sqlite3.Row) -> ProcessingRun:
        return ProcessingRun(
            run_id=row["run_id"],
            case_id=row["case_id"],
            stage=row["stage"],
            model=row["model"],
            generation_mode=row["generation_mode"],
            reasoning_effort=row["reasoning_effort"],
            temperature=row["temperature"],
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=row["total_tokens"],
            status=row["status"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )
