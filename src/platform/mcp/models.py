"""MCP 平台层使用的稳定数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class ToolReference:
    """Skill 对外部 MCP Tool 的声明。"""

    server: str
    name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.server}:{self.name}"


@dataclass(frozen=True)
class MCPToolInfo:
    """从 Provider 动态发现的 Tool 元数据。"""

    server_id: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.server_id}:{self.name}"


@dataclass(frozen=True)
class MCPServerConfig:
    server_id: str
    provider: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    auth_env: str | None = None
    enabled: bool = False
    permissions: dict[str, Any] = field(default_factory=dict)


class MCPErrorCode(StrEnum):
    AUTH_FAILED = "AUTH_FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INVALID_INPUT = "INVALID_INPUT"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MCPHealthStatus:
    server_id: str
    status: str
    error_code: MCPErrorCode | None = None
    message: str | None = None
