"""MCP Provider 注册和 Tool 目录初始化。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .client import MCPProviderBackend
from .config import mcp_enabled
from .models import MCPHealthStatus, MCPServerConfig, MCPToolInfo, ToolReference
from .tool_catalog import MCPToolCatalog


class MCPProviderManager:
    """管理 Provider 配置和动态 Tool Catalog。

    Provider 的具体连接实现通过 backend 注入，平台层不写死某一家供应商。
    """

    def __init__(
        self,
        configs: Sequence[MCPServerConfig] = (),
        providers: Mapping[str, MCPProviderBackend] | None = None,
        *,
        enabled: bool = False,
        catalog: MCPToolCatalog | None = None,
    ) -> None:
        self.configs = {config.server_id: config for config in configs}
        self.providers = dict(providers or {})
        self.enabled = enabled
        self.catalog = catalog or MCPToolCatalog()
        self.initialized = False

    @classmethod
    def from_config(
        cls,
        configs: Sequence[MCPServerConfig],
        *,
        enabled: bool | None = None,
    ) -> "MCPProviderManager":
        from .providers.langchain_adapter import LangChainMCPProvider

        providers = {
            config.server_id: LangChainMCPProvider(config)
            for config in configs
        }
        return cls(configs, providers, enabled=mcp_enabled() if enabled is None else enabled)

    async def initialize(self) -> None:
        self.catalog.clear()
        if not self.enabled:
            self.initialized = True
            return
        for server_id, config in self.configs.items():
            if not config.enabled:
                continue
            provider = self.providers.get(server_id)
            if provider is None:
                raise ValueError(f"MCP Server 未注册 Provider backend：{server_id}")
            discovered = tuple(await provider.list_tools())
            normalized = tuple(
                MCPToolInfo(
                    server_id=server_id,
                    name=tool.name,
                    description=tool.description,
                    input_schema=dict(tool.input_schema),
                )
                for tool in discovered
            )
            self.catalog.register_many(normalized)
        self.initialized = True

    async def list_servers(self) -> list[MCPServerConfig]:
        return list(self.configs.values())

    async def list_tools(self, server_id: str) -> list[MCPToolInfo]:
        if server_id not in self.configs:
            raise KeyError(f"MCP Server 不存在：{server_id}")
        return self.catalog.list_tools(server_id)

    async def get_tools(self, requested: Sequence[ToolReference]) -> list[Any]:
        if not self.enabled:
            raise RuntimeError("MCP 当前未启用")
        if not self.initialized:
            raise RuntimeError("MCP Provider Manager 尚未 initialize")
        grouped: dict[str, list[str]] = {}
        for reference in requested:
            self.catalog.get(reference)
            grouped.setdefault(reference.server, []).append(reference.name)
        resolved: list[Any] = []
        for server_id, names in grouped.items():
            resolved.extend(await self.providers[server_id].get_tools(names))
        return resolved

    async def health_check(self, server_id: str) -> MCPHealthStatus:
        config = self.configs.get(server_id)
        if config is None:
            raise KeyError(f"MCP Server 不存在：{server_id}")
        if not config.enabled:
            return MCPHealthStatus(server_id=server_id, status="disabled")
        provider = self.providers.get(server_id)
        if provider is None:
            return MCPHealthStatus(server_id=server_id, status="unavailable")
        return await provider.health_check()
