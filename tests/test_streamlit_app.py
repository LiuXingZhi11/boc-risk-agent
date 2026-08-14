from __future__ import annotations

from streamlit.testing.v1 import AppTest


def test_streamlit_app_renders_review_page() -> None:
    app = AppTest.from_file("app.py").run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "金融风险案例辅助审查原型"
    assert app.sidebar.radio[0].value == "新案例审查"


def test_streamlit_app_can_switch_to_case_library() -> None:
    app = AppTest.from_file("app.py").run(timeout=20)
    app.sidebar.radio[0].set_value("案例库").run(timeout=20)

    assert not app.exception
    assert app.header[0].value == "案例库"
