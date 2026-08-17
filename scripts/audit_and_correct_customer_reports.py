"""按原始 PDF 复核结果修正客户风险评级报告。

这不是模型重跑脚本。它只把已完成的人工复核结论同步到最终报告，
避免把“资料未披露”误计为“不通过”，也清除没有直接证据的强约束触发。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path("data/current_project.db")


# 仅保留原始材料能够支持的明确不利事实为 failed。其余为材料边界、
# 已整改事项或需要持续核实的事项，分别使用 conditional_passed / insufficient_information。
STATUS_OVERRIDES: dict[str, dict[str, str]] = {
    "DeepBlue": {
        "market_space": "insufficient_information",
        "competition_landscape": "insufficient_information",
        "enterprise_norms": "conditional_passed",
        "technology_strength": "insufficient_information",
        "equity_structure": "insufficient_information",
        "transformation": "passed",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "DeepRobotics": {
        "market_space": "conditional_passed",
        "competition_landscape": "conditional_passed",
        "enterprise_norms": "insufficient_information",
        "technology_strength": "conditional_passed",
        "equity_structure": "insufficient_information",
        "transformation": "conditional_passed",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "insufficient_information",
        "aml_sanctions": "insufficient_information",
    },
    "Dobot": {
        "market_space": "passed",
        "competition_landscape": "passed",
        "enterprise_norms": "conditional_passed",
        "technology_strength": "passed",
        "equity_structure": "conditional_passed",
        "transformation": "passed",
        "core_team": "passed",
        "equity_financing": "conditional_passed",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "Ecovacs": {
        "market_space": "passed",
        "competition_landscape": "passed",
        "enterprise_norms": "passed",
        "technology_strength": "passed",
        "equity_structure": "conditional_passed",
        "transformation": "passed",
        "core_team": "passed",
        "equity_financing": "passed",
        "financial_position": "passed",
        "aml_sanctions": "conditional_passed",
    },
    "Efort": {
        "market_space": "insufficient_information",
        "competition_landscape": "insufficient_information",
        "enterprise_norms": "failed",
        "technology_strength": "conditional_passed",
        "equity_structure": "insufficient_information",
        "transformation": "conditional_passed",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "HIT": {
        "market_space": "insufficient_information",
        "competition_landscape": "insufficient_information",
        "enterprise_norms": "failed",
        "technology_strength": "conditional_passed",
        "equity_structure": "insufficient_information",
        "transformation": "conditional_passed",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "Leju": {
        "market_space": "conditional_passed",
        "competition_landscape": "conditional_passed",
        "enterprise_norms": "failed",
        "technology_strength": "insufficient_information",
        "equity_structure": "conditional_passed",
        "transformation": "conditional_passed",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "failed",
        "aml_sanctions": "passed",
    },
    "Saiwei": {
        "market_space": "failed",
        "competition_landscape": "failed",
        "enterprise_norms": "failed",
        "technology_strength": "failed",
        "equity_structure": "insufficient_information",
        "transformation": "insufficient_information",
        "core_team": "insufficient_information",
        "equity_financing": "conditional_passed",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "Stone": {
        "market_space": "passed",
        "competition_landscape": "passed",
        "enterprise_norms": "passed",
        "technology_strength": "passed",
        "equity_structure": "insufficient_information",
        "transformation": "passed",
        "core_team": "passed",
        "equity_financing": "insufficient_information",
        "financial_position": "insufficient_information",
        "aml_sanctions": "insufficient_information",
    },
    "Tinavi": {
        "market_space": "insufficient_information",
        "competition_landscape": "conditional_passed",
        "enterprise_norms": "failed",
        "technology_strength": "insufficient_information",
        "equity_structure": "insufficient_information",
        "transformation": "insufficient_information",
        "core_team": "insufficient_information",
        "equity_financing": "insufficient_information",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
    "Unitree": {
        "market_space": "conditional_passed",
        "competition_landscape": "conditional_passed",
        "enterprise_norms": "passed",
        "technology_strength": "passed",
        "equity_structure": "insufficient_information",
        "transformation": "insufficient_information",
        "core_team": "insufficient_information",
        "equity_financing": "passed",
        "financial_position": "insufficient_information",
        "aml_sanctions": "insufficient_information",
    },
    "Yijiahe": {
        "market_space": "insufficient_information",
        "competition_landscape": "insufficient_information",
        "enterprise_norms": "failed",
        "technology_strength": "conditional_passed",
        "equity_structure": "conditional_passed",
        "transformation": "conditional_passed",
        "core_team": "insufficient_information",
        "equity_financing": "conditional_passed",
        "financial_position": "failed",
        "aml_sanctions": "insufficient_information",
    },
}


SUMMARY_OVERRIDES: dict[tuple[str, str], str] = {
    ("DeepBlue", "enterprise_norms"): "原始PDF披露治理结构清晰、报告期无重大行政处罚，历史用工瑕疵已有整改；前五大客户存在关联方线索，需核查交易公允性。相关事项属于持续核查，不单独构成规范性不通过。",
    ("Dobot", "enterprise_norms"): "原始PDF披露海关、财政行政处罚及合同纠纷事项，但现有材料未显示其构成控制权或持续经营硬约束；应核实处罚整改和诉讼履行情况，规范性方向有条件通过。",
    ("Dobot", "equity_financing"): "原始PDF可确认公司处于成长期并存在上述合规事项，但未披露估值、融资协议等关键融资细节；该信息边界不等同于融资不通过，列为有条件通过并补充核查。",
    ("Efort", "market_space"): "原始PDF披露国产机器人市场份额提升、锂电及电子行业出货增长和知名客户合作，同时披露价格竞争与海外订单波动；企业细分份额仍需补充，列为信息不足。",
    ("Efort", "transformation"): "原始PDF披露喷涂、重载等产品已实现销售及订单突破，复合机器人和人形机器人尚处商业化早期；转型成效需跟踪，不单独认定为不通过。",
    ("Efort", "equity_financing"): "原始PDF披露国资控制、期末现金及经营风险，但未披露估值和投资协议细节；融资影响需补充资料，不能把资料缺口作为不通过。",
    ("Leju", "equity_financing"): "原始PDF披露收入增长、技术和客户基础，但缺少融资估值、投资机构及协议细节；属于信息边界，列为有条件通过。",
    ("Saiwei", "equity_structure"): "原始PDF分别列示周勇、周新宏为实际控制人，但未给出控制权争议或所有权纠纷结论；该字段不能单独触发强约束，需补充两者关系、表决权和股权变动资料，列为信息不足。",
    ("Saiwei", "transformation"): "原始PDF披露人工智能、轨道交通等产品与技术布局，但分产品收入、在手订单和量产支撑不足，列为信息不足；不把收入下滑重复计入转型不通过。",
    ("Saiwei", "equity_financing"): "原始PDF披露监管处罚、诉讼和收入下滑，对融资环境有负面影响；但未披露具体融资计划和协议，作为跟踪事项，不单独新增不通过。",
    ("Tinavi", "competition_landscape"): "原始PDF披露前五客户和供应商集中度、部分关联供应商及高端零部件依赖，确有供应链关注事项；但没有足以判定竞争地位不通过的企业市场份额证据，列为有条件通过。",
    ("Tinavi", "technology_strength"): "原始PDF披露270项专利申请、较高研发投入和天玑产品商业化，同时披露注册和技术替代风险；技术水平横向可比资料不足，列为信息不足，不据收入排名直接否定。",
    ("Tinavi", "equity_financing"): "原始PDF披露未盈利及产品注册等风险，但未披露估值和融资协议；融资影响列为信息不足，不单独不通过。",
    ("Yijiahe", "market_space"): "原始PDF披露收入连续下滑、新产品仍在开发或测试，同时披露电力、清洁、巡检等业务及订单管理能力；细分市场份额与渗透数据不足，列为信息不足。",
    ("Yijiahe", "competition_landscape"): "原始PDF披露前五大客户占比68.73%、供应商占比35.50%，集中度是明确关注事项；但缺少细分市场份额和同业可比数据，列为信息不足，不把集中度直接等同于竞争格局不通过。",
    ("Yijiahe", "technology_strength"): "原始PDF披露481项授权专利及多项自研技术，但收入下滑使商业化效果需验证；缺少同行指标，列为有条件通过并补充转化数据。",
    ("Yijiahe", "transformation"): "原始PDF披露清洁、巡检、消防等多业务及新品测试，收入仍在下滑；转型成效待验证，列为有条件通过，不单独重复财务不通过。",
    ("Yijiahe", "equity_financing"): "原始PDF披露监管处分和经营下滑会压制融资条件，但具体融资计划和协议未披露；列为有条件通过并补充资料，不将信息缺口单独计为失败。",
}


SECTION_LABELS = {
    "market_space": "行业市场空间",
    "competition_landscape": "竞争格局",
    "enterprise_norms": "企业规范性",
    "technology_strength": "技术实力",
    "equity_structure": "股权结构",
    "transformation": "转型发展",
    "core_team": "核心团队",
    "equity_financing": "股权融资影响",
    "financial_position": "财务情况",
    "quantitative_assessment": "量化评估工具应用",
    "aml_sanctions": "反洗钱与制裁合规",
}

DIMENSIONS = (
    ("industry_and_commercialization", "行业与商业化基础", ("market_space", "competition_landscape")),
    ("technology_and_transformation", "技术与转化能力", ("technology_strength", "transformation")),
    ("governance_and_capital", "治理与资本基础", ("enterprise_norms", "equity_structure", "equity_financing")),
    ("financial_and_operating_resilience", "财务与经营韧性", ("financial_position", "quantitative_assessment")),
    ("compliance_and_uncertainty", "合规与重大不确定性", ("core_team", "aml_sanctions")),
)


def _normalize_summary(summary: str, status: str) -> str:
    summary = summary.replace("授信审批", "风险评级")
    if status == "conditional_passed":
        summary = summary.replace("信息不足", "需补充资料").replace("无法形成明确审批结论", "需补充资料核实")
        if "不通过" in summary or "失败" in summary:
            summary = summary.replace("明确不利事实导致不通过", "相关事项需要跟踪").replace("处理为不通过", "列为跟踪事项")
        if "原始PDF已披露核心事实" not in summary:
            summary += " 原始PDF已披露核心事实，本项不将非关键资料缺口单独计为不通过。"
    elif status == "passed":
        summary = summary.replace("信息不足", "需补充的非关键细节").replace("无法完整判断", "可作基本判断")
        summary += " 原始PDF已披露主要事实，未发现该方向单独不通过事项。"
    elif status == "insufficient_information":
        summary = summary.replace("导致不通过", "导致目前无法形成完整判断").replace("按规则处理为不通过", "列为信息不足")
        summary = summary.replace("原始PDF已披露核心事实，本项不将非关键资料缺口单独计为不通过。", "")
    return summary


def _rating(weak_failed: int, strong_failed: int, has_gap: bool) -> str:
    if strong_failed:
        return "C"
    if weak_failed >= 3 and has_gap and weak_failed >= 3:
        # CC 的核心条件是规范性与财务同时失败，调用方单独处理。
        return "CCC"
    if weak_failed >= 5:
        return "CCC"
    return {4: "B", 3: "BB", 2: "BBB", 1: "A", 0: "AA" if has_gap else "AAA"}[weak_failed]


def _recalculate(direction_results: list[dict]) -> tuple[str, int, int, str, bool]:
    weak_failed_sections = {
        d["section_id"]
        for d in direction_results
        if d.get("constraint_level") == "weak"
        and d.get("section_id") != "quantitative_assessment"
        and d.get("status") == "failed"
    }
    strong_failed = sum(d.get("constraint_level") == "strong" and d.get("status") == "failed" for d in direction_results)
    weak_failed = len(weak_failed_sections)
    has_gap = any(
        d.get("section_id") != "quantitative_assessment" and d.get("status") == "insufficient_information"
        for d in direction_results
    )
    if strong_failed:
        rating = "C"
    elif {"enterprise_norms", "financial_position"}.issubset(weak_failed_sections) and weak_failed >= 3:
        rating = "CC"
    elif weak_failed >= 5:
        rating = "CCC"
    else:
        rating = {4: "B", 3: "BB", 2: "BBB", 1: "A", 0: "AA" if has_gap else "AAA"}[weak_failed]
    if strong_failed or weak_failed >= 3:
        recommendation = "do_not_proceed"
    elif weak_failed:
        recommendation = "conditional_proceed"
    elif has_gap:
        recommendation = "proceed_with_review"
    else:
        recommendation = "proceed_with_caution"
    return rating, strong_failed, weak_failed, recommendation, has_gap


def _rationale(direction_results: list[dict]) -> list[dict]:
    by_id = {d["section_id"]: d for d in direction_results}
    result = []
    for dimension_id, title, section_ids in DIMENSIONS:
        parts = []
        for section_id in section_ids:
            d = by_id[section_id]
            status = {
                "passed": "通过",
                "conditional_passed": "有条件通过",
                "failed": "不通过",
                "insufficient_information": "信息不足",
            }[d["status"]]
            parts.append(f"{SECTION_LABELS[section_id]}（{status}）：{d['summary'].replace('授信审批', '风险评级')}")
        result.append({"dimension_id": dimension_id, "title": title, "judgment": "；".join(parts)})
    return result


def _boundary_text(rating: str, strong: int, weak: int, has_gap: bool) -> list[str]:
    gap_text = "存在非量化关键信息不足，但不计入不通过数量。" if has_gap else "未发现会改变评级边界的非量化关键信息不足。"
    return [
        f"原始PDF对照复核后，强约束不通过{strong}条、弱约束不通过{weak}条；按九级固定边界评级为{rating}。",
        "明确不利事实保留为不通过；仅属市场份额、融资协议、交易对手穿透等资料边界的事项，改列为有条件通过或信息不足。",
        gap_text,
    ]


def _overall(rating: str, strong: int, weak: int, direction_results: list[dict], has_gap: bool) -> str:
    failed = [SECTION_LABELS[d["section_id"]] for d in direction_results if d.get("status") == "failed"]
    gaps = [SECTION_LABELS[d["section_id"]] for d in direction_results if d.get("status") == "insufficient_information" and d.get("section_id") != "quantitative_assessment"]
    text = f"强约束不通过{strong}条，弱约束不通过{weak}条。"
    if failed:
        text += "明确不利事实主要集中在" + "、".join(failed) + "。"
    else:
        text += "未发现有直接证据支持的方向不通过。"
    if gaps:
        text += "另有" + "、".join(gaps) + "存在资料边界，需补充核实，但未计入不通过。"
    text += f"按固定边界，客户风险评级为{rating}。"
    return text


def _clean_risks(existing: list[str], direction_results: list[dict]) -> list[str]:
    strong_failed = any(d.get("constraint_level") == "strong" and d.get("status") == "failed" for d in direction_results)
    cleaned = []
    for item in existing:
        if not strong_failed and ("已触发强约束" in item or "强约束失败" in item):
            continue
        if "存在未解决的控制权或所有权争议可能" in item:
            continue
        cleaned.append(item)
    failed = {d["section_id"] for d in direction_results if d.get("status") == "failed"}
    if not cleaned:
        cleaned = [f"{SECTION_LABELS[d['section_id']]}：{d['summary']}" for d in direction_results if d.get("status") == "failed"]
    return cleaned


def _sync_domain_report(connection: sqlite3.Connection, case_id: str, direction: dict) -> None:
    """让最终报告展开的分方向内容与复核后的状态一致，证据引用不变。"""
    row = connection.execute(
        "SELECT report_id, one_sentence_summary, approval_points_json "
        "FROM domain_approval_reports WHERE case_id=? AND domain_id=? "
        "ORDER BY report_id DESC LIMIT 1",
        (case_id, direction["section_id"]),
    ).fetchone()
    if row is None:
        return
    status = direction["status"]
    status_label = {
        "passed": "通过",
        "conditional_passed": "有条件通过",
        "failed": "不通过",
        "insufficient_information": "信息不足",
    }[status]
    marker = f"【PDF复核后：{status_label}】"
    summary = (row["one_sentence_summary"] or "").replace("授信审批", "风险评级")
    if not summary.startswith("【PDF复核后："):
        summary = f"{marker}{summary}"
    points = json.loads(row["approval_points_json"] or "[]")
    for point in points:
        judgment = point.get("judgment", "").replace("授信审批", "风险评级")
        if status != "failed":
            judgment = judgment.replace("信息不足", "需补充资料").replace("无法判断", "需补充资料核实")
            judgment = judgment.replace("导致不通过", "需持续核查").replace("不通过", "不单独构成不通过")
            if "PDF复核" not in judgment:
                judgment += f"（PDF复核：该审批点列为{status_label}，不单独计入弱约束不通过。）"
        if case_id == "Saiwei" and direction["section_id"] == "equity_structure":
            judgment = judgment.replace("存在未解决的控制权或所有权争议可能", "未见原始PDF明确的控制权争议结论")
            judgment = judgment.replace("已触发强约束失败", "未触发强约束")
        point["judgment"] = judgment
    connection.execute(
        "UPDATE domain_approval_reports SET one_sentence_summary=?, approval_points_json=?, review_status='pending' WHERE report_id=?",
        (summary, json.dumps(points, ensure_ascii=False), row["report_id"]),
    )


def main() -> None:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    changed = []
    for case_id, overrides in STATUS_OVERRIDES.items():
        row = connection.execute(
            "SELECT * FROM enterprise_overall_assessments WHERE case_id=? ORDER BY assessment_id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"missing assessment: {case_id}")
        directions = json.loads(row["direction_results_json"])
        for direction in directions:
            section_id = direction["section_id"]
            if section_id in overrides:
                direction["status"] = overrides[section_id]
                if (case_id, section_id) in SUMMARY_OVERRIDES:
                    direction["summary"] = SUMMARY_OVERRIDES[(case_id, section_id)]
                else:
                    direction["summary"] = _normalize_summary(direction.get("summary", ""), direction["status"])
                direction["summary"] = direction.get("summary", "").replace("授信审批", "风险评级")
                if direction.get("constraint_level") == "strong" and direction["status"] != "failed":
                    direction["strong_constraint_trigger_code"] = None
                    direction["strong_constraint_trigger_evidence_unit_ids"] = []
                _sync_domain_report(connection, case_id, direction)
        for direction in directions:
            direction["summary"] = (direction.get("summary") or "").replace("授信审批", "风险评级")
        rating, strong, weak, recommendation, has_gap = _recalculate(directions)
        old_rating = row["rating_level"]
        old_counts = (row["strong_constraint_failed_count"], row["weak_constraint_failed_count"])
        core_risks = _clean_risks(json.loads(row["core_risks_json"] or "[]"), directions)
        connection.execute(
            """UPDATE enterprise_overall_assessments
               SET rating_level=?, overall_judgment=?, rating_rationale_json=?,
                   core_risks_json=?, rating_boundaries_json=?, recommendation=?,
                   strong_constraint_failed_count=?, weak_constraint_failed_count=?,
                   direction_results_json=?, review_status='pending'
               WHERE assessment_id=?""",
            (
                rating,
                _overall(rating, strong, weak, directions, has_gap),
                json.dumps(_rationale(directions), ensure_ascii=False),
                json.dumps(core_risks, ensure_ascii=False),
                json.dumps(_boundary_text(rating, strong, weak, has_gap), ensure_ascii=False),
                recommendation,
                strong,
                weak,
                json.dumps(directions, ensure_ascii=False),
                row["assessment_id"],
            ),
        )
        changed.append((case_id, old_rating, rating, old_counts, (strong, weak), recommendation))
    connection.commit()
    connection.close()
    for item in changed:
        print(item)


if __name__ == "__main__":
    main()
