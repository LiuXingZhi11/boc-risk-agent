"""授信审批指引的稳定方向、审批点和比较标准定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.industry.models import INDUSTRY_DIMENSIONS
from src.ontology.registry import REGISTRY

from .models import REVIEW_STATUSES


CONSTRAINT_LEVELS = {"strong", "weak"}
STRONG_CONSTRAINT_TRIGGER_CODES = {
    "equity_structure": ("unresolved_control_or_ownership_dispute",),
    "aml_sanctions": (
        "unresolved_sanctions_or_aml_violation",
        "prohibited_business_restriction",
    ),
}


@dataclass(frozen=True)
class GuidelineApprovalPointDefinition:
    point_id: str
    section_id: str
    title: str
    enterprise_field_ids: tuple[str, ...]
    industry_dimension_ids: tuple[str, ...] = field(default_factory=tuple)
    metric_ids: tuple[str, ...] = field(default_factory=tuple)
    max_enterprise_groups: int = 10
    max_industry_insights: int = 2
    max_metrics: int = 2
    review_status: str = "approved"

    def __post_init__(self) -> None:
        for name in ("point_id", "section_id", "title"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in (
            "enterprise_field_ids",
            "industry_dimension_ids",
            "metric_ids",
        ):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{name} items must be non-empty strings")
        if not self.enterprise_field_ids and not self.metric_ids:
            raise ValueError("an approval point needs enterprise fields or metrics")
        if self.max_enterprise_groups < 1 or self.max_industry_insights < 0 or self.max_metrics < 0:
            raise ValueError("approval point input limits are invalid")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"invalid review_status: {self.review_status!r}")
        unknown_fields = set(self.enterprise_field_ids) - set(REGISTRY.fields)
        if unknown_fields:
            raise ValueError(f"unknown enterprise fields: {sorted(unknown_fields)}")
        unknown_dimensions = set(self.industry_dimension_ids) - set(INDUSTRY_DIMENSIONS)
        if unknown_dimensions:
            raise ValueError(f"unknown industry dimensions: {sorted(unknown_dimensions)}")


@dataclass(frozen=True)
class GuidelineSectionDefinition:
    section_id: str
    title: str
    point_ids: tuple[str, ...]
    comparison_criteria: tuple[str, ...]
    ranking_enabled: bool = True
    max_comparison_card_chars: int = 2400
    review_status: str = "approved"
    constraint_level: str = "weak"
    score_weight: int = 10

    def __post_init__(self) -> None:
        for name in ("section_id", "title"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not self.point_ids or len(self.point_ids) != len(set(self.point_ids)):
            raise ValueError("point_ids must be non-empty and unique")
        if not self.comparison_criteria:
            raise ValueError("comparison_criteria must not be empty")
        if self.max_comparison_card_chars < 200:
            raise ValueError("max_comparison_card_chars is too small")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"invalid review_status: {self.review_status!r}")
        if self.constraint_level not in CONSTRAINT_LEVELS:
            raise ValueError(f"invalid constraint_level: {self.constraint_level!r}")
        if not isinstance(self.score_weight, int) or self.score_weight <= 0:
            raise ValueError("score_weight must be a positive integer")


def _point(
    point_id: str,
    section_id: str,
    title: str,
    fields: tuple[str, ...],
    dimensions: tuple[str, ...] = (),
    *,
    metrics: tuple[str, ...] = (),
    max_enterprise_groups: int = 10,
) -> GuidelineApprovalPointDefinition:
    return GuidelineApprovalPointDefinition(
        point_id=point_id,
        section_id=section_id,
        title=title,
        enterprise_field_ids=fields,
        industry_dimension_ids=dimensions,
        metric_ids=metrics,
        max_enterprise_groups=max_enterprise_groups,
    )


GUIDELINE_POINT_DEFINITIONS: tuple[GuidelineApprovalPointDefinition, ...] = (
    _point(
        "market_size",
        "market_space",
        "市场规模与增长空间",
        (
            "enterprise.main_business",
            "product.name",
            "product.commercialization_stage",
            "finance.operating_revenue",
        ),
        ("market_size_and_growth", "development_stage", "commercialization"),
        metrics=("operating_revenue",),
    ),
    _point(
        "market_penetration",
        "market_space",
        "市场渗透与替代空间",
        (
            "enterprise.main_business",
            "product.name",
            "product.commercialization_stage",
            "technology.source",
        ),
        ("market_size_and_growth", "commercialization", "industry_risks"),
    ),
    _point(
        "competition_barriers",
        "competition_landscape",
        "进退壁垒与竞争位置",
        (
            "enterprise.main_business",
            "product.name",
            "customer_supplier.customer_concentration",
            "customer_supplier.supplier_concentration",
        ),
        ("competition_landscape", "technology_routes", "industry_risks"),
    ),
    _point(
        "value_chain_position",
        "competition_landscape",
        "上下游产业链关系",
        (
            "product.name",
            "customer_supplier.customer_concentration",
            "customer_supplier.supplier_concentration",
            "customer_supplier.counterparty_name",
            "customer_supplier.related_party_status",
        ),
        ("value_chain", "competition_landscape", "industry_risks"),
    ),
    _point(
        "governance_norms",
        "enterprise_norms",
        "公司治理机制",
        (
            "enterprise.business_stage",
            "ownership.controller",
            "governance.equity_incentive_plan_status",
            "risk.matter",
        ),
        ("policy_and_regulation",),
    ),
    _point(
        "financial_norms",
        "enterprise_norms",
        "财务与管理规范性",
        (
            "finance.operating_revenue",
            "finance.operating_cash_flow",
            "finance.net_profit",
            "customer_supplier.related_party_status",
            "risk.matter",
        ),
        ("policy_and_regulation", "industry_risks"),
    ),
    _point(
        "technology_advancedness",
        "technology_strength",
        "技术先进性",
        (
            "technology.name",
            "technology.source",
            "intellectual_property.name",
            "intellectual_property.patent_application_count",
            "intellectual_property.patent_grant_count",
            "team.professional_background",
            "finance.research_expense_ratio",
        ),
        ("technology_routes", "commercialization", "industry_risks"),
        metrics=("research_expense_ratio", "patent_grant_count"),
    ),
    _point(
        "technology_stability",
        "technology_strength",
        "技术稳定性",
        (
            "technology.name",
            "technology.maturity_stage",
            "technology.ownership_status",
            "governance.equity_incentive_plan_status",
            "team.professional_background",
        ),
        ("technology_routes", "industry_risks"),
    ),
    _point(
        "technology_commercialization",
        "technology_strength",
        "技术转化为商业利益的可行性",
        (
            "technology.name",
            "product.name",
            "product.commercialization_stage",
            "finance.operating_revenue",
            "finance.research_expense_ratio",
        ),
        ("commercialization", "market_size_and_growth", "industry_risks"),
        metrics=("operating_revenue",),
    ),
    _point(
        "equity_control",
        "equity_structure",
        "控制权与股权稳定性",
        (
            "ownership.controller",
            "governance.equity_incentive_plan_status",
            "risk.matter",
        ),
        ("policy_and_regulation",),
    ),
    _point(
        "transformation_support",
        "transformation",
        "企业转型与配套支撑",
        (
            "enterprise.business_stage",
            "enterprise.main_business",
            "technology.name",
            "product.name",
            "product.commercialization_stage",
            "customer_supplier.counterparty_name",
            "finance.operating_revenue",
        ),
        ("development_stage", "technology_routes", "commercialization"),
    ),
    _point(
        "core_team",
        "core_team",
        "核心创始人与团队",
        (
            "ownership.controller",
            "team.key_person",
            "team.education_structure",
            "team.professional_background",
            "governance.equity_incentive_plan_status",
        ),
        ("technology_routes", "competition_landscape"),
    ),
    _point(
        "financing_valuation_and_pace",
        "equity_financing",
        "估值变化与融资节奏",
        (
            "enterprise.business_stage",
            "finance.cash_balance",
            "finance.interest_bearing_debt",
            "finance.operating_revenue",
            "risk.matter",
        ),
        ("development_stage", "commercialization", "industry_risks"),
    ),
    _point(
        "investment_institutions_and_agreements",
        "equity_financing",
        "投资机构与投资协议影响",
        (
            "enterprise.business_stage",
            "finance.cash_balance",
            "risk.matter",
        ),
        ("commercialization", "policy_and_regulation", "industry_risks"),
    ),
    _point(
        "financial_position",
        "financial_position",
        "财务状况与偿债基础",
        (
            "finance.operating_revenue",
            "finance.operating_cash_flow",
            "finance.net_profit",
            "finance.net_profit_attributable_to_parent",
            "finance.adjusted_net_profit_attributable_to_parent",
            "finance.cash_balance",
            "finance.interest_bearing_debt",
            "finance.research_expense_ratio",
        ),
        ("market_size_and_growth", "commercialization", "industry_risks"),
        metrics=("operating_revenue", "operating_cash_flow", "research_expense_ratio"),
    ),
    _point(
        "quantitative_assessment",
        "quantitative_assessment",
        "样本内指标与排名适用性",
        (
            "finance.operating_revenue",
            "finance.operating_cash_flow",
            "finance.research_expense_ratio",
        ),
        ("market_size_and_growth", "commercialization"),
        metrics=("operating_revenue", "operating_cash_flow", "research_expense_ratio"),
    ),
    _point(
        "aml_and_sanctions",
        "aml_sanctions",
        "反洗钱和制裁合规",
        (
            "customer_supplier.counterparty_name",
            "customer_supplier.transaction_amount",
            "customer_supplier.transaction_ratio",
            "customer_supplier.transaction_content",
            "customer_supplier.related_party_status",
            "risk.matter",
        ),
        ("policy_and_regulation", "industry_risks"),
    ),
)


GUIDELINE_SECTION_DEFINITIONS: tuple[GuidelineSectionDefinition, ...] = (
    GuidelineSectionDefinition(
        "market_space",
        "行业市场空间",
        ("market_size", "market_penetration"),
        ("市场规模和增长空间", "企业产品所处阶段和市场认可度", "替代或出海空间"),
        score_weight=10,
    ),
    GuidelineSectionDefinition(
        "competition_landscape",
        "行业竞争格局",
        ("competition_barriers", "value_chain_position"),
        ("进退壁垒", "先发或后发优势", "上下游关系和竞争稳定性"),
        score_weight=10,
    ),
    GuidelineSectionDefinition(
        "enterprise_norms",
        "企业规范性",
        ("governance_norms", "financial_norms"),
        ("治理和内部控制", "财务与管理规范", "法律和监管风险"),
        score_weight=10,
    ),
    GuidelineSectionDefinition(
        "technology_strength",
        "技术实力",
        ("technology_advancedness", "technology_stability", "technology_commercialization"),
        ("技术先进性", "技术稳定性", "技术转化为商业利益的可行性"),
        score_weight=15,
    ),
    GuidelineSectionDefinition(
        "equity_structure",
        "股权结构安排",
        ("equity_control",),
        ("控制权稳定性", "股东关系和后续变动风险"),
        constraint_level="strong",
        score_weight=10,
    ),
    GuidelineSectionDefinition(
        "transformation",
        "企业转型发展情况",
        ("transformation_support",),
        ("技术和产品积累", "资金、供应链和客户等配套支撑"),
        score_weight=8,
    ),
    GuidelineSectionDefinition(
        "core_team",
        "核心团队",
        ("core_team",),
        ("核心创始人和关键人员", "团队背景与稳定性"),
        score_weight=8,
    ),
    GuidelineSectionDefinition(
        "equity_financing",
        "股权融资影响",
        ("financing_valuation_and_pace", "investment_institutions_and_agreements"),
        ("估值和融资节奏", "投资机构专业性", "投资协议约束"),
        score_weight=8,
    ),
    GuidelineSectionDefinition(
        "financial_position",
        "财务情况",
        ("financial_position",),
        ("经营规模", "盈利和现金流", "债务和持续经营基础"),
        score_weight=12,
    ),
    GuidelineSectionDefinition(
        "quantitative_assessment",
        "量化评估工具应用",
        ("quantitative_assessment",),
        ("指标口径", "样本范围", "排名适用性和局限"),
        ranking_enabled=False,
        score_weight=4,
    ),
    GuidelineSectionDefinition(
        "aml_sanctions",
        "反洗钱和制裁合规管理要求",
        ("aml_and_sanctions",),
        ("客户和交易对手识别", "监管与制裁暴露", "已披露合规事项"),
        constraint_level="strong",
        score_weight=5,
    ),
)


GUIDELINE_POINTS_BY_ID = {item.point_id: item for item in GUIDELINE_POINT_DEFINITIONS}
GUIDELINE_SECTIONS_BY_ID = {
    item.section_id: item for item in GUIDELINE_SECTION_DEFINITIONS
}


def get_guideline_point_definitions(
    section_id: str,
) -> tuple[GuidelineApprovalPointDefinition, ...]:
    section = GUIDELINE_SECTIONS_BY_ID.get(section_id)
    if section is None:
        raise ValueError(f"unknown guideline section: {section_id!r}")
    return tuple(GUIDELINE_POINTS_BY_ID[point_id] for point_id in section.point_ids)


def validate_guideline_definitions() -> None:
    if len(GUIDELINE_SECTIONS_BY_ID) != len(GUIDELINE_SECTION_DEFINITIONS):
        raise ValueError("guideline section IDs must be unique")
    if len(GUIDELINE_POINTS_BY_ID) != len(GUIDELINE_POINT_DEFINITIONS):
        raise ValueError("guideline point IDs must be unique")
    referenced = {
        point_id
        for section in GUIDELINE_SECTION_DEFINITIONS
        for point_id in section.point_ids
    }
    if referenced != set(GUIDELINE_POINTS_BY_ID):
        raise ValueError("every guideline point must belong to exactly one section")
    for point in GUIDELINE_POINT_DEFINITIONS:
        if point.section_id not in GUIDELINE_SECTIONS_BY_ID:
            raise ValueError(f"point {point.point_id} references unknown section")
        if point.review_status != "approved":
            raise ValueError(f"point {point.point_id} is not approved")
    if sum(section.score_weight for section in GUIDELINE_SECTION_DEFINITIONS) != 100:
        raise ValueError("guideline score weights must sum to 100")


validate_guideline_definitions()
