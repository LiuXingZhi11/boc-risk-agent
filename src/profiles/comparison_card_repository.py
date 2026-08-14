"""EnterpriseComparisonCard 的 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.database import connect_database, init_database

from .comparison_cards import (
    ComparisonDimension,
    EnterpriseComparisonCard,
    profile_content_hash,
)
from .models import EnterpriseProfile
from .repository import ProfileRepository


class ComparisonCardRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save(self, card: EnterpriseComparisonCard, *, replace: bool = True) -> None:
        with connect_database(self.db_path) as connection:
            if replace:
                connection.execute(
                    "DELETE FROM comparison_cards WHERE card_id = ?", (card.card_id,)
                )
            connection.execute(
                """
                INSERT INTO comparison_cards (
                    card_id, profile_id, case_id, enterprise_name, profile_type,
                    ontology_version, profile_hash, dimensions_json,
                    generation_method, model, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card.card_id,
                    card.profile_id,
                    card.case_id,
                    card.enterprise_name,
                    card.profile_type,
                    card.ontology_version,
                    card.profile_hash,
                    json.dumps(
                        [dimension.__dict__ for dimension in card.dimensions],
                        ensure_ascii=False,
                    ),
                    card.generation_method,
                    card.model,
                    card.review_status,
                ),
            )

    def get(self, card_id: str) -> EnterpriseComparisonCard | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM comparison_cards WHERE card_id = ?", (card_id,)
            ).fetchone()
        return _card_from_row(row) if row is not None else None

    def get_by_profile(self, profile_id: str) -> EnterpriseComparisonCard | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM comparison_cards
                WHERE profile_id = ?
                ORDER BY card_id
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
        return _card_from_row(row) if row is not None else None

    def list(
        self,
        *,
        profile_type: str | None = None,
        review_status: str | None = None,
    ) -> list[EnterpriseComparisonCard]:
        query = "SELECT * FROM comparison_cards WHERE 1 = 1"
        params: list[str] = []
        for column, value in (
            ("profile_type", profile_type),
            ("review_status", review_status),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        query += " ORDER BY card_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_card_from_row(row) for row in rows]

    def list_current(
        self,
        *,
        profile_type: str | None = None,
        review_status: str | None = None,
    ) -> list[EnterpriseComparisonCard]:
        """只返回仍与数据库中正式画像版本一致的比较卡。"""
        profile_repository = ProfileRepository(self.db_path)
        result: list[EnterpriseComparisonCard] = []
        for card in self.list(
            profile_type=profile_type, review_status=review_status
        ):
            profile = profile_repository.get(card.profile_id)
            if profile is not None and self.is_current(card, profile):
                result.append(card)
        return result

    @staticmethod
    def is_current(card: EnterpriseComparisonCard, profile: EnterpriseProfile) -> bool:
        return (
            card.profile_id == profile.profile_id
            and card.ontology_version == profile.ontology_version
            and card.profile_hash == profile_content_hash(profile)
        )


def _card_from_row(row) -> EnterpriseComparisonCard:
    dimensions = tuple(
        ComparisonDimension(
            dimension_id=item["dimension_id"],
            summary=item["summary"],
            comparison_terms=tuple(item["comparison_terms"]),
            structured_features=dict(item.get("structured_features", {})),
            relation_signatures=tuple(item.get("relation_signatures", [])),
            source_item_ids=tuple(item.get("source_item_ids", [])),
            source_relation_ids=tuple(item.get("source_relation_ids", [])),
            evidence_unit_ids=tuple(item.get("evidence_unit_ids", [])),
            information_gaps=tuple(item.get("information_gaps", [])),
        )
        for item in json.loads(row["dimensions_json"])
    )
    return EnterpriseComparisonCard(
        card_id=row["card_id"],
        profile_id=row["profile_id"],
        case_id=row["case_id"],
        enterprise_name=row["enterprise_name"],
        profile_type=row["profile_type"],
        ontology_version=row["ontology_version"],
        profile_hash=row["profile_hash"],
        dimensions=dimensions,
        generation_method=row["generation_method"],
        model=row["model"],
        review_status=row["review_status"],
    )
