#!/usr/bin/env python3
"""导入经过校验的结构化案例和规则假设 JSON。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.bundle_builder import build_case_bundles
from src.storage.repository import CaseRepository
from src.utils.json_utils import load_json, load_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入结构化案例包到 SQLite")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--structured-file", type=Path, required=True)
    parser.add_argument("--rules-file", type=Path, required=True)
    parser.add_argument("--raw-text-file", type=Path, required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--case-type", default=None)
    parser.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundles = build_case_bundles(
            load_json(args.structured_file),
            load_json(args.rules_file),
            raw_text=load_text(args.raw_text_file),
            source=args.source,
            case_type=args.case_type,
        )
        repository = CaseRepository(args.database)
        for bundle in bundles:
            repository.save_case_bundle(bundle, replace=args.replace)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"案例导入失败：{exc}", file=sys.stderr)
        return 1
    print(f"成功导入案例：{len(bundles)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
