#!/usr/bin/env python3
"""按显式指定的文件导入一批样例案例。

不在脚本内自动选择历史模型输出版本，避免把不同实验产物错误配对。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_case_bundle import main as import_case_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入指定的一批样例案例")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--structured-file", type=Path, required=True)
    parser.add_argument("--rules-file", type=Path, required=True)
    parser.add_argument("--raw-text-file", type=Path, required=True)
    parser.add_argument("--source", default="sample_data")
    parser.add_argument("--case-type", default="credit")
    parser.add_argument("--replace", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    forwarded = [
        "--database", str(args.database),
        "--structured-file", str(args.structured_file),
        "--rules-file", str(args.rules_file),
        "--raw-text-file", str(args.raw_text_file),
        "--source", args.source,
        "--case-type", args.case_type,
    ]
    if args.replace:
        forwarded.append("--replace")
    return import_case_bundle(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
