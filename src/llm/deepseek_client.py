"""DeepSeek Chat Completions 客户端封装。"""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - 环境缺依赖时由调用路径给出清晰错误
    OpenAI = None  # type: ignore[assignment,misc]

from src.config.settings import get_settings
from src.llm.generation_config import GenerationConfig, REQUEST_TIMEOUT_SECONDS
from src.utils.json_utils import extract_json_from_text


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


class EmptyResponseError(ValueError):
    """API 成功响应但没有可解析正文，允许在总上限内自动重试。"""


def _usage_value(usage: Any, name: str) -> int | None:
    if usage is None:
        return None
    value = getattr(usage, name, None)
    return value if isinstance(value, int) else None


def _create_client(config: GenerationConfig) -> Any:
    if OpenAI is None:
        raise RuntimeError("未安装 openai 库，请先执行：pip install -U openai")

    settings = get_settings()
    if not settings.api_key:
        raise RuntimeError("未设置环境变量 DEEPSEEK_API_KEY。")

    kwargs: dict[str, Any] = {
        "api_key": settings.api_key,
        "base_url": config.base_url or settings.base_url,
        "max_retries": 0,
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }
    return OpenAI(**kwargs)


def _parse_response(response: Any, config: GenerationConfig) -> dict[str, Any]:
    choices = getattr(response, "choices", None)
    if not choices:
        raise EmptyResponseError("API 返回中没有 choices。")
    choice = choices[0]
    message = getattr(choice, "message", None)
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason == "length":
        raise ValueError(f"输出达到 max_tokens={config.max_tokens}，请提高上限。")
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise EmptyResponseError("API 返回了空内容。")

    parsed = extract_json_from_text(content)
    if not isinstance(parsed, dict):
        raise ValueError("模型输出的 JSON 顶层必须是对象。")

    usage = getattr(response, "usage", None)
    parsed["api_meta"] = {
        "model": config.model,
        "generation_mode": config.mode,
        "temperature": float(config.temperature)
        if config.mode == "sampling"
        else None,
        "reasoning_effort": config.reasoning_effort
        if config.mode == "thinking"
        else None,
        "finish_reason": finish_reason,
        "prompt_tokens": _usage_value(usage, "prompt_tokens"),
        "completion_tokens": _usage_value(usage, "completion_tokens"),
        "total_tokens": _usage_value(usage, "total_tokens"),
    }
    return parsed


def call_deepseek(messages: list[dict[str, str]], config: GenerationConfig) -> dict[str, Any]:
    """调用 DeepSeek 并返回模型 JSON 字段及 ``api_meta``。

    空响应固定最多尝试 3 次；其他异常由 ``max_retries`` 控制，且所有情况
    的单次任务总尝试次数都不超过 3。日志只记录异常类型和阶段，不记录请求内容。
    """
    request = config.request_kwargs()
    request["messages"] = messages
    last_error: Exception | None = None
    attempts = 0
    empty_response_count = 0

    for attempt in range(MAX_ATTEMPTS):
        attempts = attempt + 1
        try:
            client = _create_client(config)
            response = client.chat.completions.create(**request)
            parsed = _parse_response(response, config)
            parsed["api_meta"].update(
                {
                    "attempt_count": attempts,
                    "empty_response_count": empty_response_count,
                }
            )
            return parsed
        except Exception as exc:
            last_error = exc
            if isinstance(exc, EmptyResponseError):
                empty_response_count += 1
                allowed_attempts = MAX_ATTEMPTS
            else:
                allowed_attempts = min(config.max_retries + 1, MAX_ATTEMPTS)
            logger.warning(
                "DeepSeek 调用失败（第 %d/%d 次）：%s",
                attempts,
                max(attempts, allowed_attempts),
                type(exc).__name__,
            )
            if attempts < allowed_attempts:
                time.sleep(min(2 * attempts, 10))
                continue
            break

    raise RuntimeError(
        f"DeepSeek 调用失败，已尝试 {attempts} 次：{last_error}"
    ) from last_error
