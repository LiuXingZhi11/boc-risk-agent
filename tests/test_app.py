from __future__ import annotations

import app


def test_session_state_initialization_is_idempotent() -> None:
    state = {}

    app.initialize_session_state(state)
    first = dict(state)
    app.initialize_session_state(state)

    assert state == first
    assert "current_thread_id" in state
    assert "last_report" in state
