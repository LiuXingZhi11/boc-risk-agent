"""SQLite persistence for historical case analyses."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.profiles.comparison_cards import profile_content_hash
from src.profiles.models import EnterpriseProfile, EvidenceReference
from src.storage.database import connect_database, init_database

from .models import CaseAnalysisFactor, CaseOutcome, CaseReviewDirection, HistoricalCaseAnalysis


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _refs(raw: list[dict[str, Any]]) -> tuple[EvidenceReference, ...]:
    return tuple(EvidenceReference(**item) for item in raw)


def _decode_outcomes(raw: str) -> tuple[CaseOutcome, ...]:
    return tuple(CaseOutcome(**{**item, "source_item_ids": tuple(item.get("source_item_ids", [])), "source_relation_ids": tuple(item.get("source_relation_ids", [])), "evidence_refs": _refs(item.get("evidence_refs", []))}) for item in json.loads(raw))


def _decode_factors(raw: str) -> tuple[CaseAnalysisFactor, ...]:
    return tuple(CaseAnalysisFactor(**{**item, "source_item_ids": tuple(item.get("source_item_ids", [])), "source_relation_ids": tuple(item.get("source_relation_ids", [])), "evidence_refs": _refs(item.get("evidence_refs", []))}) for item in json.loads(raw))


def _decode_directions(raw: str) -> tuple[CaseReviewDirection, ...]:
    return tuple(CaseReviewDirection(**{**item, "related_factor_ids": tuple(item.get("related_factor_ids", [])), "verification_questions": tuple(item.get("verification_questions", []))}) for item in json.loads(raw))


class HistoricalCaseAnalysisRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save(self, analysis: HistoricalCaseAnalysis) -> None:
        values = (
            analysis.analysis_id, analysis.profile_id, analysis.case_id, analysis.enterprise_name,
            analysis.ontology_version, analysis.profile_hash, analysis.case_summary, analysis.outcome_status,
            _dump([asdict(item) for item in analysis.outcomes]), _dump([asdict(item) for item in analysis.factors]),
            _dump([asdict(item) for item in analysis.review_directions]), _dump(analysis.applicability_limits),
            _dump(analysis.information_gaps), analysis.generation_method, analysis.model, analysis.review_status,
            _dump(analysis.api_meta), _dump(analysis.debug_data),
        )
        sql = """INSERT INTO historical_case_analyses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(analysis_id) DO UPDATE SET profile_id=excluded.profile_id, case_id=excluded.case_id,
        enterprise_name=excluded.enterprise_name, ontology_version=excluded.ontology_version,
        profile_hash=excluded.profile_hash, case_summary=excluded.case_summary, outcome_status=excluded.outcome_status,
        outcomes_json=excluded.outcomes_json, factors_json=excluded.factors_json,
        review_directions_json=excluded.review_directions_json, applicability_limits_json=excluded.applicability_limits_json,
        information_gaps_json=excluded.information_gaps_json, generation_method=excluded.generation_method,
        model=excluded.model, review_status=excluded.review_status, api_meta_json=excluded.api_meta_json,
        debug_json=excluded.debug_json"""
        with connect_database(self.db_path) as connection:
            connection.execute(sql, values)

    def get(self, analysis_id: str) -> HistoricalCaseAnalysis | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute("SELECT * FROM historical_case_analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, profile_id: str | None = None, review_status: str | None = None) -> list[HistoricalCaseAnalysis]:
        query, params = "SELECT * FROM historical_case_analyses WHERE 1=1", []
        if profile_id is not None:
            query += " AND profile_id = ?"; params.append(profile_id)
        if review_status is not None:
            query += " AND review_status = ?"; params.append(review_status)
        query += " ORDER BY analysis_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    def get_by_profile(self, profile_id: str, *, review_status: str | None = None) -> HistoricalCaseAnalysis | None:
        values = self.list(profile_id=profile_id, review_status=review_status)
        return values[-1] if values else None

    @staticmethod
    def is_current(analysis: HistoricalCaseAnalysis, profile: EnterpriseProfile) -> bool:
        return analysis.profile_hash == profile_content_hash(profile)

    @staticmethod
    def _from_row(row: Any) -> HistoricalCaseAnalysis:
        return HistoricalCaseAnalysis(
            analysis_id=row["analysis_id"], profile_id=row["profile_id"], case_id=row["case_id"],
            enterprise_name=row["enterprise_name"], ontology_version=row["ontology_version"],
            profile_hash=row["profile_hash"], case_summary=row["case_summary"], outcome_status=row["outcome_status"],
            outcomes=_decode_outcomes(row["outcomes_json"]), factors=_decode_factors(row["factors_json"]),
            review_directions=_decode_directions(row["review_directions_json"]),
            applicability_limits=tuple(json.loads(row["applicability_limits_json"])),
            information_gaps=tuple(json.loads(row["information_gaps_json"])),
            generation_method=row["generation_method"], model=row["model"], review_status=row["review_status"],
            api_meta=json.loads(row["api_meta_json"]), debug_data=json.loads(row["debug_json"]),
        )
