"""为最终报告的信息不足方向生成只读证据核查台账。"""

import json
import sqlite3
from pathlib import Path


DATABASE = Path("data/current_project.db")
OUTPUT = Path("data/audits/final_v5_information_gap_audit.md")

SEARCH_TERMS = {
    "market_space": ("市场份额", "市场占有率", "分产品收入", "出货量", "客户验证"),
    "competition_landscape": ("市场份额", "前五大客户", "前五大供应商", "客户集中度", "供应商集中度"),
    "technology_strength": ("研发费用", "专利", "核心技术人员", "技术来源", "技术成熟度"),
    "equity_structure": ("持股比例", "控股股东", "实际控制人", "一致行动"),
    "transformation": ("商业化", "批量生产", "量产", "募投项目", "产能利用率"),
    "core_team": ("核心技术人员", "董事", "总经理", "股权激励", "简历"),
    "equity_financing": ("融资", "增资", "投资协议", "估值", "回购"),
    "financial_position": ("货币资金", "现金及现金等价物", "银行借款", "短期借款", "长期借款", "有息负债"),
    "aml_sanctions": ("制裁", "反洗钱", "出口管制", "境外客户", "客户A", "客户B"),
}


def _excerpt(content: str, term: str) -> str:
    position = content.find(term)
    start = max(position - 65, 0)
    end = min(position + len(term) + 145, len(content))
    return " ".join(content[start:end].split())


def _hits(connection: sqlite3.Connection, case_id: str, terms: tuple[str, ...]) -> list[str]:
    result = []
    for term in terms:
        rows = connection.execute(
            """
            SELECT evidence_unit_id, content
            FROM evidence_units
            WHERE case_id = ? AND content LIKE ?
            ORDER BY evidence_unit_id
            LIMIT 2
            """,
            (case_id, f"%{term}%"),
        ).fetchall()
        if rows:
            evidence = "；".join(
                f"{row['evidence_unit_id']}：{_excerpt(row['content'], term)}" for row in rows
            )
            result.append(f"- `{term}`：{evidence}")
    return result


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    assessments = connection.execute(
        """
        SELECT case_id, direction_results_json
        FROM enterprise_overall_assessments
        WHERE assessment_id LIKE ?
        ORDER BY case_id
        """,
        ("%_final_v5",),
    ).fetchall()
    lines = ["# 最终报告信息不足证据核查台账", ""]
    for assessment in assessments:
        case_id = assessment["case_id"]
        results = json.loads(assessment["direction_results_json"])
        insufficient = [
            item
            for item in results
            if item["status"] == "insufficient_information"
            and item["section_id"] != "quantitative_assessment"
        ]
        lines.extend((f"## {case_id}", ""))
        if not insufficient:
            lines.extend(("没有非量化方向的信息不足结论。", ""))
            continue
        for item in insufficient:
            section_id = item["section_id"]
            lines.extend(
                (
                    f"### {section_id}",
                    f"- 原最终结论：{item['summary']}",
                    "- 已提取证据单元检索：",
                )
            )
            evidence_hits = _hits(connection, case_id, SEARCH_TERMS[section_id])
            lines.extend(evidence_hits or ["- 未命中该方向的通用核查词。"])
            lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
