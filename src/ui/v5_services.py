"""科技型企业 V5 页面使用的轻量应用服务。"""

from __future__ import annotations

from typing import Any

from src.industry import ControlledReactIndustryWorkflow
from src.profiles.current_workflow import CurrentProfileWorkflow
from src.profiles.historical_workflow import HistoricalProfileWorkflow
from src.profiles.react_workflow import ControlledReactProfileWorkflow
from src.ui.material_services import (
    industry_source_rows,
    ingest_industry_source,
    ingest_uploaded_source,
    source_rows,
)
from src.ui.industry_services import (
    approve_industry_profile_review,
    generate_industry_profile_review as _generate_industry_profile_review,
    industry_profile_detail,
    industry_profile_rows,
)
from src.ui.profile_services import (
    approve_profile_review as _approve_profile_review,
    load_profile_review as _load_profile_review,
    profile_detail,
    profile_rows,
    profile_visual_card,
    run_domain_investigation as _run_domain_investigation,
    run_profile_topic_analysis,
    run_react_domain_investigation as _run_react_domain_investigation,
    run_react_profile_investigation as _run_react_profile_investigation,
)
from src.ui.rating_direction_services import (
    approve_direction_ranking_review,
    approve_domain_approval_review,
    direction_ranking_basis_detail,
    direction_ranking_detail,
    domain_approval_report_detail,
    generate_direction_ranking_review,
    generate_domain_approval_review,
    generate_guideline_section_review,
    generate_standalone_guideline_section_review,
    guideline_section_rows,
)
from src.ui.rating_overall_services import (
    approve_composite_approval_review,
    approve_enterprise_overall_assessment_review,
    composite_approval_report_detail,
    enterprise_overall_assessment_detail,
    generate_composite_approval_review,
    generate_enterprise_action_recommendations,
    generate_enterprise_overall_assessment_review,
    generate_standalone_enterprise_overall_assessment_review,
)
from src.ui.rating_configuration_services import (
    approval_workspace_rows,
    approve_approval_point_definition,
    approve_comparable_metric_definition,
    approve_metric_value_candidate,
    approve_peer_cohort,
    create_approval_point_definition,
    create_comparable_metric_definition,
    create_peer_cohort,
    metric_value_candidates,
)


def generate_industry_profile_review(**kwargs: Any) -> dict[str, Any]:
    """兼容旧页面入口，并保留测试替换工作流的能力。"""
    return _generate_industry_profile_review(
        workflow_class=ControlledReactIndustryWorkflow,
        **kwargs,
    )


def load_profile_review(content: bytes | str) -> dict[str, Any]:
    return _load_profile_review(content)


def run_domain_investigation(**kwargs: Any) -> dict[str, Any]:
    return _run_domain_investigation(
        historical_workflow_class=HistoricalProfileWorkflow,
        current_workflow_class=CurrentProfileWorkflow,
        **kwargs,
    )


def run_react_domain_investigation(**kwargs: Any) -> dict[str, Any]:
    return _run_react_domain_investigation(
        workflow_class=ControlledReactProfileWorkflow,
        **kwargs,
    )


def run_react_profile_investigation(**kwargs: Any) -> dict[str, Any]:
    return _run_react_profile_investigation(
        domain_runner=run_react_domain_investigation,
        **kwargs,
    )


def approve_profile_review(**kwargs: Any) -> dict[str, Any]:
    return _approve_profile_review(**kwargs)
