"""第一阶段：将案例材料结构化为事实记录。"""

from __future__ import annotations

from typing import Any

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.validators.structure_validator import validate_structured_cases


def _build_messages(case_text: str, guide_text: str) -> list[dict[str, str]]:
    system_prompt = (
        f"{guide_text}\n\n"
        "执行要求：\n"
        "1. 仅输出一个合法 JSON 对象；\n"
        "2. 不输出 Markdown 代码块或额外说明；\n"
        "3. 严格执行当前阶段，不执行其他任务。"
    )
    user_prompt = (
        "执行第一阶段：只整理结构化事实，并从事实中指定一个 "
        "target_fact_id。不要提炼规则。\n\n"
        "===== 案例材料开始 =====\n"
        f"{case_text}\n"
        "===== 案例材料结束 ====="
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _without_api_meta(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key != "api_meta"}


def structure_case(
    case_text: str,
    guide_text: str,
    config: GenerationConfig,
) -> dict[str, Any]:
    """调用第一阶段模型、校验结果并附加 API 元数据。"""
    if not case_text.strip():
        raise ValueError("case_text 不能为空。")
    if not guide_text.strip():
        raise ValueError("guide_text 不能为空。")

    result = call_deepseek(_build_messages(case_text, guide_text), config)
    validate_structured_cases(_without_api_meta(result))
    result["api_meta"] = {
        **(result.get("api_meta") or {}),
        "stage": "structure",
    }
    return result

