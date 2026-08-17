"""把已保存行动建议中的内部方向 ID 统一为中文名称。"""

import json

from src.approval.action_recommendations import normalize_action_recommendations
from src.approval.repository import ApprovalRepository


def main() -> None:
    repository = ApprovalRepository("data/current_project.db")
    for assessment in repository.list_overall_assessments():
        actions = normalize_action_recommendations(assessment.verification_priorities)
        if actions != assessment.verification_priorities:
            from dataclasses import replace

            repository.save_overall_assessment(
                replace(assessment, verification_priorities=actions)
            )
            print(f"{assessment.case_id}: normalized {len(actions)} actions")


if __name__ == "__main__":
    main()
