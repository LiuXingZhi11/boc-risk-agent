"""读取权限配置并执行当前应用层的最小权限判断。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from src.profiles.models import EnterpriseProfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERMISSION_CONFIG_PATH = PROJECT_ROOT / "authorization" / "权限规则.yaml"
DEFAULT_ROLE = "general_business"
SUPPORTED_ROLES = ("general_business", "senior_business")


@lru_cache(maxsize=1)
def load_permission_config() -> dict[str, Any]:
    with PERMISSION_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    roles = config.get("roles") or {}
    missing = set(SUPPORTED_ROLES) - set(roles)
    if missing:
        raise ValueError("权限配置缺少身份：" + ", ".join(sorted(missing)))
    return config


def permission_for_role(role: str | None) -> dict[str, Any]:
    role_id = role or DEFAULT_ROLE
    try:
        return load_permission_config()["roles"][role_id]
    except KeyError as exc:
        raise ValueError(f"未知业务身份：{role_id}") from exc


def get_role_options() -> dict[str, str]:
    return {
        role: str(permission_for_role(role).get("label", role))
        for role in SUPPORTED_ROLES
    }


def get_role_label(role: str | None) -> str:
    role_id = role or DEFAULT_ROLE
    return get_role_options().get(role_id, role_id)


def can_view_field(role: str | None, field_id: str) -> bool:
    hidden_fields = set(permission_for_role(role).get("hidden_fields", ()))
    return field_id not in hidden_fields


def can_run_profile_domain(role: str | None, domain: str) -> bool:
    denied = set(permission_for_role(role).get("denied_profile_domains", ()))
    return domain not in denied


def can_run_profile_dimension(role: str | None, dimension_id: str) -> bool:
    denied = set(permission_for_role(role).get("denied_profile_dimensions", ()))
    return dimension_id not in denied


def can_run_approval_section(role: str | None, section_id: str) -> bool:
    denied = set(permission_for_role(role).get("denied_approval_sections", ()))
    return section_id not in denied


def can_view_debug(role: str | None) -> bool:
    return bool(permission_for_role(role).get("can_view_debug", False))


def can_edit_business_prompts(role: str | None) -> bool:
    return bool(permission_for_role(role).get("can_edit_business_prompts", False))


def can_view_full_evidence(role: str | None) -> bool:
    return bool(permission_for_role(role).get("can_view_full_evidence", False))


def can_approve_results(role: str | None) -> bool:
    return bool(permission_for_role(role).get("can_approve_results", False))


def business_prompt_files() -> tuple[str, ...]:
    return tuple(load_permission_config().get("business_prompt_files", ()))


def filter_profile_for_role(profile: Any, role: str | None) -> Any:
    """返回只包含当前身份可见字段的画像副本，供页面和模型输入共用。"""
    visible_items = tuple(
        item
        for item in profile.items
        if can_view_field(role, item.field_id)
    )
    visible_item_ids = {item.item_id for item in visible_items}
    visible_relations = tuple(
        relation
        for relation in profile.relations
        if _endpoint_visible(relation.source_id, visible_item_ids)
        and _endpoint_visible(relation.target_id, visible_item_ids)
    )
    return EnterpriseProfile(
        profile_id=profile.profile_id,
        case_id=profile.case_id,
        enterprise_name=profile.enterprise_name,
        profile_type=profile.profile_type,
        ontology_version=profile.ontology_version,
        items=visible_items,
        relations=visible_relations,
        information_gaps=profile.information_gaps,
        conflicts=profile.conflicts,
        review_status=profile.review_status,
    )


def _endpoint_visible(endpoint_id: str, visible_item_ids: set[str]) -> bool:
    # the_enterprise 等主体标识不是 profile_item，不受字段过滤影响。
    return endpoint_id in visible_item_ids or endpoint_id.startswith("the_")


def filter_items_by_role(role: str | None, items: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(item for item in items if can_view_field(role, item.field_id))
