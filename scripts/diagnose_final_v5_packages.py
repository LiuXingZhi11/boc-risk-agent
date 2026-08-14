"""比较最终报告请求包体积，不调用模型。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.overall_assessment import build_overall_assessment_package
from src.approval.repository import ApprovalRepository
from src.profiles.repository import ProfileRepository


def main() -> None:
    database = "data/current_project.db"
    cohort_id = "robotics_2025_assumption_test"
    approval_repository = ApprovalRepository(database)
    profile_repository = ProfileRepository(database)
    cohort = approval_repository.get_cohort(cohort_id)
    rankings = tuple(approval_repository.list_direction_rankings(cohort_id, review_status="pending"))
    profiles = {profile.case_id: profile for profile in profile_repository.list()}
    for case_id in ("DeepRobotics", "HIT", "Unitree", "Ecovacs"):
        profile = profiles[case_id]
        reports = tuple(
            approval_repository.list_domain_reports(
                cohort_id=cohort_id,
                case_id=case_id,
                review_status="pending",
            )
        )
        package = build_overall_assessment_package(
            enterprise_name=profile.enterprise_name,
            profile_reporting_periods=tuple(
                sorted({item.reporting_period for item in profile.items if item.reporting_period})
            ),
            cohort_name=cohort.cohort_name,
            cohort_fiscal_period=cohort.fiscal_period,
            cohort_selection_rule=cohort.selection_rule,
            reports=reports,
            rankings=rankings,
            is_experimental=True,
        )
        print(
            case_id,
            f"characters={len(json.dumps(package, ensure_ascii=False))}",
            f"reports={len(reports)}",
            f"approval_points={sum(len(report.approval_points) for report in reports)}",
        )


if __name__ == "__main__":
    main()
