"""统一 Ontology 下的企业画像模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.ontology.schema import (
    CONTENT_ROLES,
    EXTRACTION_METHODS,
    INFORMATION_STATUSES,
    ONTOLOGY_VERSION,
    validate_relation,
)
from src.ontology.registry import REGISTRY


@dataclass(frozen=True)
class EvidenceReference:
    evidence_unit_id: str
    excerpt: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_unit_id.strip():
            raise ValueError("evidence_unit_id 不能为空。")


@dataclass(frozen=True)
class ProfileItem:
    item_id: str
    field_id: str
    section_id: str
    value: Any
    value_type: str
    information_status: str
    content_role: str
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    subject: str | None = None
    value_scope: str | None = None
    unit: str | None = None
    source_date: str | None = None
    reporting_period: str | None = None
    event_date: str | None = None
    effective_date: str | None = None
    review_status: str = "pending"
    extraction_method: str = "manual"
    ontology_version: str = ONTOLOGY_VERSION

    def __post_init__(self) -> None:
        for name in ("item_id", "field_id", "section_id", "value_type"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} 不能为空。")
        if self.subject is not None and (
            not isinstance(self.subject, str) or not self.subject.strip()
        ):
            raise ValueError("subject 必须是非空字符串或 None。")
        if self.value_scope is not None and (
            not isinstance(self.value_scope, str) or not self.value_scope.strip()
        ):
            raise ValueError("value_scope 必须是非空字符串或 None。")
        field = REGISTRY.validate_field(self.field_id, self.section_id, self.value_type)
        REGISTRY.validate_value(self.field_id, self.value)
        if self.information_status not in INFORMATION_STATUSES:
            raise ValueError(f"information_status 非法：{self.information_status!r}")
        if self.content_role not in CONTENT_ROLES:
            raise ValueError(f"content_role 非法：{self.content_role!r}")
        if self.review_status not in {"pending", "accepted", "rejected"}:
            raise ValueError(f"review_status 非法：{self.review_status!r}")
        if self.extraction_method not in EXTRACTION_METHODS:
            raise ValueError(f"extraction_method 非法：{self.extraction_method!r}")
        if self.review_status == "accepted" and not self.evidence_refs:
            raise ValueError("审核通过的 ProfileItem 必须绑定 EvidenceUnit。")
        if self.value_type == "money" and not self.unit:
            raise ValueError("金额类 ProfileItem 必须包含币种或单位。")
        if self.value_type == "integer" and (
            isinstance(self.value, bool)
            or not isinstance(self.value, int)
            or self.value < 0
        ):
            raise ValueError("integer 类型 ProfileItem 必须是非负整数。")
        if self.value_type == "ratio" and isinstance(self.value, (int, float)):
            if not 0 <= self.value <= 1:
                raise ValueError("ratio 必须在 0 至 1 之间。")
        if field.reporting_period_required and not self.reporting_period:
            raise ValueError(f"字段 {self.field_id} 必须包含统计期间。")
        if field.currency_required and not self.unit:
            raise ValueError(f"字段 {self.field_id} 必须包含币种。")
        if field.value_scope_required and not self.value_scope:
            raise ValueError(f"字段 {self.field_id} 必须包含统计范围。")


@dataclass(frozen=True)
class ProfileRelation:
    relation_id: str
    relation_type: str
    source_id: str
    source_type: str
    target_id: str
    target_type: str
    information_status: str
    content_role: str
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    review_status: str = "pending"

    def __post_init__(self) -> None:
        validate_relation(self.relation_type, self.source_type, self.target_type)
        if self.information_status not in INFORMATION_STATUSES:
            raise ValueError(f"information_status 非法：{self.information_status!r}")
        if self.content_role not in CONTENT_ROLES:
            raise ValueError(f"content_role 非法：{self.content_role!r}")


@dataclass(frozen=True)
class EnterpriseProfile:
    profile_id: str
    case_id: str
    enterprise_name: str
    profile_type: str
    ontology_version: str = ONTOLOGY_VERSION
    items: tuple[ProfileItem, ...] = field(default_factory=tuple)
    relations: tuple[ProfileRelation, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)
    review_status: str = "pending"

    def __post_init__(self) -> None:
        if self.profile_type not in {"historical", "current"}:
            raise ValueError(f"profile_type 非法：{self.profile_type!r}")
        if not self.profile_id.strip() or not self.case_id.strip() or not self.enterprise_name.strip():
            raise ValueError("profile_id、case_id 和 enterprise_name 不能为空。")
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("ProfileItem 的 item_id 不得重复。")


class HistoricalEnterpriseProfile(EnterpriseProfile):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(profile_type="historical", **kwargs)


class CurrentEnterpriseProfile(EnterpriseProfile):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(profile_type="current", **kwargs)
