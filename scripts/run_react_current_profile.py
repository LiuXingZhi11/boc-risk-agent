"""运行当前企业的单领域受控 ReAct 画像调查。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config.settings import get_settings
from src.evidence import EvidenceQueryService, EvidenceRepository
from src.llm.generation_config import GenerationConfig
from src.profiles.react_models import ReactLimits
from src.profiles.react_workflow import (
    ControlledReactProfileWorkflow,
    REACT_SUPPORTED_DOMAINS,
)


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--domain", choices=REACT_SUPPORTED_DOMAINS, required=True)
    parser.add_argument("--query", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default=settings.model)
    parser.add_argument("--max-tokens", type=int, default=18000)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-model-calls", type=int, default=6)
    parser.add_argument("--max-search-calls", type=int, default=2)
    parser.add_argument("--max-read-calls", type=int, default=2)
    parser.add_argument("--max-read-units", type=int, default=8)
    parser.add_argument("--max-total-read-units", type=int, default=12)
    parser.add_argument("--max-catalog-items", type=int, default=10)
    parser.add_argument("--confirm-paid-call", action="store_true")
    parser.add_argument(
        "--guide-file",
        type=Path,
        default=PROJECT_ROOT / "prompts" / "科技型企业企业画像抽取协议_V1.md",
    )
    args = parser.parse_args()
    if not args.confirm_paid_call:
        print("未确认付费调用，受控 ReAct 调查未执行。")
        return

    workflow = ControlledReactProfileWorkflow(
        EvidenceQueryService(EvidenceRepository(args.database))
    )
    react_config = GenerationConfig(
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
    limits = ReactLimits(
        max_model_calls=args.max_model_calls,
        max_search_calls=args.max_search_calls,
        max_read_calls=args.max_read_calls,
        max_read_units=args.max_read_units,
        max_total_read_units=args.max_total_read_units,
        max_catalog_items=args.max_catalog_items,
    )
    result = workflow.run_current_domain(
        case_id=args.case_id,
        domain=args.domain,
        react_config=react_config,
        extraction_config=extraction_config,
        query=args.query,
        limits=limits,
        guide_text=args.guide_file.read_text(encoding="utf-8"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"react current profile run written: {args.output}")


if __name__ == "__main__":
    main()
