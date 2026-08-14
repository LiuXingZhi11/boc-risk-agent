from types import SimpleNamespace

import pytest

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig


def _response(content, *, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )


class _SequenceClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )

    def create(self, **kwargs):
        self.calls += 1
        return next(self.responses)


def test_empty_response_retries_up_to_success_even_when_general_retries_disabled(monkeypatch):
    client = _SequenceClient([_response(""), _response("  "), _response('{"ok": true}')])
    monkeypatch.setattr("src.llm.deepseek_client._create_client", lambda config: client)
    monkeypatch.setattr("src.llm.deepseek_client.time.sleep", lambda seconds: None)

    result = call_deepseek(
        [{"role": "user", "content": "test"}],
        GenerationConfig(max_retries=0),
    )

    assert result["ok"] is True
    assert client.calls == 3
    assert result["api_meta"]["attempt_count"] == 3
    assert result["api_meta"]["empty_response_count"] == 2


def test_empty_response_stops_after_three_attempts(monkeypatch):
    client = _SequenceClient([_response(""), _response(""), _response("")])
    monkeypatch.setattr("src.llm.deepseek_client._create_client", lambda config: client)
    monkeypatch.setattr("src.llm.deepseek_client.time.sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="已尝试 3 次"):
        call_deepseek(
            [{"role": "user", "content": "test"}],
            GenerationConfig(max_retries=0),
        )

    assert client.calls == 3


def test_nonempty_parse_failure_respects_general_retry_setting(monkeypatch):
    client = _SequenceClient([_response("not-json"), _response('{"ok": true}')])
    monkeypatch.setattr("src.llm.deepseek_client._create_client", lambda config: client)
    monkeypatch.setattr("src.llm.deepseek_client.time.sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="已尝试 1 次"):
        call_deepseek(
            [{"role": "user", "content": "test"}],
            GenerationConfig(max_retries=0),
        )

    assert client.calls == 1


def test_length_response_is_not_misreported_as_empty(monkeypatch):
    client = _SequenceClient([_response("", finish_reason="length")])
    monkeypatch.setattr("src.llm.deepseek_client._create_client", lambda config: client)

    with pytest.raises(RuntimeError, match="输出达到 max_tokens=10000"):
        call_deepseek(
            [{"role": "user", "content": "test"}],
            GenerationConfig(max_tokens=10000, max_retries=0),
        )

    assert client.calls == 1
