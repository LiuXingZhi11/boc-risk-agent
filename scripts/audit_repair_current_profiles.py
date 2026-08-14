"""依据当前 PDF 证据修正正式企业画像中的确定性漏项和口径错误。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DB = Path("data/current_project.db")


def ref(evidence_unit_id: str, excerpt: str) -> str:
    return json.dumps(
        [{"evidence_unit_id": evidence_unit_id, "excerpt": excerpt}],
        ensure_ascii=False,
    )


def add_item(
    connection: sqlite3.Connection,
    profile_id: str,
    item_id: str,
    section_id: str,
    field_id: str,
    value: Any,
    value_type: str,
    evidence_unit_id: str,
    excerpt: str,
    *,
    value_scope: str | None = None,
    unit: str | None = None,
    reporting_period: str | None = None,
    subject: str | None = None,
) -> None:
    exists = connection.execute(
        "SELECT 1 FROM profile_items WHERE profile_id = ? AND item_id = ?",
        (profile_id, item_id),
    ).fetchone()
    if exists:
        return
    connection.execute(
        """
        INSERT INTO profile_items (
            profile_id, item_id, section_id, field_id, value_json, value_type,
            information_status, content_role, evidence_refs_json, subject, value_scope,
            unit, source_date, reporting_period, event_date, effective_date,
            review_status, extraction_method, ontology_version
        ) VALUES (?, ?, ?, ?, ?, ?, 'confirmed', 'audited_information', ?, ?, ?, ?, NULL, ?, NULL, NULL,
                  'accepted', 'manual', '0.8.0')
        """,
        (
            profile_id,
            item_id,
            section_id,
            field_id,
            json.dumps(value, ensure_ascii=False),
            value_type,
            ref(evidence_unit_id, excerpt),
            subject,
            value_scope,
            unit,
            reporting_period,
        ),
    )


def profile_id(connection: sqlite3.Connection, case_id: str) -> str:
    return connection.execute(
        "SELECT profile_id FROM profiles WHERE case_id = ?", (case_id,)
    ).fetchone()[0]


def add_finance(
    connection: sqlite3.Connection,
    case_id: str,
    values: list[tuple[str, str, float, str, str, str, str]],
) -> None:
    pid = profile_id(connection, case_id)
    for item_id, field, value, period, unit, evidence_id, excerpt in values:
        add_item(
            connection,
            pid,
            item_id,
            "finance_capital",
            field,
            value,
            "ratio" if field.endswith("ratio") else "money",
            evidence_id,
            excerpt,
            unit=None if field.endswith("ratio") else unit,
            reporting_period=period,
        )


def add_ip(
    connection: sqlite3.Connection,
    case_id: str,
    item_id: str,
    field: str,
    value: Any,
    value_type: str,
    scope: str,
    evidence_id: str,
    excerpt: str,
    *,
    period: str = "2025-12-31",
) -> None:
    add_item(
        connection,
        profile_id(connection, case_id),
        item_id,
        "technology_ip",
        field,
        value,
        value_type,
        evidence_id,
        excerpt,
        value_scope=scope,
        reporting_period=period if value_type == "integer" else None,
    )


def main() -> None:
    connection = sqlite3.connect(DB)
    try:
        # 年报三年主要会计数据：补回被首次抽取遗漏的 2023/2024 年事实。
        add_finance(connection, "Efort", [
            ("audit_fin_efort_revenue_2024", "finance.operating_revenue", 137319.30, "2024", "万元", "src_12b0e4c82f45eac1:eu_00021", "营业收入 2024年 137,319.30 万元"),
            ("audit_fin_efort_revenue_2023", "finance.operating_revenue", 188646.63, "2023", "万元", "src_12b0e4c82f45eac1:eu_00021", "营业收入 2023年 188,646.63 万元"),
            ("audit_fin_efort_profit_2024", "finance.net_profit_attributable_to_parent", -15715.53, "2024", "万元", "src_12b0e4c82f45eac1:eu_00021", "归属于上市公司股东的净利润 2024年 -15,715.53 万元"),
            ("audit_fin_efort_profit_2023", "finance.net_profit_attributable_to_parent", -4744.80, "2023", "万元", "src_12b0e4c82f45eac1:eu_00021", "归属于上市公司股东的净利润 2023年 -4,744.80 万元"),
            ("audit_fin_efort_cash_2024", "finance.operating_cash_flow", 1140.93, "2024", "万元", "src_12b0e4c82f45eac1:eu_00021", "经营活动产生的现金流量净额 2024年 1,140.93 万元"),
            ("audit_fin_efort_cash_2023", "finance.operating_cash_flow", -22441.51, "2023", "万元", "src_12b0e4c82f45eac1:eu_00021", "经营活动产生的现金流量净额 2023年 -22,441.51 万元"),
            ("audit_fin_efort_rd_2024", "finance.research_expense", 13173.06, "2024", "万元", "src_12b0e4c82f45eac1:eu_00102", "上年度费用化研发投入 13,173.06 万元"),
            ("audit_fin_efort_rd_ratio_2024", "finance.research_expense_ratio", 0.0959, "2024", "万元", "src_12b0e4c82f45eac1:eu_00022", "研发投入占营业收入比例 2024年 9.59%"),
            ("audit_fin_efort_rd_ratio_2023", "finance.research_expense_ratio", 0.0488, "2023", "万元", "src_12b0e4c82f45eac1:eu_00022", "研发投入占营业收入比例 2023年 4.88%"),
        ])
        add_finance(connection, "Stone", [
            ("audit_fin_stone_revenue_2024", "finance.operating_revenue", 11944707206, "2024", "元", "src_2d906c5c343c62df:eu_00021", "营业收入 2024年 11,944,707,206 元"),
            ("audit_fin_stone_revenue_2023", "finance.operating_revenue", 8653783788, "2023", "元", "src_2d906c5c343c62df:eu_00021", "营业收入 2023年 8,653,783,788 元"),
            ("audit_fin_stone_profit_2024", "finance.net_profit_attributable_to_parent", 1976563235, "2024", "元", "src_2d906c5c343c62df:eu_00021", "归属于上市公司股东的净利润 2024年 1,976,563,235 元"),
            ("audit_fin_stone_profit_2023", "finance.net_profit_attributable_to_parent", 2051217414, "2023", "元", "src_2d906c5c343c62df:eu_00021", "归属于上市公司股东的净利润 2023年 2,051,217,414 元"),
            ("audit_fin_stone_cash_2024", "finance.operating_cash_flow", 1733868018, "2024", "元", "src_2d906c5c343c62df:eu_00021", "经营活动产生的现金流量净额 2024年 1,733,868,018 元"),
            ("audit_fin_stone_cash_2023", "finance.operating_cash_flow", 2185931368, "2023", "元", "src_2d906c5c343c62df:eu_00021", "经营活动产生的现金流量净额 2023年 2,185,931,368 元"),
            ("audit_fin_stone_rd_2024", "finance.research_expense", 971438814, "2024", "元", "src_2d906c5c343c62df:eu_00073", "上年度费用化研发投入 971,438,814 元"),
            ("audit_fin_stone_rd_ratio_2024", "finance.research_expense_ratio", 0.0813, "2024", "元", "src_2d906c5c343c62df:eu_00022", "研发投入占营业收入比例 2024年 8.13%"),
            ("audit_fin_stone_rd_ratio_2023", "finance.research_expense_ratio", 0.0715, "2023", "元", "src_2d906c5c343c62df:eu_00022", "研发投入占营业收入比例 2023年 7.15%"),
        ])
        add_finance(connection, "Ecovacs", [
            ("audit_fin_ecovacs_revenue_2024", "finance.operating_revenue", 16542228496.41, "2024", "元", "src_60a507099901a68c:eu_00017", "营业收入 2024年 16,542,228,496.41 元"),
            ("audit_fin_ecovacs_revenue_2023", "finance.operating_revenue", 15502073508.19, "2023", "元", "src_60a507099901a68c:eu_00017", "营业收入 2023年 15,502,073,508.19 元"),
            ("audit_fin_ecovacs_profit_2024", "finance.net_profit_attributable_to_parent", 806087087.89, "2024", "元", "src_60a507099901a68c:eu_00017", "归属于上市公司股东的净利润 2024年 806,087,087.89 元"),
            ("audit_fin_ecovacs_profit_2023", "finance.net_profit_attributable_to_parent", 612075147.00, "2023", "元", "src_60a507099901a68c:eu_00017", "归属于上市公司股东的净利润 2023年 612,075,147.00 元"),
            ("audit_fin_ecovacs_cash_2024", "finance.operating_cash_flow", 852247410.78, "2024", "元", "src_60a507099901a68c:eu_00017", "经营活动产生的现金流量净额 2024年 852,247,410.78 元"),
            ("audit_fin_ecovacs_cash_2023", "finance.operating_cash_flow", 1091317060.63, "2023", "元", "src_60a507099901a68c:eu_00017", "经营活动产生的现金流量净额 2023年 1,091,317,060.63 元"),
            ("audit_fin_ecovacs_rd_2024", "finance.research_expense", 884923156.65, "2024", "元", "src_60a507099901a68c:eu_00047", "研发费用 2024年 884,923,156.65 元"),
            ("audit_fin_ecovacs_rd_ratio_2024", "finance.research_expense_ratio", 0.05349479707900579, "2024", "元", "src_60a507099901a68c:eu_00047", "研发费用 2024年 884,923,156.65 元，占营业收入约5.35%"),
        ])
        add_finance(connection, "Tinavi", [
            ("audit_fin_tinavi_rd_2025", "finance.research_expense", 123170805.09, "2025", "元", "src_98feb4845f10c2ee:eu_00071", "费用化研发投入 2025年 123,170,805.09 元"),
            ("audit_fin_tinavi_rd_2024", "finance.research_expense", 85595497.56, "2024", "元", "src_98feb4845f10c2ee:eu_00071", "费用化研发投入 2024年 85,595,497.56 元"),
            ("audit_fin_tinavi_rd_ratio_2025", "finance.research_expense_ratio", 0.4983, "2025", "元", "src_98feb4845f10c2ee:eu_00018", "研发投入占营业收入比例 2025年 49.83%"),
            ("audit_fin_tinavi_rd_ratio_2024", "finance.research_expense_ratio", 0.6534, "2024", "元", "src_98feb4845f10c2ee:eu_00018", "研发投入占营业收入比例 2024年 65.34%"),
            ("audit_fin_tinavi_rd_ratio_2023", "finance.research_expense_ratio", 0.7163, "2023", "元", "src_98feb4845f10c2ee:eu_00018", "研发投入占营业收入比例 2023年 71.63%"),
        ])

        # 天智航：区分累计授权、发明授权和当前有效专利，去掉重跑产生的恢复重复项。
        # 基础信息：补回原文明确披露、但首次画像遗漏的企业成立时间。
        for case_id, item_id, value, evidence_id, excerpt in [
            ("DeepBlue", "audit_basic_deepblue_founded", "2013-01-05", "src_9139a580080bcf27:eu_00023", "成立日期 2013年1月5日"),
            ("Dobot", "audit_basic_dobot_founded", "2015-07-30", "src_da69df494da495ff:eu_00024", "有限公司成立日期 2015年7月30日"),
            ("Efort", "audit_basic_efort_founded", "2016-05-31", "src_12b0e4c82f45eac1:eu_00498", "于2016年5月31日在芜湖市工商行政管理局办理完毕工商变更登记"),
            ("Stone", "audit_basic_stone_founded", "2014-07-04", "src_2d906c5c343c62df:eu_00449", "北京市海淀区于2014年7月4日注册成立的有限责任公司"),
            ("Tinavi", "audit_basic_tinavi_founded", "2010-10-22", "src_98feb4845f10c2ee:eu_00411", "公司成立于2010年10月22日"),
            ("Yijiahe", "audit_basic_yijiahe_founded", "2015-07-31", "src_ef32f4301fd38608:eu_00373", "2015年7月31日，公司整体变更设立为股份有限公司"),
        ]:
            add_item(
                connection,
                profile_id(connection, case_id),
                item_id,
                "basic_information",
                "enterprise.founded_date",
                value,
                "date",
                evidence_id,
                excerpt,
            )

        ecovacs = profile_id(connection, "Ecovacs")
        connection.execute(
            "UPDATE profile_items SET value_json = ?, evidence_refs_json = ? WHERE profile_id = ? AND item_id = 'enterprise_and_control:item_002'",
            (
                json.dumps("1998-03", ensure_ascii=False),
                ref("src_60a507099901a68c:eu_00299", "成立于1998年3月"),
                ecovacs,
            ),
        )
        ecovacs_topic = connection.execute(
            "SELECT result_json FROM profile_topic_analyses WHERE profile_id = ? AND dimension_id = 'enterprise_and_team'",
            (ecovacs,),
        ).fetchone()
        if ecovacs_topic:
            ecovacs_result = json.loads(ecovacs_topic[0])
            ecovacs_result["domain_summary"] = ecovacs_result["domain_summary"].replace(
                "为1998年成立的科沃斯机器人股份有限公司",
                "为1998年3月成立的科沃斯机器人股份有限公司",
            )
            connection.execute(
                "UPDATE profile_topic_analyses SET result_json = ? WHERE profile_id = ? AND dimension_id = 'enterprise_and_team'",
                (json.dumps(ecovacs_result, ensure_ascii=False), ecovacs),
            )

        tinavi = profile_id(connection, "Tinavi")
        connection.execute(
            "DELETE FROM profile_items WHERE profile_id = ? AND item_id LIKE 'technology_and_ip:recovery:%'",
            (tinavi,),
        )
        connection.execute(
            "UPDATE profile_items SET value_scope = CASE value_json WHEN '270' THEN '发明专利申请（累计）' WHEN '93' THEN '发明专利授权（累计）' WHEN '87' THEN '目前有效发明专利' ELSE value_scope END WHERE profile_id = ? AND field_id LIKE 'intellectual_property.patent_%'",
            (tinavi,),
        )
        add_ip(connection, "Tinavi", "audit_ip_tinavi_application_total", "intellectual_property.patent_application_count", 661, "integer", "累计专利申请总数", "src_98feb4845f10c2ee:eu_00058", "累积申请专利661项")
        add_ip(connection, "Tinavi", "audit_ip_tinavi_grant_total", "intellectual_property.patent_grant_count", 448, "integer", "累计专利授权总数", "src_98feb4845f10c2ee:eu_00058", "累积获得专利授权448项")
        add_ip(connection, "Tinavi", "audit_ip_tinavi_valid_total", "intellectual_property.patent_grant_count", 426, "integer", "目前有效专利总数", "src_98feb4845f10c2ee:eu_00058", "目前有效专利426项")
        add_item(connection, tinavi, "audit_ip_tinavi_software", "technology_ip", "intellectual_property.name", "软件著作权41项", "entity_ref", "src_98feb4845f10c2ee:eu_00070", "软件著作权累计申请并获得备案授权41项")

        # 深之蓝：补齐 15 项核心技术的来源和成熟阶段、7 项技术储备、专利分项和核心团队学历。
        deepblue = profile_id(connection, "DeepBlue")
        core = [
            "复杂水体环境检测和作业机器人系统技术", "大范围长航时海洋观测水下滑翔机系统技术", "中小型自主水下航行器系统技术",
            "融合水动力/材料/设计美学的水下智能产品系统设计技术", "高功率密度水下电源技术", "高效率水下推进技术",
            "水下全电驱作业机械手技术", "水下全姿态运动自动控制技术", "水下智能感知与图像处理技术", "水下机器人操控软件技术",
            "水下多源高精度导航技术", "水下多链路多介质通信技术", "非刚体结构高可靠灌封密封技术", "水下动静密封及检测技术", "水下线缆可靠连接技术",
        ]
        for index, subject in enumerate(core, 1):
            source_id = "src_9139a580080bcf27:eu_00323" if index <= 4 else ("src_9139a580080bcf27:eu_00324" if index <= 9 else ("src_9139a580080bcf27:eu_00325" if index <= 13 else "src_9139a580080bcf27:eu_00326"))
            add_item(connection, deepblue, f"audit_deepblue_source_{index:02d}", "technology_ip", "technology.source", "自主研发", "text", source_id, "技术来源：自主研发", subject=subject)
            add_item(connection, deepblue, f"audit_deepblue_maturity_{index:02d}", "technology_ip", "technology.maturity_stage", "批量生产", "enum", source_id, "所处阶段：批量生产", subject=subject)
        reserves = [
            ("智能电动作业级 ROV 系统技术", "概念阶段"), ("深远海长航程自主水下航行器系统技术", "研发初期"),
            ("深海驻留自主水下机器人系统技术", "概念阶段"), ("水下机器人智能选矿采矿技术", "概念阶段"),
            ("基于水下机器人的全自动船舶清洗技术", "概念阶段"), ("水下智能控制技术", "研发初期"), ("水下机器人仿真技术", "研发初期"),
        ]
        for index, (subject, stage) in enumerate(reserves, 1):
            add_item(connection, deepblue, f"audit_deepblue_reserve_maturity_{index:02d}", "technology_ip", "technology.maturity_stage", stage, "enum", "src_9139a580080bcf27:eu_00349", f"技术储备：{subject}，所处阶段：{stage}", subject=subject)
        add_ip(connection, "DeepBlue", "audit_ip_deepblue_total", "intellectual_property.patent_grant_count", 392, "integer", "境内外专利总数", "src_9139a580080bcf27:eu_00028", "截至2025年12月31日拥有境内外专利392项")
        add_ip(connection, "DeepBlue", "audit_ip_deepblue_domestic_invention", "intellectual_property.patent_grant_count", 108, "integer", "境内发明专利", "src_9139a580080bcf27:eu_00028", "其中境内发明专利108项")
        add_ip(connection, "DeepBlue", "audit_ip_deepblue_overseas_invention", "intellectual_property.patent_grant_count", 12, "integer", "境外发明专利", "src_9139a580080bcf27:eu_00028", "其中境外发明专利12项")
        add_item(connection, deepblue, "audit_ip_deepblue_acquisition", "technology_ip", "intellectual_property.name", "部分专利为继受取得", "entity_ref", "src_9139a580080bcf27:eu_01008", "专利清单中同时披露原始取得和继受取得")
        connection.execute(
            "UPDATE profile_items SET value_json = ?, evidence_refs_json = ? WHERE profile_id = ? AND item_id = 'technology_and_ip:ip_005'",
            (
                json.dumps("以自有为主，部分专利为继受取得", ensure_ascii=False),
                ref("src_9139a580080bcf27:eu_01008", "专利清单中同时披露原始取得和继受取得"),
                deepblue,
            ),
        )
        add_item(connection, deepblue, "audit_team_deepblue_education", "ownership_governance_team", "team.education_structure", "7名核心技术人员中博士1名、硕士3名、本科3名，专业覆盖控制科学与工程、机械设计与理论、电力系统及其自动化、机械制造及自动化、测控技术与仪器、港口航道与海岸工程。", "text", "src_9139a580080bcf27:eu_00342", "核心技术人员学历、专业和职称表")
        add_item(connection, deepblue, "audit_team_deepblue_background", "ownership_governance_team", "team.professional_background", "核心技术人员分别负责水下机器人总体、动力、电源、控制导航、AUV、ROV及水下助推机器人研发与产品线管理，覆盖软件、硬件、机械设计、电力电子、信号处理等专业背景。", "text", "src_9139a580080bcf27:eu_00342", "核心技术人员简历及科研情况")

        # 亿嘉和：补充年报明确列出的技术能力和软件著作权数量。
        yijiahe = profile_id(connection, "Yijiahe")
        for index, name in enumerate(["机器视觉", "自主导航", "多模态环境感知", "AI算法", "深度学习", "驱动控制", "具身智能"], 1):
            add_item(connection, yijiahe, f"audit_tech_yijiahe_{index:02d}", "technology_ip", "technology.name", name, "entity_ref", "src_ef32f4301fd38608:eu_00071", "核心技术覆盖机器视觉、自主导航、多模态环境感知、AI算法、深度学习、驱动控制、具身智能", subject=name)
            add_item(connection, yijiahe, f"audit_tech_yijiahe_source_{index:02d}", "technology_ip", "technology.source", "自主研发", "text", "src_ef32f4301fd38608:eu_00071", "自主研发核心技术", subject=name)
        connection.execute("UPDATE profile_items SET value_json = ? WHERE profile_id = ? AND item_id = 'technology_and_ip:ip_004'", (json.dumps("软件著作权154项", ensure_ascii=False), yijiahe))

        # 其余企业：补充原文明确披露的专利分项和软件著作权，避免把非专利权利混入专利字段。
        add_ip(connection, "DeepRobotics", "audit_ip_deeprobotics_total", "intellectual_property.patent_grant_count", 84, "integer", "授权专利总数", "src_ce1e56d9875c94cb:eu_00266", "授权发明专利25项、实用新型专利59项")
        add_ip(connection, "DeepRobotics", "audit_ip_deeprobotics_invention", "intellectual_property.patent_grant_count", 25, "integer", "授权发明专利", "src_ce1e56d9875c94cb:eu_00266", "授权发明专利25项")
        add_ip(connection, "DeepRobotics", "audit_ip_deeprobotics_utility", "intellectual_property.patent_grant_count", 59, "integer", "授权实用新型专利", "src_ce1e56d9875c94cb:eu_00266", "实用新型专利59项")
        add_item(connection, profile_id(connection, "DeepRobotics"), "audit_ip_deeprobotics_software", "technology_ip", "intellectual_property.name", "软件著作权8项", "entity_ref", "src_ce1e56d9875c94cb:eu_00266", "软件著作权8项")
        add_ip(connection, "Dobot", "audit_ip_dobot_total", "intellectual_property.patent_grant_count", 651, "integer", "境内外授权专利总数", "src_da69df494da495ff:eu_00031", "已授权境内专利625项、已授权境外专利26项")
        add_ip(connection, "Dobot", "audit_ip_dobot_domestic_invention", "intellectual_property.patent_grant_count", 233, "integer", "境内发明专利", "src_da69df494da495ff:eu_00031", "境内发明专利233项")
        add_ip(connection, "Dobot", "audit_ip_dobot_overseas_invention", "intellectual_property.patent_grant_count", 20, "integer", "境外发明专利", "src_da69df494da495ff:eu_00031", "境外发明专利20项")
        add_item(connection, profile_id(connection, "Dobot"), "audit_ip_dobot_software", "technology_ip", "intellectual_property.name", "软件著作权135项", "entity_ref", "src_da69df494da495ff:eu_00031", "软件著作权135项")
        add_item(connection, profile_id(connection, "Leju"), "audit_ip_leju_software", "technology_ip", "intellectual_property.name", "软件著作权40项", "entity_ref", "src_e3cebccebea77d82:eu_00661", "拥有40项软件著作权")
        add_item(connection, profile_id(connection, "Efort"), "audit_ip_efort_software", "technology_ip", "intellectual_property.name", "软件著作权140项", "entity_ref", "src_12b0e4c82f45eac1:eu_00088", "拥有软件著作权140项")

        # 科沃斯：年报同时披露授权专利与在申专利总量，补回在申专利口径。
        add_ip(connection, "Ecovacs", "audit_ip_ecovacs_application_total", "intellectual_property.patent_application_count", 1948, "integer", "在申专利总数", "src_60a507099901a68c:eu_00090", "在申专利共计1,948项")
        add_ip(connection, "Ecovacs", "audit_ip_ecovacs_application_invention", "intellectual_property.patent_application_count", 1341, "integer", "在申发明专利", "src_60a507099901a68c:eu_00090", "在申发明专利1,341项")

        # 石头年报的 1,975 项是“本年度新增授权专利”，另外两项不是专利。
        stone = profile_id(connection, "Stone")
        connection.execute("UPDATE profile_items SET value_scope = '2025年度新增授权专利' WHERE profile_id = ? AND field_id = 'intellectual_property.patent_grant_count' AND value_scope IN ('发明专利','实用新型专利','外观设计专利')", (stone,))
        connection.execute("DELETE FROM profile_items WHERE profile_id = ? AND item_id IN ('technology_and_ip:ip_025', 'technology_and_ip:ip_026')", (stone,))
        for item_id, excerpt in [
            ("technology_and_ip:ip_022", "其中新增发明专利244项"),
            ("technology_and_ip:ip_023", "新增实用新型专利600项"),
            ("technology_and_ip:ip_024", "新增外观设计专利1,131项"),
        ]:
            connection.execute(
                "UPDATE profile_items SET evidence_refs_json = ? WHERE profile_id = ? AND item_id = ?",
                (ref("src_2d906c5c343c62df:eu_00247", excerpt), stone, item_id),
            )
        for item_id, value, excerpt in [
            ("audit_ip_stone_software", "软件著作权2项", "新增软件著作权2项"),
            ("audit_ip_stone_trademark", "商标及作品著作权1,289项", "新增授权商标及作品著作权合计1,289项"),
        ]:
            add_item(connection, stone, item_id, "technology_ip", "intellectual_property.name", value, "entity_ref", "src_2d906c5c343c62df:eu_00057", excerpt)

        # 已完成的石头科技技术主题中，修正模型对专利三类拆分口径的概括。
        topic_row = connection.execute(
            "SELECT result_json FROM profile_topic_analyses WHERE profile_id = ? AND dimension_id = 'technology_and_ip'",
            (stone,),
        ).fetchone()
        if topic_row:
            topic_result = json.loads(topic_row[0])
            topic_result["domain_summary"] = topic_result["domain_summary"].replace(
                "并在2025年度新增授权专利上以多个统计口径披露了专利数量。",
                "并按发明、实用新型和外观设计三类拆分披露2025年度新增授权专利数量。",
            )
            for analysis in topic_result.get("topic_analyses", []):
                if analysis.get("topic_id") != "ip_protection":
                    continue
                analysis["conclusion"] = (
                    "企业拥有经审计确认的软件著作权2项、商标及作品著作权1,289项；"
                    "2025年度新增授权专利按类型拆分为发明专利244项、实用新型专利600项、外观设计专利1,131项，"
                    "三项为同一年度新增授权专利的类型分项，不应相加后解读为累计专利存量。"
                )
                if len(analysis.get("key_signals", [])) >= 2:
                    analysis["key_signals"][1] = (
                        "2025年度新增授权专利按发明、实用新型和外观设计三类披露，"
                        "对应数量分别为244项、600项和1,131项。"
                    )
                if analysis.get("information_boundaries"):
                    analysis["information_boundaries"][0] = (
                        "材料未披露报告期末累计专利存量、有效专利数量及专利权利状态，"
                        "不能仅凭年度新增授权数量判断期末专利余额。"
                    )
            if len(topic_result.get("information_boundaries", [])) >= 3:
                topic_result["information_boundaries"][2] = (
                    "2025年度新增授权专利已按发明、实用新型和外观设计三类拆分披露，"
                    "但未披露报告期末累计专利存量及有效状态。"
                )
            connection.execute(
                "UPDATE profile_topic_analyses SET result_json = ? WHERE profile_id = ? AND dimension_id = 'technology_and_ip'",
                (json.dumps(topic_result, ensure_ascii=False), stone),
            )

        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
