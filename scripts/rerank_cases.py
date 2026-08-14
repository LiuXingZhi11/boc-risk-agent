#!/usr/bin/env python3
"""对混合召回候选调用 DeepSeek 重排。"""

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
from src.retrieval.hybrid import hybrid_retrieve
from src.retrieval.persistence import load_bm25_index, load_embedding_index
from src.retrieval.reranker import rerank_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="对历史案例候选进行 DeepSeek 重排")
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "retrieval",
        help="检索索引目录",
    )
    parser.add_argument("--query", required=True, help="新案例结构化摘要或风险事件描述")
    parser.add_argument("--top-k-candidates", type=int, default=5)
    parser.add_argument("--top-k-reranked", type=int, default=3)
    parser.add_argument("--device", default="cpu", help="Embedding 运行设备，默认 cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.top_k_candidates <= 0 or args.top_k_reranked <= 0:
        print("候选和重排数量必须大于 0", file=sys.stderr)
        return 2

    settings = get_settings()
    bm25_index = load_bm25_index(args.index_dir)
    embedding_index = load_embedding_index(args.index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding_index.model_name,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    candidates = hybrid_retrieve(
        args.query,
        bm25_index,
        embedding_index,
        encoder,
        top_k_bm25=args.top_k_candidates,
        top_k_embedding=args.top_k_candidates,
        final_k=args.top_k_candidates,
    )
    config = GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_retries=1,
        max_tokens=12000,
    )
    result = rerank_candidates(
        args.query,
        candidates,
        config,
        top_k=args.top_k_reranked,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
