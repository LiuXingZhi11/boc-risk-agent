"""召回相似历史画像并调用 DeepSeek 生成详细比较。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.generation_config import GenerationConfig
from src.config.settings import get_settings
from src.evidence import EvidenceRepository
from src.profiles import (
    ComparisonCardRepository,
    ComparisonCardSimilarityService,
    CurrentEnterpriseProfile,
    HistoricalEnterpriseProfile,
    ProfileRepository,
    compare_profile_candidates,
)
from src.retrieval.embedding import LocalEmbeddingModel
from src.profiles.material_context import build_profile_material_context


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--current-profile-id", required=True)
    parser.add_argument("--current-card-id", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--use-bge", action="store_true")
    parser.add_argument("--model-path", default="BAAI/bge-base-zh-v1.5")
    parser.add_argument("--model-cache", type=Path, default=PROJECT_ROOT / "models")
    parser.add_argument("--model", default=get_settings().model)
    parser.add_argument("--max-tokens", type=int, default=12000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--guide-file",
        type=Path,
        default=PROJECT_ROOT / "prompts" / "科技型企业画像详细比较协议_V1.md",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profile_repository = ProfileRepository(args.database)
    current = profile_repository.get(args.current_profile_id)
    if not isinstance(current, CurrentEnterpriseProfile):
        raise SystemExit("current profile not found or profile_type is not current")
    card_repository = ComparisonCardRepository(args.database)
    current_card = card_repository.get(args.current_card_id)
    if current_card is None or current_card.profile_id != current.profile_id:
        raise SystemExit("current comparison card not found or does not match profile")
    encoder = (
        LocalEmbeddingModel(args.model_path, cache_dir=args.model_cache)
        if args.use_bge
        else None
    )
    matches = ComparisonCardSimilarityService(
        card_repository,
        encoder=encoder,
        embedding_model_name=args.model_path,
    ).find_similar(current_card, limit=args.limit)
    historical_profiles = []
    for match in matches:
        profile = profile_repository.get(match.historical_profile_id)
        if isinstance(profile, HistoricalEnterpriseProfile):
            historical_profiles.append(profile)
    run = compare_profile_candidates(
        current,
        historical_profiles,
        matches,
        config=GenerationConfig(
            model=args.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=args.max_tokens,
            max_retries=args.max_retries,
        ),
        guide_text=args.guide_file.read_text(encoding="utf-8"),
        material_contexts={
            item.profile_id: build_profile_material_context(
                item,
                EvidenceRepository(args.database).list_sources(case_id=item.case_id),
            )
            for item in (current, *historical_profiles)
        },
    )
    payload = run.to_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
