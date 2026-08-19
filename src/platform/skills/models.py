"""Skill manifest 对应的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.platform.mcp.models import ToolReference


@dataclass(frozen=True)
class SkillLimits:
    max_tool_calls: int = 3
    timeout_seconds: int = 60


@dataclass(frozen=True)
class SkillDefinition:
    schema_version: int
    skill_id: str
    name: str
    version: str
    description: str
    owners: tuple[str, ...]
    enabled: bool
    priority: int
    applies_to: tuple[str, ...]
    activation_mode: str
    prompt_file: str
    prompt_text: str
    tools: tuple[ToolReference, ...]
    limits: SkillLimits
    required_context: tuple[str, ...]
    optional_context: tuple[str, ...]
    output_type: str
    external_tool_results: str
    path: Path
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSummary:
    skill_id: str
    name: str
    version: str
    enabled: bool
    priority: int
    applies_to: tuple[str, ...]


@dataclass(frozen=True)
class SkillRegistryReport:
    loaded: tuple[str, ...]
    errors: dict[str, str]
