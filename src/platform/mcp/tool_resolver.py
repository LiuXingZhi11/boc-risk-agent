"""根据 Skill 的 ToolReference 解析并包装外部 Tool。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool

from src.platform.skills.runtime import SkillRuntimeContext

from .audit import InMemoryAuditSink
from .models import ToolReference
from .registry import MCPProviderManager
from .tool_proxy import MCPToolProxy, ToolCallBudget


class MCPToolResolver:
    def __init__(
        self,
        manager: MCPProviderManager,
        *,
        audit_sink: InMemoryAuditSink | None = None,
        max_result_chars: int = 12000,
        platform_max_tool_calls: int = 10,
    ) -> None:
        self.manager = manager
        self.audit_sink = audit_sink or InMemoryAuditSink()
        self.max_result_chars = max_result_chars
        self.platform_max_tool_calls = platform_max_tool_calls

    async def resolve(
        self,
        references: Sequence[ToolReference],
        *,
        skill_id: str,
        skill_version: str,
        runtime_context: SkillRuntimeContext,
        max_tool_calls: int,
        timeout_seconds: int,
    ) -> list[BaseTool]:
        if len(references) > self.platform_max_tool_calls:
            raise ValueError(
                f"MCP Tool 数量超过平台上限：{len(references)} > {self.platform_max_tool_calls}"
            )
        raw_tools = await self.manager.get_tools(references)
        if len(raw_tools) != len(references):
            raise ValueError("MCP Provider 返回的 Tool 数量与请求不一致")
        resolved: list[BaseTool] = []
        budget = ToolCallBudget(min(max_tool_calls, self.platform_max_tool_calls))
        for reference, raw_tool in zip(references, raw_tools):
            info = self.manager.catalog.get(reference)
            proxy = MCPToolProxy(
                raw_tool,
                info,
                run_id=runtime_context.run_id,
                skill_id=skill_id,
                skill_version=skill_version,
                max_tool_calls=budget.limit,
                timeout_seconds=timeout_seconds,
                max_result_chars=self.max_result_chars,
                subject_name=runtime_context.company_name,
                subject_identifier=runtime_context.unified_social_credit_code,
                audit_sink=self.audit_sink,
                budget=budget,
            )
            resolved.append(proxy.as_langchain_tool())
        return resolved
