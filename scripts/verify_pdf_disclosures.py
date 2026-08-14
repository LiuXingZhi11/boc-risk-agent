"""直接读取原始 PDF 的指定页，复核已入库证据是否来自原文。"""

import json
import sqlite3
from pathlib import Path

from pypdf import PdfReader


DATABASE = Path("data/current_project.db")

# 这些单元分别对应“股权、资金或商业化披露”的典型误判，不调用模型。
CHECKS = {
    "src_ce1e56d9875c94cb:eu_00068": "直接持有发行人",
    "src_ce1e56d9875c94cb:eu_00310": "货币资金",
    "src_b5790478eb18b8fa:eu_00021": "控制公司",
    "src_b5790478eb18b8fa:eu_00292": "货币资金",
    "src_9139a580080bcf27:eu_00096": "合计控制公司",
    "src_8c28d5fe0b5a3392:eu_00030": "机器人本体销售出货量",
}


def _page_numbers(location: dict[str, object]) -> tuple[int, ...]:
    """兼容证据单元的页码位置格式，PDF 页码转为 pypdf 的零基下标。"""
    pages = location.get("pages") or location.get("page_numbers")
    if isinstance(pages, list):
        return tuple(int(page) - 1 for page in pages)
    if location.get("page_start"):
        start = int(location["page_start"])
        end = int(location.get("page_end") or start)
        return tuple(range(start - 1, end))
    page = location.get("page") or location.get("page_number")
    return (int(page) - 1,) if page else ()


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT unit.evidence_unit_id, unit.content, unit.location_json, source.path
        FROM evidence_units AS unit
        JOIN sources AS source ON source.source_id = unit.source_id
        WHERE unit.evidence_unit_id IN ({})
        """.format(",".join("?" for _ in CHECKS)),
        tuple(CHECKS),
    ).fetchall()
    by_id = {row["evidence_unit_id"]: row for row in rows}

    for evidence_id, term in CHECKS.items():
        row = by_id[evidence_id]
        location = json.loads(row["location_json"])
        pages = _page_numbers(location)
        if not pages:
            print(f"{evidence_id}: no page mapping, location={location}", flush=True)
            continue
        reader = PdfReader(row["path"])
        original = "\n".join(reader.pages[page].extract_text() or "" for page in pages)
        # PDF 提取时表格空格可能变化，统一后做包含判断。
        normalized_original = "".join(original.split())
        normalized_term = "".join(term.split())
        print(
            f"{evidence_id}: page={','.join(str(page + 1) for page in pages)}, "
            f"term={term}, found={normalized_term in normalized_original}",
            flush=True,
        )


if __name__ == "__main__":
    main()
