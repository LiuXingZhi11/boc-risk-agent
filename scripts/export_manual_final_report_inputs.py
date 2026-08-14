"""导出人工编制最终报告所需的已审核方向结论，不调用模型。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.repository import ApprovalRepository


def main() -> None:
    repository = ApprovalRepository("data/current_project.db")
    cohort_id = "robotics_2025_assumption_test"
    for case_id in ("DeepRobotics", "HIT"):
        reports = repository.list_domain_reports(
            cohort_id=cohort_id,
            case_id=case_id,
            review_status="pending",
        )
        print(f"\n=== {case_id} ===")
        for report in sorted(reports, key=lambda item: item.domain_id):
            evidence_ids = [
                reference.evidence_unit_id
                for point in report.approval_points
                for reference in point.evidence_refs[:1]
            ]
            print(f"[{report.domain_id}] {report.one_sentence_summary}")
            print(f"evidence={','.join(evidence_ids)}")
            for point in report.approval_points:
                print(f"- {point.title}: {point.judgment}")


if __name__ == "__main__":
    main()
