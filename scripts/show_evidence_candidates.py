"""按企业和关键字展示最相关的已提取原文，不调用模型。"""

import sqlite3
import sys


def main() -> None:
    case_id, *terms = sys.argv[1:]
    connection = sqlite3.connect("data/current_project.db")
    connection.row_factory = sqlite3.Row
    for term in terms:
        print(f"\n=== {case_id} / {term} ===")
        rows = connection.execute(
            "SELECT evidence_unit_id, content FROM evidence_units WHERE case_id = ? AND content LIKE ? LIMIT 4",
            (case_id, f"%{term}%"),
        ).fetchall()
        for row in rows:
            content = " ".join(row["content"].split())
            position = content.find(term)
            print(row["evidence_unit_id"])
            print(content[max(position - 130, 0) : position + 330])


if __name__ == "__main__":
    main()
