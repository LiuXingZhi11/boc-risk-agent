"""为当前数据库中已有的客户风险评级报告补生成行动建议。"""

from src.approval.repository import ApprovalRepository
from src.ui.v5_services import generate_enterprise_action_recommendations
from src.profiles.repository import ProfileRepository


DATABASE = "data/current_project.db"


def main() -> None:
    assessments = ApprovalRepository(DATABASE).list_overall_assessments()
    profiles = ProfileRepository(DATABASE)
    for assessment in assessments:
        candidates = profiles.list(case_id=assessment.case_id)
        if not candidates:
            print(f"{assessment.case_id}: missing profile")
            continue
        profile = candidates[0]
        print(f"{assessment.case_id}: generating action recommendations", flush=True)
        try:
            result = generate_enterprise_action_recommendations(
                database=DATABASE,
                assessment_id=assessment.assessment_id,
                profile_id=profile.profile_id,
            )
            print(
                f"{assessment.case_id}: {len(result['assessment']['verification_priorities'])} actions saved",
                flush=True,
            )
        except Exception as exc:
            print(f"{assessment.case_id}: failed - {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
