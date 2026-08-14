"""BM25/Embedding 索引持久化。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .bm25 import BM25Index
from .documents import RetrievalDocument
from .embedding import EmbeddingIndex


INDEX_VERSION = "retrieval-v1"
RETRIEVAL_TEXT_VERSION = "retrieval-text-v1"


def persist_indices(
    output_dir: str | Path,
    bm25_index: BM25Index,
    embedding_index: EmbeddingIndex,
    *,
    source_database: str,
    retrieval_text_version: str = RETRIEVAL_TEXT_VERSION,
) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _write_json(
        directory / "bm25_metadata.json",
        [_document_payload(document) for document in bm25_index.documents],
    )
    _write_json(directory / "tokenized_corpus.json", [list(tokens) for tokens in bm25_index.tokenized_corpus])
    np.save(directory / "embeddings.npy", embedding_index.vectors)
    _write_json(
        directory / "embedding_metadata.json",
        {
            "embedding_model": embedding_index.model_name,
            "documents": [_document_payload(document) for document in embedding_index.documents],
        },
    )
    _write_json(
        directory / "index_manifest.json",
        {
            "index_version": INDEX_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding_model": embedding_index.model_name,
            "case_count": len(embedding_index.documents),
            "case_ids": [document.case_id for document in embedding_index.documents],
            "source_database": source_database,
            "retrieval_text_version": retrieval_text_version,
        },
    )


def load_bm25_index(input_dir: str | Path) -> BM25Index:
    directory = Path(input_dir)
    metadata = json.loads((directory / "bm25_metadata.json").read_text(encoding="utf-8"))
    tokenized = json.loads((directory / "tokenized_corpus.json").read_text(encoding="utf-8"))
    return BM25Index(_documents_from_payload(metadata), tokenized_corpus=tokenized)


def load_embedding_index(input_dir: str | Path) -> EmbeddingIndex:
    directory = Path(input_dir)
    metadata = json.loads((directory / "embedding_metadata.json").read_text(encoding="utf-8"))
    vectors = np.load(directory / "embeddings.npy")
    return EmbeddingIndex(
        _documents_from_payload(metadata["documents"]),
        vectors,
        model_name=metadata["embedding_model"],
    )


def _document_payload(document: RetrievalDocument) -> dict[str, Any]:
    return {
        "case_id": document.case_id,
        "retrieval_text": document.retrieval_text,
        "metadata": document.metadata,
    }


def _documents_from_payload(payload: list[dict[str, Any]]) -> list[RetrievalDocument]:
    return [
        RetrievalDocument(
            case_id=item["case_id"],
            retrieval_text=item["retrieval_text"],
            metadata=item["metadata"],
        )
        for item in payload
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
