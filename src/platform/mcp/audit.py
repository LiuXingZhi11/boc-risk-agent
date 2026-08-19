"""MCP Tool 调用审计。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from src.evidence.external_models import ExternalEvidenceTrace


@dataclass(frozen=True)
class ToolCallAudit:
    trace_id: str
    qualified_tool_name: str
    status: str
    error_code: str | None
    started_at: str
    completed_at: str | None


@dataclass
class InMemoryAuditSink:
    audits: list[ToolCallAudit] = field(default_factory=list)
    traces: list[ExternalEvidenceTrace] = field(default_factory=list)

    def record_audit(self, audit: ToolCallAudit) -> None:
        self.audits.append(audit)

    def record_trace(self, trace: ExternalEvidenceTrace) -> None:
        self.traces.append(trace)

    def all_traces(self) -> Iterable[ExternalEvidenceTrace]:
        return tuple(self.traces)
