from __future__ import annotations

from src.retrieval.bm25 import BM25Result
from src.retrieval.documents import RetrievalDocument
from src.retrieval.embedding import EmbeddingResult
from src.retrieval.hybrid import hybrid_retrieve


def document(case_id: str) -> RetrievalDocument:
    return RetrievalDocument(case_id, f"案例 {case_id}", {"case_name": case_id})


class StubBM25Index:
    def __init__(self, results: list[BM25Result]) -> None:
        self.results = results

    def search(self, query_text: str, top_k: int = 5) -> list[BM25Result]:
        return self.results[:top_k]


class StubEmbeddingIndex:
    def __init__(self, results: list[EmbeddingResult]) -> None:
        self.results = results

    def search(self, query_text: str, encoder, top_k: int = 5) -> list[EmbeddingResult]:
        return self.results[:top_k]


def test_hybrid_deduplicates_and_prioritizes_both_hits() -> None:
    common = document("CASE_COMMON")
    bm25_only = document("CASE_BM25")
    embedding_only = document("CASE_EMBEDDING")
    bm25 = StubBM25Index(
        [
            BM25Result("CASE_BM25", 1, 7.0, bm25_only),
            BM25Result("CASE_COMMON", 2, 5.0, common),
        ]
    )
    embedding = StubEmbeddingIndex(
        [
            EmbeddingResult("CASE_COMMON", 1, 0.91, common),
            EmbeddingResult("CASE_EMBEDDING", 2, 0.88, embedding_only),
        ]
    )

    results = hybrid_retrieve("风险查询", bm25, embedding, encoder=object(), final_k=3)

    assert [result.case_id for result in results] == [
        "CASE_COMMON",
        "CASE_BM25",
        "CASE_EMBEDDING",
    ]
    assert results[0].both_hit is True
    assert results[0].match_type == "both"
    assert results[0].bm25_rank == 2
    assert results[0].embedding_rank == 1
    assert results[0].rank == 1
    assert results[1].embedding_rank is None
    assert results[2].bm25_rank is None


def test_hybrid_is_deterministic_and_handles_empty_inputs() -> None:
    case_a = document("CASE_A")
    case_b = document("CASE_B")
    bm25 = StubBM25Index(
        [BM25Result("CASE_B", 1, 1.0, case_b), BM25Result("CASE_A", 1, 1.0, case_a)]
    )
    embedding = StubEmbeddingIndex([])

    results = hybrid_retrieve("风险查询", bm25, embedding, encoder=object(), final_k=5)
    assert [result.case_id for result in results] == ["CASE_A", "CASE_B"]
    assert hybrid_retrieve("", bm25, embedding, encoder=object()) == []
    assert hybrid_retrieve("风险查询", bm25, embedding, encoder=object(), final_k=0) == []


def test_hybrid_respects_each_candidate_limit() -> None:
    documents = [document(f"CASE_{index}") for index in range(3)]
    bm25_results = [
        BM25Result(doc.case_id, index + 1, 3.0 - index, doc)
        for index, doc in enumerate(documents)
    ]
    embedding_results = [
        EmbeddingResult(doc.case_id, index + 1, 0.9 - index / 10, doc)
        for index, doc in enumerate(documents)
    ]

    results = hybrid_retrieve(
        "风险查询",
        StubBM25Index(bm25_results),
        StubEmbeddingIndex(embedding_results),
        encoder=object(),
        top_k_bm25=1,
        top_k_embedding=2,
        final_k=5,
    )

    assert [result.case_id for result in results] == ["CASE_0", "CASE_1"]
    assert results[0].both_hit is True
    assert results[1].match_type == "embedding"
