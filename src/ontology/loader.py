"""加载程序接口本体并合并业务字段语义。"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ONTOLOGY_MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "prompts"
    / "data"
    / "企业画像本体.yaml"
)
ONTOLOGY_SEMANTICS_PATH = (
    ONTOLOGY_MANIFEST_PATH.parent / "企业画像字段语义.yaml"
)

_SEMANTIC_KEYS = frozenset(
    {
        "label",
        "description",
        "synonyms",
        "include_when",
        "exclude_when",
        "extraction_notes",
    }
)


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    with ONTOLOGY_MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    with ONTOLOGY_SEMANTICS_PATH.open("r", encoding="utf-8") as handle:
        semantics = yaml.safe_load(handle)

    semantic_fields = semantics.get("fields", {})
    manifest_fields = {item["id"]: item for item in manifest["fields"]}
    unknown_fields = set(semantic_fields) - set(manifest_fields)
    if unknown_fields:
        raise ValueError(
            "业务字段语义包含未知 field_id："
            + ", ".join(sorted(unknown_fields))
        )
    for field_id, semantic in semantic_fields.items():
        unknown_keys = set(semantic) - _SEMANTIC_KEYS
        if unknown_keys:
            raise ValueError(
                f"业务字段语义 {field_id} 不得修改程序接口字段："
                + ", ".join(sorted(unknown_keys))
            )
        manifest_fields[field_id].update(semantic)
    missing_fields = set(manifest_fields) - set(semantic_fields)
    if missing_fields:
        raise ValueError(
            "程序接口字段缺少业务语义："
            + ", ".join(sorted(missing_fields))
        )
    manifest["fields"] = list(manifest_fields.values())
    return manifest


def ontology_hash() -> str:
    payload = (
        ONTOLOGY_MANIFEST_PATH.read_bytes()
        + b"\0"
        + ONTOLOGY_SEMANTICS_PATH.read_bytes()
    )
    return hashlib.sha256(payload).hexdigest()
