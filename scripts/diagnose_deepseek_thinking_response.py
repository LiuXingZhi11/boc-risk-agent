"""只打印 Thinking 接口响应字段的存在情况，不打印提示词、密钥或企业材料。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import get_settings
from src.llm.deepseek_client import _create_client
from src.llm.generation_config import GenerationConfig


def main() -> None:
    config = GenerationConfig(
        model=get_settings().model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=256,
        max_retries=0,
    )
    request = config.request_kwargs()
    request["messages"] = [
        {"role": "system", "content": "只输出合法 JSON。"},
        {"role": "user", "content": "输出 {\"ok\": true}。"},
    ]
    response = _create_client(config).chat.completions.create(**request)
    choice = response.choices[0] if response.choices else None
    message = choice.message if choice else None
    print(
        {
            "choice_count": len(response.choices or []),
            "finish_reason": getattr(choice, "finish_reason", None),
            "content_present": bool(getattr(message, "content", None)),
            "reasoning_content_present": bool(getattr(message, "reasoning_content", None)),
            "refusal_present": bool(getattr(message, "refusal", None)),
        }
    )


if __name__ == "__main__":
    main()
