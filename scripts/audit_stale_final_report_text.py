"""检查最终报告中与已修正方向状态冲突的旧缺失表述。"""

import sqlite3
from pathlib import Path


DATABASE = Path("data/current_project.db")
SECTION_TERMS = {
    "equity_structure": ("持股比例", "控股股东", "控制权"),
    "financial_position": ("货币资金", "现金余额", "有息负债", "短期借款"),
    "core_team": ("核心技术人员", "团队履历", "股权激励"),
    "equity_financing": ("投资协议", "融资", "估值", "回购"),
    "market_space": ("出货量", "商业化", "市场份额"),
    "competition_landscape": ("客户集中度", "供应商集中度", "市场份额"),
    "technology_strength": ("研发费用", "专利", "技术成熟度"),
    "transformation": ("商业化", "量产", "募投项目"),
}


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT case_id, overall_judgment, core_risks_json, verification_priorities_json,
               rating_rationale_json, direction_results_json
        FROM enterprise_overall_assessments
        WHERE assessment_id LIKE ?
        ORDER BY case_id
        """,
        ("%_final_v5",),
    ).fetchall()
    import json

    for row in rows:
        statuses = {item["section_id"]: item["status"] for item in json.loads(row["direction_results_json"])}
        text = "\n".join(
            [
                row["overall_judgment"],
                *json.loads(row["core_risks_json"]),
                *json.loads(row["verification_priorities_json"]),
                *(item["judgment"] for item in json.loads(row["rating_rationale_json"])),
            ]
        )
        stale = [
            f"{section_id}:{term}"
            for section_id, terms in SECTION_TERMS.items()
            if statuses.get(section_id) == "conditional_passed"
            for term in terms
            if term in text and ("未披露" in text or "缺少" in text or "不足" in text)
        ]
        print(row["case_id"], ",".join(stale) or "clean")


if __name__ == "__main__":
    main()
