#!/usr/bin/env python3
"""从 SQLite 案例库重建 BM25 与本地 BGE 检索索引。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.retrieval.bm25 import build_bm25_index
from src.retrieval.documents import build_retrieval_document
from src.retrieval.embedding import LocalEmbeddingModel, build_embedding_index
from src.retrieval.persistence import persist_indices
from src.storage.repository import CaseRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="重建案例检索索引")
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "data" / "risk_cases.db",
        help="案例 SQLite 数据库路径",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "retrieval",
        help="检索索引输出目录",
    )
    parser.add_argument(
        "--allow-unapproved",
        action="store_true",
        help="允许把未完成人工审核的案例加入索引；正式索引默认关闭",
    )
    parser.add_argument("--device", default="cpu", help="Embedding 运行设备，默认 cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    repository = CaseRepository(args.database)
    statuses = None if args.allow_unapproved else "approved"
    documents = []
    for case in repository.list_cases(review_status=statuses):
        bundle = repository.get_case_bundle(case.case_id)
        if bundle is not None:
            documents.append(
                build_retrieval_document(bundle, allow_unapproved=args.allow_unapproved)
            )

    encoder = LocalEmbeddingModel(
        model_name=settings.embedding_model,
        cache_dir=settings.model_cache_dir,
        device=args.device,
    )
    bm25_index = build_bm25_index(documents)
    embedding_index = build_embedding_index(
        documents,
        encoder,
        model_name=settings.embedding_model,
    )
    persist_indices(
        args.output_dir,
        bm25_index,
        embedding_index,
        source_database=str(args.database),
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "case_count": len(documents),
                "case_ids": [document.case_id for document in documents],
                "embedding_model": settings.embedding_model,
                "review_filter": "all" if args.allow_unapproved else "approved",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
