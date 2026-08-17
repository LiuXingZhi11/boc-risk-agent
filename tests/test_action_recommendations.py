from src.approval.action_recommendations import (
    build_action_recommendation_messages,
    normalize_action_recommendations,
    validate_action_recommendations,
)
from src.approval.models import EnterpriseOverallAssessment, OverallAssessmentRationale
from src.approval.overall_assessment import overall_assessment_to_markdown
from src.profiles.models import EvidenceReference


def _assessment() -> EnterpriseOverallAssessment:
    return EnterpriseOverallAssessment(
        assessment_id="a",
        cohort_id="c",
        case_id="e",
        rating_level="AA",
        overall_judgment="需要补充资料。",
        rating_rationale=(OverallAssessmentRationale("d", "维度", "判断。"),),
        core_risks=("客户主体待核验。",),
        mitigating_factors=(),
        rating_boundaries=("当前为试验口径。",),
        verification_priorities=("核实客户主体。",),
        source_direction_report_ids=("r",),
        source_direction_ranking_sections=(),
        evidence_refs=(EvidenceReference("e"),),
    )


def test_action_recommendations_validate_and_normalize_direction_ids():
    result = validate_action_recommendations(
        {"action_recommendations": ["关联方向：financial_position；行动：补充财务报表。"]}
    )
    assert result == ("关联方向：财务情况；行动：补充财务报表。",)


def test_action_prompt_contains_rating_and_direction_context():
    messages = build_action_recommendation_messages(_assessment(), enterprise_name="测试企业")
    assert "客户风险评级报告" in messages[1]["content"]
    assert "财务情况" in messages[1]["content"] or "direction_results" in messages[1]["content"]
    assert "行动建议" in messages[0]["content"]


def test_action_recommendations_are_rendered_as_subitems():
    assessment = _assessment()
    markdown = overall_assessment_to_markdown(
        EnterpriseOverallAssessment(
            **{
                **assessment.__dict__,
                "verification_priorities": (
                    "行动类型：事实核验；优先级：高；行动：补充材料；原因：主体待核验；关联方向：企业治理；所需材料或核验对象：工商资料；建议时点：提交报告前；完成标准/升级条件：主体一致。",
                ),
            }
        )
    )
    assert "### 1. 补充材料" in markdown
    assert "- 行动类型：事实核验" in markdown
    assert "- 完成标准/升级条件：主体一致。" in markdown
