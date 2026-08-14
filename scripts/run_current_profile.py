"""运行新案例 CurrentEnterpriseProfile 候选抽取。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evidence import EvidenceQueryService, EvidenceRepository
from src.llm.generation_config import GenerationConfig
from src.config.settings import get_settings
from src.profiles.current_workflow import CurrentProfileWorkflow
from src.profiles.extraction import PROFILE_DOMAINS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--model", default=get_settings().model)
    parser.add_argument("--max-tokens", type=int, default=18000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-evidence-per-domain", type=int, default=20)
    parser.add_argument("--max-selected-evidence-per-domain", type=int, default=5)
    parser.add_argument("--domains", nargs="*", default=list(PROFILE_DOMAINS))
    parser.add_argument(
        "--guide-file",
        type=Path,
        default=PROJECT_ROOT / "prompts" / "科技型企业企业画像抽取协议_V1.md",
    )
    args = parser.parse_args()

    workflow = CurrentProfileWorkflow(
        EvidenceQueryService(EvidenceRepository(args.database))
    )
    selection_config = GenerationConfig(
        model=args.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
    )
    extraction_config = GenerationConfig(
        model=args.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
    )
    result = workflow.run(
        case_id=args.case_id,
        selection_config=selection_config,
        extraction_config=extraction_config,
        query=args.query,
        domains=tuple(args.domains),
        max_evidence_per_domain=args.max_evidence_per_domain,
        max_selected_evidence_per_domain=args.max_selected_evidence_per_domain,
        guide_text=args.guide_file.read_text(encoding="utf-8"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"current profile run written: {args.output}")


if __name__ == "__main__":
    main()
