"""ComparisonCard 的结构化、BM25 与可选 BGE 混合召回。"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from src.retrieval.bm25 import BM25Index, tokenize
from src.retrieval.documents import RetrievalDocument
from src.retrieval.embedding import Encoder, EmbeddingIndex, build_embedding_index

from .comparison_card_repository import ComparisonCardRepository
from .comparison_cards import (
    ComparisonDimension,
    EnterpriseComparisonCard,
    comparison_dimension_text,
)


@dataclass(frozen=True)
class ComparisonCardMatch:
    historical_card_id: str
    historical_profile_id: str
    historical_case_id: str
    historical_enterprise_name: str
    score: float
    structured_score: float
    bm25_score: float
    embedding_score: float | None
    matched_dimensions: tuple[str, ...]
    matched_features: tuple[str, ...]
    matched_terms: tuple[str, ...]
    matched_relation_signatures: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "matched_dimensions": list(self.matched_dimensions),
            "matched_features": list(self.matched_features),
            "matched_terms": list(self.matched_terms),
            "matched_relation_signatures": list(
                self.matched_relation_signatures
            ),
            "evidence_unit_ids": list(self.evidence_unit_ids),
        }


@dataclass
class _Signals:
    structured: list[float] = field(default_factory=list)
    bm25_reciprocal_ranks: list[float] = field(default_factory=list)
    embedding_scores: list[float] = field(default_factory=list)
    dimensions: set[str] = field(default_factory=set)
    features: set[str] = field(default_factory=set)
    terms: set[str] = field(default_factory=set)
    relations: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)


class ComparisonCardSimilarityService:
    """只从审核通过且仍与画像版本一致的历史比较卡中召回。"""

    def __init__(
        self,
        repository: ComparisonCardRepository,
        *,
        encoder: Encoder | None = None,
        embedding_model_name: str = "local-bge",
    ) -> None:
        self.repository = repository
        self.encoder = encoder
        self.embedding_model_name = embedding_model_name

    def find_similar(
        self,
        current_card: EnterpriseComparisonCard,
        *,
        limit: int = 5,
        candidate_k_per_dimension: int = 10,
    ) -> list[ComparisonCardMatch]:
        if limit <= 0:
            return []
        historical = [
            card
            for card in self.repository.list_current(
                profile_type="historical", review_status="approved"
            )
            if card.case_id != current_card.case_id
            and card.ontology_version == current_card.ontology_version
        ]
        if not historical:
            return []

        historical_by_id = {card.card_id: card for card in historical}
        dimensions_by_id = {
            card.card_id: {item.dimension_id: item for item in card.dimensions}
            for card in historical
        }
        signals = {card.card_id: _Signals() for card in historical}

        for current_dimension in current_card.dimensions:
            documents = _dimension_documents(
                historical, current_dimension.dimension_id
            )
            if not documents:
                continue
            query = comparison_dimension_text(current_dimension)
            query_tokens = set(tokenize(query))
            bm25_results = BM25Index(documents).search(
                query, top_k=len(documents)
            )
            lexical_hits = [
                result
                for result in bm25_results
                if query_tokens & set(tokenize(result.document.retrieval_text))
            ][:candidate_k_per_dimension]
            for lexical_rank, result in enumerate(lexical_hits, start=1):
                card_id = result.document.metadata["card_id"]
                item = signals[card_id]
                item.bm25_reciprocal_ranks.append(1 / lexical_rank)
                item.dimensions.add(current_dimension.dimension_id)
                historical_dimension = dimensions_by_id[card_id][
                    current_dimension.dimension_id
                ]
                item.terms.update(
                    _normalized_term_intersection(
                        current_dimension, historical_dimension
                    )
                )
                item.evidence.update(historical_dimension.evidence_unit_ids)

            if self.encoder is not None:
                embedding_index = build_embedding_index(
                    documents,
                    self.encoder,
                    model_name=self.embedding_model_name,
                )
                for result in embedding_index.search(
                    query,
                    self.encoder,
                    top_k=candidate_k_per_dimension,
                ):
                    if result.score <= 0:
                        continue
                    card_id = result.document.metadata["card_id"]
                    item = signals[card_id]
                    item.embedding_scores.append(result.score)
                    item.dimensions.add(current_dimension.dimension_id)
                    historical_dimension = dimensions_by_id[card_id][
                        current_dimension.dimension_id
                    ]
                    item.evidence.update(historical_dimension.evidence_unit_ids)

            for card in historical:
                historical_dimension = dimensions_by_id[card.card_id].get(
                    current_dimension.dimension_id
                )
                if historical_dimension is None:
                    continue
                score, features, terms, relations = _structured_compare(
                    current_dimension, historical_dimension
                )
                if score <= 0:
                    continue
                item = signals[card.card_id]
                item.structured.append(score)
                item.dimensions.add(current_dimension.dimension_id)
                item.features.update(features)
                item.terms.update(terms)
                item.relations.update(relations)
                item.evidence.update(historical_dimension.evidence_unit_ids)

        matches: list[ComparisonCardMatch] = []
        dimension_count = max(1, len(current_card.dimensions))
        for card_id, item in signals.items():
            if not item.dimensions:
                continue
            structured_score = mean(item.structured) if item.structured else 0.0
            bm25_score = min(
                1.0, sum(item.bm25_reciprocal_ranks) / dimension_count
            )
            embedding_score = (
                mean(item.embedding_scores) if item.embedding_scores else None
            )
            if self.encoder is None:
                score = 0.55 * structured_score + 0.45 * bm25_score
            else:
                score = (
                    0.45 * structured_score
                    + 0.35 * bm25_score
                    + 0.20 * (embedding_score or 0.0)
                )
            card = historical_by_id[card_id]
            matches.append(
                ComparisonCardMatch(
                    historical_card_id=card.card_id,
                    historical_profile_id=card.profile_id,
                    historical_case_id=card.case_id,
                    historical_enterprise_name=card.enterprise_name,
                    score=round(score, 4),
                    structured_score=round(structured_score, 4),
                    bm25_score=round(bm25_score, 4),
                    embedding_score=(
                        round(embedding_score, 4)
                        if embedding_score is not None
                        else None
                    ),
                    matched_dimensions=tuple(sorted(item.dimensions)),
                    matched_features=tuple(sorted(item.features)),
                    matched_terms=tuple(sorted(item.terms)),
                    matched_relation_signatures=tuple(sorted(item.relations)),
                    evidence_unit_ids=tuple(sorted(item.evidence)),
                )
            )
        matches.sort(
            key=lambda match: (
                -match.score,
                -len(match.matched_dimensions),
                match.historical_card_id,
            )
        )
        return _deduplicate_enterprises(matches, historical_by_id)[:limit]


def _deduplicate_enterprises(
    matches: list[ComparisonCardMatch],
    cards_by_id: dict[str, EnterpriseComparisonCard],
) -> list[ComparisonCardMatch]:
    """同一历史企业存在多个画像版本时，优先保留覆盖维度更多的当前版本。"""
    selected: dict[str, ComparisonCardMatch] = {}
    for match in matches:
        key = "".join(match.historical_enterprise_name.casefold().split())
        previous = selected.get(key)
        if previous is None:
            selected[key] = match
            continue
        current_dimensions = len(cards_by_id[match.historical_card_id].dimensions)
        previous_dimensions = len(cards_by_id[previous.historical_card_id].dimensions)
        if (current_dimensions, match.score, len(match.matched_dimensions), match.historical_card_id) > (
            previous_dimensions,
            previous.score,
            len(previous.matched_dimensions),
            previous.historical_card_id,
        ):
            selected[key] = match
    return sorted(
        selected.values(),
        key=lambda match: (-match.score, -len(match.matched_dimensions), match.historical_card_id),
    )


def _dimension_documents(
    cards: list[EnterpriseComparisonCard],
    dimension_id: str,
) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for card in cards:
        dimension = next(
            (
                item
                for item in card.dimensions
                if item.dimension_id == dimension_id
            ),
            None,
        )
        if dimension is None:
            continue
        documents.append(
            RetrievalDocument(
                case_id=f"{card.case_id}::{dimension_id}",
                retrieval_text=comparison_dimension_text(dimension),
                metadata={
                    "card_id": card.card_id,
                    "profile_id": card.profile_id,
                    "case_id": card.case_id,
                    "enterprise_name": card.enterprise_name,
                    "dimension_id": dimension_id,
                },
            )
        )
    return documents


def _structured_compare(
    current: ComparisonDimension,
    historical: ComparisonDimension,
) -> tuple[float, set[str], set[str], set[str]]:
    common_feature_ids = set(current.structured_features) & set(
        historical.structured_features
    )
    matched_features = {
        field_id
        for field_id in common_feature_ids
        if current.structured_features[field_id]
        == historical.structured_features[field_id]
    }
    current_relations = set(current.relation_signatures)
    historical_relations = set(historical.relation_signatures)
    matched_relations = current_relations & historical_relations
    current_terms = {_normalize(term) for term in current.comparison_terms}
    historical_terms = {_normalize(term) for term in historical.comparison_terms}
    matched_terms = _normalized_term_intersection(current, historical)

    feature_score = (
        len(matched_features) / len(common_feature_ids)
        if common_feature_ids
        else 0.0
    )
    relation_union = current_relations | historical_relations
    relation_score = (
        len(matched_relations) / len(relation_union) if relation_union else 0.0
    )
    # 术语只占较小权重；同义表达主要交给 BM25/BGE。
    term_union = current_terms | historical_terms
    term_score = len(matched_terms) / len(term_union) if term_union else 0.0
    available = [
        (feature_score, 0.5, bool(common_feature_ids)),
        (relation_score, 0.3, bool(relation_union)),
        (term_score, 0.2, bool(term_union)),
    ]
    denominator = sum(weight for _, weight, present in available if present)
    score = (
        sum(value * weight for value, weight, present in available if present)
        / denominator
        if denominator
        else 0.0
    )
    return score, matched_features, matched_terms, matched_relations


def _normalize(value: str) -> str:
    return "".join(value.casefold().split())


def _normalized_term_intersection(
    current: ComparisonDimension,
    historical: ComparisonDimension,
) -> set[str]:
    current_terms = {_normalize(term) for term in current.comparison_terms}
    historical_terms = {_normalize(term) for term in historical.comparison_terms}
    return current_terms & historical_terms
