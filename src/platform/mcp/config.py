"""读取 MCP Provider 配置，不负责建立真实网络连接。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import MCPServerConfig


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MCP_CONFIG_PATH = PROJECT_ROOT / "config" / "mcp_servers.yaml"


def load_mcp_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_MCP_CONFIG_PATH
    if not config_path.exists():
        return {"providers": {}}
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("MCP 配置的 providers 必须是对象")
    return config


def load_server_configs(path: str | Path | None = None) -> tuple[MCPServerConfig, ...]:
    providers = load_mcp_config(path).get("providers", {})
    configs: list[MCPServerConfig] = []
    for server_id, raw in providers.items():
        if not isinstance(raw, dict):
            raise ValueError(f"MCP Server 配置非法：{server_id!r}")
        configs.append(
            MCPServerConfig(
                server_id=str(server_id),
                provider=str(raw.get("provider", "generic")),
                transport=str(raw.get("transport", "http")),
                url=raw.get("url"),
                command=raw.get("command"),
                args=tuple(str(item) for item in raw.get("args", ())),
                auth_env=raw.get("auth_env"),
                enabled=bool(raw.get("enabled", False)),
                permissions=dict(raw.get("permissions", {}) or {}),
            )
        )
    return tuple(configs)


def mcp_enabled() -> bool:
    return os.getenv("MCP_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
