"""企业画像 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path

from src.storage.database import connect_database, init_database

from .models import (
    CurrentEnterpriseProfile,
    EnterpriseProfile,
    EvidenceReference,
    HistoricalEnterpriseProfile,
    ProfileItem,
    ProfileRelation,
)


class ProfileRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save(self, profile: EnterpriseProfile, *, replace: bool = True) -> None:
        with connect_database(self.db_path) as connection:
            if replace:
                connection.execute("DELETE FROM profiles WHERE profile_id = ?", (profile.profile_id,))
            connection.execute(
                """
                INSERT INTO profiles (
                    profile_id, case_id, enterprise_name, profile_type,
                    ontology_version, information_gaps_json, conflicts_json,
                    review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.profile_id,
                    profile.case_id,
                    profile.enterprise_name,
                    profile.profile_type,
                    profile.ontology_version,
                    json.dumps(list(profile.information_gaps), ensure_ascii=False),
                    json.dumps(list(profile.conflicts), ensure_ascii=False),
                    profile.review_status,
                ),
            )
            connection.executemany(
                """
                INSERT INTO profile_items (
                    profile_id, item_id, section_id, field_id, value_json, value_type,
                    information_status, content_role, evidence_refs_json, subject, value_scope, unit,
                    source_date, reporting_period, event_date, effective_date,
                    review_status, extraction_method, ontology_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        profile.profile_id,
                        item.item_id,
                        item.section_id,
                        item.field_id,
                        json.dumps(item.value, ensure_ascii=False),
                        item.value_type,
                        item.information_status,
                        item.content_role,
                        json.dumps([ref.__dict__ for ref in item.evidence_refs], ensure_ascii=False),
                        item.subject,
                        item.value_scope,
                        item.unit,
                        item.source_date,
                        item.reporting_period,
                        item.event_date,
                        item.effective_date,
                        item.review_status,
                        item.extraction_method,
                        item.ontology_version,
                    )
                    for item in profile.items
                ],
            )
            connection.executemany(
                """
                INSERT INTO profile_relations (
                    profile_id, relation_id, relation_type, source_id, source_type,
                    target_id, target_type, information_status, content_role,
                    evidence_refs_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        profile.profile_id,
                        relation.relation_id,
                        relation.relation_type,
                        relation.source_id,
                        relation.source_type,
                        relation.target_id,
                        relation.target_type,
                        relation.information_status,
                        relation.content_role,
                        json.dumps([ref.__dict__ for ref in relation.evidence_refs], ensure_ascii=False),
                        relation.review_status,
                    )
                    for relation in profile.relations
                ],
            )

    def get(self, profile_id: str) -> EnterpriseProfile | None:
        with connect_database(self.db_path) as connection:
            profile_row = connection.execute(
                "SELECT * FROM profiles WHERE profile_id = ?", (profile_id,)
            ).fetchone()
            if profile_row is None:
                return None
            item_rows = connection.execute(
                "SELECT * FROM profile_items WHERE profile_id = ? ORDER BY item_id", (profile_id,)
            ).fetchall()
            relation_rows = connection.execute(
                "SELECT * FROM profile_relations WHERE profile_id = ? ORDER BY relation_id", (profile_id,)
            ).fetchall()

        items = tuple(
            ProfileItem(
                item_id=row["item_id"],
                section_id=row["section_id"],
                field_id=row["field_id"],
                value=json.loads(row["value_json"]),
                value_type=row["value_type"],
                information_status=row["information_status"],
                content_role=row["content_role"],
                evidence_refs=tuple(EvidenceReference(**ref) for ref in json.loads(row["evidence_refs_json"])),
                subject=row["subject"],
                value_scope=row["value_scope"],
                unit=row["unit"],
                source_date=row["source_date"],
                reporting_period=row["reporting_period"],
                event_date=row["event_date"],
                effective_date=row["effective_date"],
                review_status=row["review_status"],
                extraction_method=row["extraction_method"],
                ontology_version=row["ontology_version"],
            )
            for row in item_rows
        )
        relations = tuple(
            ProfileRelation(
                relation_id=row["relation_id"],
                relation_type=row["relation_type"],
                source_id=row["source_id"],
                source_type=row["source_type"],
                target_id=row["target_id"],
                target_type=row["target_type"],
                information_status=row["information_status"],
                content_role=row["content_role"],
                evidence_refs=tuple(EvidenceReference(**ref) for ref in json.loads(row["evidence_refs_json"])),
                review_status=row["review_status"],
            )
            for row in relation_rows
        )
        profile_kwargs = {
            "profile_id": profile_row["profile_id"],
            "case_id": profile_row["case_id"],
            "enterprise_name": profile_row["enterprise_name"],
            "ontology_version": profile_row["ontology_version"],
            "items": items,
            "relations": relations,
            "information_gaps": tuple(json.loads(profile_row["information_gaps_json"])),
            "conflicts": tuple(json.loads(profile_row["conflicts_json"])),
            "review_status": profile_row["review_status"],
        }
        profile_class = (
            HistoricalEnterpriseProfile
            if profile_row["profile_type"] == "historical"
            else CurrentEnterpriseProfile
        )
        return profile_class(**profile_kwargs)

    def list(
        self,
        *,
        case_id: str | None = None,
        profile_type: str | None = None,
        review_status: str | None = None,
    ) -> list[EnterpriseProfile]:
        if profile_type is not None and profile_type not in {"historical", "current"}:
            raise ValueError("profile_type 必须是 historical 或 current。")
        if review_status is not None and review_status not in {"pending", "approved", "rejected"}:
            raise ValueError("review_status 必须是 pending、approved 或 rejected。")
        query = "SELECT profile_id FROM profiles WHERE 1 = 1"
        params: list[str] = []
        for column, value in (
            ("case_id", case_id),
            ("profile_type", profile_type),
            ("review_status", review_status),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        query += " ORDER BY profile_id"
        with connect_database(self.db_path) as connection:
            profile_ids = [
                row["profile_id"] for row in connection.execute(query, params).fetchall()
            ]
        return [profile for profile_id in profile_ids if (profile := self.get(profile_id)) is not None]
