"""企业画像领域与行业背景维度之间的通用对应关系。"""

from src.industry.models import INDUSTRY_DIMENSIONS
from src.profiles.extraction import PROFILE_DOMAINS


DOMAIN_INDUSTRY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "enterprise_and_control": ("development_stage", "policy_and_regulation"),
    "team": ("technology_routes", "competition_landscape"),
    "technology_and_ip": ("technology_routes", "industry_risks"),
    "product_and_project": (
        "development_stage",
        "technology_routes",
        "commercialization",
    ),
    "market_and_commercialization": (
        "market_size_and_growth",
        "competition_landscape",
        "commercialization",
    ),
    "customer_and_supplier": (
        "value_chain",
        "competition_landscape",
        "industry_risks",
    ),
    "finance_and_funding": (
        "market_size_and_growth",
        "commercialization",
        "industry_risks",
    ),
    "risk_matters": ("policy_and_regulation", "industry_risks"),
    "authoritative_findings": ("policy_and_regulation",),
    "outcome_and_resolution": ("policy_and_regulation", "industry_risks"),
}


def validate_domain_industry_mapping() -> None:
    if set(DOMAIN_INDUSTRY_DIMENSIONS) != set(PROFILE_DOMAINS):
        raise ValueError("domain-industry mapping must cover every profile domain")
    valid_dimensions = set(INDUSTRY_DIMENSIONS)
    for domain_id, dimension_ids in DOMAIN_INDUSTRY_DIMENSIONS.items():
        if not dimension_ids:
            raise ValueError(f"{domain_id} must map to at least one industry dimension")
        if not set(dimension_ids).issubset(valid_dimensions):
            raise ValueError(f"{domain_id} references an unknown industry dimension")


validate_domain_industry_mapping()
