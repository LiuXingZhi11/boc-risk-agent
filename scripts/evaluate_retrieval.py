#!/usr/bin/env python3
"""评估 BM25、Embedding 和混合召回的 Top-K 指标。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.retrieval.embedding import LocalEmbeddingModel
from src.retrieval.hybrid import hybrid_retrieve
from src.retrieval.persistence import load_bm25_index, load_embedding_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="评估案例检索 Top-K 指标")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def _ids(results: list[Any]) -> list[str]:
    return [item.case_id for item in results]


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    """读取评估清单；清单是数组，不使用只接受对象的业务 JSON 工具。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 manifest: {path}") from exc
    if not isinstance(value, list) or not value:
        raise ValueError("manifest 必须是非空数组。")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("manifest 每一项必须是对象。")
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = _load_manifest(args.manifest)
    settings = get_settings()
    bm25 = load_bm25_index(args.index_dir)
    embedding = load_embedding_index(args.index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding.model_name,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    rows: list[dict[str, Any]] = []
    for item in manifest:
        query = item["query"]
        relevant = set(item["relevant_case_ids"])
        bm25_ids = _ids(bm25.search(query, top_k=args.top_k))
        embedding_ids = _ids(embedding.search(query, encoder, top_k=args.top_k))
        hybrid_ids = _ids(
            hybrid_retrieve(
                query,
                bm25,
                embedding,
                encoder,
                top_k_bm25=args.top_k,
                top_k_embedding=args.top_k,
                final_k=args.top_k,
            )
        )
        rows.append(
            {
                "test_case_id": item["test_case_id"],
                "risk_type": item.get("risk_type"),
                "relevant_case_ids": sorted(relevant),
                "bm25_top_k": bm25_ids,
                "embedding_top_k": embedding_ids,
                "hybrid_top_k": hybrid_ids,
                "bm25_hit": bool(set(bm25_ids) & relevant),
                "embedding_hit": bool(set(embedding_ids) & relevant),
                "hybrid_hit": bool(set(hybrid_ids) & relevant),
                "hybrid_relevant_count": len(set(hybrid_ids) & relevant),
            }
        )
    query_count = len(rows)
    report = {
        "query_count": query_count,
        "top_k": args.top_k,
        "metrics": {
            "bm25_recall_at_k": sum(row["bm25_hit"] for row in rows) / query_count,
            "embedding_recall_at_k": sum(row["embedding_hit"] for row in rows) / query_count,
            "hybrid_recall_at_k": sum(row["hybrid_hit"] for row in rows) / query_count,
            "hybrid_mean_relevant_count": sum(row["hybrid_relevant_count"] for row in rows) / query_count,
        },
        "queries": rows,
        "limitations": [
            "本评估只衡量检索召回，不代表比较、问题或报告内容质量。",
            "合成案例用于流程和指标复现，不替代真实业务人工评价。",
        ],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
