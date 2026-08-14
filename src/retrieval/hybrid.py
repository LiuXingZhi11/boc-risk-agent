"""BM25 与 Embedding 的候选合并。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bm25 import BM25Index
from .documents import RetrievalDocument
from .embedding import EmbeddingIndex, Encoder


@dataclass(frozen=True)
class HybridResult:
    """一次混合召回中的单个案例候选。

    两种检索器的原始排名和分数都保留，避免把不同量纲的分数直接相加。
    """

    case_id: str
    document: RetrievalDocument
    bm25_rank: int | None = None
    bm25_score: float | None = None
    embedding_rank: int | None = None
    embedding_score: float | None = None
    both_hit: bool = False
    rank: int = 0

    @property
    def match_type(self) -> str:
        return "both" if self.both_hit else "bm25" if self.bm25_rank is not None else "embedding"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_name": self.document.metadata.get("case_name"),
            "rank": self.rank,
            "match_type": self.match_type,
            "bm25_rank": self.bm25_rank,
            "bm25_score": self.bm25_score,
            "embedding_rank": self.embedding_rank,
            "embedding_score": self.embedding_score,
            "metadata": self.document.metadata,
        }


def hybrid_retrieve(
    query_text: str,
    bm25_index: BM25Index,
    embedding_index: EmbeddingIndex,
    encoder: Encoder,
    *,
    top_k_bm25: int = 5,
    top_k_embedding: int = 5,
    final_k: int = 5,
) -> list[HybridResult]:
    """分别召回后按案例 ID 合并，双路命中的候选优先。

    BM25 和余弦相似度不在这里做跨模型分数融合；排序主要依据是否双路命中，
    再依据候选在两路中的最佳排名和案例 ID 做确定性排序。
    """
    if final_k <= 0 or not query_text.strip():
        return []

    bm25_results = bm25_index.search(query_text, top_k=top_k_bm25)
    embedding_results = embedding_index.search(
        query_text,
        encoder,
        top_k=top_k_embedding,
    )
    merged: dict[str, dict[str, Any]] = {}

    for result in bm25_results:
        item = merged.setdefault(
            result.case_id,
            {"case_id": result.case_id, "document": result.document},
        )
        item.update(bm25_rank=result.rank, bm25_score=result.score)

    for result in embedding_results:
        item = merged.setdefault(
            result.case_id,
            {"case_id": result.case_id, "document": result.document},
        )
        item.update(embedding_rank=result.rank, embedding_score=result.score)

    def sort_key(item: dict[str, Any]) -> tuple[int, int, float, str]:
        bm25_rank = item.get("bm25_rank")
        embedding_rank = item.get("embedding_rank")
        best_rank = min(
            rank for rank in (bm25_rank, embedding_rank) if rank is not None
        )
        scores = [
            score
            for score in (item.get("bm25_score"), item.get("embedding_score"))
            if score is not None
        ]
        # 仅作为相同最佳排名时的稳定辅助排序，不代表跨模型分数融合。
        best_score = max(scores) if scores else 0.0
        return (
            0 if bm25_rank is not None and embedding_rank is not None else 1,
            best_rank,
            -best_score,
            item["case_id"],
        )

    ordered = sorted(merged.values(), key=sort_key)[:final_k]
    return [
        HybridResult(
            case_id=item["case_id"],
            document=item["document"],
            bm25_rank=item.get("bm25_rank"),
            bm25_score=item.get("bm25_score"),
            embedding_rank=item.get("embedding_rank"),
            embedding_score=item.get("embedding_score"),
            both_hit=item.get("bm25_rank") is not None and item.get("embedding_rank") is not None,
            rank=rank,
        )
        for rank, item in enumerate(ordered, start=1)
    ]
