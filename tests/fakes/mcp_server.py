"""平台测试使用的 Fake MCP Provider，不连接真实外部服务。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.platform.mcp.models import MCPHealthStatus, MCPToolInfo


class FakeRawTool:
    def __init__(self, response: object = None, *, delay_seconds: float = 0) -> None:
        self.response = response
        self.delay_seconds = delay_seconds

    async def ainvoke(self, payload: object) -> object:
        import asyncio

        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if callable(self.response):
            return self.response(payload)
        return self.response


class FakeMCPProvider:
    def __init__(
        self,
        server_id: str,
        tools: Sequence[MCPToolInfo],
        raw_tools: dict[str, object] | None = None,
    ) -> None:
        self.server_id = server_id
        self.tools = tuple(tools)
        self.raw_tools = raw_tools or {}

    async def list_tools(self) -> Sequence[MCPToolInfo]:
        return self.tools

    async def health_check(self) -> MCPHealthStatus:
        return MCPHealthStatus(server_id=self.server_id, status="ok")

    async def get_tools(self, names: Sequence[str]) -> Sequence[dict[str, Any]]:
        return [
            self.raw_tools.get(name, {"server_id": self.server_id, "name": name})
            for name in names
        ]
