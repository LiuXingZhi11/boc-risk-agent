"""兼容旧 profile_type 的固定调查领域画像候选流程。"""

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
from .evidence_discovery import build_team_evidence_bundle, search_balanced_evidence


HISTORICAL_DOMAIN_QUERIES: dict[str, tuple[str, ...]] = {
    "enterprise_and_control": ("发行人", "实际控制人", "股东"),
    "team": (
        "核心技术人员",
        "实际控制人",
        "董事长",
        "学历",
        "主要工作经历",
        "主要职业经历",
        "股权激励",
    ),
    "technology_and_ip": ("核心技术", "专利", "知识产权", "技术来源"),
    "product_and_project": ("主要产品", "研发项目", "产业化", "产品"),
    "market_and_commercialization": ("市场", "竞争", "商业化", "销售"),
    "customer_and_supplier": ("前五名客户", "前五名供应商", "客户集中度", "供应商集中度", "采购额"),
    "finance_and_funding": (
        "营业收入",
        "净利润",
        "现金流",
        "研发费用",
        "主要会计数据",
        "应收账款",
        "担保",
    ),
    "risk_matters": ("风险", "诉讼", "处罚", "违规"),
    "authoritative_findings": ("行政处罚", "监管认定", "复议决定", "法院"),
    "outcome_and_resolution": ("终止上市", "退市", "赔偿", "整改"),
}


@dataclass(frozen=True)
class HistoricalDomainResult:
    domain: str
    evidence_units: tuple[EvidenceUnit, ...]
    candidates: dict[str, Any] | None = None
    evidence_catalog: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    selected_evidence_unit_ids: tuple[str, ...] = field(default_factory=tuple)
    selection_api_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HistoricalProfileRun:
    case_id: str
    profile_type: str = "historical"
    domains: tuple[HistoricalDomainResult, ...] = field(default_factory=tuple)


class HistoricalProfileWorkflow:
    """固定领域负责覆盖范围，领域内证据查询保持简单可控。"""

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
        domains: tuple[str, ...] = PROFILE_DOMAINS,
        max_evidence_per_domain: int = 20,
        max_selected_evidence_per_domain: int = 5,
        guide_text: str = "",
    ) -> HistoricalProfileRun:
        if config is not None:
            selection_config = selection_config or config
            extraction_config = extraction_config or config
        if selection_config is None or extraction_config is None:
            raise ValueError("必须提供 selection_config 和 extraction_config。")
        results: list[HistoricalDomainResult] = []
        for domain in domains:
            if domain not in HISTORICAL_DOMAIN_QUERIES:
                raise ValueError(f"历史调查领域非法：{domain!r}")
            team_bundle = (
                build_team_evidence_bundle(self.evidence_service, case_id=case_id)
                if domain == "team"
                else []
            )
            units = team_bundle or self._search_domain(case_id, domain, max_evidence_per_domain)
            catalog = build_evidence_catalog(
                units,
                keywords=HISTORICAL_DOMAIN_QUERIES[domain],
            )
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
            selected_units = tuple(
                unit for unit in units if unit.evidence_unit_id in set(selected_ids)
            )
            candidates = None
            if selected_units:
                candidates = self.extractor(
                    selected_units,
                    domain=domain,
                    profile_type="historical",
                    config=extraction_config,
                    guide_text=guide_text,
                )
            results.append(
                HistoricalDomainResult(
                    domain,
                    selected_units,
                    candidates,
                    tuple(catalog),
                    tuple(selected_ids),
                    selection_api_meta,
                )
            )
        return HistoricalProfileRun(case_id=case_id, domains=tuple(results))

    def _search_domain(self, case_id: str, domain: str, limit: int) -> list[EvidenceUnit]:
        return search_balanced_evidence(
            self.evidence_service,
            case_id=case_id,
            keywords=HISTORICAL_DOMAIN_QUERIES[domain],
            limit=limit,
        )
