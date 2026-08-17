"""按已保存的 11 个方向状态，将现有评级直接迁移为 21 级。"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.approval.guideline_definitions import GUIDELINE_SECTION_DEFINITIONS
from src.approval.models import FinalDirectionResult
from src.approval.overall_assessment import expected_rating_level
from src.storage.database import init_database


DATABASE = PROJECT_ROOT / "data" / "current_project.db"

_LEGACY_RATING_MENTION = re.compile(
    r"(客户风险评级|评级)(为|：|:)(AAA|BBB|CCC|AA|CC|A|B|C|D)(?![A-Z0-9])"
)
def _rewrite_legacy_rating_mentions(value: str, rating_level: str) -> str:
    return _LEGACY_RATING_MENTION.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{rating_level}",
        value,
    )


def migrate(database: Path = DATABASE) -> list[tuple[str, str, str]]:
    init_database(database)
    titles = {item.section_id: item for item in GUIDELINE_SECTION_DEFINITIONS}
    changes: list[tuple[str, str, str]] = []
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT assessment_id, rating_level, direction_results_json, "
            "overall_judgment, rating_rationale_json, core_risks_json, "
            "mitigating_factors_json, rating_boundaries_json, "
            "verification_priorities_json "
            "FROM enterprise_overall_assessments ORDER BY assessment_id"
        ).fetchall()
        for assessment_id, old_level, raw_results, *text_values in rows:
            payloads = json.loads(raw_results)
            results = tuple(
                FinalDirectionResult(
                    section_id=item["section_id"],
                    constraint_level=titles[item["section_id"]].constraint_level,
                    status=item["status"],
                    summary=item["summary"],
                    strong_constraint_trigger_code=item.get(
                        "strong_constraint_trigger_code"
                    ),
                    strong_constraint_trigger_evidence_unit_ids=tuple(
                        item.get("strong_constraint_trigger_evidence_unit_ids", [])
                    ),
                )
                for item in payloads
            )
            new_level = expected_rating_level(results)
            updated_text = tuple(
                _rewrite_legacy_rating_mentions(value, new_level)
                for value in text_values
            )
            if old_level != new_level or updated_text != tuple(text_values):
                connection.execute(
                    "UPDATE enterprise_overall_assessments "
                    "SET rating_level = ?, overall_judgment = ?, "
                    "rating_rationale_json = ?, core_risks_json = ?, "
                    "mitigating_factors_json = ?, rating_boundaries_json = ?, "
                    "verification_priorities_json = ? WHERE assessment_id = ?",
                    (new_level, *updated_text, assessment_id),
                )
                changes.append((assessment_id, old_level, new_level))
    return changes


if __name__ == "__main__":
    for assessment_id, old_level, new_level in migrate():
        print(f"{assessment_id}: {old_level} -> {new_level}")
