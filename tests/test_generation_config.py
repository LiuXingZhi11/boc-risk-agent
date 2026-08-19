import pytest

from src.llm.generation_config import GenerationConfig
from src.config import settings as settings_module
from src.config.settings import get_settings


def test_project_default_model_is_deepseek_v4_flash(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    assert GenerationConfig().model == "deepseek-v4-flash"
    assert GenerationConfig().mode == "thinking"
    assert get_settings().model == "deepseek-v4-flash"


def test_model_config_file_is_canonical(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "model_config.yaml"
    config_path.write_text(
        "provider: deepseek\n"
        "model: test-model\n"
        "base_url: https://example.invalid/v1\n"
        "api_key: test-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("DEEPSEEK_MODEL", "ignored-by-file")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://ignored.invalid")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ignored-key")

    settings = get_settings()

    assert settings.model == "test-model"
    assert settings.base_url == "https://example.invalid/v1"
    assert settings.api_key == "test-key"
    assert GenerationConfig().model == "test-model"


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
