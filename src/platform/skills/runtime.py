"""Skill 运行时上下文和解析计划。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.platform.mcp.models import ToolReference


@dataclass(frozen=True)
class SkillRuntimeContext:
    run_id: str
    case_id: str | None = None
    company_name: str | None = None
    unified_social_credit_code: str | None = None
    domain: str | None = None
    industry_name: str | None = None
    agent_scope: str = ""
    user_role: str | None = None

    def get(self, key: str) -> Any:
        return getattr(self, key)


@dataclass(frozen=True)
class SkillRuntimeLimits:
    max_tool_calls: int
    timeout_seconds: int


@dataclass(frozen=True)
class SkillRuntimePlan:
    skill_ids: tuple[str, ...]
    prompt_sections: tuple[str, ...]
    tool_refs: tuple[ToolReference, ...]
    required_context: frozenset[str]
    limits: SkillRuntimeLimits
