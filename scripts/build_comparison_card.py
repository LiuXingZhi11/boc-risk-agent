"""从已审核 EnterpriseProfile 生成并保存 ComparisonCard。"""

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
    ProfileRepository,
    approve_comparison_card,
    generate_comparison_card,
)
from src.profiles.material_context import build_profile_material_context


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default=get_settings().model)
    parser.add_argument("--max-tokens", type=int, default=8000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="生成后直接标记 approved；正式环境建议先人工查看输出。",
    )
    args = parser.parse_args()

    profile = ProfileRepository(args.database).get(args.profile_id)
    if profile is None:
        raise SystemExit(f"profile not found: {args.profile_id}")
    guide_path = PROJECT_ROOT / "prompts" / "科技型企业比较卡生成协议_V1.md"
    config = GenerationConfig(
        model=args.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
    )
    card, api_meta = generate_comparison_card(
        profile,
        config=config,
        guide_text=guide_path.read_text(encoding="utf-8"),
        material_context=build_profile_material_context(
            profile,
            EvidenceRepository(args.database).list_sources(case_id=profile.case_id),
        ),
    )
    if args.approve:
        card = approve_comparison_card(card)
    ComparisonCardRepository(args.database).save(card)
    payload = {"comparison_card": card.to_dict(), "api_meta": api_meta}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
