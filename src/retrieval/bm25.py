"""基于 jieba 和 rank-bm25 的关键词检索。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import jieba
from rank_bm25 import BM25Okapi

from .documents import RetrievalDocument


def tokenize(text: str) -> list[str]:
    return [token.strip() for token in jieba.lcut(text) if token.strip()]


@dataclass(frozen=True)
class BM25Result:
    case_id: str
    rank: int
    score: float
    document: RetrievalDocument


class BM25Index:
    def __init__(
        self,
        documents: Iterable[RetrievalDocument],
        *,
        tokenized_corpus: Iterable[Iterable[str]] | None = None,
    ) -> None:
        self.documents = tuple(documents)
        if tokenized_corpus is None:
            self.tokenized_corpus = tuple(tokenize(doc.retrieval_text) for doc in self.documents)
        else:
            self.tokenized_corpus = tuple(tuple(token for token in tokens) for tokens in tokenized_corpus)
        if len(self.documents) != len(self.tokenized_corpus):
            raise ValueError("BM25 文档和分词语料数量不一致。")
        self._bm25 = BM25Okapi([list(tokens) for tokens in self.tokenized_corpus]) if self.documents else None

    def search(self, query_text: str, top_k: int = 5) -> list[BM25Result]:
        if top_k <= 0 or not query_text.strip() or self._bm25 is None:
            return []
        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        indices = sorted(
            range(len(self.documents)),
            key=lambda index: (-float(scores[index]), self.documents[index].case_id),
        )[:top_k]
        return [
            BM25Result(
                case_id=self.documents[index].case_id,
                rank=rank,
                score=float(scores[index]),
                document=self.documents[index],
            )
            for rank, index in enumerate(indices, start=1)
        ]


def build_bm25_index(documents: Iterable[RetrievalDocument]) -> BM25Index:
    return BM25Index(documents)
