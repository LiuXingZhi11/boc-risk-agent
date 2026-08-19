#!/usr/bin/env python3
"""初始化科技型企业风险评级 SQLite 数据库。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.database import init_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="初始化科技型企业风险评级 SQLite 数据库")
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data" / "current_project.db",
        help="数据库文件路径，默认使用 data/current_project.db。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        init_database(args.database)
    except OSError as exc:
        print(f"数据库初始化失败：{exc}", file=sys.stderr)
        return 1
    print(f"数据库已初始化：{args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
