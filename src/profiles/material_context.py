"""画像后续模型调用共享的企业与来源材料上下文。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.sources.models import SourceAsset

from .models import EnterpriseProfile


def build_profile_material_context(
    profile: EnterpriseProfile,
    sources: Iterable[SourceAsset] = (),
) -> dict[str, Any]:
    """只传来源标识信息，不重复传入原始文档正文。"""
    reporting_periods = sorted(
        {
            item.reporting_period.strip()
            for item in profile.items
            if item.review_status != "rejected"
            and isinstance(item.reporting_period, str)
            and item.reporting_period.strip()
        }
    )
    documents = [
        {
            "source_id": source.source_id,
            "document_title": source.title,
            "source_type": source.source_type,
            "source_date": source.source_date,
        }
        for source in sources
        if source.case_id == profile.case_id
    ]
    return {
        "case_id": profile.case_id,
        "enterprise_name": profile.enterprise_name,
        "profile_type": profile.profile_type,
        "reporting_periods": reporting_periods,
        "source_documents": documents,
    }
