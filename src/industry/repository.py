"""行业背景画像 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path

from src.profiles.models import EvidenceReference
from src.storage.database import connect_database, init_database

from .models import IndustryBackgroundProfile, IndustryInsight


class IndustryProfileRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save(self, profile: IndustryBackgroundProfile) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO industry_profiles (
                    profile_id, industry_id, industry_name, source_ids_json,
                    insights_json, information_gaps_json, review_status,
                    generation_method, model, api_meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.industry_id,
                    profile.industry_name,
                    json.dumps(profile.source_ids, ensure_ascii=False),
                    json.dumps(
                        [
                            {
                                **insight.__dict__,
                                "evidence_refs": [
                                    reference.__dict__
                                    for reference in insight.evidence_refs
                                ],
                            }
                            for insight in profile.insights
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(profile.information_gaps, ensure_ascii=False),
                    profile.review_status,
                    profile.generation_method,
                    profile.model,
                    json.dumps(profile.api_meta, ensure_ascii=False),
                ),
            )

    def get(self, profile_id: str) -> IndustryBackgroundProfile | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM industry_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return _profile_from_row(row) if row else None

    def list(
        self,
        *,
        industry_id: str | None = None,
        review_status: str | None = None,
    ) -> list[IndustryBackgroundProfile]:
        query = "SELECT * FROM industry_profiles WHERE 1 = 1"
        params: list[str] = []
        if industry_id is not None:
            query += " AND industry_id = ?"
            params.append(industry_id)
        if review_status is not None:
            query += " AND review_status = ?"
            params.append(review_status)
        query += " ORDER BY profile_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_profile_from_row(row) for row in rows]


def _profile_from_row(row) -> IndustryBackgroundProfile:
    insights = tuple(
        IndustryInsight(
            **{
                **raw,
                "evidence_refs": tuple(
                    EvidenceReference(**reference)
                    for reference in raw["evidence_refs"]
                ),
            }
        )
        for raw in json.loads(row["insights_json"])
    )
    return IndustryBackgroundProfile(
        profile_id=row["profile_id"],
        industry_id=row["industry_id"],
        industry_name=row["industry_name"],
        source_ids=tuple(json.loads(row["source_ids_json"])),
        insights=insights,
        information_gaps=tuple(json.loads(row["information_gaps_json"])),
        review_status=row["review_status"],
        generation_method=row["generation_method"],
        model=row["model"],
        api_meta=json.loads(row["api_meta_json"]),
    )
