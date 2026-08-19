"""Skill manifest V1 校验和对象构造。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.platform.mcp.models import ToolReference

from .models import SkillDefinition, SkillLimits


AGENT_SCOPES = frozenset(
    {
        "profile.discovery",
        "profile.recovery",
        "profile.topic_analysis",
        "industry.discovery",
        "direction.review",
        "report.final",
    }
)
CONTEXT_KEYS = frozenset(
    {
        "run_id",
        "case_id",
        "company_name",
        "unified_social_credit_code",
        "domain",
        "industry_name",
        "agent_scope",
        "user_role",
    }
)
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class SkillValidationError(ValueError):
    pass


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillValidationError(f"{field_name} 必须是非空字符串")
    return value.strip()


def _string_list(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SkillValidationError(f"{field_name} 必须是字符串数组")
    return tuple(item.strip() for item in value if item.strip())


def build_skill_definition(
    manifest: dict[str, Any],
    *,
    skill_dir: Path,
    prompt_text: str,
) -> SkillDefinition:
    if not isinstance(manifest, dict):
        raise SkillValidationError("skill.yaml 顶层必须是对象")
    required = {"schema_version", "id", "name", "version", "description"}
    missing = required - set(manifest)
    if missing:
        raise SkillValidationError("缺少字段：" + ", ".join(sorted(missing)))

    if manifest["schema_version"] != 1:
        raise SkillValidationError("schema_version 只能是 1")
    skill_id = _string(manifest["id"], "id")
    if not _ID_RE.fullmatch(skill_id):
        raise SkillValidationError("id 只能使用小写字母、数字和下划线，且以字母开头")
    if skill_dir.name != "_template" and skill_dir.name != skill_id:
        raise SkillValidationError("Skill 目录名必须与 id 一致")
    version = _string(manifest["version"], "version")
    if not _VERSION_RE.fullmatch(version):
        raise SkillValidationError("version 必须符合 major.minor.patch")

    owners = _string_list(manifest.get("owners", []), "owners")
    applies_to = _string_list(manifest.get("applies_to", []), "applies_to")
    unknown_scopes = set(applies_to) - AGENT_SCOPES
    if unknown_scopes:
        raise SkillValidationError("未知 applies_to：" + ", ".join(sorted(unknown_scopes)))

    activation = manifest.get("activation", {}) or {}
    if not isinstance(activation, dict) or activation.get("mode", "explicit") != "explicit":
        raise SkillValidationError("activation.mode 第一版必须是 explicit")
    prompt = manifest.get("prompt", {}) or {}
    if not isinstance(prompt, dict):
        raise SkillValidationError("prompt 必须是对象")
    prompt_file = _string(prompt.get("file", "SKILL.md"), "prompt.file")
    prompt_path = (skill_dir / prompt_file).resolve()
    if skill_dir.resolve() not in prompt_path.parents:
        raise SkillValidationError("prompt.file 必须位于 Skill 目录内")
    if not prompt_text.strip():
        raise SkillValidationError("SKILL.md 不能为空")

    tools_raw = manifest.get("tools", []) or []
    if not isinstance(tools_raw, list):
        raise SkillValidationError("tools 必须是数组")
    tools: list[ToolReference] = []
    seen_tools: set[str] = set()
    for item in tools_raw:
        if not isinstance(item, dict):
            raise SkillValidationError("每个 Tool 声明必须是对象")
        reference = ToolReference(
            server=_string(item.get("server"), "tools.server"),
            name=_string(item.get("name"), "tools.name"),
        )
        if reference.qualified_name in seen_tools:
            raise SkillValidationError(f"重复 Tool 声明：{reference.qualified_name}")
        seen_tools.add(reference.qualified_name)
        tools.append(reference)

    limits = manifest.get("limits", {}) or {}
    if not isinstance(limits, dict):
        raise SkillValidationError("limits 必须是对象")
    max_tool_calls = limits.get("max_tool_calls", 3)
    timeout_seconds = limits.get("timeout_seconds", 60)
    if not isinstance(max_tool_calls, int) or max_tool_calls <= 0:
        raise SkillValidationError("limits.max_tool_calls 必须是正整数")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise SkillValidationError("limits.timeout_seconds 必须是正整数")

    context = manifest.get("context", {}) or {}
    if not isinstance(context, dict):
        raise SkillValidationError("context 必须是对象")
    required_context = _string_list(context.get("required", []), "context.required")
    optional_context = _string_list(context.get("optional", []), "context.optional")
    unknown_context = (set(required_context) | set(optional_context)) - CONTEXT_KEYS
    if unknown_context:
        raise SkillValidationError("未知 context key：" + ", ".join(sorted(unknown_context)))
    overlap = set(required_context) & set(optional_context)
    if overlap:
        raise SkillValidationError("required/optional 不能重复：" + ", ".join(sorted(overlap)))

    output = manifest.get("output", {}) or {}
    persistence = manifest.get("persistence", {}) or {}
    if not isinstance(output, dict) or not isinstance(persistence, dict):
        raise SkillValidationError("output 和 persistence 必须是对象")

    return SkillDefinition(
        schema_version=1,
        skill_id=skill_id,
        name=_string(manifest["name"], "name"),
        version=version,
        description=_string(manifest["description"], "description"),
        owners=owners,
        enabled=bool(manifest.get("enabled", False)),
        priority=int(manifest.get("priority", 100)),
        applies_to=applies_to,
        activation_mode="explicit",
        prompt_file=prompt_file,
        prompt_text=prompt_text,
        tools=tuple(tools),
        limits=SkillLimits(max_tool_calls=max_tool_calls, timeout_seconds=timeout_seconds),
        required_context=required_context,
        optional_context=optional_context,
        output_type=_string(output.get("type", "advisory"), "output.type"),
        external_tool_results=_string(
            persistence.get("external_tool_results", "trace_only"),
            "persistence.external_tool_results",
        ),
        path=skill_dir,
        manifest=dict(manifest),
    )
