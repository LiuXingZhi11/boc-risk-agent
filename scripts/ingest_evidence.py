"""将 PDF/HTML 数据源解析并写入 EvidenceUnit SQLite 库。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evidence import EvidenceRepository
from src.sources import ingest_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--paths", nargs="+", required=True)
    parser.add_argument("--source-date")
    args = parser.parse_args()

    repository = EvidenceRepository(args.database)
    total = 0
    for raw_path in args.paths:
        path = Path(raw_path)
        source, units = ingest_source(
            path,
            case_id=args.case_id,
            source_date=args.source_date,
        )
        repository.save_source(source)
        repository.save_units(list(units))
        total += len(units)
        print(f"{path.name}: {source.source_type}, {len(units)} units")
    print(f"ingested={len(args.paths)}, evidence_units={total}, database={args.database}")


if __name__ == "__main__":
    main()
