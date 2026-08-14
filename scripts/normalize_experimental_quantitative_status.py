"""将试验样本最终报告中的量化评估改为方法性信息边界。"""

from dataclasses import replace

from src.approval.overall_assessment import _recommendation
from src.approval.repository import ApprovalRepository
from src.approval.models import FinalDirectionResult


DATABASE = "data/current_project.db"
COHORT_ID = "robotics_2025_assumption_test"


def main() -> None:
    repository = ApprovalRepository(DATABASE)
    updated = []
    for assessment in repository.list_overall_assessments(cohort_id=COHORT_ID):
        if not assessment.assessment_id.endswith("_final_v3"):
            continue
        directions = tuple(
            replace(
                item,
                status="insufficient_information",
                summary="当前同行样本包含跨期材料，量化比较仅作流程验证，不能作为正式企业评价依据。",
            )
            if item.section_id == "quantitative_assessment"
            else item
            for item in assessment.direction_results
        )
        strong_count, weak_count, recommendation = _recommendation(directions)
        rating = assessment.rating_level
        if recommendation == "proceed_with_caution" and rating == "C":
            rating = "B"
        repository.save_overall_assessment(
            replace(
                assessment,
                rating_level=rating,
                recommendation=recommendation,
                strong_constraint_failed_count=strong_count,
                weak_constraint_failed_count=weak_count,
                direction_results=directions,
            )
        )
        updated.append((assessment.case_id, recommendation, rating, weak_count))
    print(updated)


if __name__ == "__main__":
    main()
