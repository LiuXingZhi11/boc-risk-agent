"""汇总信息不足方向中已检索到的企业披露候选，不调用模型。"""

import json
import sqlite3
from pathlib import Path


DATABASE = Path("data/current_project.db")
KEY_TERMS = {
    "market_space": ("市场份额", "出货量", "客户验证", "分产品收入"),
    "competition_landscape": ("市场份额", "前五大客户", "前五大供应商", "客户集中度"),
    "technology_strength": ("研发费用", "专利", "技术成熟度", "核心技术人员"),
    "equity_structure": ("实际控制人", "控股股东", "持股比例", "一致行动"),
    "transformation": ("批量生产", "商业化", "出货量", "募投项目"),
    "core_team": ("核心技术人员", "董事", "总经理", "股权激励", "简历"),
    "equity_financing": ("融资", "增资", "投资协议", "回购", "估值"),
    "financial_position": ("货币资金", "短期借款", "长期借款", "银行借款", "现金及现金等价物"),
    "aml_sanctions": ("制裁", "反洗钱", "出口管制", "境外客户", "客户A"),
}


def main() -> None:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    assessments = connection.execute(
        "SELECT case_id, direction_results_json FROM enterprise_overall_assessments WHERE assessment_id LIKE ? ORDER BY case_id",
        ("%_final_v5",),
    ).fetchall()
    for assessment in assessments:
        case_id = assessment["case_id"]
        for result in json.loads(assessment["direction_results_json"]):
            section_id = result["section_id"]
            if result["status"] != "insufficient_information" or section_id == "quantitative_assessment":
                continue
            hits = []
            for term in KEY_TERMS[section_id]:
                count = connection.execute(
                    "SELECT COUNT(*) FROM evidence_units WHERE case_id = ? AND content LIKE ?",
                    (case_id, f"%{term}%"),
                ).fetchone()[0]
                if count:
                    hits.append(f"{term}({count})")
            print(f"{case_id}\t{section_id}\t{','.join(hits) or '-'}")


if __name__ == "__main__":
    main()
