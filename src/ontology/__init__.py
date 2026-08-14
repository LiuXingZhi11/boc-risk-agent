"""科技型企业 Ontology。"""

from .loader import ONTOLOGY_MANIFEST_PATH, load_manifest, ontology_hash
from .registry import FieldDefinition, OntologyRegistry, REGISTRY
from .schema import CONTENT_ROLES, INFORMATION_STATUSES, ONTOLOGY_VERSION, OBJECT_TYPES, RELATION_TYPES

__all__ = [
    "CONTENT_ROLES",
    "INFORMATION_STATUSES",
    "ONTOLOGY_MANIFEST_PATH",
    "ONTOLOGY_VERSION",
    "OBJECT_TYPES",
    "RELATION_TYPES",
    "load_manifest",
    "ontology_hash",
    "FieldDefinition",
    "OntologyRegistry",
    "REGISTRY",
]
