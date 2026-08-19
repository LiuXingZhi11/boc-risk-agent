"""外部 MCP 证据的追踪记录，与内部 EvidenceUnit 分开。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalEvidenceTrace:
    trace_id: str
    run_id: str
    skill_id: str
    skill_version: str
    provider: str
    server_id: str
    tool_name: str
    subject_name: str | None
    subject_identifier: str | None
    requested_at: str
    completed_at: str | None
    status: str
    request_summary: dict[str, Any]
    result_summary: dict[str, Any] | None
    raw_result_hash: str | None
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
