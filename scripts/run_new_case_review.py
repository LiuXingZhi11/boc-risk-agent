#!/usr/bin/env python3
"""执行固定的新案例审查流程。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig
from src.retrieval.embedding import LocalEmbeddingModel
from src.retrieval.persistence import load_bm25_index, load_embedding_index
from src.review.fixed_review import (
    run_fixed_review_comparison,
    run_fixed_review_context,
    run_fixed_review_questions,
    run_fixed_review_report,
)
from src.storage.repository import CaseRepository
from src.utils.json_utils import load_text, save_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行固定新案例审查流程")
    parser.add_argument("--raw-case-file", type=Path, required=True)
    parser.add_argument("--structure-guide", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "data" / "risk_cases.db")
    parser.add_argument("--index-dir", type=Path, default=PROJECT_ROOT / "data" / "retrieval")
    parser.add_argument("--output", type=Path, default=None, help="可选的上下文 JSON 输出路径")
    parser.add_argument("--top-k-candidates", type=int, default=5)
    parser.add_argument("--top-k-historical", type=int, default=3)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-tokens", type=int, default=18000)
    parser.add_argument(
        "--with-comparison",
        action="store_true",
        help="对已加载的 Top 3 历史案例执行逐案例比较",
    )
    parser.add_argument(
        "--with-questions",
        action="store_true",
        help="在比较结果基础上生成待核实问题；必须同时启用 --with-comparison",
    )
    parser.add_argument(
        "--with-report",
        action="store_true",
        help="汇总为固定审查报告；必须同时启用 --with-comparison 和 --with-questions",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.with_questions and not args.with_comparison:
        print("--with-questions 必须同时使用 --with-comparison", file=sys.stderr)
        return 2
    if args.with_report and not args.with_questions:
        print("--with-report 必须同时使用 --with-questions", file=sys.stderr)
        return 2
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
    bm25_index = load_bm25_index(args.index_dir)
    embedding_index = load_embedding_index(args.index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding_index.model_name,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    context = run_fixed_review_context(
        raw_case_text=load_text(args.raw_case_file),
        structure_guide=load_text(args.structure_guide),
        structure_config=structure_config,
        repository=CaseRepository(args.database),
        bm25_index=bm25_index,
        embedding_index=embedding_index,
        encoder=encoder,
        rerank_config=thinking_config,
        top_k_candidates=args.top_k_candidates,
        top_k_historical=args.top_k_historical,
    )
    comparison_context = (
        run_fixed_review_comparison(context, thinking_config) if args.with_comparison else None
    )
    payload = comparison_context.to_dict() if comparison_context else context.to_dict()
    questions = ()
    if comparison_context is not None and args.with_questions:
        questions = run_fixed_review_questions(comparison_context, thinking_config)
        payload["questions_to_verify"] = [question.to_dict() for question in questions]
    if comparison_context is not None and args.with_report:
        payload = run_fixed_review_report(comparison_context, questions).to_dict()
    if args.output is not None:
        save_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
