"""行业背景受控 ReAct 的运行结构。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.evidence.models import EvidenceUnit
from src.evidence.service import EvidenceQueryService
from src.profiles.react_models import ReactTraceEntry

from .models import IndustryProfileGeneration


@dataclass(frozen=True)
class IndustryReactLimits:
    max_model_calls: int = 8
    max_search_calls: int = 10
    max_read_calls: int = 10
    max_read_units: int = 36
    max_catalog_items: int = 16


@dataclass
class IndustryReactSession:
    industry_id: str
    industry_name: str
    evidence_service: EvidenceQueryService
    limits: IndustryReactLimits
    discovered_units: dict[str, EvidenceUnit] = field(default_factory=dict)
    read_units: dict[str, EvidenceUnit] = field(default_factory=dict)
    catalog_items: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence_dimensions: dict[str, set[str]] = field(default_factory=dict)
    trace: list[ReactTraceEntry] = field(default_factory=list)


@dataclass(frozen=True)
class IndustryReactRun:
    industry_id: str
    status: str
    generation: IndustryProfileGeneration | None = None
    execution_mode: str = "react"
    evidence_catalog: tuple[dict[str, Any], ...] = ()
    selected_evidence_unit_ids: tuple[str, ...] = ()
    react_trace: tuple[ReactTraceEntry, ...] = ()
    api_meta: tuple[dict[str, Any], ...] = ()
    batch_statuses: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
