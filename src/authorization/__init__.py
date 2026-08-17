"""应用层身份和内容访问控制。"""

from .service import (
    DEFAULT_ROLE,
    SUPPORTED_ROLES,
    can_edit_business_prompts,
    can_approve_results,
    can_run_approval_section,
    can_run_profile_domain,
    can_run_profile_dimension,
    can_view_debug,
    can_view_field,
    can_view_full_evidence,
    business_prompt_files,
    filter_profile_for_role,
    get_role_label,
    get_role_options,
    load_permission_config,
    permission_for_role,
)

__all__ = [
    "DEFAULT_ROLE",
    "SUPPORTED_ROLES",
    "can_edit_business_prompts",
    "can_approve_results",
    "can_run_approval_section",
    "can_run_profile_domain",
    "can_run_profile_dimension",
    "can_view_debug",
    "can_view_field",
    "can_view_full_evidence",
    "business_prompt_files",
    "filter_profile_for_role",
    "get_role_label",
    "get_role_options",
    "load_permission_config",
    "permission_for_role",
]
