"""从环境变量和项目根目录的 .env 读取运行配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


@dataclass(frozen=True)
class Settings:
    """模型和外部服务运行配置。"""

    api_key: str | None = field(default=None, repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    embedding_model: str = "BAAI/bge-base-zh-v1.5"
    model_cache_dir: str = str(PROJECT_ROOT / "models")


def get_settings() -> Settings:
    """读取当前进程环境；调用时读取以便测试和 CLI 覆盖环境变量。"""
    _load_dotenv()
    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5"),
        model_cache_dir=os.getenv("MODEL_CACHE_DIR", str(PROJECT_ROOT / "models")),
    )
