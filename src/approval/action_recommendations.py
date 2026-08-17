"""为客户风险评级报告生成面向业务人员的后续行动建议。"""

from __future__ import annotations

import json
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.prompts import load_prompt

from .guideline_definitions import GUIDELINE_SECTION_DEFINITIONS
from .models import EnterpriseOverallAssessment


_STATUS_LABELS = {
    "passed": "通过",
    "conditional_passed": "有条件通过",
    "failed": "不通过",
    "insufficient_information": "信息不足",
}
_CONSTRAINT_LABELS = {"strong": "强约束", "weak": "弱约束"}
_SECTION_TITLES = {
    item.section_id: item.title for item in GUIDELINE_SECTION_DEFINITIONS
}


def build_action_recommendation_messages(
    assessment: EnterpriseOverallAssessment,
    *,
    enterprise_name: str = "当前企业",
) -> list[dict[str, str]]:
    """只向模型提供已经形成的评级结论和方向摘要。"""
    package: dict[str, Any] = {
        "enterprise_name": enterprise_name,
        "rating_level": assessment.rating_level,
        "recommendation": assessment.recommendation,
        "strong_constraint_failed_count": assessment.strong_constraint_failed_count,
        "weak_constraint_failed_count": assessment.weak_constraint_failed_count,
        "overall_judgment": assessment.overall_judgment,
        "core_risks": list(assessment.core_risks),
        "mitigating_factors": list(assessment.mitigating_factors),
        "rating_boundaries": list(assessment.rating_boundaries),
        "existing_verification_priorities": list(assessment.verification_priorities),
        "direction_results": [
            {
                "section_id": item.section_id,
                "section_title": _SECTION_TITLES.get(item.section_id, item.section_id),
                "constraint_level": _CONSTRAINT_LABELS[item.constraint_level],
                "status": _STATUS_LABELS[item.status],
                "summary": item.summary,
            }
            for item in assessment.direction_results
        ],
    }
    system = load_prompt("action/行动建议规则.md")
    user = (
        "请根据以下已经审核的客户风险评级报告，生成报告末尾的后续行动建议。"
        "只能使用输入中的事实和结论，不得添加外部信息。只输出 JSON 对象。\n\n"
        f"评级报告输入：\n{json.dumps(package, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validate_action_recommendations(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        raise ValueError("action recommendation output must be an object")
    values = raw.get("action_recommendations")
    if not isinstance(values, list) or not values:
        raise ValueError("action_recommendations must be a non-empty list")
    cleaned = tuple(item.strip() for item in values if isinstance(item, str) and item.strip())
    if len(cleaned) != len(values):
        raise ValueError("action_recommendations must contain only non-empty strings")
    if len(cleaned) > 8:
        raise ValueError("action_recommendations must contain no more than 8 items")
    return normalize_action_recommendations(cleaned)


def normalize_action_recommendations(values: tuple[str, ...]) -> tuple[str, ...]:
    """将模型偶尔输出的内部方向 ID 转为业务可读名称。"""
    replacements = sorted(
        {
            item.section_id: item.title
            for item in GUIDELINE_SECTION_DEFINITIONS
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    normalized = []
    for value in values:
        text = value.replace("授信审批", "风险评级")
        for section_id, title in replacements:
            text = text.replace(section_id, title)
        normalized.append(text)
    return tuple(normalized)


def generate_action_recommendations(
    assessment: EnterpriseOverallAssessment,
    *,
    enterprise_name: str = "当前企业",
    config: GenerationConfig,
) -> tuple[str, ...]:
    raw = call_deepseek(
        build_action_recommendation_messages(
            assessment,
            enterprise_name=enterprise_name,
        ),
        config,
    )
    return validate_action_recommendations(raw)
