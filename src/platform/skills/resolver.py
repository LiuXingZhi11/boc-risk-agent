"""把显式请求的 Skill 解析为 Agent 可消费的运行时计划。"""

from __future__ import annotations

import os

from src.platform.mcp.models import ToolReference

from .models import SkillDefinition
from .registry import SkillRegistry
from .runtime import SkillRuntimeContext, SkillRuntimeLimits, SkillRuntimePlan


class SkillResolver:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def resolve(
        self,
        *,
        agent_scope: str,
        skill_ids: tuple[str, ...] | list[str] = (),
        runtime_context: SkillRuntimeContext | None = None,
    ) -> SkillRuntimePlan:
        skills: list[SkillDefinition] = []
        for skill_id in skill_ids:
            skill = self.registry.get(skill_id)
            if not self._is_enabled(skill_id):
                raise ValueError(f"Skill 尚未启用：{skill_id}")
            if agent_scope not in skill.applies_to:
                raise ValueError(f"Skill 不适用于 Agent scope：{skill_id} / {agent_scope}")
            self._check_context(skill, runtime_context)
            skills.append(skill)

        tool_refs: list[ToolReference] = []
        seen: set[str] = set()
        prompt_sections: list[str] = []
        required_context: set[str] = set()
        for skill in sorted(skills, key=lambda item: (item.priority, item.skill_id)):
            prompt_sections.append(
                f'<skill id="{skill.skill_id}" version="{skill.version}">\n'
                f"{skill.prompt_text.strip()}\n"
                "</skill>"
            )
            required_context.update(skill.required_context)
            for reference in skill.tools:
                if reference.qualified_name not in seen:
                    seen.add(reference.qualified_name)
                    tool_refs.append(reference)

        max_tools = int(os.getenv("SKILL_MAX_TOOLS_PER_AGENT", "12"))
        if len(tool_refs) > max_tools:
            raise ValueError(f"Skill Tool 数量超过平台上限：{len(tool_refs)} > {max_tools}")

        limits = SkillRuntimeLimits(
            max_tool_calls=min((skill.limits.max_tool_calls for skill in skills), default=0),
            timeout_seconds=min((skill.limits.timeout_seconds for skill in skills), default=0),
        )
        return SkillRuntimePlan(
            skill_ids=tuple(skill.skill_id for skill in skills),
            prompt_sections=tuple(prompt_sections),
            tool_refs=tuple(tool_refs),
            required_context=frozenset(required_context),
            limits=limits,
        )

    def _is_enabled(self, skill_id: str) -> bool:
        if self.registry.enabled_ids is not None:
            return skill_id in self.registry.enabled_ids
        return self.registry.get(skill_id).enabled

    @staticmethod
    def _check_context(
        skill: SkillDefinition,
        context: SkillRuntimeContext | None,
    ) -> None:
        missing = [
            key
            for key in skill.required_context
            if context is None or context.get(key) in (None, "")
        ]
        if missing:
            raise ValueError(
                f"Skill 缺少运行时上下文：{skill.skill_id}: {', '.join(sorted(missing))}"
            )
