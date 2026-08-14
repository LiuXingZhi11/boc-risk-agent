import pytest

from src.llm.generation_config import GenerationConfig
from src.config.settings import get_settings


def test_project_default_model_is_deepseek_v4_flash(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    assert GenerationConfig().model == "deepseek-v4-flash"
    assert GenerationConfig().mode == "thinking"
    assert get_settings().model == "deepseek-v4-flash"


def test_thinking_and_sampling_parameters_are_mutually_exclusive() -> None:
    thinking = GenerationConfig(mode="thinking", temperature=0.2, reasoning_effort="high")
    thinking_request = thinking.request_kwargs()
    assert "reasoning_effort" in thinking_request
    assert "temperature" not in thinking_request

    sampling = GenerationConfig(mode="sampling", temperature=0.4, reasoning_effort="high")
    sampling_request = sampling.request_kwargs()
    assert "temperature" in sampling_request
    assert "reasoning_effort" not in sampling_request


def test_generation_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="mode"):
        GenerationConfig(mode="unknown")
    with pytest.raises(ValueError, match="temperature"):
        GenerationConfig(temperature=2.1)
    with pytest.raises(ValueError, match="0 至 2"):
        GenerationConfig(max_retries=3)
