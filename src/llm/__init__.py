"""大语言模型客户端。"""

from .deepseek_client import call_deepseek
from .generation_config import GenerationConfig

__all__ = ["GenerationConfig", "call_deepseek"]

