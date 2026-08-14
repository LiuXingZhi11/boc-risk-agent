"""为当前 final_v5 的每条信息不足生成原始 PDF 复核台账。"""

import json
import sqlite3
from pathlib import Path

from pypdf import PdfReader


DATABASE = Path("data/current_project.db")
OUTPUT = Path("data/audits/final_v5_full_pdf_gap_recheck.md")
SEARCH_TERMS = {
    "market_space": ("市场份额", "市场占有率", "出货量", "订单", "营业收入"),
    "competition_landscape": ("市场份额", "主要客户", "客户集中度", "供应商集中度", "竞争"),
    "transformation": ("商业化", "量产", "订单", "产品收入", "出货量"),
    "aml_sanctions": ("反洗钱", "制裁", "受益所有人", "出口管制", "境外客户"),
}


def _pages(location: dict[str, object]) -> tuple[int, ...]:
    start = location.get("page_start")
    if not start:
        return ()
    end = location.get("page_end") or start
    return tuple(range(int(start) - 1, int(end)))


def _excerpt(content: str, term: str) -> str:
    position = content.find(term)
    start = max(position - 80, 0)
    end = min(position + len(term) + 200, len(content))
    return " ".join(content[start:end].split())


def _direct_pdf_contains(
    path: str,
    location: dict[str, object],
    term: str,
    readers: dict[str, PdfReader],
) -> bool:
    pages = _pages(location)
    if not pages:
        return False
    reader = readers.setdefault(path, PdfReader(path))
    text = "\n".join(reader.pages[page].extract_text() or "" for page in pages)
    return "".join(term.split()) in "".join(text.split())


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    reports = connection.execute(
        """
        SELECT case_id, direction_results_json
        FROM enterprise_overall_assessments
        WHERE assessment_id LIKE '%_final_v5'
        ORDER BY case_id
        """
    ).fetchall()
    readers: dict[str, PdfReader] = {}
    lines = [
        "# 当前最终报告信息不足全量 PDF 复核台账",
        "",
        "本台账逐家列出当前 `final_v5` 的信息不足方向。证据命中后直接读取该证据对应的原 PDF 页；"
        "`原页命中` 只证明词语存在，最终是否足以支撑判断仍须按原文语义人工分类。",
        "",
    ]
    for report in reports:
        case_id = report["case_id"]
        results = json.loads(report["direction_results_json"])
        gaps = [item for item in results if item["status"] == "insufficient_information"]
        lines.extend((f"## {case_id}", ""))
        if not gaps:
            lines.extend(("当前无信息不足方向。", ""))
            continue
        for item in gaps:
            section_id = item["section_id"]
            lines.extend((f"### {section_id}", f"- 当前结论：{item['summary']}"))
            if section_id == "quantitative_assessment":
                lines.extend((
                    "- 分类：方法性边界。试验样本排名不属于企业原始 PDF 是否披露的信息问题，本次不修改。",
                    "",
                ))
                continue
            terms = SEARCH_TERMS.get(section_id, ())
            matches = []
            for term in terms:
                rows = connection.execute(
                    """
                    SELECT unit.evidence_unit_id, unit.content, unit.location_json, source.path
                    FROM evidence_units AS unit
                    JOIN sources AS source ON source.source_id = unit.source_id
                    WHERE unit.case_id = ? AND unit.content LIKE ?
                    ORDER BY unit.evidence_unit_id
                    LIMIT 2
                    """,
                    (case_id, f"%{term}%"),
                ).fetchall()
                for row in rows:
                    location = json.loads(row["location_json"])
                    page_text = ",".join(str(page + 1) for page in _pages(location))
                    direct = _direct_pdf_contains(row["path"], location, term, readers)
                    matches.append(
                        (
                            term,
                            row["evidence_unit_id"],
                            page_text,
                            direct,
                            _excerpt(row["content"], term),
                        )
                    )
            if not matches:
                lines.append("- 检索结果：未命中该方向的主题词；需人工确认原 PDF 是否确无关键披露。")
            else:
                lines.append("- 已入库原文与原 PDF 页命中：")
                for term, evidence_id, pages, direct, excerpt in matches:
                    lines.append(
                        f"  - 主题词“{term}”；证据 `{evidence_id}`；PDF 页 {pages or '未记录'}；"
                        f"原页命中：{'是' if direct else '否'}；摘录：{excerpt}"
                    )
            lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
