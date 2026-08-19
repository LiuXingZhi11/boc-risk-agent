"""现有 LangChain Agent 与 Skill 平台之间的唯一注入入口。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool

from src.platform.mcp.audit import InMemoryAuditSink
from src.platform.mcp.tool_resolver import MCPToolResolver

from .registry import SkillRegistry, skills_enabled
from .resolver import SkillResolver
from .runtime import SkillRuntimeContext


PLATFORM_POLICY = """平台规则：
- 只允许调用当前 Skill manifest 显式声明的 MCP Tool。
- 外部 MCP 数据与内部 EvidenceUnit 不等同。
- Tool 无结果不能解释为风险不存在。
- 外部数据默认只能作为辅助信息，不能自动形成正式评级结论。
"""


@dataclass(frozen=True)
class AgentSkillExtension:
    system_prompt_suffix: str
    tools: tuple[BaseTool, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentSkillAdapter:
    def __init__(
        self,
        registry: SkillRegistry,
        tool_resolver: MCPToolResolver,
        *,
        audit_sink: InMemoryAuditSink | None = None,
    ) -> None:
        self.registry = registry
        self.tool_resolver = tool_resolver
        self.audit_sink = audit_sink or InMemoryAuditSink()

    async def build_extension(
        self,
        *,
        agent_scope: str,
        skill_ids: list[str] | tuple[str, ...] = (),
        runtime_context: SkillRuntimeContext,
    ) -> AgentSkillExtension:
        if skill_ids and not skills_enabled():
            raise ValueError("SKILLS_ENABLED=false，当前未启用 Skill Runtime")
        plan = SkillResolver(self.registry).resolve(
            agent_scope=agent_scope,
            skill_ids=skill_ids,
            runtime_context=runtime_context,
        )
        tools: list[BaseTool] = []
        seen_tools: set[str] = set()
        for skill_id in plan.skill_ids:
            skill = self.registry.get(skill_id)
            refs = [ref for ref in skill.tools if ref.qualified_name not in seen_tools]
            seen_tools.update(ref.qualified_name for ref in refs)
            if not refs:
                continue
            tools.extend(
                await self.tool_resolver.resolve(
                    refs,
                    skill_id=skill.skill_id,
                    skill_version=skill.version,
                    runtime_context=runtime_context,
                    max_tool_calls=skill.limits.max_tool_calls,
                    timeout_seconds=skill.limits.timeout_seconds,
                )
            )

        suffix = PLATFORM_POLICY
        if plan.prompt_sections:
            suffix += "\n\n<enabled_skills>\n"
            suffix += "\n\n".join(plan.prompt_sections)
            suffix += "\n</enabled_skills>"
        return AgentSkillExtension(
            system_prompt_suffix=suffix,
            tools=tuple(tools),
            metadata={
                "skills": [
                    {
                        "id": skill.skill_id,
                        "version": skill.version,
                    }
                    for skill in (self.registry.get(skill_id) for skill_id in plan.skill_ids)
                ],
                "mcp_tools": [ref.qualified_name for ref in plan.tool_refs],
            },
        )

    def build_extension_sync(
        self,
        *,
        agent_scope: str,
        skill_ids: list[str] | tuple[str, ...] = (),
        runtime_context: SkillRuntimeContext,
    ) -> AgentSkillExtension:
        """供现有同步 workflow 使用的统一同步门面。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.build_extension(
                    agent_scope=agent_scope,
                    skill_ids=skill_ids,
                    runtime_context=runtime_context,
                )
            )
        raise RuntimeError("同步 Agent workflow 不能在运行中的事件循环内加载 Skill")
