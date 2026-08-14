"""查看分领域画像候选，并在明确批准后写入正式 EnterpriseProfile。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.profiles import ProfileRepository, aggregate_profile_run, finalize_and_save_profile_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="历史或当前画像运行 JSON。")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--enterprise-name", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="确认候选后写入 approved 正式画像；不提供时只输出待审核内容。",
    )
    args = parser.parse_args()

    run = json.loads(args.input.read_text(encoding="utf-8"))
    bundle = aggregate_profile_run(run)
    payload: dict[str, object] = {"review_bundle": bundle, "saved_profile": None}
    if args.approve:
        profile = finalize_and_save_profile_review(
            bundle["candidates"],
            repository=ProfileRepository(args.database),
            evidence_unit_ids=bundle["evidence_unit_ids"],
            decision="accept",
            profile_id=args.profile_id,
            case_id=bundle["case_id"],
            enterprise_name=args.enterprise_name,
            profile_type=bundle["profile_type"],
        )
        payload["saved_profile"] = asdict(profile) if profile is not None else None

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
