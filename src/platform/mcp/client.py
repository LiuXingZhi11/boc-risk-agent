"""MCP Provider 后端协议。

真实的 langchain-mcp-adapters 连接将在后续 ToolResolver 阶段接入；
本阶段只规定 Provider Manager 所需的最小异步接口。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .models import MCPHealthStatus, MCPToolInfo


class MCPProviderBackend(Protocol):
    async def list_tools(self) -> Sequence[MCPToolInfo]:
        ...

    async def health_check(self) -> MCPHealthStatus:
        ...

    async def get_tools(self, names: Sequence[str]) -> Sequence[Any]:
        ...
