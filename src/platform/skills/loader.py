"""Skill 目录发现和加载。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from .models import SkillDefinition
from .schema import build_skill_definition


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILLS_ROOT = PROJECT_ROOT / "skills"


class SkillLoader:
    def __init__(self, root: str | Path = DEFAULT_SKILLS_ROOT) -> None:
        self.root = Path(root)

    def discover(self) -> list[Path]:
        if not self.root.exists():
            return []
        paths = []
        for manifest_path in self.root.rglob("skill.yaml"):
            relative_parts = manifest_path.relative_to(self.root).parts
            if "_template" in relative_parts:
                continue
            paths.append(manifest_path.parent)
        return sorted(paths)

    def load_directory(self, skill_dir: str | Path) -> SkillDefinition:
        directory = Path(skill_dir)
        manifest_path = directory / "skill.yaml"
        if not manifest_path.exists():
            raise ValueError(f"缺少 skill.yaml：{directory}")
        with manifest_path.open("r", encoding="utf-8") as handle:
            manifest = yaml.safe_load(handle) or {}
        prompt_file = ((manifest.get("prompt") or {}).get("file") or "SKILL.md")
        prompt_path = directory / prompt_file
        if not prompt_path.exists():
            raise ValueError(f"缺少 Skill Prompt：{prompt_path}")
        prompt_text = prompt_path.read_text(encoding="utf-8")
        return build_skill_definition(
            manifest,
            skill_dir=directory,
            prompt_text=prompt_text,
        )

    def load_all(self) -> Iterable[SkillDefinition]:
        for directory in self.discover():
            yield self.load_directory(directory)
