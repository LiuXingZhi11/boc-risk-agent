from streamlit.testing.v1 import AppTest


def test_v5_streamlit_app_renders_workspace() -> None:
    app = AppTest.from_file("v5_app.py").run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "科技型企业风险辅助审查系统"
    assert app.sidebar.radio[0].value == "材料管理"
    assert app.sidebar.radio[0].options == [
        "材料管理",
        "企业画像",
        "行业背景",
        "授信审批报告",
    ]


def test_v5_data_source_empty_form_shows_error() -> None:
    app = AppTest.from_file("v5_app.py").run(timeout=20)
    case_input = next(item for item in app.text_input if item.label == "案例 ID")

    assert case_input.value == ""
    next(item for item in app.button if item.label == "解析并写入证据库").click().run()

    assert any("请填写案例 ID" in item.value for item in app.error)


def test_v5_investigation_defaults_empty_and_does_not_run() -> None:
    app = AppTest.from_file("v5_app.py").run(timeout=20)
    app.sidebar.radio[0].set_value("企业画像").run()

    case_input = next(item for item in app.text_input if item.label == "调查案例 ID")
    profile_type = next(item for item in app.selectbox if item.label == "画像类型")
    domains = next(item for item in app.multiselect if item.label == "调查领域")
    assert case_input.value == ""
    assert profile_type.value == ""
    assert domains.value == []

    next(item for item in app.button if item.label == "运行领域调查").click().run()

    assert any("选择画像类型" in item.value for item in app.error)


def test_v5_debug_workspace_is_hidden_until_enabled() -> None:
    app = AppTest.from_file("v5_app.py").run(timeout=20)

    assert "开发调试" not in app.sidebar.radio[0].options
    debug_toggle = next(item for item in app.sidebar.toggle if item.label == "显示开发调试工具")
    debug_toggle.set_value(True).run()

    assert "开发调试" in app.sidebar.radio[0].options
