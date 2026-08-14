"""以常规输出上限补跑 DeepSeek 空响应的最终报告。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.overall_assessment import (
    build_overall_assessment_package,
    generate_overall_assessment,
)
from src.approval.repository import ApprovalRepository
from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig
from src.profiles.repository import ProfileRepository


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"
MISSING_PROFILES = (
    ("DeepRobotics", "DeepRobotics-rechunk-profile-2026-08-07"),
    ("HIT", "HIT-profile-2026-08-11"),
)


def main() -> None:
    approval_repository = ApprovalRepository(DATABASE)
    profile_repository = ProfileRepository(DATABASE)
    cohort = approval_repository.get_cohort(COHORT_ID)
    rankings = tuple(approval_repository.list_direction_rankings(COHORT_ID, review_status="pending"))
    settings = get_settings()
    for case_id, profile_id in MISSING_PROFILES:
        assessment_id = f"robotics_2025_assumption_{case_id}_final_v5"
        if approval_repository.get_overall_assessment(assessment_id) is not None:
            print(f"SKIP {case_id} already_saved", flush=True)
            continue
        profile = profile_repository.get(profile_id)
        reports = tuple(
            approval_repository.list_domain_reports(
                cohort_id=COHORT_ID,
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
        print(f"START {case_id}", flush=True)
        try:
            assessment = generate_overall_assessment(
                assessment_id,
                package,
                reports,
                rankings,
                config=GenerationConfig(
                    model=settings.model,
                    mode="thinking",
                    reasoning_effort="high",
                    max_tokens=12000,
                    max_retries=2,
                ),
            )
            approval_repository.save_overall_assessment(assessment)
            print(
                f"DONE {case_id} rating={assessment.rating_level} "
                f"recommendation={assessment.recommendation} "
                f"strong_failed={assessment.strong_constraint_failed_count} "
                f"weak_failed={assessment.weak_constraint_failed_count}",
                flush=True,
            )
        except Exception as error:
            print(f"FAILED {case_id} error={error}", flush=True)


if __name__ == "__main__":
    main()
