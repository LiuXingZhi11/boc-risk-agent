#!/usr/bin/env python3
"""受约束计划式 Agent 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.agent.fixed_services import (
    FixedReviewAgentDependencies,
    build_fixed_flow_fallback,
    build_fixed_review_executor_services,
)
from src.config.settings import get_settings
from src.graphs.agent_graph import build_agent_graph
from src.llm.generation_config import GenerationConfig
from src.retrieval.embedding import LocalEmbeddingModel
from src.retrieval.persistence import load_bm25_index, load_embedding_index
from src.storage.repository import CaseRepository
from src.utils.json_utils import load_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行受约束计划式 Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="开始一次 Agent 审查")
    _add_common_args(start)
    start.add_argument("--raw-case-file", type=Path, required=True)
    start.add_argument("--user-request", default="完成新案例辅助审查")

    resume = subparsers.add_parser("resume", help="恢复人工补充后的 Agent 审查")
    _add_common_args(resume)
    resume.add_argument("--human-input", required=True)

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--structure-guide",
        type=Path,
        default=PROJECT_ROOT / "prompts" / "金融风险案例结构化协议_第一阶段_最终精简版.md",
    )
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "risk_cases.db")
    parser.add_argument("--index-dir", type=Path, default=PROJECT_ROOT / "data" / "retrieval")
    parser.add_argument("--checkpoint", type=Path, default=PROJECT_ROOT / "data" / "agent_checkpoints.db")
    parser.add_argument("--thread-id", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-tokens", type=int, default=18000)
    parser.add_argument("--top-k-candidates", type=int, default=5)
    parser.add_argument("--top-k-historical", type=int, default=3)


def _print_json(value: Any, output: Path | None = None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    print(text)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


def _build_graph(args: argparse.Namespace, guide_text: str, checkpointer):
    settings = get_settings()
    structure_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=args.max_tokens,
    )
    thinking_config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=args.max_tokens,
    )
    repository = CaseRepository(args.database)
    bm25_index = load_bm25_index(args.index_dir)
    embedding_index = load_embedding_index(args.index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding_index.model_name,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    dependencies = FixedReviewAgentDependencies(
        structure_guide=guide_text,
        structure_config=structure_config,
        rerank_config=thinking_config,
        comparison_config=thinking_config,
        question_config=thinking_config,
        repository=repository,
        bm25_index=bm25_index,
        embedding_index=embedding_index,
        encoder=encoder,
        top_k_candidates=args.top_k_candidates,
        top_k_historical=args.top_k_historical,
    )
    services = build_fixed_review_executor_services(dependencies)
    return build_agent_graph(
        planner_config=thinking_config,
        services=services,
        fixed_flow_fallback=build_fixed_flow_fallback(dependencies),
        checkpointer=checkpointer,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    thread_id = args.thread_id or f"AGENT_{uuid.uuid4().hex[:12].upper()}"
    config = {"configurable": {"thread_id": thread_id}}
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_context = SqliteSaver.from_conn_string(str(args.checkpoint))
    checkpointer = checkpoint_context.__enter__()
    try:
        guide_text = load_text(args.structure_guide)
        graph = _build_graph(args, guide_text, checkpointer)
        if args.command == "start":
            state = {
                "thread_id": thread_id,
                "run_id": thread_id,
                "user_request": args.user_request,
                "raw_case_text": load_text(args.raw_case_file),
                "completed_steps": [],
                "trace": [],
                "errors": [],
                "iteration_count": 0,
                "replan_count": 0,
            }
            result = graph.invoke(state, config)
        else:
            result = graph.invoke(Command(resume=args.human_input), config)
        _print_json(result, args.output)
        return 1 if result.get("agent_status") == "failed" else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    finally:
        checkpoint_context.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
