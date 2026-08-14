"""DeepSeek 生成参数及 thinking/sampling 互斥规则。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


VALID_MODES = {"thinking", "sampling"}
VALID_REASONING_EFFORTS = {"high", "max"}
REQUEST_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class GenerationConfig:
    model: str = "deepseek-v4-flash"
    mode: str = "thinking"
    temperature: float = 0.2
    reasoning_effort: str = "high"
    max_retries: int = 2
    max_tokens: int = 18000
    base_url: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(
                "mode 只能是 thinking 或 sampling，"
                f"当前为 {self.mode!r}。"
            )
        if not isinstance(self.temperature, (int, float)) or isinstance(
            self.temperature, bool
        ):
            raise ValueError("temperature 必须是数字。")
        if not math.isfinite(float(self.temperature)) or not 0.0 <= float(
            self.temperature
        ) <= 2.0:
            raise ValueError("temperature 必须位于 0 到 2 之间。")
        if self.mode == "thinking" and self.reasoning_effort not in VALID_REASONING_EFFORTS:
            raise ValueError("thinking 模式的 reasoning_effort 必须为 high 或 max。")
        if (
            not isinstance(self.max_retries, int)
            or isinstance(self.max_retries, bool)
            or not 0 <= self.max_retries <= 2
        ):
            raise ValueError("max_retries 必须是 0 至 2 的整数，单次任务总尝试次数不得超过 3。")
        if not isinstance(self.max_tokens, int) or self.max_tokens <= 0:
            raise ValueError("max_tokens 必须是正整数。")
        if not self.model.strip():
            raise ValueError("model 必须是非空字符串。")

    def request_kwargs(self) -> dict[str, Any]:
        """返回 API 请求参数；不把互斥参数发送到错误的模式。"""
        request: dict[str, Any] = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "stream": False,
            "max_tokens": self.max_tokens,
        }
        if self.mode == "thinking":
            request["reasoning_effort"] = self.reasoning_effort
            request["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            request["temperature"] = float(self.temperature)
            request["extra_body"] = {"thinking": {"type": "disabled"}}
        return request
