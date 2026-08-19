"""离线校验一个 Skill 目录。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.platform.skills.validator import validate_skill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skill_dir", type=Path)
    args = parser.parse_args()
    try:
        skill = validate_skill(args.skill_dir)
    except Exception as exc:
        print(f"INVALID: {type(exc).__name__}: {exc}")
        return 1
    print(
        json.dumps(
            {
                "id": skill.skill_id,
                "version": skill.version,
                "applies_to": skill.applies_to,
                "tools": [tool.qualified_name for tool in skill.tools],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
