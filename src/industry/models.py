"""独立于企业画像的行业背景画像模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.profiles.models import EvidenceReference


INDUSTRY_DIMENSIONS = (
    "development_stage",
    "market_size_and_growth",
    "technology_routes",
    "value_chain",
    "competition_landscape",
    "commercialization",
    "policy_and_regulation",
    "industry_risks",
)
INDUSTRY_DIMENSION_DESCRIPTIONS = {
    "development_stage": "行业发展历程、成熟度和当前所处阶段，不包括具体技术或零部件价值",
    "market_size_and_growth": "市场规模、出货量、增长率、市场预测及直接需求驱动",
    "technology_routes": "技术架构、技术路线、核心技术方向及路线演进",
    "value_chain": "上游原材料与零部件、中游产品、下游应用等产业链分工",
    "competition_landscape": "市场参与者、市场份额、集中度及竞争关系",
    "commercialization": "量产、成本、应用落地、客户验证及商业模式",
    "policy_and_regulation": "具体产业政策、法律法规、标准、准入、监管要求或明确政策建议",
    "industry_risks": "不利影响、不确定性、技术瓶颈、供应链约束或安全伦理问题，不包括收益与机会",
}
INDUSTRY_INSIGHT_TYPES = (
    "reported_fact",
    "forecast",
    "analysis_judgment",
)


@dataclass(frozen=True)
class IndustryInsight:
    insight_id: str
    dimension_id: str
    statement: str
    insight_type: str
    evidence_refs: tuple[EvidenceReference, ...]
    time_scope: str | None = None
    geographic_scope: str | None = None
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if not self.insight_id.strip() or not self.statement.strip():
            raise ValueError("insight_id 和 statement 不能为空。")
        if self.dimension_id not in INDUSTRY_DIMENSIONS:
            raise ValueError(f"行业维度非法：{self.dimension_id!r}")
        if self.insight_type not in INDUSTRY_INSIGHT_TYPES:
            raise ValueError(f"行业要点类型非法：{self.insight_type!r}")
        if not self.evidence_refs:
            raise ValueError("行业要点必须绑定 EvidenceUnit。")
        if self.review_status not in {"pending", "accepted", "rejected"}:
            raise ValueError(f"行业要点审核状态非法：{self.review_status!r}")


@dataclass(frozen=True)
class IndustryBackgroundProfile:
    profile_id: str
    industry_id: str
    industry_name: str
    source_ids: tuple[str, ...]
    insights: tuple[IndustryInsight, ...]
    information_gaps: tuple[str, ...] = field(default_factory=tuple)
    review_status: str = "pending"
    generation_method: str = "llm"
    model: str | None = None
    api_meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("profile_id", "industry_id", "industry_name"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} 不能为空。")
        insight_ids = [insight.insight_id for insight in self.insights]
        if len(insight_ids) != len(set(insight_ids)):
            raise ValueError("IndustryInsight 的 insight_id 不得重复。")
        if self.review_status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"行业画像审核状态非法：{self.review_status!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IndustryProfileGeneration:
    profile: IndustryBackgroundProfile
    rejected_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "rejected_candidates": list(self.rejected_candidates),
        }
