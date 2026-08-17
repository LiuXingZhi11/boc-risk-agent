from streamlit.testing.v1 import AppTest


def test_v5_streamlit_app_renders_workspace() -> None:
    app = AppTest.from_file("v5_app.py").run(timeout=20)
    assert not app.exception
    assert app.title[0].value == "科技型企业风险辅助审查系统"
    assert app.sidebar.radio[0].options == [
        "材料管理",
        "企业画像",
        "行业背景",
        "客户风险评级报告",
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
    case_input = next(item for item in app.selectbox if item.label == "调查案例")
    domains = next(item for item in app.multiselect if item.label == "调查领域")
    assert case_input.value == ""
    assert domains.value == []
    next(item for item in app.button if item.label == "运行领域调查").click().run()
    assert any("选择调查案例" in item.value for item in app.error)
