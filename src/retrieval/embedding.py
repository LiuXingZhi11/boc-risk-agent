"""本地 BGE Embedding 索引；模型只在首次 encode 时加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np

from .documents import RetrievalDocument


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


@dataclass
class LocalEmbeddingModel:
    model_name: str = "BAAI/bge-base-zh-v1.5"
    cache_dir: str | Path | None = None
    device: str = "cpu"
    _model: Any = None

    def _resolve_model_path(self) -> str:
        configured_path = Path(self.model_name)
        if configured_path.exists():
            return str(configured_path)
        if self.cache_dir is None:
            return self.model_name

        cache_root = Path(self.cache_dir)
        model_cache = cache_root / f"models--{self.model_name.replace('/', '--')}"
        ref_path = model_cache / "refs" / "main"
        if not ref_path.exists():
            raise RuntimeError(f"本地 Embedding 模型缓存不存在：{model_cache}")
        revision = ref_path.read_text(encoding="utf-8").strip()
        snapshot = model_cache / "snapshots" / revision
        if not snapshot.exists():
            raise RuntimeError(f"本地 Embedding 模型快照不存在：{snapshot}")
        return str(snapshot)

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - 环境缺依赖时给出明确错误
                raise RuntimeError("未安装 sentence-transformers，无法加载 Embedding 模型。") from exc
            model_path = self._resolve_model_path()
            kwargs: dict[str, Any] = {"device": self.device}
            if self.cache_dir is not None:
                kwargs["cache_folder"] = str(self.cache_dir)
                kwargs["local_files_only"] = True
            self._model = SentenceTransformer(model_path, **kwargs)
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        vectors = self._load().encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


@dataclass(frozen=True)
class EmbeddingResult:
    case_id: str
    rank: int
    score: float
    document: RetrievalDocument


class EmbeddingIndex:
    def __init__(self, documents: Sequence[RetrievalDocument], vectors: np.ndarray, *, model_name: str) -> None:
        self.documents = tuple(documents)
        self.vectors = np.asarray(vectors, dtype=np.float32)
        self.model_name = model_name
        if self.vectors.ndim != 2:
            raise ValueError("Embedding 向量必须是二维数组。")
        if self.vectors.shape[0] != len(self.documents):
            raise ValueError("Embedding 向量行数必须与文档数量一致。")

    def search(
        self,
        query_text: str,
        encoder: Encoder,
        top_k: int = 5,
    ) -> list[EmbeddingResult]:
        if top_k <= 0 or not query_text.strip() or not self.documents:
            return []
        query_vectors = np.asarray(encoder.encode([query_text]), dtype=np.float32)
        if query_vectors.shape != (1, self.vectors.shape[1]):
            raise ValueError("查询向量维度与索引不一致。")
        query = query_vectors[0]
        query_norm = np.linalg.norm(query)
        vector_norms = np.linalg.norm(self.vectors, axis=1)
        denominator = vector_norms * query_norm
        scores = np.divide(
            self.vectors @ query,
            denominator,
            out=np.zeros_like(vector_norms),
            where=denominator != 0,
        )
        indices = sorted(
            range(len(self.documents)),
            key=lambda index: (-float(scores[index]), self.documents[index].case_id),
        )[:top_k]
        return [
            EmbeddingResult(
                case_id=self.documents[index].case_id,
                rank=rank,
                score=float(scores[index]),
                document=self.documents[index],
            )
            for rank, index in enumerate(indices, start=1)
        ]


def build_embedding_index(
    documents: Sequence[RetrievalDocument],
    encoder: Encoder,
    *,
    model_name: str,
) -> EmbeddingIndex:
    vectors = encoder.encode([doc.retrieval_text for doc in documents])
    return EmbeddingIndex(documents, vectors, model_name=model_name)
