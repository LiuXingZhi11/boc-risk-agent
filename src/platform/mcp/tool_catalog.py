"""MCP Tool 动态目录。"""

from __future__ import annotations

from .models import MCPToolInfo, ToolReference


class MCPToolCatalog:
    def __init__(self) -> None:
        self._tools: dict[str, MCPToolInfo] = {}

    def register(self, tool: MCPToolInfo) -> None:
        key = tool.qualified_name
        if key in self._tools:
            raise ValueError(f"重复 MCP Tool：{key}")
        self._tools[key] = tool

    def register_many(self, tools: list[MCPToolInfo] | tuple[MCPToolInfo, ...]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, reference: ToolReference) -> MCPToolInfo:
        try:
            return self._tools[reference.qualified_name]
        except KeyError as exc:
            raise KeyError(f"MCP Tool 不存在：{reference.qualified_name}") from exc

    def list_tools(self, server_id: str | None = None) -> list[MCPToolInfo]:
        tools = list(self._tools.values())
        if server_id is not None:
            tools = [tool for tool in tools if tool.server_id == server_id]
        return sorted(tools, key=lambda tool: tool.qualified_name)

    def clear(self) -> None:
        self._tools.clear()
