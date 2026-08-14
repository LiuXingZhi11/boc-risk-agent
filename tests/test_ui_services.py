from __future__ import annotations

from src.ui.services import _public_json


class ValueObject:
    value = {"type": "human_input"}


def test_public_json_converts_interrupt_like_values() -> None:
    assert _public_json({"interrupt": ValueObject()}) == {
        "interrupt": {"type": "human_input"}
    }
