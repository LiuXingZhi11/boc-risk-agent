"""受控 ReAct 企业画像调查的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.evidence.models import EvidenceUnit
from src.evidence.service import EvidenceQueryService


@dataclass(frozen=True)
class ReactLimits:
    max_model_calls: int = 6
    max_search_calls: int = 2
    max_read_calls: int = 2
    max_read_units: int = 8
    max_catalog_items: int = 10
    max_recovery_rounds: int = 1
    max_recovery_model_calls: int = 2
    max_recovery_search_calls: int = 1
    max_recovery_read_calls: int = 1
    max_recovery_read_units: int = 4
    max_total_read_units: int = 12
    max_relation_repair_calls: int = 1


@dataclass(frozen=True)
class ReactTraceEntry:
    tool_name: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]


@dataclass
class ReactToolSession:
    case_id: str
    domain: str
    evidence_service: EvidenceQueryService
    limits: ReactLimits
    phase: str = "react_evidence_discovery"
    discovered_units: dict[str, EvidenceUnit] = field(default_factory=dict)
    read_units: dict[str, EvidenceUnit] = field(default_factory=dict)
    catalog_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    trace: list[ReactTraceEntry] = field(default_factory=list)


@dataclass(frozen=True)
class ReactDomainResult:
    domain: str
    status: str
    evidence_units: tuple[EvidenceUnit, ...] = ()
    candidates: dict[str, Any] | None = None
    evidence_catalog: tuple[dict[str, Any], ...] = ()
    selected_evidence_unit_ids: tuple[str, ...] = ()
    react_trace: tuple[ReactTraceEntry, ...] = ()
    api_meta: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ReactProfileRun:
    case_id: str
    profile_type: str = "current"
    execution_mode: str = "react"
    domains: tuple[ReactDomainResult, ...] = ()
