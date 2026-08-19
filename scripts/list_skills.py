"""列出仓库中可发现的 Skill。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.platform.skills.registry import SkillRegistry


def main() -> int:
    registry = SkillRegistry()
    report = registry.refresh()
    for skill in registry.list_skills(enabled_only=False):
        scopes = ", ".join(skill.applies_to)
        print(f"{skill.skill_id}\t{skill.version}\tenabled={skill.enabled}\t{scopes}")
    if report.errors:
        print("\nINVALID SKILLS:")
        for path, error in report.errors.items():
            print(f"- {path}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
