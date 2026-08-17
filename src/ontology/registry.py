"""Ontology 字段和关系注册表。"""

from __future__ import annotations

from dataclasses import dataclass

from .loader import load_manifest


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    section_id: str
    label: str
    value_type: str
    evidence_required: bool
    reporting_period_required: bool = False
    currency_required: bool = False
    value_scope_required: bool = False
    allowed_values: tuple[str, ...] = ()
    description: str = ""
    synonyms: tuple[str, ...] = ()
    include_when: tuple[str, ...] = ()
    exclude_when: tuple[str, ...] = ()
    extraction_notes: tuple[str, ...] = ()
    deprecated_since: str | None = None
    replaced_by: str | None = None


class OntologyRegistry:
    def __init__(self) -> None:
        manifest = load_manifest()
        self.fields = {
            item["id"]: FieldDefinition(
                field_id=item["id"],
                section_id=item["section_id"],
                label=item.get("label", item["id"]),
                value_type=item["value_type"],
                evidence_required=item.get("evidence_required", False),
                reporting_period_required=item.get("reporting_period_required", False),
                currency_required=item.get("currency_required", False),
                value_scope_required=item.get("value_scope_required", False),
                allowed_values=tuple(item.get("allowed_values", ())),
                description=item.get("description", ""),
                synonyms=tuple(item.get("synonyms", ())),
                include_when=tuple(item.get("include_when", ())),
                exclude_when=tuple(item.get("exclude_when", ())),
                extraction_notes=tuple(item.get("extraction_notes", ())),
                deprecated_since=item.get("deprecated_since"),
                replaced_by=item.get("replaced_by"),
            )
            for item in manifest["fields"]
        }
        self.sections = {item["id"] for item in manifest["fact_sections"]}

    def get_field(self, field_id: str) -> FieldDefinition:
        try:
            return self.fields[field_id]
        except KeyError as exc:
            raise ValueError(f"Ontology field_id 非法：{field_id!r}") from exc

    def validate_field(self, field_id: str, section_id: str, value_type: str) -> FieldDefinition:
        field = self.get_field(field_id)
        if section_id not in self.sections:
            raise ValueError(f"Ontology section_id 非法：{section_id!r}")
        if field.section_id != section_id:
            raise ValueError(f"字段 {field_id} 不属于板块 {section_id}。")
        if field.value_type != value_type:
            raise ValueError(f"字段 {field_id} 的 value_type 应为 {field.value_type}，实际为 {value_type}。")
        return field

    def validate_value(self, field_id: str, value: object) -> None:
        field = self.get_field(field_id)
        if field.allowed_values and value not in field.allowed_values:
            raise ValueError(
                f"字段 {field_id} 的值必须是：{', '.join(field.allowed_values)}。"
            )


REGISTRY = OntologyRegistry()
