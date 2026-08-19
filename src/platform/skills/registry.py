"""Skill 注册表和中央启用配置。"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import yaml

from .loader import DEFAULT_SKILLS_ROOT, SkillLoader
from .models import SkillDefinition, SkillRegistryReport, SkillSummary


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENABLED_PATH = PROJECT_ROOT / "config" / "enabled_skills.yaml"


def load_enabled_skill_ids(path: str | Path = DEFAULT_ENABLED_PATH) -> frozenset[str]:
    config_path = Path(path)
    if not config_path.exists():
        return frozenset()
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    values = config.get("enabled_skills", [])
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError("enabled_skills 必须是字符串数组")
    return frozenset(values)


def skills_enabled() -> bool:
    return os.getenv("SKILLS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SkillRegistry:
    def __init__(
        self,
        loader: SkillLoader | None = None,
        *,
        enabled_ids: Iterable[str] | None = None,
    ) -> None:
        self.loader = loader or SkillLoader(DEFAULT_SKILLS_ROOT)
        if enabled_ids is not None:
            self.enabled_ids: frozenset[str] | None = frozenset(enabled_ids)
        elif self.loader.root.resolve() == DEFAULT_SKILLS_ROOT.resolve():
            self.enabled_ids = load_enabled_skill_ids()
        else:
            # 临时目录和离线测试使用 manifest 内的 enabled 字段。
            self.enabled_ids = None
        self._skills: dict[str, SkillDefinition] = {}
        self._errors: dict[str, str] = {}

    def refresh(self) -> SkillRegistryReport:
        self._skills.clear()
        self._errors.clear()
        for directory in self.loader.discover():
            try:
                skill = self.loader.load_directory(directory)
                if skill.skill_id in self._skills:
                    raise ValueError(f"重复 Skill id：{skill.skill_id}")
                self._skills[skill.skill_id] = skill
            except Exception as exc:
                self._errors[str(directory)] = f"{type(exc).__name__}: {exc}"
        return SkillRegistryReport(
            loaded=tuple(sorted(self._skills)),
            errors=dict(self._errors),
        )

    def list_skills(self, enabled_only: bool = True) -> list[SkillSummary]:
        skills = list(self._skills.values())
        if enabled_only:
            if self.enabled_ids is None:
                skills = [skill for skill in skills if skill.enabled]
            else:
                skills = [skill for skill in skills if skill.skill_id in self.enabled_ids]
        return [
            SkillSummary(
                skill_id=skill.skill_id,
                name=skill.name,
                version=skill.version,
                enabled=(skill.skill_id in self.enabled_ids)
                if self.enabled_ids is not None
                else skill.enabled,
                priority=skill.priority,
                applies_to=skill.applies_to,
            )
            for skill in sorted(skills, key=lambda item: (item.priority, item.skill_id))
        ]

    def get(self, skill_id: str) -> SkillDefinition:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"Skill 不存在：{skill_id}") from exc

    def get_for_agent(self, agent_scope: str) -> list[SkillDefinition]:
        return [
            self._skills[summary.skill_id]
            for summary in self.list_skills(enabled_only=True)
            if agent_scope in summary.applies_to
        ]

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)
