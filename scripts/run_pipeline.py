#!/usr/bin/env python3
"""V4 兼容的模块化命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig
from src.services.rule_service import extract_rule_hypotheses
from src.services.structure_service import structure_case
from src.utils.json_utils import load_json, load_text, save_json


SCRIPT_VERSION = "2026-07-17-modular-v4"


def _temperature(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("temperature 必须是数字。") from exc
    if not 0.0 <= result <= 2.0:
        raise argparse.ArgumentTypeError("temperature 必须位于 0 到 2 之间。")
    return result


def _add_common_api_args(parser: argparse.ArgumentParser) -> None:
    settings = get_settings()
    parser.add_argument("--model", default=None, help=f"默认使用 .env 中的模型（当前为 {settings.model}）。")
    parser.add_argument("--retries", type=int, default=2, help="初次调用之外的最大重试次数。")
    parser.add_argument("--base-url", default=None, help="覆盖 .env 中的 DeepSeek Base URL。")


def _add_generation_args(parser: argparse.ArgumentParser, default_mode: str) -> None:
    parser.add_argument("--mode", choices=["thinking", "sampling"], default=default_mode)
    parser.add_argument("--temperature", type=_temperature, default=0.2)
    parser.add_argument("--reasoning-effort", choices=["high", "max"], default="high")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepSeek 金融风险案例两阶段处理脚本（模块化 V4）")
    subparsers = parser.add_subparsers(dest="command", required=True)

    structure = subparsers.add_parser("structure", help="只执行案例事实结构化。")
    structure.add_argument("--case-file", type=Path, required=True)
    structure.add_argument("--guide", type=Path, required=True)
    structure.add_argument("--output", type=Path, required=True)
    structure.add_argument("--max-tokens", type=int, default=18000)
    _add_generation_args(structure, "sampling")
    _add_common_api_args(structure)

    rules = subparsers.add_parser("rules", help="只执行单案例规则假设提炼。")
    rules.add_argument("--structured-file", type=Path, required=True)
    rules.add_argument("--guide", type=Path, required=True)
    rules.add_argument("--output", type=Path, required=True)
    rules.add_argument("--max-tokens", type=int, default=12000)
    _add_generation_args(rules, "thinking")
    _add_common_api_args(rules)

    pipeline = subparsers.add_parser("pipeline", help="依次执行结构化和规则提炼。")
    pipeline.add_argument("--case-file", type=Path, required=True)
    pipeline.add_argument("--structure-guide", type=Path, required=True)
    pipeline.add_argument("--rule-guide", type=Path, required=True)
    pipeline.add_argument("--structured-output", type=Path, required=True)
    pipeline.add_argument("--rules-output", type=Path, required=True)
    pipeline.add_argument("--structure-max-tokens", type=int, default=18000)
    pipeline.add_argument("--rule-max-tokens", type=int, default=12000)
    pipeline.add_argument("--structure-mode", choices=["thinking", "sampling"], default="sampling")
    pipeline.add_argument("--structure-temperature", type=_temperature, default=0.2)
    pipeline.add_argument("--structure-reasoning-effort", choices=["high", "max"], default="high")
    pipeline.add_argument("--rule-mode", choices=["thinking", "sampling"], default="thinking")
    pipeline.add_argument("--rule-temperature", type=_temperature, default=0.2)
    pipeline.add_argument("--rule-reasoning-effort", choices=["high", "max"], default="high")
    _add_common_api_args(pipeline)
    return parser


def _config(args: argparse.Namespace, *, mode: str, temperature: float, reasoning_effort: str, max_tokens: int) -> GenerationConfig:
    settings = get_settings()
    return GenerationConfig(
        model=args.model or settings.model,
        mode=mode,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        max_retries=args.retries,
        max_tokens=max_tokens,
        base_url=args.base_url,
    )


def _run_structure(args: argparse.Namespace) -> dict[str, Any]:
    result = structure_case(
        load_text(args.case_file),
        load_text(args.guide),
        _config(args, mode=args.mode, temperature=args.temperature, reasoning_effort=args.reasoning_effort, max_tokens=args.max_tokens),
    )
    save_json(args.output, result)
    print(f"结构化案例已保存：{args.output}")
    print(f"案例数量：{len(result['case_records'])}")
    return result


def _run_rules(args: argparse.Namespace, structured_data: dict[str, Any] | None = None) -> dict[str, Any]:
    result = extract_rule_hypotheses(
        structured_data if structured_data is not None else load_json(args.structured_file),
        load_text(args.guide),
        _config(args, mode=args.mode, temperature=args.temperature, reasoning_effort=args.reasoning_effort, max_tokens=args.max_tokens),
    )
    save_json(args.output, result)
    print(f"规则假设已保存：{args.output}")
    print(f"单案例规则假设数量：{len(result['single_case_rule_hypotheses'])}")
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"脚本版本：{SCRIPT_VERSION}")
    try:
        if args.command == "structure":
            _run_structure(args)
        elif args.command == "rules":
            _run_rules(args)
        elif args.command == "pipeline":
            structured = structure_case(
                load_text(args.case_file),
                load_text(args.structure_guide),
                _config(args, mode=args.structure_mode, temperature=args.structure_temperature, reasoning_effort=args.structure_reasoning_effort, max_tokens=args.structure_max_tokens),
            )
            save_json(args.structured_output, structured)
            print(f"结构化案例已保存：{args.structured_output}")
            print(f"案例数量：{len(structured['case_records'])}")
            rules = extract_rule_hypotheses(
                structured,
                load_text(args.rule_guide),
                _config(args, mode=args.rule_mode, temperature=args.rule_temperature, reasoning_effort=args.rule_reasoning_effort, max_tokens=args.rule_max_tokens),
            )
            save_json(args.rules_output, rules)
            print(f"规则假设已保存：{args.rules_output}")
            print(f"单案例规则假设数量：{len(rules['single_case_rule_hypotheses'])}")
        else:  # argparse 已限制，此处仅为类型检查兜底
            raise ValueError(f"未知命令：{args.command}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

