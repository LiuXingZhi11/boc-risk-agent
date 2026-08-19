"""读取统一模型配置及其他运行参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.yaml"


def _load_dotenv_fallback(path: Path) -> None:
    """在未安装 python-dotenv 时读取简单的 KEY=VALUE .env 文件。"""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_dotenv_fallback(env_path)
    else:
        load_dotenv(env_path, override=False)


def load_model_config(path: str | Path | None = None) -> dict[str, str]:
    """读取统一的模型配置文件。"""
    config_path = Path(path) if path is not None else MODEL_CONFIG_PATH
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("模型配置文件顶层必须是对象")
    return {
        str(key): str(value).strip()
        for key, value in raw.items()
        if value is not None
    }


@dataclass(frozen=True)
class Settings:
    """模型和外部服务运行配置。"""

    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"


def get_settings() -> Settings:
    """读取当前进程环境；调用时读取以便测试和 CLI 覆盖环境变量。"""
    _load_dotenv()
    model_config = load_model_config()
    return Settings(
        api_key=model_config.get("api_key") or os.getenv("DEEPSEEK_API_KEY"),
        base_url=model_config.get("base_url") or os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ),
        model=model_config.get("model") or os.getenv(
            "DEEPSEEK_MODEL", "deepseek-v4-flash"
        ),
    )
