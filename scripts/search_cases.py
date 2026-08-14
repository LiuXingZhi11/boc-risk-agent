#!/usr/bin/env python3
"""使用已持久化的混合索引检索历史案例。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.retrieval.embedding import LocalEmbeddingModel
from src.retrieval.hybrid import hybrid_retrieve
from src.retrieval.persistence import load_bm25_index, load_embedding_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检索历史风险案例")
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "retrieval",
        help="检索索引目录",
    )
    parser.add_argument("--query", required=True, help="风险事件或业务事实描述")
    parser.add_argument("--top-k", type=int, default=5, help="返回候选数量")
    parser.add_argument("--top-k-bm25", type=int, default=5)
    parser.add_argument("--top-k-embedding", type=int, default=5)
    parser.add_argument("--device", default="cpu", help="Embedding 运行设备，默认 cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.top_k <= 0:
        print("--top-k 必须大于 0", file=sys.stderr)
        return 2

    settings = get_settings()
    bm25_index = load_bm25_index(args.index_dir)
    embedding_index = load_embedding_index(args.index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding_index.model_name,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    results = hybrid_retrieve(
        args.query,
        bm25_index,
        embedding_index,
        encoder,
        top_k_bm25=args.top_k_bm25,
        top_k_embedding=args.top_k_embedding,
        final_k=args.top_k,
    )
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
