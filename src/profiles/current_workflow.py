"""新案例 CurrentEnterpriseProfile 的证据发现和候选抽取流程。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from src.evidence.models import EvidenceUnit
from src.evidence.service import EvidenceQueryService
from src.llm.generation_config import GenerationConfig

from .extraction import (
    EvidenceSelectionResult,
    PROFILE_DOMAINS,
    build_evidence_catalog,
    extract_profile_candidates,
    select_evidence_units,
)
from .historical_workflow import HISTORICAL_DOMAIN_QUERIES
from .evidence_discovery import build_team_evidence_bundle, search_balanced_evidence


@dataclass(frozen=True)
class CurrentDomainResult:
    domain: str
    evidence_units: tuple[EvidenceUnit, ...]
    candidates: dict[str, Any] | None = None
    evidence_catalog: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    selected_evidence_unit_ids: tuple[str, ...] = field(default_factory=tuple)
    selection_api_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CurrentProfileRun:
    case_id: str
    profile_type: str = "current"
    domains: tuple[CurrentDomainResult, ...] = field(default_factory=tuple)


class CurrentProfileWorkflow:
    """新案例允许信息不完整，但复用统一的目录选择和证据读取机制。"""

    def __init__(
        self,
        evidence_service: EvidenceQueryService,
        *,
        extractor: Callable[..., dict[str, Any]] = extract_profile_candidates,
        selector: Callable[..., list[str]] = select_evidence_units,
    ) -> None:
        self.evidence_service = evidence_service
        self.extractor = extractor
        self.selector = selector

    def run(
        self,
        *,
        case_id: str,
        config: GenerationConfig | None = None,
        selection_config: GenerationConfig | None = None,
        extraction_config: GenerationConfig | None = None,
        query: str = "",
        domains: tuple[str, ...] = PROFILE_DOMAINS,
        max_evidence_per_domain: int = 20,
        max_selected_evidence_per_domain: int = 5,
        guide_text: str = "",
    ) -> CurrentProfileRun:
        if config is not None:
            selection_config = selection_config or config
            extraction_config = extraction_config or config
        if selection_config is None or extraction_config is None:
            raise ValueError("必须提供 selection_config 和 extraction_config。")
        results: list[CurrentDomainResult] = []
        for domain in domains:
            if domain not in HISTORICAL_DOMAIN_QUERIES:
                raise ValueError(f"新案例调查领域非法：{domain!r}")
            team_bundle = (
                build_team_evidence_bundle(self.evidence_service, case_id=case_id)
                if domain == "team"
                else []
            )
            if team_bundle:
                units = team_bundle
                keywords = HISTORICAL_DOMAIN_QUERIES[domain]
            else:
                units, keywords = self._search_domain(
                    case_id, domain, query, max_evidence_per_domain
                )
            catalog = build_evidence_catalog(units, keywords=keywords)
            if team_bundle:
                selection = [unit.evidence_unit_id for unit in team_bundle]
                selection_api_meta = {
                    "skipped": True,
                    "reason": "team_evidence_bundle_selected_locally",
                    "person_units": sum(
                        unit.metadata.get("block_type") == "person_biography"
                        for unit in team_bundle
                    ),
                }
            else:
                selection = self.selector(
                    catalog,
                    domain=domain,
                    config=selection_config,
                    max_selected=max_selected_evidence_per_domain,
                    guide_text="",
                ) if catalog else []
                selection_api_meta = {}
            if isinstance(selection, EvidenceSelectionResult):
                selected_ids = list(selection.selected_evidence_unit_ids)
                selection_api_meta = selection.api_meta
            else:
                selected_ids = list(selection)
            selected_set = set(selected_ids)
            selected_units = tuple(unit for unit in units if unit.evidence_unit_id in selected_set)
            candidates = (
                self.extractor(
                    selected_units,
                    domain=domain,
                    profile_type="current",
                    config=extraction_config,
                    guide_text=guide_text,
                )
                if selected_units
                else None
            )
            results.append(
                CurrentDomainResult(
                    domain,
                    selected_units,
                    candidates,
                    tuple(catalog),
                    tuple(selected_ids),
                    selection_api_meta,
                )
            )
        return CurrentProfileRun(case_id=case_id, domains=tuple(results))

    def _search_domain(
        self,
        case_id: str,
        domain: str,
        query: str,
        limit: int,
    ) -> tuple[list[EvidenceUnit], tuple[str, ...]]:
        keywords = tuple(dict.fromkeys((query, *HISTORICAL_DOMAIN_QUERIES[domain])))
        units = search_balanced_evidence(
            self.evidence_service,
            case_id=case_id,
            keywords=keywords,
            limit=limit,
        )
        return units, keywords
