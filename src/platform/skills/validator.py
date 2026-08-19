"""Skill 离线校验入口。"""

from __future__ import annotations

from pathlib import Path

from .loader import SkillLoader
from .models import SkillDefinition


def validate_skill(path: str | Path) -> SkillDefinition:
    directory = Path(path)
    return SkillLoader(directory.parent).load_directory(directory)
