"""不同数据源共享的证据单元模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串。")
    return value.strip()


@dataclass(frozen=True)
class EvidenceUnit:
    """可被检索、读取和引用的最小证据单元。

    location 保留数据源特有定位信息，例如 PDF 页码、HTML 节点路径。
    """

    evidence_unit_id: str
    source_id: str
    case_id: str
    content_type: str
    content: str
    location: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_date: str | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_unit_id", "source_id", "case_id", "content_type", "content"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.location, Mapping):
            raise ValueError("location 必须是对象。")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata 必须是对象。")
        if self.source_date is not None:
            object.__setattr__(self, "source_date", _text(self.source_date, "source_date"))
        if not self.content_hash:
            raise ValueError("content_hash 不能为空。")
