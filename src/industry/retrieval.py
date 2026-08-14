"""为行业画像构造小规模、分维度的本地证据包。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.evidence import EvidenceQueryService
from src.evidence.models import EvidenceUnit

from .models import INDUSTRY_DIMENSIONS


INDUSTRY_SEARCH_TERMS = {
    "development_stage": (
        "发展阶段", "发展历程", "发展现状", "成熟度", "定义", "分类", "演进"
    ),
    "market_size_and_growth": (
        "市场规模", "增长率", "出货量", "市场预期", "细分市场", "区域市场", "需求"
    ),
    "technology_routes": (
        "技术路线", "核心技术", "关键技术", "技术体系", "技术架构", "技术演进", "感知控制"
    ),
    "value_chain": (
        "产业链", "上游", "下游", "关键零部件", "供应链", "利润池", "本体", "平台"
    ),
    "competition_landscape": (
        "竞争格局", "市场份额", "参与者", "厂商", "集中度", "头部企业", "国产化"
    ),
    "commercialization": (
        "商业化", "量产", "应用场景", "成本", "客户", "订单", "交付", "服务网络", "盈利"
    ),
    "policy_and_regulation": (
        "政策", "规划", "标准", "监管", "法律法规", "合规", "隐私", "数据安全", "出口管制"
    ),
    "industry_risks": (
        "风险", "挑战", "瓶颈", "制约", "安全事故", "责任", "就业", "隐私", "供应链风险"
    ),
}


@dataclass(frozen=True)
class IndustryEvidenceBundle:
    industry_id: str
    evidence_units: tuple[EvidenceUnit, ...]
    dimension_evidence_ids: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "industry_id": self.industry_id,
            "evidence_unit_ids": [
                unit.evidence_unit_id for unit in self.evidence_units
            ],
            "dimension_evidence_ids": self.dimension_evidence_ids,
        }


def industry_scope_id(industry_id: str) -> str:
    value = industry_id.strip()
    if not value:
        raise ValueError("industry_id 不能为空。")
    return f"INDUSTRY::{value}"


def build_industry_evidence_bundle(
    service: EvidenceQueryService,
    *,
    industry_id: str,
    max_per_dimension: int = 2,
    max_total_units: int = 20,
) -> IndustryEvidenceBundle:
    scope_id = industry_scope_id(industry_id)
    selected: dict[str, EvidenceUnit] = {}
    dimension_ids: dict[str, tuple[str, ...]] = {}
    for dimension_id in INDUSTRY_DIMENSIONS:
        matches: dict[str, EvidenceUnit] = {}
        for term in INDUSTRY_SEARCH_TERMS[dimension_id]:
            for unit in service.search_evidence(
                term,
                case_id=scope_id,
                top_k=max_per_dimension,
            ):
                matches.setdefault(unit.evidence_unit_id, unit)
                if len(matches) == max_per_dimension:
                    break
            if len(matches) == max_per_dimension:
                break
        dimension_ids[dimension_id] = tuple(matches)
        for evidence_id, unit in matches.items():
            if evidence_id not in selected and len(selected) < max_total_units:
                selected[evidence_id] = unit
    allowed_ids = set(selected)
    return IndustryEvidenceBundle(
        industry_id=industry_id,
        evidence_units=tuple(selected.values()),
        dimension_evidence_ids={
            dimension_id: tuple(
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id in allowed_ids
            )
            for dimension_id, evidence_ids in dimension_ids.items()
        },
    )
