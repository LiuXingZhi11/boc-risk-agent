"""行业背景工作区的页面服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.evidence import EvidenceQueryService, EvidenceRepository
from src.config.settings import get_settings
from src.industry import (
    ControlledReactIndustryWorkflow,
    IndustryReactLimits,
    IndustryProfileRepository,
    approve_industry_profile,
)
from src.llm.generation_config import GenerationConfig


def generate_industry_profile_review(
    *,
    database: str | Path,
    profile_id: str,
    industry_id: str,
    industry_name: str,
    max_model_calls: int = 8,
    max_search_calls: int = 10,
    max_read_calls: int = 10,
    max_read_units: int = 36,
    max_catalog_items: int = 16,
    max_tokens: int = 24000,
    max_retries: int = 2,
    workflow_class: Any | None = None,
) -> dict[str, Any]:
    evidence_service = EvidenceQueryService(EvidenceRepository(database))
    settings = get_settings()
    workflow = (workflow_class or ControlledReactIndustryWorkflow)(evidence_service)
    run = workflow.run(
        profile_id=profile_id,
        industry_id=industry_id,
        industry_name=industry_name,
        react_config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        extraction_config=GenerationConfig(
            model=settings.model,
            mode="thinking",
            reasoning_effort="high",
            max_tokens=max_tokens,
            max_retries=max_retries,
        ),
        limits=IndustryReactLimits(
            max_model_calls=max_model_calls,
            max_search_calls=max_search_calls,
            max_read_calls=max_read_calls,
            max_read_units=max_read_units,
            max_catalog_items=max_catalog_items,
        ),
        guide_text="",
    )
    if run.generation is not None:
        IndustryProfileRepository(database).save(run.generation.profile)
    return run.to_dict()


def approve_industry_profile_review(
    *,
    database: str | Path,
    profile_id: str,
) -> dict[str, Any]:
    repository = IndustryProfileRepository(database)
    profile = repository.get(profile_id)
    if profile is None:
        raise ValueError(f"IndustryBackgroundProfile 不存在：{profile_id}")
    approved = approve_industry_profile(profile)
    repository.save(approved)
    return approved.to_dict()


def industry_profile_rows(database: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile.profile_id,
            "industry_id": profile.industry_id,
            "industry_name": profile.industry_name,
            "review_status": profile.review_status,
            "insights": len(profile.insights),
            "sources": len(profile.source_ids),
        }
        for profile in IndustryProfileRepository(database).list()
    ]


def industry_profile_detail(
    database: str | Path,
    profile_id: str,
) -> dict[str, Any] | None:
    profile = IndustryProfileRepository(database).get(profile_id)
    return profile.to_dict() if profile is not None else None


__all__ = [
    "approve_industry_profile_review",
    "generate_industry_profile_review",
    "industry_profile_detail",
    "industry_profile_rows",
]
