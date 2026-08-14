"""第二阶段：从结构化案例中提炼单案例规则假设。"""

from __future__ import annotations

import json
from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.validators.rule_validator import validate_rule_hypotheses
from src.validators.structure_validator import validate_structured_cases


def _without_api_meta(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "api_meta"}


def _build_messages(structured_cases: dict[str, Any], guide_text: str) -> list[dict[str, str]]:
    clean_data = _without_api_meta(structured_cases)
    system_prompt = (
        f"{guide_text}\n\n"
        "执行要求：\n"
        "1. 仅输出一个合法 JSON 对象；\n"
        "2. 不输出 Markdown 代码块或额外说明；\n"
        "3. 严格执行当前阶段，不执行其他任务。"
    )
    user_prompt = (
        "执行第二阶段：只根据结构化事实生成单案例规则假设。"
        "不要生成风险信号、跨案例规则或额外字段。\n\n"
        "===== 结构化案例开始 =====\n"
        f"{json.dumps(clean_data, ensure_ascii=False, indent=2)}\n"
        "===== 结构化案例结束 ====="
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def extract_rule_hypotheses(
    structured_cases: dict[str, Any],
    guide_text: str,
    config: GenerationConfig,
) -> dict[str, Any]:
    """校验输入，调用第二阶段模型并校验规则结果。"""
    if not isinstance(structured_cases, dict):
        raise ValueError("structured_cases 必须是对象。")
    if not guide_text.strip():
        raise ValueError("guide_text 不能为空。")

    clean_data = _without_api_meta(structured_cases)
    validate_structured_cases(clean_data)
    result = call_deepseek(_build_messages(clean_data, guide_text), config)
    validate_rule_hypotheses(_without_api_meta(result), clean_data)
    result["api_meta"] = {
        **(result.get("api_meta") or {}),
        "stage": "rules",
    }
    return result

