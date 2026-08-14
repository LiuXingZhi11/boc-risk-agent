"""加载项目唯一的 Ontology manifest。"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ONTOLOGY_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "ontology" / "manifest.yaml"


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    with ONTOLOGY_MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def ontology_hash() -> str:
    return hashlib.sha256(ONTOLOGY_MANIFEST_PATH.read_bytes()).hexdigest()
