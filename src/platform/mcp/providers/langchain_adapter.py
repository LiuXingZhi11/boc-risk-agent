"""基于官方 langchain-mcp-adapters 的通用 Provider 后端。

本模块只在 MCP Provider 被显式启用时导入官方依赖和读取认证环境变量。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from src.platform.mcp.models import MCPHealthStatus, MCPServerConfig, MCPToolInfo


class LangChainMCPProvider:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._client: Any | None = None

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise RuntimeError(
                "使用真实 MCP Provider 前请安装 langchain-mcp-adapters"
            ) from exc

        connection: dict[str, Any] = {"transport": self.config.transport}
        if self.config.url:
            connection["url"] = self.config.url
        if self.config.command:
            connection["command"] = self.config.command
        if self.config.args:
            connection["args"] = list(self.config.args)
        if self.config.auth_env:
            token = os.getenv(self.config.auth_env)
            if not token:
                raise RuntimeError(f"MCP Provider 缺少环境变量：{self.config.auth_env}")
            connection["headers"] = {"Authorization": f"Bearer {token}"}
        self._client = MultiServerMCPClient({self.config.server_id: connection})
        return self._client

    async def _load_tools(self) -> list[Any]:
        client = await self._get_client()
        return list(await client.get_tools())

    async def list_tools(self) -> Sequence[MCPToolInfo]:
        tools = await self._load_tools()
        return tuple(
            MCPToolInfo(
                server_id=self.config.server_id,
                name=str(tool.name),
                description=str(getattr(tool, "description", "") or ""),
                input_schema=_tool_schema(tool),
            )
            for tool in tools
        )

    async def health_check(self) -> MCPHealthStatus:
        try:
            await self._load_tools()
        except Exception:
            return MCPHealthStatus(server_id=self.config.server_id, status="unavailable")
        return MCPHealthStatus(server_id=self.config.server_id, status="ok")

    async def get_tools(self, names: Sequence[str]) -> Sequence[Any]:
        tools = await self._load_tools()
        by_name = {str(tool.name): tool for tool in tools}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise KeyError(f"MCP Tool 不存在：{', '.join(missing)}")
        return [by_name[name] for name in names]


def _tool_schema(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        return dict(args_schema.model_json_schema())
    args = getattr(tool, "args", {})
    return {"properties": dict(args)} if isinstance(args, dict) else {}
