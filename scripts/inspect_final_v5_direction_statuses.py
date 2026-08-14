"""列出最终报告逐条状态，供人工校准通过口径。"""

import json
import sqlite3


connection = sqlite3.connect("data/current_project.db")
rows = connection.execute(
    """
    SELECT case_id, rating_level, recommendation, direction_results_json
    FROM enterprise_overall_assessments
    WHERE assessment_id LIKE '%_final_v5'
    ORDER BY case_id
    """
).fetchall()
for case_id, rating_level, recommendation, payload in rows:
    statuses = json.loads(payload)
    compact = ", ".join(
        f"{item['section_id']}={item['status']}" for item in statuses
    )
    print(f"{case_id} | {rating_level} | {recommendation}")
    print(compact)
    for item in statuses:
        if item["status"] == "conditional_passed":
            print(f"  - {item['section_id']}: {item['summary']}")
