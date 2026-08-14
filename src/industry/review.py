"""行业背景画像人工批准。"""

from __future__ import annotations

from dataclasses import replace

from .models import IndustryBackgroundProfile


def approve_industry_profile(
    profile: IndustryBackgroundProfile,
) -> IndustryBackgroundProfile:
    if profile.review_status != "pending":
        raise ValueError("只有 pending 行业画像可以批准。")
    return replace(
        profile,
        insights=tuple(
            replace(insight, review_status="accepted")
            for insight in profile.insights
        ),
        review_status="approved",
    )
