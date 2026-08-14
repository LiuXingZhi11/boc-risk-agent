"""为机器人试验样本逐家生成最终授信审批报告 v5。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.approval.repository import ApprovalRepository
from src.ui.v5_services import generate_enterprise_overall_assessment_review


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"
PROFILES = (
    ("DeepBlue", "DeepBlue-react-profile-2026-08-10"),
    ("DeepRobotics", "DeepRobotics-rechunk-profile-2026-08-07"),
    ("Dobot", "Dobot-rechunk-profile-2026-08-07"),
    ("Ecovacs", "Ecovacs-rechunk-profile-2026-08-07"),
    ("Efort", "Efort-rechunk-profile-2026-08-07"),
    ("HIT", "HIT-profile-2026-08-11"),
    ("Leju", "Leju-rechunk-profile-2026-08-07"),
    ("Saiwei", "Saiwei-profile-2026-08-11"),
    ("Stone", "Stone-rechunk-profile-2026-08-07"),
    ("Tinavi", "Tinavi-react-profile-2026-08-10"),
    ("Yijiahe", "Yijiahe-react-profile-2026-08-10"),
)


def main() -> None:
    repository = ApprovalRepository(DATABASE)
    for case_id, profile_id in PROFILES:
        assessment_id = f"robotics_2025_assumption_{case_id}_final_v5"
        if repository.get_overall_assessment(assessment_id) is not None:
            print(f"SKIP {case_id} already_saved", flush=True)
            continue
        print(f"START {case_id}", flush=True)
        try:
            result = generate_enterprise_overall_assessment_review(
                database=DATABASE,
                assessment_id=assessment_id,
                cohort_id=COHORT_ID,
                profile_id=profile_id,
            )
            assessment = result["assessment"]
            print(
                "DONE "
                f"{case_id} rating={assessment['rating_level']} "
                f"recommendation={assessment['recommendation']} "
                f"strong_failed={assessment['strong_constraint_failed_count']} "
                f"weak_failed={assessment['weak_constraint_failed_count']}",
                flush=True,
            )
        except Exception as error:
            print(f"FAILED {case_id} error={error}", flush=True)


if __name__ == "__main__":
    main()
