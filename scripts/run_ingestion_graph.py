#!/usr/bin/env python3
"""历史案例入库图命令行演示入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.graphs.ingestion_graph import build_ingestion_graph
from src.llm.generation_config import GenerationConfig
from src.utils.json_utils import load_json, load_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="历史案例入库 LangGraph 演示")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="启动一个新的入库任务。")
    start.add_argument("--raw-case-file", type=Path, required=True)
    start.add_argument("--structure-guide", type=Path, required=True)
    start.add_argument("--rule-guide", type=Path, required=True)
    _add_runtime_args(start)

    show = subparsers.add_parser("show", help="查看任务当前状态。")
    _add_state_args(show)

    resume = subparsers.add_parser("resume", help="提交人工决定并恢复任务。")
    _add_state_args(resume)
    resume.add_argument(
        "--decision",
        choices=["accept", "reject", "accept_with_edits"],
        required=True,
    )
    resume.add_argument("--structured-file", type=Path, default=None)
    resume.add_argument("--rules-file", type=Path, default=None)
    return parser


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "risk_cases.db")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT_ROOT / "data" / "ingestion_checkpoints.db",
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--source", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-tokens", type=int, default=18000)


def _add_state_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "risk_cases.db")
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=PROJECT_ROOT / "data" / "ingestion_checkpoints.db",
    )
    parser.add_argument("--thread-id", required=True)


def _configs(model: str | None, max_tokens: int = 18000) -> tuple[GenerationConfig, GenerationConfig]:
    settings = get_settings()
    selected_model = model or settings.model
    structure_config_kwargs = {
        "model": selected_model,
        "mode": "sampling",
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    rule_config_kwargs = {
        "model": selected_model,
        "mode": "thinking",
        "reasoning_effort": "high",
        "max_tokens": max_tokens,
    }
    return GenerationConfig(**structure_config_kwargs), GenerationConfig(**rule_config_kwargs)


def _graph(checkpoint_path: Path, database_path: Path, *, guide_text: str = "", rule_text: str = "", model: str | None = None, max_tokens: int = 18000):
    structure_config, rule_config = _configs(model, max_tokens)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpointer_context = SqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = checkpointer_context.__enter__()
    graph = build_ingestion_graph(
        structure_guide=guide_text,
        rule_guide=rule_text,
        structure_config=structure_config,
        rule_config=rule_config,
        database_path=str(database_path),
        checkpointer=checkpointer,
    )
    return graph, checkpointer_context


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _print_state(graph: Any, config: dict[str, Any]) -> None:
    snapshot = graph.get_state(config)
    _print_json({"values": snapshot.values, "next": snapshot.next})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = {"configurable": {"thread_id": args.thread_id}}
    context = None
    try:
        if args.command == "start":
            graph, context = _graph(
                args.checkpoint,
                args.database,
                guide_text=load_text(args.structure_guide),
                rule_text=load_text(args.rule_guide),
                model=args.model,
                max_tokens=args.max_tokens,
            )
            result = graph.invoke(
                {
                    "thread_id": args.thread_id,
                    "raw_case_text": load_text(args.raw_case_file),
                    "source": args.source,
                },
                config,
            )
            _print_json(result)
            return 1 if result.get("error") else 0
        else:
            graph, context = _graph(args.checkpoint, args.database)
            if args.command == "show":
                _print_state(graph, config)
            elif args.command == "resume":
                payload: dict[str, Any] = {"decision": args.decision}
                if args.decision == "accept_with_edits":
                    if args.structured_file is None or args.rules_file is None:
                        raise ValueError("accept_with_edits 必须同时提供 --structured-file 和 --rules-file。")
                    payload["structured_case"] = load_json(args.structured_file)
                    payload["rule_hypotheses"] = load_json(args.rules_file)
                result = graph.invoke(Command(resume=payload), config)
                _print_json(result)
                return 1 if result.get("error") else 0
            else:
                raise ValueError(f"未知命令：{args.command}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if context is not None:
            context.__exit__(None, None, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
