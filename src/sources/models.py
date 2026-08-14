"""数据源模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SourceAsset:
    source_id: str
    case_id: str
    source_type: str
    path: str
    title: str
    source_date: str | None
    content_hash: str
    ingestion_status: str = "ready"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_id", "case_id", "source_type", "path", "title", "content_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串。")
        if self.source_date is not None and not isinstance(self.source_date, str):
            raise ValueError("source_date 必须是字符串或 None。")
