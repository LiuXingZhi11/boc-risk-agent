"""使用 ComparisonCard 检索相似的已审核历史企业画像。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.profiles import ComparisonCardRepository, ComparisonCardSimilarityService
from src.retrieval.embedding import LocalEmbeddingModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--current-card-id", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--use-bge", action="store_true")
    parser.add_argument("--model-path", default="BAAI/bge-base-zh-v1.5")
    parser.add_argument("--model-cache", type=Path, default=PROJECT_ROOT / "models")
    args = parser.parse_args()

    repository = ComparisonCardRepository(args.database)
    current = repository.get(args.current_card_id)
    if current is None:
        raise SystemExit(f"comparison card not found: {args.current_card_id}")
    encoder = (
        LocalEmbeddingModel(args.model_path, cache_dir=args.model_cache)
        if args.use_bge
        else None
    )
    results = ComparisonCardSimilarityService(
        repository,
        encoder=encoder,
        embedding_model_name=args.model_path,
    ).find_similar(current, limit=args.limit)
    print(
        json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
