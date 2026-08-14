"""从 manifest.yaml 加载的稳定 Ontology 定义。"""

from .loader import load_manifest, ontology_hash

_MANIFEST = load_manifest()
ONTOLOGY_VERSION = _MANIFEST["ontology"]["version"]
OBJECT_TYPES = frozenset(item["id"] for item in _MANIFEST["objects"])
RELATION_TYPES = {
    item["id"]: (tuple(item["domain"]), tuple(item["range"]))
    for item in _MANIFEST["relations"]
}
CONTENT_ROLES = frozenset(_MANIFEST["content_role"])
INFORMATION_STATUSES = frozenset(_MANIFEST["information_status"])
EXTRACTION_METHODS = frozenset(_MANIFEST["extraction_methods"])
COMPARISON_DIMENSION_SECTIONS = {
    item["id"]: tuple(item["section_ids"])
    for item in _MANIFEST.get("comparison_dimensions", [])
}


def validate_relation(relation_type: str, source_type: str, target_type: str) -> None:
    try:
        expected_sources, expected_targets = RELATION_TYPES[relation_type]
    except KeyError as exc:
        raise ValueError(f"关系类型非法：{relation_type!r}") from exc
    if source_type not in expected_sources or target_type not in expected_targets:
        raise ValueError(
            f"关系 {relation_type} 的 domain/range 不允许 {source_type}/{target_type}，"
            f"实际为 {source_type}/{target_type}。"
        )
