"""科技型企业风险辅助审查系统 V5 Streamlit 工作区。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import streamlit as st

from src.authorization import (
    business_prompt_files,
    can_approve_results,
    can_edit_business_prompts,
    can_run_profile_dimension,
    can_run_profile_domain,
    can_run_approval_section,
    can_view_debug,
    can_view_full_evidence,
    get_role_label,
    get_role_options,
)
from src.approval.repository import ApprovalRepository
from src.ontology.loader import load_manifest
from src.prompts import load_profile_dimension_mapping
from src.profiles.visual_card import ROLE_LABELS, STATUS_LABELS
from src.ui.v5_services import (
    approval_workspace_rows,
    approve_approval_point_definition,
    approve_comparable_metric_definition,
    approve_composite_approval_review,
    approve_domain_approval_review,
    approve_metric_value_candidate,
    approve_peer_cohort,
    approve_industry_profile_review,
    approve_profile_review,
    composite_approval_report_detail,
    create_approval_point_definition,
    create_comparable_metric_definition,
    create_peer_cohort,
    domain_approval_report_detail,
    generate_industry_profile_review,
    generate_enterprise_overall_assessment_review,
    generate_standalone_enterprise_overall_assessment_review,
    generate_composite_approval_review,
    generate_direction_ranking_review,
    generate_domain_approval_review,
    generate_guideline_section_review,
    generate_standalone_guideline_section_review,
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
    run_react_profile_investigation,
    source_rows,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "current_project.db"
UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"
_PROFILE_DIMENSION_MAPPING = load_profile_dimension_mapping()
PROFILE_DOMAINS = tuple(
    item["id"] for item in _PROFILE_DIMENSION_MAPPING["extraction_domains"]
)
PROFILE_DOMAIN_LABELS = {
    item["id"]: item["label"]
    for item in _PROFILE_DIMENSION_MAPPING["extraction_domains"]
}


def _ontology_labels() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    manifest = load_manifest()
    return (
        {item["id"]: item["label"] for item in manifest["fields"]},
        {item["id"]: item["label"] for item in manifest["fact_sections"]},
        {item["id"]: item["label"] for item in manifest["relations"]},
    )


def _render_value(value: object) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def _debug_enabled() -> bool:
    return bool(st.session_state.get("v5_show_debug", False))


def _current_role() -> str:
    return str(st.session_state.get("v5_role", "general_business"))


def _business_prompt_editor(role: str) -> None:
    if not can_edit_business_prompts(role):
        return
    files = business_prompt_files()
    if not files:
        return
    with st.sidebar.expander("业务提示词维护", expanded=False):
        selected = st.selectbox(
            "可维护文件",
            files,
            format_func=lambda value: Path(value).name,
            key="v5_prompt_file",
        )
        path = PROJECT_ROOT / selected
        if not path.is_file():
            st.error("提示词文件不存在")
            return
        content = path.read_text(encoding="utf-8")
        edited = st.text_area(
            "文件内容",
            value=content,
            height=220,
            key=f"v5_prompt_content:{selected}",
        )
        if st.button("保存业务提示词", key="v5_prompt_save"):
            path.write_text(edited, encoding="utf-8")
            load_manifest.cache_clear()
            st.success("已保存，新的业务规则将在后续调用中使用。")


def _profile_option_map(rows: list[dict[str, object]]) -> dict[str, str]:
    """将企业画像选项显示为中文企业名，内部仍返回稳定 profile_id。"""
    options: dict[str, str] = {}
    for row in rows:
        name = str(row["enterprise_name"])
        label = name
        if label in options:
            label = f"{name}（案例 {row['case_id']}）"
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
                st.write(f"评级判断：{point['judgment']}")
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


def _sidebar() -> tuple[str, str, str]:
    st.sidebar.header("项目配置")
    role_options = get_role_options()
    role = st.sidebar.selectbox(
        "使用身份",
        list(role_options),
        format_func=lambda value: role_options[value],
        key="v5_role",
    )
    st.sidebar.caption(f"当前身份：{get_role_label(role)}")
    _business_prompt_editor(role)
    database = st.sidebar.text_input("SQLite 数据库", str(DEFAULT_DATABASE))
    pages = ["材料管理", "企业画像", "行业背景", "客户风险评级报告"]
    page = st.sidebar.radio(
        "工作区",
        pages,
    )
    st.sidebar.caption("所有输出仅用于历史参考和信息核实辅助。")
    st.session_state["v5_show_debug"] = can_view_debug(role)
    return database, page, role


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
    if not can_approve_results(_current_role()):
        st.info("一般业务人员不能审核或写入正式企业画像，请联系高级业务人员。")
        return
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
    role = _current_role()
    if show_header:
        st.header("生成画像候选")
    st.caption("当前企业画像统一使用受控 ReAct；选择多个领域时，系统会按领域逐个调查并合并为一次待审核候选。")
    all_sources = source_rows(database)
    source_case_ids = sorted({str(row["case_id"]) for row in all_sources})
    profile_names = {
        str(row["case_id"]): str(row["enterprise_name"])
        for row in profile_rows(database)
    }
    source_titles = {
        case_id: next(
            (str(row["title"]) for row in all_sources if str(row["case_id"]) == case_id),
            "",
        )
        for case_id in source_case_ids
    }
    case_options = {
        case_id: (
            f"{profile_names[case_id]}（{case_id}）"
            if case_id in profile_names
            else f"{source_titles[case_id]}（{case_id}）"
        )
        for case_id in source_case_ids
    }
    case_labels = {label: case_id for case_id, label in case_options.items()}
    selected_case_label = st.selectbox(
        "调查案例",
        [""] + list(case_labels),
        key="investigation_case_id",
    )
    case_id = case_labels.get(selected_case_label, "")
    allowed_domains = [
        domain for domain in PROFILE_DOMAINS
        if can_run_profile_domain(role, domain)
    ]
    select_all = st.checkbox("选择全部可见领域", key="investigation_select_all")
    current_domains = [
        domain
        for domain in st.session_state.get("investigation_domains", [])
        if domain in allowed_domains
    ]
    st.session_state["investigation_domains"] = (
        list(allowed_domains) if select_all else current_domains
    )
    domains = st.multiselect(
        "调查领域",
        allowed_domains,
        format_func=lambda value: PROFILE_DOMAIN_LABELS.get(value, value),
        key="investigation_domains",
    )
    query = st.text_input("当前案例补充查询词")
    first, second = st.columns(2)
    max_catalog = first.number_input("每领域目录候选上限", 1, 50, 20)
    max_selected = second.number_input("每领域正文读取上限", 1, 10, 5)
    confirmed = st.checkbox("我确认本次操作将调用 DeepSeek 并可能产生费用")
    if st.button("运行领域调查", type="primary"):
        if not case_id or not domains:
            st.error("请先在材料管理导入企业材料、选择调查案例，并至少选择一个调查领域。")
        elif not confirmed:
            st.error("请先确认本次操作可能产生 DeepSeek 费用。")
        else:
            try:
                with st.spinner("正在执行证据调查和画像候选抽取……"):
                    result = run_react_profile_investigation(
                        database=database,
                        case_id=case_id.strip(),
                        domains=tuple(domains),
                        query=query.strip(),
                        max_catalog_items=int(max_catalog),
                        max_read_units=int(max_selected),
                        role=role,
                    )
                st.session_state["v5_profile_run"] = result
                st.success("领域调查完成，请切换到“审核并入库”确认候选事实。")
            except Exception as exc:
                st.error(f"领域调查失败：{exc}")
    result = st.session_state.get("v5_profile_run")
    if result:
        st.success("候选画像已保留在当前页面会话中。可直接到“审核并入库”勾选“使用本次页面调查结果”；如需稍后或在其他设备审核，请先下载 JSON。")
        if can_view_debug(role):
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
    role = _current_role()
    st.header("正式企业画像")
    st.caption("画像卡先展示已审核事实；主题分析单独调用 DeepSeek，结果仍保留事实和证据引用。")
    rows = profile_rows(database)
    profile_options = _profile_option_map(rows)
    selected_label = st.selectbox("企业画像", [""] + list(profile_options))
    selected = profile_options.get(selected_label, "")
    if selected:
        card = profile_visual_card(database, selected, role=role)
        if card is None:
            st.error("未找到企业画像。")
            return
        saved_analysis = st.session_state.get("v5_topic_analysis")
        if (
            saved_analysis
            and saved_analysis.get("profile_id") == selected
            and can_view_full_evidence(role)
        ):
            card = saved_analysis["card"]
        st.subheader(card["enterprise_name"])
        st.caption(f"案例 {card['case_id']} · 画像状态：{card['review_status']}")
        metrics = st.columns(4)
        metrics[0].metric("画像事实", card["item_count"])
        metrics[1].metric("关联证据", card["evidence_count"])
        metrics[2].metric("权威/结果事实", card["authority_fact_count"])
        metrics[3].metric("信息缺口", len(card["information_gaps"]))

        visible_dimensions = [
            dimension
            for dimension in card["dimensions"]
            if can_run_profile_dimension(role, dimension["dimension_id"])
        ]
        dimensions_by_id = {
            dimension["dimension_id"]: dimension for dimension in visible_dimensions
        }
        analysis_dimension = st.selectbox(
            "需要分析的画像领域",
            [dimension["dimension_id"] for dimension in visible_dimensions],
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
                            role=role,
                        )
                    st.session_state["v5_topic_analysis"] = {
                        "profile_id": selected,
                        **analysis_result,
                    }
                    if analysis_result["run"]["status"] == "completed":
                        st.success("主题分析已生成，可在对应领域展开查看。")
                        st.rerun()
                    else:
                        st.error(f"主题分析未完成：{analysis_result['run'].get('error', '未知错误')}")
                        read_topics = analysis_result["run"].get("read_topic_ids", ())
                        if read_topics:
                            st.caption("本次已读取主题：" + "、".join(read_topics))
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
                    st.text(topic["summary"])
                    if topic.get("analysis"):
                        st.markdown("**分析结论**")
                        st.text(topic["analysis"])
                    if topic.get("key_signals"):
                        st.markdown("**分析信号**")
                        for signal in topic["key_signals"]:
                            st.text(signal)
                    if topic.get("information_boundaries"):
                        st.markdown("**信息边界**")
                        for boundary in topic["information_boundaries"]:
                            st.text(boundary)
                    if topic["records"]:
                        st.dataframe(list(topic["records"]), width="stretch", hide_index=True)
                    with st.expander(
                        f"查看支撑事实（{len(topic['facts'])} 条，{topic['claim_count']} 条企业陈述）",
                        expanded=False,
                    ):
                        for fact in topic["facts"]:
                            st.markdown(f"**{fact['field_label']}**")
                            st.text(fact["value"])
                            st.caption(f"{fact['role_label']} · {fact['status_label']}")
                            if fact["context"]:
                                st.text(fact["context"])
                            if fact["evidence"]:
                                with st.expander(
                                    f"查看证据（{len(fact['evidence'])} 条）", expanded=False
                                ):
                                    for evidence in fact["evidence"]:
                                        heading = evidence["source_title"]
                                        if evidence["location"]:
                                            heading += f" · {evidence['location']}"
                                        st.markdown("**证据来源**")
                                        st.text(heading)
                                        st.caption("证据编号")
                                        st.text(evidence["evidence_unit_id"])
                                        if evidence["excerpt"]:
                                            st.text(evidence["excerpt"])

        if card["information_gaps"]:
            st.subheader("当前信息缺口")
            for gap in card["information_gaps"]:
                st.text(gap)
        if card["conflicts"]:
            st.subheader("待核实冲突")
            for conflict in card["conflicts"]:
                st.warning("发现待核实冲突")
                st.text(conflict)
        if _debug_enabled():
            with st.expander("调试信息（完整画像 JSON）"):
                st.json(profile_detail(database, selected), expanded=False)


def _render_approval_report_detail(database: str, detail: dict[str, object]) -> None:
    """以可读的指标名和折叠证据展示单份分方向风险评级报告。"""
    report = detail["report"]
    metric_names = {
        definition.metric_id: definition.name
        for definition in ApprovalRepository(database).list_metric_definitions()
    }
    st.caption(f"审核状态：{report['review_status']}")
    st.markdown(report["one_sentence_summary"])
    for index, point in enumerate(report["approval_points"], start=1):
        st.markdown(f"## 评级判断点 {index}：{point['title']}")
        st.markdown(f"- 企业现状：{_business_text(point['enterprise_observation'])}")
        if point["industry_benchmark"]:
            st.markdown(f"- 行业基准：{_business_text(point['industry_benchmark'])}")
        if point["peer_comparison"]:
            st.markdown(f"- 同行比较：{_business_text(point['peer_comparison'])}")
        st.markdown(f"- 评级判断：{_business_text(point['judgment'])}")
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
    ).replace("授信审批", "风险评级")


def _render_action_recommendations(values: list[str] | tuple[str, ...]) -> None:
    """将行动建议按编号和字段子项展示，兼容旧的长字符串。"""
    st.markdown("**后续行动建议**")
    for index, value in enumerate(values, start=1):
        parts = [
            part.strip()
            for part in re.split(r"[；;]\s*", _business_text(value))
            if part.strip()
        ]
        title = next(
            (
                part.split("：", 1)[1].strip()
                for part in parts
                if part.startswith("行动：")
            ),
            f"行动建议 {index}",
        )
        st.markdown(f"**{index}. {title}**")
        body_parts = [part for part in parts if not part.startswith("行动：")]
        if body_parts:
            for part in body_parts:
                st.markdown(f"- {part}")
        else:
            st.markdown(f"- {_business_text(value)}")


def _render_final_approval_report(database: str, detail: dict[str, object]) -> None:
    """展示一份面向业务人员的最终报告，并折叠其分方向依据。"""
    role = _current_role()
    assessment = detail["assessment"]
    direction_results = assessment["direction_results"]
    if not direction_results:
        st.info("该记录为旧版综合评定，未包含11个方向的通过状态。请重新生成客户风险评级报告。")
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
        item["section_id"]: item["title"]
        for item in guideline_section_rows()
        if can_run_approval_section(role, item["section_id"])
    }
    columns = st.columns(4)
    columns[0].metric("推进建议", recommendation_labels[assessment["recommendation"]])
    columns[1].metric("客户风险评级", assessment["rating_level"])
    columns[2].metric("强约束不通过", f"{assessment['strong_constraint_failed_count']} 条")
    columns[3].metric("弱约束不通过", f"{assessment['weak_constraint_failed_count']} 条")
    st.caption(f"审核状态：{assessment['review_status']}")
    st.write(assessment["overall_judgment"])

    for title, values in (
        ("主要风险", assessment["core_risks"]),
        ("缓释因素", assessment["mitigating_factors"]),
        ("判断边界", assessment["rating_boundaries"]),
        ("后续行动建议", assessment["verification_priorities"]),
    ):
        if values:
            if title == "后续行动建议":
                _render_action_recommendations(values)
            else:
                st.markdown(f"**{title}**：" + "；".join(_business_text(value) for value in values))

    st.subheader("风险评级指引逐条结论")
    for result in direction_results:
        section_id = result["section_id"]
        if section_id not in section_titles:
            continue
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
                    st.caption("评级判断点、同行排名与原文证据")
                    _render_approval_report_detail(database, report_detail)

    if can_view_full_evidence(role):
        st.download_button(
            "下载客户风险评级报告 Markdown",
            detail["assessment_markdown"],
            file_name=f"{assessment['assessment_id']}.md",
            mime="text/markdown",
            key="final_approval_report_download",
        )


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
    role = _current_role()
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
            if can_approve_results(role) and st.button("批准并保存行业画像"):
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


def _approval_workspace(database: str) -> None:
    st.header("客户风险评级报告")
    st.caption("先按企业和风险评级方向查看结果；生成、审核和同行排名放在单独的工作区。")
    report_view, report_management = st.tabs(["查看企业风险评级报告", "生成、审核与同行排名"])
    with report_view:
        _guideline_approval_report_view(database)
    with report_management:
        _guideline_approval_workspace(database)


def _guideline_approval_report_view(database: str) -> None:
    """按企业、报告批次和指引方向查看单份风险评级报告。"""
    role = _current_role()
    rows = approval_workspace_rows(database)
    sections = guideline_section_rows()
    section_titles = {
        item["section_id"]: item["title"]
        for item in sections
        if can_run_approval_section(role, item["section_id"])
    }
    section_order = {item["section_id"]: index for index, item in enumerate(sections)}
    guideline_reports = [
        item for item in rows["domain_reports"] if item["domain_id"] in section_titles
    ]
    if not guideline_reports:
        st.info("尚未生成风险评级分方向报告。")
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
    cohort_ids = list(dict.fromkeys(item["cohort_id"] for item in enterprise_reports))
    cohort_options = {}
    for cohort_id in cohort_ids:
        if cohort_id is None:
            label = "单企业分析（未进行同行比较）"
        else:
            cohort = cohorts.get(cohort_id, {})
            label = (
                f"{cohort.get('cohort_name', cohort_id)}"
                f"（{cohort.get('fiscal_period', '报告期未标注')}）"
            )
        cohort_options[label] = cohort_id
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

    st.info("该企业当前批次尚未生成客户风险评级报告。可在“生成、审核与同行排名”中生成。")


def _peer_cohort_management(
    database: str,
    rows: dict,
    profiles: list[dict],
    industries: list[dict],
    role: str,
) -> None:
    st.subheader("同行样本管理")
    profile_names = {
        str(item["case_id"]): str(item["enterprise_name"])
        for item in profiles
        if item["review_status"] == "approved"
    }
    cohorts = list(rows["cohorts"])
    if can_approve_results(role):
        with st.expander("新建同行样本组", expanded=False):
            industry_options = {
                f"{item['industry_name']}（{item['industry_id']}）": item["industry_id"]
                for item in industries
                if item["review_status"] == "approved"
            }
            cohort_id = st.text_input("样本组 ID", key="cohort_manage_id")
            cohort_name = st.text_input("样本组名称", key="cohort_manage_name")
            industry_label = st.selectbox(
                "对应行业",
                [""] + list(industry_options),
                key="cohort_manage_industry",
            )
            fiscal_period = st.text_input(
                "样本报告期", key="cohort_manage_period", placeholder="例如 2025"
            )
            selection_rule = st.text_area(
                "入样规则",
                key="cohort_manage_rule",
                placeholder="例如：智能机器人行业已批准企业画像，报告期为 2025 年",
            )
            company_options = {
                f"{name}（{case_id}）": case_id
                for case_id, name in sorted(profile_names.items(), key=lambda item: item[1])
            }
            selected_companies = st.multiselect(
                "同行企业（至少选择两家）",
                list(company_options),
                key="cohort_manage_companies",
            )
            if st.button("创建待审核同行样本组", key="cohort_manage_create"):
                existing_ids = {str(item["cohort_id"]) for item in cohorts}
                if not cohort_id.strip() or not cohort_name.strip() or not industry_label:
                    st.error("请填写样本组 ID、名称并选择对应行业。")
                elif cohort_id.strip() in existing_ids:
                    st.error("样本组 ID 已存在，请创建新的版本 ID。")
                elif not fiscal_period.strip() or not selection_rule.strip():
                    st.error("请填写样本报告期和入样规则。")
                elif len(selected_companies) < 2:
                    st.error("同行样本组至少需要两家企业。")
                else:
                    create_peer_cohort(
                        database=database,
                        cohort_id=cohort_id.strip(),
                        industry_id=industry_options[industry_label],
                        cohort_name=cohort_name.strip(),
                        fiscal_period=fiscal_period.strip(),
                        company_case_ids=tuple(company_options[label] for label in selected_companies),
                        selection_rule=selection_rule.strip(),
                    )
                    st.success("同行样本组已创建，等待高级业务人员批准。")
                    st.rerun()
    else:
        st.caption("当前身份只能查看已批准同行样本，不能创建或批准样本组。")

    pending = [item for item in cohorts if item["review_status"] == "pending"]
    if can_approve_results(role) and pending:
        pending_options = {
            f"{item['cohort_name']}（{item['cohort_id']}）": item["cohort_id"]
            for item in pending
        }
        pending_label = st.selectbox(
            "待批准同行样本组",
            [""] + list(pending_options),
            key="cohort_manage_pending",
        )
        pending_id = pending_options.get(pending_label, "")
        if st.button(
            "批准所选同行样本组",
            disabled=not pending_id,
            key="cohort_manage_approve",
        ):
            approve_peer_cohort(database=database, cohort_id=pending_id)
            st.success("同行样本组已批准，可用于风险评级报告和排名。")
            st.rerun()

    if cohorts:
        st.caption("当前同行样本组")
        for cohort in cohorts:
            status = {"approved": "已批准", "pending": "待审核"}.get(
                cohort["review_status"], cohort["review_status"]
            )
            company_names = "、".join(
                profile_names.get(case_id, case_id)
                for case_id in cohort["company_case_ids"]
            )
            with st.expander(
                f"{cohort['cohort_name']} · {status} · {len(cohort['company_case_ids'])} 家企业",
                expanded=False,
            ):
                st.text(f"样本组 ID：{cohort['cohort_id']}")
                st.text(f"行业：{cohort['industry_id']} · 报告期：{cohort['fiscal_period']}")
                st.text(f"入样规则：{cohort['selection_rule']}")
                st.text(f"企业：{company_names}")


def _guideline_approval_workspace(database: str) -> None:
    role = _current_role()
    """按新手册提供风险评级方向报告和同方向排名入口。"""
    st.caption("企业画像领域只作为输入，最终报告按风险评级指引方向组织。")
    rows = approval_workspace_rows(database)
    sections = guideline_section_rows()
    section_options = {
        f"{item['section_id']} · {item['title']}": item["section_id"]
        for item in sections
        if can_run_approval_section(role, item["section_id"])
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

    _peer_cohort_management(database, rows, profiles, industries, role)

    st.subheader("单企业分方向风险评级报告")
    report_mode = st.radio(
        "分方向分析模式",
        ["单企业分析", "同行增强分析"],
        horizontal=True,
        key="guideline_report_mode",
    )
    section_label = st.selectbox(
        "风险评级指引方向",
        [""] + list(section_options),
        key="guideline_section_generate",
    )
    cohort_id = ""
    if report_mode == "同行增强分析":
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
        "我确认生成风险评级指引报告将调用 DeepSeek 并可能产生费用",
        key="guideline_report_confirm",
    )
    if st.button("生成待审核风险评级指引报告", key="guideline_report_generate"):
        if not section_label or not profile_id or not industry_profile_id:
            st.error("请先选择方向、企业画像和行业背景画像。")
        elif report_mode == "同行增强分析" and not cohort_id:
            st.error("同行增强分析需要选择同行样本。")
        elif not report_id.strip():
            st.error("请填写分方向报告 ID。")
        elif not confirmed:
            st.error("请先确认模型调用费用。")
        else:
            try:
                if report_mode == "单企业分析":
                    result = generate_standalone_guideline_section_review(
                        database=database,
                        report_id=report_id.strip(),
                        profile_id=profile_id,
                        industry_profile_id=industry_profile_id,
                        section_id=section_options[section_label],
                        role=role,
                    )
                else:
                    result = generate_guideline_section_review(
                        database=database,
                        report_id=report_id.strip(),
                        cohort_id=cohort_id,
                        profile_id=profile_id,
                        industry_profile_id=industry_profile_id,
                        section_id=section_options[section_label],
                        role=role,
                    )
                st.session_state["guideline_last_section_report"] = result
                st.success("已生成待审核风险评级指引分方向报告。")
            except Exception as exc:
                st.error(f"风险评级指引报告生成失败：{exc}")
    latest = st.session_state.get("guideline_last_section_report")
    if latest:
        st.markdown(latest["report_markdown"])
        st.download_button(
            "下载风险评级指引分方向报告 Markdown",
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
        f"{item['cohort_id'] or '单企业分析'}"
        ): item["report_id"]
        for item in pending_reports
    }
    pending_report_label = st.selectbox(
        "批准待审核分方向报告",
        [""] + list(pending_report_options),
        key="guideline_report_pending",
    )
    pending_report = pending_report_options.get(pending_report_label, "")
    if can_approve_results(role) and st.button("批准所选风险评级指引报告", disabled=not pending_report, key="guideline_report_approve"):
        try:
            approve_domain_approval_review(database=database, report_id=pending_report)
            st.success("风险评级指引分方向报告已批准。")
            st.rerun()
        except Exception as exc:
            st.error(f"风险评级指引报告批准失败：{exc}")

    st.divider()
    st.subheader("同一风险评级指引方向的企业排名")
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
                    role=role,
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
                        role=role,
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
            if ranking["ranking"]["review_status"] == "pending" and can_approve_results(role) and st.button(
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
    st.subheader("客户风险评级报告")
    st.caption("单企业分析不要求同行排名；同行增强分析会将可用排名作为补充信息。")
    assessment_mode = st.radio(
        "最终评级模式",
        ["单企业分析", "同行增强分析"],
        horizontal=True,
        key="overall_assessment_mode",
    )
    assessment_cohort_id = ""
    if assessment_mode == "同行增强分析":
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
    if st.button("生成待审核客户风险评级报告", key="overall_assessment_generate"):
        if not assessment_profile_id or not assessment_id.strip():
            st.error("请先选择企业并填写最终报告 ID。")
        elif assessment_mode == "同行增强分析" and not assessment_cohort_id:
            st.error("同行增强分析需要选择同行样本。")
        elif not assessment_confirmed:
            st.error("请先确认模型调用费用。")
        else:
            try:
                if assessment_mode == "单企业分析":
                    result = generate_standalone_enterprise_overall_assessment_review(
                        database=database,
                        assessment_id=assessment_id.strip(),
                        profile_id=assessment_profile_id,
                    )
                else:
                    result = generate_enterprise_overall_assessment_review(
                        database=database,
                        assessment_id=assessment_id.strip(),
                        cohort_id=assessment_cohort_id,
                        profile_id=assessment_profile_id,
                    )
                st.session_state["overall_assessment_latest"] = result
                st.success("已生成待审核客户风险评级报告。")
            except Exception as exc:
                st.error(f"最终报告生成失败：{exc}")
    latest_assessment = st.session_state.get("overall_assessment_latest")
    if latest_assessment:
        st.markdown(latest_assessment["assessment_markdown"])
        st.download_button(
            "下载本次客户风险评级报告 Markdown",
            latest_assessment["assessment_markdown"],
            file_name="customer_risk_rating_report.md",
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
            f"{item['cohort_id'] or '单企业分析'} · {item['rating_level']} · {item['review_status']} · "
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
    if can_approve_results(role) and st.button(
        "批准所选最终报告",
        disabled=not pending_assessment,
        key="overall_assessment_approve_button",
    ):
        try:
            approve_enterprise_overall_assessment_review(
                database=database,
                assessment_id=pending_assessment,
            )
            st.success("客户风险评级报告已批准。")
            st.rerun()
        except Exception as exc:
            st.error(f"最终报告批准失败：{exc}")


def main() -> None:
    st.set_page_config(page_title="科技型企业风险辅助审查系统", layout="wide")
    st.title("科技型企业风险辅助审查系统")
    database, page, _role = _sidebar()
    if page == "材料管理":
        _sources(database)
    elif page == "企业画像":
        _enterprise_workspace(database)
    elif page == "行业背景":
        _industry_workspace(database)
    elif page == "客户风险评级报告":
        _approval_workspace(database)
    else:
        st.error("未找到对应工作区")


if __name__ == "__main__":
    main()
