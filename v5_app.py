"""科技型企业风险辅助审查系统 V5 Streamlit 工作区。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from src.approval.repository import ApprovalRepository
from src.ontology.loader import load_manifest
from src.profiles.visual_card import ROLE_LABELS, STATUS_LABELS
from src.ui.v5_services import (
    approval_workspace_rows,
    approve_approval_point_definition,
    approve_comparable_metric_definition,
    approve_composite_approval_review,
    approve_domain_approval_review,
    approve_metric_value_candidate,
    approve_peer_cohort,
    approve_historical_case_analysis_review,
    approve_industry_profile_review,
    approve_profile_review,
    comparison_card_rows,
    composite_approval_report_detail,
    create_approval_point_definition,
    create_comparable_metric_definition,
    create_peer_cohort,
    domain_approval_report_detail,
    find_similar_profiles,
    generate_industry_profile_review,
    generate_enterprise_overall_assessment_review,
    generate_composite_approval_review,
    generate_direction_ranking_review,
    generate_domain_approval_review,
    generate_guideline_section_review,
    generate_profile_comparison_card,
    generate_historical_case_analysis_review,
    historical_case_analysis_detail,
    historical_case_analysis_rows,
    industry_profile_detail,
    industry_profile_rows,
    enterprise_overall_assessment_detail,
    industry_source_rows,
    approve_direction_ranking_review,
    approve_enterprise_overall_assessment_review,
    direction_ranking_basis_detail,
    direction_ranking_detail,
    guideline_section_rows,
    ingest_industry_source,
    ingest_uploaded_source,
    load_profile_review,
    metric_value_candidates,
    profile_detail,
    profile_rows,
    profile_visual_card,
    run_profile_topic_analysis,
    run_domain_investigation,
    run_react_domain_investigation,
    run_detailed_review_report,
    source_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "current_project.db"
UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"
PROFILE_DOMAINS = (
    "enterprise_and_control",
    "team",
    "technology_and_ip",
    "product_and_project",
    "market_and_commercialization",
    "customer_and_supplier",
    "finance_and_funding",
    "risk_matters",
    "authoritative_findings",
    "outcome_and_resolution",
)


def _ontology_labels() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    manifest = load_manifest()
    return (
        {item["id"]: item["label"] for item in manifest["fields"]},
        {item["id"]: item["label"] for item in manifest["profile_sections"]},
        {item["id"]: item["label"] for item in manifest["relations"]},
    )


def _render_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def _debug_enabled() -> bool:
    return bool(st.session_state.get("v5_show_debug", False))


def _profile_option_map(rows: list[dict[str, object]]) -> dict[str, str]:
    """将企业画像选项显示为中文企业名，内部仍返回稳定 profile_id。"""
    type_labels = {"current": "当前画像", "historical": "历史画像"}
    options: dict[str, str] = {}
    for row in rows:
        name = str(row["enterprise_name"])
        profile_type = type_labels.get(str(row.get("profile_type", "")), "企业画像")
        label = f"{name}（{profile_type}）"
        if label in options:
            label = f"{name}（{profile_type}，案例 {row['case_id']}）"
        options[label] = str(row["profile_id"])
    return options


def _render_direction_ranking_basis(basis: dict[str, object]) -> None:
    """展示方向排名所使用的固定标准和逐企业比较卡。"""
    section = basis["section"]
    cohort = basis["cohort"]
    st.markdown("**固定比较标准**：" + "；".join(section["comparison_criteria"]))
    st.caption(
        f"样本报告期：{cohort['fiscal_period']}；入样规则：{cohort['selection_rule']}"
    )
    st.caption("以下为排名时每家企业使用的比较卡；查看不调用 DeepSeek，也不会改变排名。")
    for item in basis["cards"]:
        card = item["card"]
        with st.expander(f"{item['enterprise_name']} · 比较卡", expanded=False):
            st.markdown("**方向总结**：" + card["one_sentence_summary"])
            st.caption(
                f"来源报告：{item['source_section_report_id']}；"
                f"审核状态：{item['source_report_review_status']}"
            )
            for point in card["approval_points"]:
                st.markdown(f"#### {point['title']}")
                st.write(f"审批判断：{point['judgment']}")
                st.write(f"企业现状：{point['enterprise_observation']}")
                if point["industry_benchmark"]:
                    st.write(f"行业基准：{point['industry_benchmark']}")
                if point["peer_comparison"]:
                    st.write(f"同行比较：{point['peer_comparison']}")
                if point["metric_results"]:
                    st.markdown("**数值指标**")
                    st.dataframe(point["metric_results"], width="stretch", hide_index=True)
                if point["key_facts"]:
                    st.markdown("**关键事实**")
                    st.dataframe(point["key_facts"], width="stretch", hide_index=True)
                if point["information_gaps"]:
                    st.caption("信息缺口：" + "；".join(point["information_gaps"]))


def _candidate_item_rows(candidates: dict[str, object]) -> list[dict[str, object]]:
    field_labels, section_labels, _ = _ontology_labels()
    return [
        {
            "领域": section_labels.get(item["section_id"], item["section_id"]),
            "主体": item.get("subject") or "未标明",
            "事实": field_labels.get(item["field_id"], item["field_id"]),
            "内容": _render_value(item["value"]),
            "统计范围": item.get("value_scope") or "",
            "信息性质": ROLE_LABELS.get(item["content_role"], item["content_role"]),
            "状态": STATUS_LABELS.get(item["information_status"], item["information_status"]),
            "证据数": len(item.get("evidence_unit_ids", [])),
        }
        for item in candidates["profile_items"]
    ]


def _candidate_relation_rows(candidates: dict[str, object]) -> list[dict[str, object]]:
    _, _, relation_labels = _ontology_labels()
    return [
        {
            "关系": relation_labels.get(item["relation_type"], item["relation_type"]),
            "来源类型": item["source_type"],
            "目标类型": item["target_type"],
            "信息性质": ROLE_LABELS.get(item["content_role"], item["content_role"]),
            "状态": STATUS_LABELS.get(item["information_status"], item["information_status"]),
            "证据数": len(item.get("evidence_unit_ids", [])),
        }
        for item in candidates["profile_relations"]
    ]


def _sidebar() -> tuple[str, str, bool]:
    st.sidebar.header("项目配置")
    database = st.sidebar.text_input("SQLite 数据库", str(DEFAULT_DATABASE))
    show_advanced = st.sidebar.toggle("显示高级工具", value=False)
    show_debug = st.sidebar.toggle("显示开发调试工具", value=False)
    st.session_state["v5_show_debug"] = show_debug
    pages = ["材料管理", "企业画像", "行业背景", "授信审批报告"]
    if show_advanced:
        pages.extend(["历史案例", "相似案例与报告", "审批配置（高级）"])
    if show_debug:
        pages.append("开发调试")
    page = st.sidebar.radio(
        "工作区",
        pages,
    )
    st.sidebar.caption("所有输出仅用于历史参考和信息核实辅助。")
    return database, page, show_debug


def _sources(database: str, *, show_header: bool = True) -> None:
    if show_header:
        st.header("材料管理")
    st.caption("导入企业 PDF 或 HTML，系统会切分并写入可追溯的证据库。行业研报请在“行业背景”中管理。")
    case_id = st.text_input("案例 ID", "")
    uploads = st.file_uploader("导入 PDF 或 HTML", type=["pdf", "html", "htm"], accept_multiple_files=True)
    if st.button("解析并写入证据库", type="primary"):
        if not case_id.strip() or not uploads:
            st.error("请填写案例 ID 并选择文件。")
        else:
            try:
                results = [
                    ingest_uploaded_source(
                        database=database,
                        case_id=case_id.strip(),
                        upload_root=UPLOAD_ROOT,
                        filename=upload.name,
                        content=upload.getvalue(),
                    )
                    for upload in uploads
                ]
                st.success(f"已导入 {len(results)} 个数据源。")
                st.session_state["v5_ingestion_results"] = results
            except Exception as exc:
                st.error(f"导入失败：{exc}")
    all_sources = source_rows(database)
    source_case_ids = sorted({str(row["case_id"]) for row in all_sources})
    profile_names = {
        str(row["case_id"]): str(row["enterprise_name"])
        for row in profile_rows(database)
    }
    source_options = {
        profile_names.get(case_id, f"案例 {case_id}"): case_id
        for case_id in source_case_ids
    }
    selected_source_label = st.selectbox(
        "查看已导入材料的企业",
        [""] + list(source_options),
        key="source_view_case_id",
    )
    selected_case_id = source_options.get(selected_source_label, "")
    if selected_case_id:
        selected_sources = [row for row in all_sources if row["case_id"] == selected_case_id]
        st.caption(f"已导入 {len(selected_sources)} 份材料，共 {sum(row['evidence_units'] for row in selected_sources)} 个证据单元。")
        for source in selected_sources:
            st.markdown(f"- **{source['title']}**：{source['evidence_units']} 个证据单元")
            st.caption(f"材料类型：{source['type']}")
    if _debug_enabled() and st.session_state.get("v5_ingestion_results"):
        with st.expander("开发调试：本次导入记录"):
            st.json(st.session_state["v5_ingestion_results"], expanded=False)


def _profile_review(database: str, *, show_header: bool = True) -> None:
    if show_header:
        st.header("审核并写入正式画像")
    st.caption("审核领域调查生成的候选事实；可直接使用本次页面结果，或上传“生成候选”页下载的候选 JSON。确认后才写入正式企业画像。")
    uploaded = st.file_uploader("上传候选画像运行 JSON", type=["json"])
    latest_run = st.session_state.get("v5_profile_run")
    use_latest = bool(latest_run) and st.checkbox("使用本次页面调查结果", value=False)
    if uploaded is None and not use_latest:
        return
    try:
        bundle = load_profile_review(uploaded.getvalue()) if uploaded is not None else load_profile_review(
            json.dumps(latest_run, ensure_ascii=False)
        )
    except Exception as exc:
        st.error(f"无法读取画像结果：{exc}")
        return
    candidates = bundle["candidates"]
    diagnostics = bundle["diagnostics"]
    columns = st.columns(4)
    columns[0].metric("领域", len(diagnostics["domains_with_candidates"]))
    columns[1].metric("画像项", len(candidates["profile_items"]))
    columns[2].metric("关系", len(candidates["profile_relations"]))
    columns[3].metric("待复核", len(diagnostics["consistency_warnings"]))
    st.subheader("待审核事实")
    st.dataframe(_candidate_item_rows(candidates), width="stretch", hide_index=True)
    if candidates["profile_relations"]:
        st.subheader("待审核关系")
        st.dataframe(_candidate_relation_rows(candidates), width="stretch", hide_index=True)
    if candidates["information_gaps"]:
        st.subheader("信息缺口")
        for gap in candidates["information_gaps"]:
            st.markdown(f"- {gap}")
    if diagnostics["consistency_warnings"] or diagnostics["rejected_candidates"]:
        st.warning("候选中存在需要复核或已被过滤的内容；如需查看技术原因，请开启左侧“显示开发调试工具”。")

    profile_id = st.text_input("正式画像 ID", "")
    enterprise_name = st.text_input("企业名称")
    confirmed = st.checkbox("我已查看候选及校验记录，确认写入 approved 正式画像")
    if st.button("批准并写入画像库", type="primary", disabled=not confirmed):
        if not profile_id.strip() or not enterprise_name.strip():
            st.error("请填写正式画像 ID 和企业名称。")
        else:
            try:
                approve_profile_review(
                    database=database,
                    bundle=bundle,
                    profile_id=profile_id.strip(),
                    enterprise_name=enterprise_name.strip(),
                )
                st.success("正式画像已写入。")
            except Exception as exc:
                st.error(f"画像入库失败：{exc}")
    if _debug_enabled():
        with st.expander("开发调试：候选原文与校验记录"):
            st.json({"candidates": candidates, "diagnostics": diagnostics}, expanded=False)


def _investigation(database: str, *, show_header: bool = True) -> None:
    if show_header:
        st.header("生成画像候选")
    st.caption("固定流程适合稳定批量生成；受控 ReAct 会按需搜索和读取少量证据。两种模式都会调用 DeepSeek。")
    investigation_mode = st.selectbox("调查模式", ["", "固定流程", "受控 ReAct（试验）"])
    react_mode = investigation_mode == "受控 ReAct（试验）"
    case_id = st.text_input("调查案例 ID", "", key="investigation_case_id")
    profile_type = st.selectbox(
        "画像类型",
        ["", "current"] if react_mode else ["", "historical", "current"],
    )
    domains = st.multiselect(
        "调查领域",
        PROFILE_DOMAINS,
        default=[],
    )
    query = st.text_input("当前案例补充查询词（历史画像忽略）")
    first, second = st.columns(2)
    max_catalog = first.number_input("每领域目录候选上限", 1, 50, 20)
    max_selected = second.number_input("每领域正文读取上限", 1, 10, 5)
    confirmed = st.checkbox("我确认本次操作将调用 DeepSeek 并可能产生费用")
    if st.button("运行领域调查", type="primary"):
        if not investigation_mode or not case_id.strip() or not profile_type or not domains:
            st.error("请选择调查模式、填写案例 ID、选择画像类型，并至少选择一个调查领域。")
        elif not confirmed:
            st.error("请先确认本次操作可能产生 DeepSeek 费用。")
        elif react_mode and (profile_type != "current" or len(domains) != 1):
            st.error("受控 ReAct 目前支持 current 画像，每次运行一个调查领域。")
        else:
            try:
                with st.spinner("正在执行证据调查和画像候选抽取……"):
                    if react_mode:
                        result = run_react_domain_investigation(
                            database=database,
                            case_id=case_id.strip(),
                            domain=domains[0],
                            query=query.strip(),
                            max_catalog_items=int(max_catalog),
                            max_read_units=int(max_selected),
                        )
                    else:
                        result = run_domain_investigation(
                            database=database,
                            case_id=case_id.strip(),
                            profile_type=profile_type,
                            domains=tuple(domains),
                            query=query.strip(),
                            max_evidence_per_domain=int(max_catalog),
                            max_selected_evidence_per_domain=int(max_selected),
                        )
                st.session_state["v5_profile_run"] = result
                st.success("领域调查完成，请切换到“审核并入库”确认候选事实。")
            except Exception as exc:
                st.error(f"领域调查失败：{exc}")
    result = st.session_state.get("v5_profile_run")
    if result:
        st.success("候选画像已保留在当前页面会话中。可直接到“审核并入库”勾选“使用本次页面调查结果”；如需稍后或在其他设备审核，请先下载 JSON。")
        st.download_button(
            "下载候选画像运行 JSON",
            json.dumps(result, ensure_ascii=False, indent=2),
            file_name=f"{result['case_id']}_{result['profile_type']}_profile_run.json",
            mime="application/json",
        )
    if result and _debug_enabled():
        with st.expander("开发调试：本次画像运行 JSON"):
            st.json(result, expanded=False)


def _profiles(database: str) -> None:
    st.header("正式企业画像")
    st.caption("画像卡先展示已审核事实；主题分析单独调用 DeepSeek，结果仍保留事实和证据引用。")
    rows = profile_rows(database)
    profile_options = _profile_option_map(rows)
    selected_label = st.selectbox("企业画像", [""] + list(profile_options))
    selected = profile_options.get(selected_label, "")
    if selected:
        card = profile_visual_card(database, selected)
        if card is None:
            st.error("未找到企业画像。")
            return
        saved_analysis = st.session_state.get("v5_topic_analysis")
        if saved_analysis and saved_analysis.get("profile_id") == selected:
            card = saved_analysis["card"]
        type_label = "历史企业画像" if card["profile_type"] == "historical" else "当前企业画像"
        st.subheader(card["enterprise_name"])
        st.caption(f"{type_label} · 案例 {card['case_id']} · 画像状态：{card['review_status']}")
        metrics = st.columns(4)
        metrics[0].metric("画像事实", card["item_count"])
        metrics[1].metric("关联证据", card["evidence_count"])
        metrics[2].metric("权威/结果事实", card["authority_fact_count"])
        metrics[3].metric("信息缺口", len(card["information_gaps"]))

        dimensions_by_id = {dimension["dimension_id"]: dimension for dimension in card["dimensions"]}
        analysis_dimension = st.selectbox(
            "需要分析的画像领域",
            [dimension["dimension_id"] for dimension in card["dimensions"]],
            format_func=lambda value: dimensions_by_id[value]["label"],
            key="profile_analysis_dimension",
        )
        analysis_confirmed = st.checkbox(
            "我确认生成主题分析将调用 DeepSeek 并可能产生费用",
            key="profile_analysis_confirmed",
        )
        if st.button("生成该领域主题分析", type="primary"):
            if not analysis_confirmed:
                st.error("请先确认本步骤会调用 DeepSeek。")
            else:
                try:
                    with st.spinner("正在按主题读取事实并生成画像分析……"):
                        analysis_result = run_profile_topic_analysis(
                            database=database,
                            profile_id=selected,
                            dimension_id=analysis_dimension,
                        )
                    st.session_state["v5_topic_analysis"] = {
                        "profile_id": selected,
                        **analysis_result,
                    }
                    if analysis_result["run"]["status"] == "completed":
                        st.success("主题分析已生成，可在对应领域展开查看。")
                    else:
                        st.error(f"主题分析未完成：{analysis_result['run'].get('error', '未知错误')}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"主题分析失败：{exc}")

        if card["historical_outcomes"]:
            st.subheader("历史结果")
            for fact in card["historical_outcomes"]:
                st.markdown(f"- **{fact['field_label']}**：{fact['value']}（{fact['role_label']}）")

        st.subheader("画像概览")
        st.caption("各领域默认收起；点击领域标题查看内部事实和证据。")
        for dimension in card["dimensions"]:
            summary = (
                f"{dimension['label']} · {len(dimension['facts'])} 条事实 · "
                f"{dimension['claim_count']} 条企业陈述 · "
                f"{dimension['authority_count']} 条权威/结果事实 · "
                f"{len(dimension['topics'])} 个主题"
            )
            with st.expander(summary, expanded=False):
                if not dimension["topics"]:
                    st.caption("当前没有已审核事实")
                    continue
                for topic in dimension["topics"]:
                    st.markdown(f"#### {topic['title']}")
                    st.write(topic["summary"])
                    if topic.get("analysis"):
                        st.info(topic["analysis"])
                    if topic.get("key_signals"):
                        st.markdown("**分析信号**：" + "；".join(topic["key_signals"]))
                    if topic.get("information_boundaries"):
                        st.caption("信息边界：" + "；".join(topic["information_boundaries"]))
                    if topic["records"]:
                        st.dataframe(list(topic["records"]), width="stretch", hide_index=True)
                    with st.expander(
                        f"查看支撑事实（{len(topic['facts'])} 条，{topic['claim_count']} 条企业陈述）",
                        expanded=False,
                    ):
                        for fact in topic["facts"]:
                            st.markdown(
                                f"**{fact['field_label']}**：{fact['value']}  \n"
                                f"`{fact['role_label']}` · {fact['status_label']}"
                            )
                            if fact["context"]:
                                st.caption(fact["context"])
                            if fact["evidence"]:
                                with st.expander(
                                    f"查看证据（{len(fact['evidence'])} 条）", expanded=False
                                ):
                                    for evidence in fact["evidence"]:
                                        heading = evidence["source_title"]
                                        if evidence["location"]:
                                            heading += f" · {evidence['location']}"
                                        st.markdown(f"**{heading}**")
                                        st.caption(evidence["evidence_unit_id"])
                                        if evidence["excerpt"]:
                                            st.write(evidence["excerpt"])

        if card["information_gaps"]:
            st.subheader("当前信息缺口")
            for gap in card["information_gaps"]:
                st.markdown(f"- {gap}")
        if card["conflicts"]:
            st.subheader("待核实冲突")
            for conflict in card["conflicts"]:
                st.warning(conflict)
        if _debug_enabled():
            with st.expander("调试信息（完整画像 JSON）"):
                st.json(profile_detail(database, selected), expanded=False)


def _render_approval_report_detail(database: str, detail: dict[str, object]) -> None:
    """以可读的指标名和折叠证据展示单份分方向审批报告。"""
    report = detail["report"]
    metric_names = {
        definition.metric_id: definition.name
        for definition in ApprovalRepository(database).list_metric_definitions()
    }
    st.caption(f"审核状态：{report['review_status']}")
    st.markdown(report["one_sentence_summary"])
    for index, point in enumerate(report["approval_points"], start=1):
        st.markdown(f"## 审批点 {index}：{point['title']}")
        st.markdown(f"- 企业现状：{_business_text(point['enterprise_observation'])}")
        if point["industry_benchmark"]:
            st.markdown(f"- 行业基准：{_business_text(point['industry_benchmark'])}")
        if point["peer_comparison"]:
            st.markdown(f"- 同行比较：{_business_text(point['peer_comparison'])}")
        st.markdown(f"- 审批判断：{_business_text(point['judgment'])}")
        for ranking in point["ranking_results"]:
            metric_name = metric_names.get(ranking["metric_id"], ranking["metric_id"])
            st.markdown(
                f"- 样本内指标排名（{metric_name}）："
                f"第 {ranking['rank']}/{ranking['sample_size']} 名，名次分 {ranking['rank_points']}"
            )
        if point["information_gaps"]:
            st.markdown(f"- 信息缺口：{'；'.join(point['information_gaps'])}")
        evidence_refs = point["evidence_refs"]
        with st.expander(f"查看证据引用（{len(evidence_refs)} 条）", expanded=False):
            for reference in evidence_refs:
                st.markdown("**原文证据**")
                st.caption(reference["evidence_unit_id"])
                if reference.get("excerpt"):
                    st.write(reference["excerpt"])


def _business_text(text: str) -> str:
    """移除旧报告正文中泄漏的内部引用标识，保留业务结论。"""
    return re.sub(
        r"（基于(?:metric_id|enterprise_item_id|industry_insight_id|information_gap_numbers)[^）]*）",
        "",
        text,
    )


def _render_final_approval_report(database: str, detail: dict[str, object]) -> None:
    """展示一份面向业务人员的最终报告，并折叠其分方向依据。"""
    assessment = detail["assessment"]
    direction_results = assessment["direction_results"]
    if not direction_results:
        st.info("该记录为旧版综合评定，未包含11个方向的通过状态。请重新生成最终授信审批报告。")
        return

    recommendation_labels = {
        "proceed_with_caution": "可推进",
        "proceed_with_review": "审慎推进",
        "conditional_proceed": "有条件推进",
        "do_not_proceed": "不建议推进",
    }
    status_labels = {
        "passed": "通过",
        "conditional_passed": "有条件通过",
        "failed": "不通过",
        "insufficient_information": "信息不足",
    }
    constraint_labels = {"strong": "强约束", "weak": "弱约束"}
    section_titles = {
        item["section_id"]: item["title"] for item in guideline_section_rows()
    }
    columns = st.columns(4)
    columns[0].metric("推进建议", recommendation_labels[assessment["recommendation"]])
    columns[1].metric("综合等级", assessment["rating_level"])
    columns[2].metric("强约束不通过", f"{assessment['strong_constraint_failed_count']} 条")
    columns[3].metric("弱约束不通过", f"{assessment['weak_constraint_failed_count']} 条")
    st.caption(f"审核状态：{assessment['review_status']}")
    st.write(assessment["overall_judgment"])

    for title, values in (
        ("主要风险", assessment["core_risks"]),
        ("缓释因素", assessment["mitigating_factors"]),
        ("判断边界", assessment["rating_boundaries"]),
        ("优先核实事项", assessment["verification_priorities"]),
    ):
        if values:
            st.markdown(f"**{title}**：" + "；".join(values))

    st.subheader("授信审批指引逐条结论")
    for result in direction_results:
        section_id = result["section_id"]
        heading = (
            f"{section_titles[section_id]} · {constraint_labels[result['constraint_level']]} · "
            f"{status_labels[result['status']]}"
        )
        with st.expander(heading, expanded=False):
            st.write(result["summary"])
            report_id = next(
                (
                    value
                    for value in assessment["source_direction_report_ids"]
                    if f"_{section_id}_" in value
                ),
                "",
            )
            if report_id:
                report_detail = domain_approval_report_detail(database, report_id)
                if report_detail:
                    st.caption("审批点、同行排名与原文证据")
                    _render_approval_report_detail(database, report_detail)

    st.download_button(
        "下载最终授信审批报告 Markdown",
        detail["assessment_markdown"],
        file_name=f"{assessment['assessment_id']}.md",
        mime="text/markdown",
        key="final_approval_report_download",
    )


def _historical_case_analysis(database: str) -> None:
    st.header("历史企业案例分析")
    st.caption("从审核通过的历史企业画像提炼单案分析。正文面向人员阅读；来源 ID、过滤记录和模型元数据仅在调试区展示。")
    profiles = [row for row in profile_rows(database) if row["profile_type"] == "historical" and row["review_status"] == "approved"]
    profile_options = _profile_option_map(profiles)
    selected_label = st.selectbox("历史企业画像", [""] + list(profile_options))
    selected_profile = profile_options.get(selected_label, "")
    confirmed = st.checkbox("我确认生成案例分析将调用 DeepSeek 并可能产生费用")
    if st.button("生成待审核案例分析", type="primary"):
        if not selected_profile:
            st.error("请先选择历史企业画像。")
        elif not confirmed:
            st.error("请先确认本步骤会调用 DeepSeek。")
        else:
            try:
                st.session_state["v5_case_analysis"] = generate_historical_case_analysis_review(database=database, profile_id=selected_profile)
                st.success("案例分析已生成，当前仍为待审核状态。")
            except Exception as exc:
                st.error(f"案例分析生成失败：{exc}")

    rows = historical_case_analysis_rows(database)
    st.dataframe(
        [
            {
                "企业": row["enterprise_name"],
                "案例结果状态": row["outcome_status"],
                "审核状态": row["review_status"],
                "分析因素数": row["factors"],
                "是否对应当前画像": row["current"],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
    )
    analysis_options = {f"{row['enterprise_name']} · {row['review_status']}": row["analysis_id"] for row in rows}
    selected_label = st.selectbox("查看案例分析", [""] + list(analysis_options))
    selected_analysis = analysis_options.get(selected_label, "")
    detail = historical_case_analysis_detail(database, selected_analysis) if selected_analysis else st.session_state.get("v5_case_analysis")
    if not detail:
        return
    st.markdown(detail["human_markdown"])
    st.download_button("下载可读 Markdown", detail["human_markdown"], file_name="historical_case_analysis.md", mime="text/markdown")
    if _debug_enabled():
        with st.expander("调试信息（来源、过滤记录与模型元数据）"):
            st.json(detail["debug"], expanded=False)
            st.download_button("下载调试 JSON", json.dumps(detail["debug"], ensure_ascii=False, indent=2), file_name="historical_case_analysis_debug.json", mime="application/json")
    if detail["debug"]["review_status"] == "pending":
        approval = st.checkbox("我已阅读正文并确认批准该案例分析", key="approve_case_analysis")
        if st.button("批准案例分析"):
            if not approval:
                st.error("请先完成审核确认。")
            else:
                try:
                    st.session_state["v5_case_analysis"] = approve_historical_case_analysis_review(database=database, analysis_id=detail["debug"]["analysis_id"])
                    st.success("案例分析已批准。")
                except Exception as exc:
                    st.error(f"批准失败：{exc}")


def _similar(database: str) -> None:
    st.caption("先选择已批准的当前企业检索卡，在本地召回少量相似历史企业；召回分数只用于排序。")
    cards = comparison_card_rows(database)
    current_cards = [row for row in cards if row["profile_type"] == "current"]
    card_options = {f"{row['enterprise_name']} · {row['review_status']}": row["card_id"] for row in current_cards}
    selected_label = st.selectbox("当前企业检索卡", [""] + list(card_options), key="similar_card")
    selected = card_options.get(selected_label, "")
    limit = st.slider("返回数量", 1, 10, 5)
    if st.button("本地检索相似案例", type="primary"):
        if not selected:
            st.error("请先选择当前企业检索卡。")
        else:
            try:
                st.session_state["v5_similar_matches"] = find_similar_profiles(database, selected, limit=limit)
            except Exception as exc:
                st.error(f"检索失败：{exc}")
    matches = st.session_state.get("v5_similar_matches", [])
    if matches:
        st.subheader("已召回的历史企业")
        st.dataframe(
            [
                {
                    "历史企业": match["historical_enterprise_name"],
                    "案例 ID": match["historical_case_id"],
                    "召回分数": round(match["score"], 4),
                    "主要匹配维度": "、".join(match["matched_dimensions"]) or "无",
                }
                for match in matches
            ],
            width="stretch",
            hide_index=True,
        )
        if _debug_enabled():
            with st.expander("开发调试：相似案例召回详情"):
                st.json(matches, expanded=False)


def _comparison_cards(database: str) -> None:
    st.caption("从已审核企业画像生成分维度检索卡；点击生成会调用 DeepSeek。")
    profiles = [row for row in profile_rows(database) if row["review_status"] == "approved"]
    profile_options = _profile_option_map(profiles)
    selected_label = st.selectbox("正式企业画像", [""] + list(profile_options), key="comparison_profile")
    selected = profile_options.get(selected_label, "")
    approve = st.checkbox("生成后直接批准该检索卡进入相似案例流程")
    confirmed = st.checkbox("我确认生成检索卡将调用 DeepSeek 并可能产生费用")
    if st.button("生成检索卡", type="primary"):
        if not selected:
            st.error("请先选择正式画像。")
        elif not confirmed:
            st.error("请先确认本次操作可能产生 DeepSeek 费用。")
        else:
            try:
                with st.spinner("正在生成分维度比较卡……"):
                    result = generate_profile_comparison_card(
                        database=database,
                        profile_id=selected,
                        approve=approve,
                )
                st.success("检索卡已保存。")
                st.session_state["v5_comparison_card"] = result
            except Exception as exc:
                st.error(f"比较卡生成失败：{exc}")
    st.subheader("已生成的检索卡")
    st.dataframe(
        [
            {
                "企业": row["enterprise_name"],
                "画像类型": "历史" if row["profile_type"] == "historical" else "当前",
                "审核状态": row["review_status"],
                "覆盖维度": row["dimensions"],
            }
            for row in comparison_card_rows(database)
        ],
        width="stretch",
        hide_index=True,
    )
    if _debug_enabled() and st.session_state.get("v5_comparison_card"):
        with st.expander("开发调试：本次 ComparisonCard 结果"):
            st.json(st.session_state["v5_comparison_card"], expanded=False)


def _detailed_report(database: str) -> None:
    st.caption(
        "本步骤先对已召回的少量历史画像进行详细比较，再生成当前企业核心风险判断。"
        "有历史候选时调用两次 DeepSeek；没有历史候选时跳过比较、只调用一次生成风险判断。"
    )
    cards = comparison_card_rows(database)
    current_cards = [row for row in cards if row["profile_type"] == "current"]
    card_options = {f"{row['enterprise_name']} · {row['review_status']}": row for row in current_cards}
    selected_label = st.selectbox("当前企业检索卡", [""] + list(card_options), key="detail_current_card")
    selected_card = card_options.get(selected_label, {}).get("card_id", "")
    selected_row = next((row for row in current_cards if row["card_id"] == selected_card), None)
    approved_industry_profiles = [
        row
        for row in industry_profile_rows(database)
        if row["review_status"] == "approved"
    ]
    industry_options = {
        f"{row['industry_name']} · {row['profile_id']}": row["profile_id"]
        for row in approved_industry_profiles
    }
    selected_industry_label = st.selectbox(
        "行业背景画像（可选）",
        [""] + list(industry_options),
        key="detail_industry_profile",
    )
    selected_industry_profile_id = industry_options.get(selected_industry_label, "")
    limit = st.slider("详细比较历史企业数量", 1, 5, 3)
    confirmed = st.checkbox("我确认详细比较和核心风险判断将调用 DeepSeek 并可能产生费用")
    if st.button("运行详细比较并生成报告", type="primary"):
        if selected_row is None:
            st.error("请先选择当前企业检索卡。")
        elif not confirmed:
            st.error("请先确认本次操作可能产生 DeepSeek 费用。")
        else:
            try:
                with st.spinner("正在执行详细画像比较……"):
                    result = run_detailed_review_report(
                        database=database,
                        current_profile_id=selected_row["profile_id"],
                        current_card_id=selected_row["card_id"],
                        limit=limit,
                        industry_profile_id=selected_industry_profile_id,
                    )
                st.session_state["v5_review_report"] = result
                st.success("详细比较、核心风险判断和报告已生成。")
            except Exception as exc:
                st.error(f"详细比较失败：{exc}")
    result = st.session_state.get("v5_review_report")
    if result:
        st.warning(result["report"]["disclaimer"])
        st.markdown(result["report_markdown"])
        first, second = st.columns(2)
        first.download_button(
            "下载可读报告 Markdown",
            result["report_markdown"],
            file_name="v5_review_report.md",
            mime="text/markdown",
        )
        if _debug_enabled():
            with st.expander("开发调试：报告 JSON"):
                second.download_button(
                    "下载报告 JSON",
                    json.dumps(result, ensure_ascii=False, indent=2),
                    file_name="v5_review_report.json",
                    mime="application/json",
                )
                st.json(result, expanded=False)


def _enterprise_workspace(database: str) -> None:
    st.header("企业画像")
    st.caption("按“生成候选 → 审核入库 → 查看画像”的顺序完成企业信息整理。")
    investigation, review, profiles = st.tabs(["1. 生成候选", "2. 审核并入库", "3. 查看企业画像"])
    with investigation:
        _investigation(database, show_header=False)
    with review:
        _profile_review(database, show_header=False)
    with profiles:
        _profiles(database)


def _industry_workspace(database: str) -> None:
    st.header("行业背景")
    st.caption("行业材料与企业材料独立保存；行业共性不能直接作为某家企业的事实。")
    ingestion, generation, profiles = st.tabs(
        ["1. 导入行业材料", "2. 生成并审核画像", "3. 查看行业画像"]
    )
    with ingestion:
        industry_id = st.text_input("行业 ID", "", key="industry_ingest_id")
        industry_name = st.text_input("行业名称", "", key="industry_ingest_name")
        source_date = st.text_input("报告日期（可选）", "", key="industry_source_date")
        uploads = st.file_uploader(
            "导入行业 PDF 或 HTML",
            type=["pdf", "html", "htm"],
            accept_multiple_files=True,
            key="industry_uploads",
        )
        if st.button("解析并写入行业证据库", type="primary"):
            if not industry_id.strip() or not industry_name.strip() or not uploads:
                st.error("请填写行业 ID、行业名称并选择文件。")
            else:
                try:
                    results = [
                        ingest_industry_source(
                            database=database,
                            industry_id=industry_id.strip(),
                            industry_name=industry_name.strip(),
                            upload_root=UPLOAD_ROOT,
                            filename=upload.name,
                            content=upload.getvalue(),
                            source_date=source_date.strip() or None,
                        )
                        for upload in uploads
                    ]
                    st.session_state["v5_industry_ingestion"] = results
                    st.success(f"已导入 {len(results)} 份行业材料。")
                except Exception as exc:
                    st.error(f"行业材料导入失败：{exc}")
        all_industry_sources = industry_source_rows(database)
        industry_options = {
            f"{row['industry_name']}（{row['industry_id']}）": row["industry_id"]
            for row in all_industry_sources
        }
        selected_industry_id = st.selectbox(
            "查看已导入行业材料的行业",
            [""] + list(industry_options),
            key="industry_source_view",
        )
        if selected_industry_id:
            selected_sources = [
                row
                for row in all_industry_sources
                if row["industry_id"] == industry_options[selected_industry_id]
            ]
            st.caption(
                f"已导入 {len(selected_sources)} 份材料，共 "
                f"{sum(row['evidence_units'] for row in selected_sources)} 个证据单元。"
            )
            for source in selected_sources:
                st.markdown(f"- **{source['title']}**：{source['evidence_units']} 个证据单元")
                if source["source_date"]:
                    st.caption(f"报告日期：{source['source_date']}")

    with generation:
        st.caption(
            "受控 ReAct 先搜索轻量目录并分批读取正文，再生成待审核画像。"
            "默认最多8次 Agent 模型调用、10次搜索、4次读取，累计12个正文切片；"
            "画像按四个双维度批次生成并做一次全局语义审核，第二阶段最多调用五次。"
        )
        sources = industry_source_rows(database)
        industries = {
            f"{row['industry_name']} · {row['industry_id']}": row
            for row in sources
        }
        selected_label = st.selectbox(
            "行业材料集合",
            [""] + list(industries),
            key="industry_generation_source",
        )
        selected = industries.get(selected_label)
        profile_id = st.text_input("行业画像 ID", "", key="industry_profile_id")
        confirmed = st.checkbox(
            "我确认生成行业画像将调用 DeepSeek 并可能产生费用",
            key="industry_generation_confirmed",
        )
        if st.button("生成待审核行业画像", type="primary"):
            if selected is None or not profile_id.strip():
                st.error("请选择行业材料集合并填写行业画像 ID。")
            elif not confirmed:
                st.error("请先确认本步骤会调用 DeepSeek。")
            else:
                try:
                    with st.spinner("正在生成行业背景画像……"):
                        result = generate_industry_profile_review(
                            database=database,
                            profile_id=profile_id.strip(),
                            industry_id=selected["industry_id"],
                            industry_name=selected["industry_name"],
                        )
                    st.session_state["v5_industry_generation"] = result
                    if result["status"] == "pending_review":
                        st.success("ReAct 调查完成，待审核行业画像已生成并保存。")
                    else:
                        st.warning(f"行业调查结束：{result['status']}")
                except Exception as exc:
                    st.error(f"行业画像生成失败：{exc}")
        pending = [
            row
            for row in industry_profile_rows(database)
            if row["review_status"] == "pending"
        ]
        pending_options = {
            f"{row['industry_name']} · {row['profile_id']}": row["profile_id"]
            for row in pending
        }
        pending_label = st.selectbox(
            "待审核行业画像",
            [""] + list(pending_options),
            key="pending_industry_profile",
        )
        pending_id = pending_options.get(pending_label, "")
        if pending_id:
            detail = industry_profile_detail(database, pending_id)
            st.dataframe(
                [
                    {
                        "维度": insight["dimension_id"],
                        "类型": insight["insight_type"],
                        "行业背景要点": insight["statement"],
                        "证据数": len(insight["evidence_refs"]),
                    }
                    for insight in detail["insights"]
                ],
                width="stretch",
                hide_index=True,
            )
            if st.button("批准并保存行业画像"):
                try:
                    approve_industry_profile_review(
                        database=database,
                        profile_id=pending_id,
                    )
                    st.success("行业画像已批准。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"行业画像批准失败：{exc}")

    with profiles:
        rows = industry_profile_rows(database)
        options = {
            f"{row['industry_name']}（{row['insights']} 条要点，{row['review_status']}）": row["profile_id"]
            for row in rows
        }
        selected_profile_label = st.selectbox(
            "行业画像",
            [""] + list(options),
            key="industry_profile_detail",
        )
        selected_profile_id = options.get(selected_profile_label, "")
        if selected_profile_id:
            detail = industry_profile_detail(database, selected_profile_id)
            if _debug_enabled():
                st.json(detail, expanded=False)
            else:
                st.subheader(detail["industry_name"])
                st.caption(
                    f"审核状态：{detail['review_status']} · "
                    f"{len(detail['insights'])} 条行业要点 · "
                    f"{len(detail['source_ids'])} 份来源材料"
                )
                dimension_labels = {
                    "development_stage": "行业发展阶段",
                    "market_size_and_growth": "市场规模与增长",
                    "technology_routes": "技术路线",
                    "value_chain": "产业链与价值链",
                    "competition_landscape": "竞争格局",
                    "commercialization": "商业化",
                    "policy_and_regulation": "政策与监管",
                    "industry_risks": "行业风险",
                }
                for dimension_id, label in dimension_labels.items():
                    insights = [
                        insight
                        for insight in detail["insights"]
                        if insight["dimension_id"] == dimension_id
                    ]
                    with st.expander(f"{label} · {len(insights)} 条要点", expanded=False):
                        if not insights:
                            st.caption("当前没有已提取要点。")
                        for insight in insights:
                            st.markdown(f"- {insight['statement']}")
                            context = " · ".join(
                                value
                                for value in (
                                    insight.get("insight_type"),
                                    insight.get("time_scope"),
                                    insight.get("geographic_scope"),
                                )
                                if value
                            )
                            if context:
                                st.caption(context)


def _advanced_approval_workspace(database: str) -> None:
    st.header("同行比较与审批报告")
    st.caption("按“配置口径 → 确认指标 → 生成并审批报告”操作。样本排名仅代表当前同行样本。")
    setup, values, reports, guideline_reports = st.tabs(
        ["1. 配置", "2. 确认指标", "3. 审批报告", "4. 授信指引报告"]
    )
    with setup:
        st.subheader("同行样本")
        cohort_id = st.text_input("同行样本 ID", key="approval_cohort_id")
        industry_id = st.text_input("行业 ID", key="approval_cohort_industry")
        cohort_name = st.text_input("样本名称", key="approval_cohort_name")
        fiscal_period = st.text_input("报告期", key="approval_cohort_period")
        case_ids = st.text_input("企业案例 ID（逗号分隔）", key="approval_cohort_cases")
        selection_rule = st.text_input("入样规则", key="approval_cohort_rule")
        if st.button("保存待审核同行样本"):
            try:
                create_peer_cohort(
                    database=database, cohort_id=cohort_id.strip(), industry_id=industry_id.strip(),
                    cohort_name=cohort_name.strip(), fiscal_period=fiscal_period.strip(),
                    company_case_ids=tuple(item.strip() for item in case_ids.split(",") if item.strip()),
                    selection_rule=selection_rule.strip(),
                )
                st.success("已保存待审核同行样本。")
            except Exception as exc:
                st.error(str(exc))
        rows = approval_workspace_rows(database)
        st.dataframe(rows["cohorts"], width="stretch", hide_index=True)
        pending_cohort = st.selectbox("批准同行样本", [""] + [item["cohort_id"] for item in rows["cohorts"] if item["review_status"] == "pending"])
        if st.button("批准所选同行样本", disabled=not pending_cohort):
            try:
                approve_peer_cohort(database=database, cohort_id=pending_cohort)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        st.subheader("可比指标与画像字段绑定")
        metric_id = st.text_input("指标 ID", key="approval_metric_id")
        direction = st.selectbox("审批方向", PROFILE_DOMAINS, key="approval_metric_domain")
        point_id = st.text_input("所属审批点 ID", key="approval_metric_point")
        metric_name = st.text_input("指标名称", key="approval_metric_name")
        comparison_direction = st.selectbox("比较方向", ["higher_is_better", "lower_is_better"])
        unit = st.text_input("统一单位", key="approval_metric_unit")
        value_scope = st.text_input("统计范围", key="approval_metric_scope")
        section_id = st.text_input("画像 section_id", key="approval_metric_section")
        field_id = st.text_input("画像 field_id", key="approval_metric_field")
        if st.button("保存待审核指标口径"):
            try:
                create_comparable_metric_definition(
                    database=database, metric_id=metric_id.strip(), approval_direction_id=direction,
                    approval_point_id=point_id.strip(), name=metric_name.strip(),
                    comparison_direction=comparison_direction, unit=unit.strip(), value_scope=value_scope.strip(),
                    section_id=section_id.strip(), field_id=field_id.strip(),
                )
                st.success("已保存待审核指标口径。")
            except Exception as exc:
                st.error(str(exc))
        st.dataframe(rows["metrics"], width="stretch", hide_index=True)
        pending_metric = st.selectbox("批准指标口径", [""] + [item["metric_id"] for item in rows["metrics"] if item["review_status"] == "pending"])
        if st.button("批准所选指标口径", disabled=not pending_metric):
            try:
                approve_comparable_metric_definition(database=database, metric_id=pending_metric)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        st.subheader("审批点定义")
        definition_id = st.text_input("审批点 ID", key="approval_point_id")
        definition_domain = st.selectbox("审批点方向", PROFILE_DOMAINS, key="approval_point_domain")
        definition_title = st.text_input("审批点标题", key="approval_point_title")
        definition_fields = st.text_input("允许企业字段（逗号分隔）", key="approval_point_fields")
        definition_metrics = st.text_input("允许指标 ID（逗号分隔）", key="approval_point_metrics")
        definition_dimensions = st.text_input("允许行业维度（逗号分隔）", key="approval_point_dimensions")
        if st.button("保存待审核审批点"):
            split = lambda text: tuple(item.strip() for item in text.split(",") if item.strip())
            try:
                create_approval_point_definition(
                    database=database, approval_point_id=definition_id.strip(), approval_direction_id=definition_domain,
                    title=definition_title.strip(), enterprise_field_ids=split(definition_fields),
                    metric_ids=split(definition_metrics), industry_dimension_ids=split(definition_dimensions),
                )
                st.success("已保存待审核审批点。")
            except Exception as exc:
                st.error(str(exc))

    with values:
        rows = approval_workspace_rows(database)
        cohorts = [item for item in rows["cohorts"] if item["review_status"] == "approved"]
        metrics = [item for item in rows["metrics"] if item["review_status"] == "approved"]
        profiles = [item for item in profile_rows(database) if item["review_status"] == "approved"]
        profile_options = _profile_option_map(profiles)
        cohort_id = st.selectbox("已批准同行样本", [""] + [item["cohort_id"] for item in cohorts], key="approval_value_cohort")
        profile_label = st.selectbox("已批准企业画像", [""] + list(profile_options), key="approval_value_profile")
        profile_id = profile_options.get(profile_label, "")
        metric_id = st.selectbox("已批准指标", [""] + [item["metric_id"] for item in metrics], key="approval_value_metric")
        if st.button("生成指标候选"):
            try:
                st.session_state["approval_metric_candidates"] = metric_value_candidates(
                    database=database, cohort_id=cohort_id, profile_id=profile_id, metric_id=metric_id
                )
            except Exception as exc:
                st.error(str(exc))
        candidates = st.session_state.get("approval_metric_candidates", [])
        if candidates:
            st.dataframe(candidates, width="stretch", hide_index=True)
            selected_item = st.selectbox("确认来源画像项", [item["source_item_id"] for item in candidates])
            if st.button("确认并保存已批准指标值"):
                try:
                    approve_metric_value_candidate(
                        database=database, cohort_id=cohort_id, profile_id=profile_id,
                        metric_id=metric_id, source_item_id=selected_item,
                    )
                    st.success("已保存已批准指标值。")
                except Exception as exc:
                    st.error(str(exc))

    with reports:
        rows = approval_workspace_rows(database)
        cohorts = [item for item in rows["cohorts"] if item["review_status"] == "approved"]
        profiles = [item for item in profile_rows(database) if item["review_status"] == "approved"]
        profile_options = _profile_option_map(profiles)
        industries = [item for item in industry_profile_rows(database) if item["review_status"] == "approved"]
        cohort_id = st.selectbox("同行样本", [""] + [item["cohort_id"] for item in cohorts], key="approval_report_cohort")
        profile_label = st.selectbox("企业画像", [""] + list(profile_options), key="approval_report_profile")
        profile_id = profile_options.get(profile_label, "")
        industry_profile_id = st.selectbox("行业背景", [""] + [item["profile_id"] for item in industries], key="approval_report_industry")
        domain_id = st.selectbox("审批方向", PROFILE_DOMAINS, key="approval_report_domain")
        report_id = st.text_input("方向报告 ID", key="approval_report_id")
        confirmed = st.checkbox("我确认生成方向报告将调用 DeepSeek 并可能产生费用", key="approval_report_confirm")
        if st.button("生成待审核方向报告"):
            if not confirmed:
                st.error("请先确认模型调用费用。")
            else:
                try:
                    result = generate_domain_approval_review(
                        database=database, report_id=report_id.strip(), cohort_id=cohort_id,
                        profile_id=profile_id, industry_profile_id=industry_profile_id, domain_id=domain_id,
                    )
                    st.session_state["approval_last_domain_report"] = result
                except Exception as exc:
                    st.error(str(exc))
        if st.session_state.get("approval_last_domain_report"):
            latest = st.session_state["approval_last_domain_report"]
            st.markdown(latest["report_markdown"])
            st.download_button(
                "下载方向报告 Markdown", latest["report_markdown"],
                file_name="domain_approval_report.md", mime="text/markdown",
            )
        st.dataframe(rows["domain_reports"], width="stretch", hide_index=True)
        pending = st.selectbox("批准方向报告", [""] + [item["report_id"] for item in rows["domain_reports"] if item["review_status"] == "pending"])
        if st.button("批准所选方向报告", disabled=not pending):
            try:
                approve_domain_approval_review(database=database, report_id=pending)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.subheader("综合核心风险判断")
        composite_id = st.text_input("综合报告 ID", key="approval_composite_id")
        composite_case_id = st.text_input("企业案例 ID", key="approval_composite_case")
        composite_confirmed = st.checkbox(
            "我确认生成综合报告将调用 DeepSeek 并可能产生费用",
            key="approval_composite_confirm",
        )
        if st.button("生成待审核综合报告"):
            if not composite_confirmed:
                st.error("请先确认模型调用费用。")
            else:
                try:
                    result = generate_composite_approval_review(
                        database=database, report_id=composite_id.strip(),
                        cohort_id=cohort_id, case_id=composite_case_id.strip(),
                    )
                    st.session_state["approval_last_composite_report"] = result
                except Exception as exc:
                    st.error(str(exc))
        if st.session_state.get("approval_last_composite_report"):
            latest = st.session_state["approval_last_composite_report"]
            st.markdown(latest["report_markdown"])
            st.download_button(
                "下载综合报告 Markdown", latest["report_markdown"],
                file_name="composite_approval_report.md", mime="text/markdown",
            )
        st.dataframe(rows["composite_reports"], width="stretch", hide_index=True)
        pending_composite = st.selectbox(
            "批准综合报告",
            [""] + [item["report_id"] for item in rows["composite_reports"] if item["review_status"] == "pending"],
        )
        if st.button("批准所选综合报告", disabled=not pending_composite):
            try:
                approve_composite_approval_review(database=database, report_id=pending_composite)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with guideline_reports:
        _guideline_approval_workspace(database)


def _approval_workspace(database: str) -> None:
    st.header("授信审批报告")
    st.caption("先按企业和审批方向查看结果；生成、审核和同行排名放在单独的工作区。")
    report_view, report_management = st.tabs(["查看企业审批报告", "生成、审核与同行排名"])
    with report_view:
        _guideline_approval_report_view(database)
    with report_management:
        _guideline_approval_workspace(database)


def _guideline_approval_report_view(database: str) -> None:
    """按企业、报告批次和指引方向查看单份审批报告。"""
    rows = approval_workspace_rows(database)
    sections = guideline_section_rows()
    section_titles = {item["section_id"]: item["title"] for item in sections}
    section_order = {item["section_id"]: index for index, item in enumerate(sections)}
    guideline_reports = [
        item for item in rows["domain_reports"] if item["domain_id"] in section_titles
    ]
    if not guideline_reports:
        st.info("尚未生成授信审批分方向报告。")
        return

    profiles = [item for item in profile_rows(database) if item["review_status"] == "approved"]
    enterprise_names = {str(item["case_id"]): str(item["enterprise_name"]) for item in profiles}
    enterprise_case_ids = sorted(
        {str(item["case_id"]) for item in guideline_reports},
        key=lambda case_id: enterprise_names.get(case_id, case_id),
    )
    enterprise_options = {
        enterprise_names.get(case_id, case_id): case_id for case_id in enterprise_case_ids
    }
    selected_enterprise = st.selectbox(
        "企业",
        list(enterprise_options),
        key="guideline_report_view_enterprise",
    )
    selected_case_id = enterprise_options[selected_enterprise]
    enterprise_reports = [
        item for item in guideline_reports if item["case_id"] == selected_case_id
    ]

    cohorts = {item["cohort_id"]: item for item in rows["cohorts"]}
    cohort_ids = sorted({str(item["cohort_id"]) for item in enterprise_reports})
    cohort_options = {
        f"{cohorts.get(cohort_id, {}).get('cohort_name', cohort_id)}（{cohorts.get(cohort_id, {}).get('fiscal_period', '报告期未标注')}）": cohort_id
        for cohort_id in cohort_ids
    }
    selected_cohort_label = st.selectbox(
        "报告批次（同行样本）",
        list(cohort_options),
        key="guideline_report_view_cohort",
    )
    selected_cohort_id = cohort_options[selected_cohort_label]
    batch_reports = [
        item for item in enterprise_reports if item["cohort_id"] == selected_cohort_id
    ]

    assessment_rows = [
        item
        for item in rows["overall_assessments"]
        if item["case_id"] == selected_case_id and item["cohort_id"] == selected_cohort_id
        and item["direction_results"]
    ]
    if assessment_rows:
        assessment = sorted(assessment_rows, key=lambda item: item["assessment_id"])[-1]
        detail = enterprise_overall_assessment_detail(database, assessment["assessment_id"])
        if detail:
            _render_final_approval_report(database, detail)
        return

    st.info("该企业当前批次尚未生成最终授信审批报告。可在“生成、审核与同行排名”中生成。")


def _guideline_approval_workspace(database: str) -> None:
    """按新手册提供授信指引方向报告和同方向排名入口。"""
    st.caption("企业画像领域只作为输入，最终报告按授信审批指引方向组织。")
    rows = approval_workspace_rows(database)
    sections = guideline_section_rows()
    section_options = {
        f"{item['section_id']} · {item['title']}": item["section_id"]
        for item in sections
    }
    cohorts = [item for item in rows["cohorts"] if item["review_status"] == "approved"]
    cohort_options = {item["cohort_id"]: item for item in cohorts}
    profiles = [item for item in profile_rows(database) if item["review_status"] == "approved"]
    profile_options = _profile_option_map(profiles)
    enterprise_names = {str(item["case_id"]): str(item["enterprise_name"]) for item in profiles}
    industries = [
        item for item in industry_profile_rows(database) if item["review_status"] == "approved"
    ]
    industry_options = {item["profile_id"]: item for item in industries}

    st.subheader("单企业分方向审批报告")
    section_label = st.selectbox(
        "授信指引方向",
        [""] + list(section_options),
        key="guideline_section_generate",
    )
    cohort_id = st.selectbox(
        "已批准同行样本",
        [""] + list(cohort_options),
        key="guideline_report_cohort",
    )
    profile_label = st.selectbox(
        "已批准企业画像",
        [""] + list(profile_options),
        key="guideline_report_profile",
    )
    profile_id = profile_options.get(profile_label, "")
    industry_profile_id = st.selectbox(
        "已批准行业背景画像",
        [""] + list(industry_options),
        key="guideline_report_industry",
    )
    report_id = st.text_input("分方向报告 ID", key="guideline_report_id")
    confirmed = st.checkbox(
        "我确认生成授信指引报告将调用 DeepSeek 并可能产生费用",
        key="guideline_report_confirm",
    )
    if st.button("生成待审核授信指引报告", key="guideline_report_generate"):
        if not section_label or not cohort_id or not profile_id or not industry_profile_id:
            st.error("请先选择方向、同行样本、企业画像和行业背景画像。")
        elif not report_id.strip():
            st.error("请填写分方向报告 ID。")
        elif not confirmed:
            st.error("请先确认模型调用费用。")
        else:
            try:
                result = generate_guideline_section_review(
                    database=database,
                    report_id=report_id.strip(),
                    cohort_id=cohort_id,
                    profile_id=profile_id,
                    industry_profile_id=industry_profile_id,
                    section_id=section_options[section_label],
                )
                st.session_state["guideline_last_section_report"] = result
                st.success("已生成待审核授信指引分方向报告。")
            except Exception as exc:
                st.error(f"授信指引报告生成失败：{exc}")
    latest = st.session_state.get("guideline_last_section_report")
    if latest:
        st.markdown(latest["report_markdown"])
        st.download_button(
            "下载授信指引分方向报告 Markdown",
            latest["report_markdown"],
            file_name="guideline_section_report.md",
            mime="text/markdown",
            key="guideline_report_download",
        )

    guideline_section_ids = {item["section_id"] for item in sections}
    guideline_reports = [
        item for item in rows["domain_reports"] if item["domain_id"] in guideline_section_ids
    ]
    pending_reports = [item for item in guideline_reports if item["review_status"] == "pending"]
    pending_report_options = {
        (
            f"{enterprise_names.get(item['case_id'], item['case_id'])} · "
            f"{next(section['title'] for section in sections if section['section_id'] == item['domain_id'])} · "
            f"{item['cohort_id']}"
        ): item["report_id"]
        for item in pending_reports
    }
    pending_report_label = st.selectbox(
        "批准待审核分方向报告",
        [""] + list(pending_report_options),
        key="guideline_report_pending",
    )
    pending_report = pending_report_options.get(pending_report_label, "")
    if st.button("批准所选授信指引报告", disabled=not pending_report, key="guideline_report_approve"):
        try:
            approve_domain_approval_review(database=database, report_id=pending_report)
            st.success("授信指引分方向报告已批准。")
            st.rerun()
        except Exception as exc:
            st.error(f"授信指引报告批准失败：{exc}")

    st.divider()
    st.subheader("同一授信指引方向的企业排名")
    rank_section_label = st.selectbox(
        "排名方向",
        [""] + list(section_options),
        key="guideline_ranking_section",
    )
    rank_cohort_id = st.selectbox(
        "排名同行样本",
        [""] + list(cohort_options),
        key="guideline_ranking_cohort",
    )
    rank_industry_profile_id = st.selectbox(
        "排名行业背景画像",
        [""] + list(industry_options),
        key="guideline_ranking_industry",
    )
    ranking_confirmed = st.checkbox(
        "我确认生成方向排名将调用 DeepSeek 并可能产生费用",
        key="guideline_ranking_confirm",
    )
    if st.button("生成待审核方向排名", key="guideline_ranking_generate"):
        if not rank_section_label or not rank_cohort_id or not rank_industry_profile_id:
            st.error("请先选择排名方向、同行样本和行业背景画像。")
        elif not ranking_confirmed:
            st.error("请先确认模型调用费用。")
        else:
            try:
                result = generate_direction_ranking_review(
                    database=database,
                    cohort_id=rank_cohort_id,
                    industry_profile_id=rank_industry_profile_id,
                    section_id=section_options[rank_section_label],
                )
                st.session_state["guideline_last_ranking"] = result
                st.success("已生成待审核方向排名。")
            except Exception as exc:
                st.error(f"方向排名生成失败：{exc}")
    latest_ranking = st.session_state.get("guideline_last_ranking")
    if latest_ranking:
        st.markdown(latest_ranking["ranking_markdown"])
        st.download_button(
            "下载方向排名 Markdown",
            latest_ranking["ranking_markdown"],
            file_name="guideline_direction_ranking.md",
            mime="text/markdown",
            key="guideline_ranking_download",
        )
    basis_industry_profile_id = rank_industry_profile_id
    if not basis_industry_profile_id and len(industry_options) == 1:
        basis_industry_profile_id = next(iter(industry_options))
    if rank_cohort_id and rank_section_label:
        ranking = direction_ranking_detail(
            database,
            rank_cohort_id,
            section_options[rank_section_label],
        )
        if ranking:
            st.caption(f"当前排名审核状态：{ranking['ranking']['review_status']}")
            st.markdown(ranking["ranking_markdown"])
            if basis_industry_profile_id:
                try:
                    basis = direction_ranking_basis_detail(
                        database=database,
                        cohort_id=rank_cohort_id,
                        industry_profile_id=basis_industry_profile_id,
                        section_id=section_options[rank_section_label],
                    )
                    if basis:
                        with st.expander("查看排名依据与企业比较卡", expanded=False):
                            _render_direction_ranking_basis(basis)
                except Exception as exc:
                    st.warning(f"当前无法重建排名依据：{exc}")
            else:
                st.info("请选择行业背景画像后查看排名依据与企业比较卡。")
            st.download_button(
                "下载当前方向排名 Markdown",
                ranking["ranking_markdown"],
                file_name=(
                    f"{rank_cohort_id}_{section_options[rank_section_label]}_ranking.md"
                ),
                mime="text/markdown",
                key="guideline_saved_ranking_download",
            )
            if ranking["ranking"]["review_status"] == "pending" and st.button(
                "批准当前方向排名",
                key="guideline_ranking_approve",
            ):
                try:
                    approve_direction_ranking_review(
                        database=database,
                        cohort_id=rank_cohort_id,
                        section_id=section_options[rank_section_label],
                    )
                    st.success("方向排名已批准。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"方向排名批准失败：{exc}")

    st.divider()
    st.subheader("最终授信审批报告")
    st.caption("生成一份包含总体建议、强弱约束统计、综合等级和11个方向结论的最终报告。")
    assessment_cohort_id = st.selectbox(
        "最终报告同行样本",
        [""] + list(cohort_options),
        key="overall_assessment_cohort",
    )
    assessment_profile_label = st.selectbox(
        "最终报告企业",
        [""] + list(profile_options),
        key="overall_assessment_profile",
    )
    assessment_profile_id = profile_options.get(assessment_profile_label, "")
    assessment_id = st.text_input("最终报告 ID", key="overall_assessment_id")
    assessment_confirmed = st.checkbox(
        "我确认生成最终报告将调用 DeepSeek 并可能产生费用",
        key="overall_assessment_confirm",
    )
    if st.button("生成待审核最终授信审批报告", key="overall_assessment_generate"):
        if not assessment_cohort_id or not assessment_profile_id or not assessment_id.strip():
            st.error("请先选择同行样本、企业并填写最终报告 ID。")
        elif not assessment_confirmed:
            st.error("请先确认模型调用费用。")
        else:
            try:
                result = generate_enterprise_overall_assessment_review(
                    database=database,
                    assessment_id=assessment_id.strip(),
                    cohort_id=assessment_cohort_id,
                    profile_id=assessment_profile_id,
                )
                st.session_state["overall_assessment_latest"] = result
                st.success("已生成待审核最终授信审批报告。")
            except Exception as exc:
                st.error(f"最终报告生成失败：{exc}")
    latest_assessment = st.session_state.get("overall_assessment_latest")
    if latest_assessment:
        st.markdown(latest_assessment["assessment_markdown"])
        st.download_button(
            "下载本次最终授信审批报告 Markdown",
            latest_assessment["assessment_markdown"],
            file_name="final_approval_report.md",
            mime="text/markdown",
            key="overall_assessment_latest_download",
        )

    assessment_rows = [
        item
        for item in approval_workspace_rows(database)["overall_assessments"]
        if item["direction_results"]
    ]
    assessment_options = {
        (
            f"{enterprise_names.get(item['case_id'], item['case_id'])} · "
            f"{item['cohort_id']} · {item['rating_level']}级 · {item['review_status']} · "
            f"{item['assessment_id']}"
        ): item["assessment_id"]
        for item in assessment_rows
    }
    selected_assessment_label = st.selectbox(
        "查看已生成最终报告",
        [""] + list(assessment_options),
        key="overall_assessment_detail",
    )
    selected_assessment_id = assessment_options.get(selected_assessment_label)
    if selected_assessment_id:
        detail = enterprise_overall_assessment_detail(database, selected_assessment_id)
        if detail:
            _render_final_approval_report(database, detail)
    pending_assessments = [
        item
        for item in assessment_rows
        if item["review_status"] == "pending" and not item["is_experimental"]
    ]
    pending_assessment = st.selectbox(
        "批准最终报告",
        [""] + [item["assessment_id"] for item in pending_assessments],
        key="overall_assessment_approve",
    )
    if st.button(
        "批准所选最终报告",
        disabled=not pending_assessment,
        key="overall_assessment_approve_button",
    ):
        try:
            approve_enterprise_overall_assessment_review(
                database=database,
                assessment_id=pending_assessment,
            )
            st.success("最终授信审批报告已批准。")
            st.rerun()
        except Exception as exc:
            st.error(f"最终报告批准失败：{exc}")


def _review_workspace(database: str) -> None:
    st.header("相似案例与报告")
    st.caption("先生成检索卡并召回历史企业，再对少量候选生成可读的辅助审查报告。")
    cards, similar, report = st.tabs(["1. 准备检索", "2. 查看相似案例", "3. 生成辅助报告"])
    with cards:
        _comparison_cards(database)
    with similar:
        _similar(database)
    with report:
        _detailed_report(database)


def _debug_tools(database: str) -> None:
    st.header("开发调试")
    st.caption("此区域保留原始数据和运行状态，默认不在业务工作区展示。")
    profiles = profile_rows(database)
    st.subheader("已入库企业画像")
    st.dataframe(profiles, width="stretch", hide_index=True)
    selected = st.selectbox("查看原始画像 JSON", [""] + [row["profile_id"] for row in profiles], key="debug_profile")
    if selected:
        st.json(profile_detail(database, selected), expanded=False)
    st.subheader("运行状态")
    state = {
        key: value
        for key, value in st.session_state.items()
        if key.startswith("v5_")
    }
    st.json(state, expanded=False)


def main() -> None:
    st.set_page_config(page_title="科技型企业风险辅助审查系统", layout="wide")
    st.title("科技型企业风险辅助审查系统")
    database, page, _ = _sidebar()
    if page == "材料管理":
        _sources(database)
    elif page == "企业画像":
        _enterprise_workspace(database)
    elif page == "行业背景":
        _industry_workspace(database)
    elif page == "授信审批报告":
        _approval_workspace(database)
    elif page == "历史案例":
        _historical_case_analysis(database)
    elif page == "相似案例与报告":
        _review_workspace(database)
    elif page == "审批配置（高级）":
        _advanced_approval_workspace(database)
    else:
        _debug_tools(database)


if __name__ == "__main__":
    main()
