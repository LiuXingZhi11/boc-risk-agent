"""固定审查流程中的结构化、检索、重排和历史详情加载。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from src.llm.generation_config import GenerationConfig
from src.retrieval.bm25 import BM25Index
from src.retrieval.documents import build_retrieval_text
from src.retrieval.embedding import EmbeddingIndex, Encoder
from src.retrieval.hybrid import HybridResult, hybrid_retrieve
from src.retrieval.reranker import RerankResponse, rerank_candidates
from src.services.structure_service import structure_case
from src.storage.repository import CaseRepository

from .case_context import build_new_case_bundle, load_historical_case_details
from .comparison import (
    CaseComparison,
    collect_historical_rule_references,
    compare_case_pairs,
)
from .questions import ReviewQuestion, generate_review_questions


@dataclass(frozen=True)
class FixedReviewContext:
    """固定流程的中间结果，不包含比较结论或审批结论。"""

    run_id: str
    raw_case_text: str
    structured_case: dict[str, Any]
    new_case_bundle: Any
    retrieval_query: str
    candidates: tuple[HybridResult, ...]
    rerank: RerankResponse
    historical_cases: tuple[Any, ...]

    @property
    def degraded(self) -> bool:
        return self.rerank.degraded

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "raw_case_text": self.raw_case_text,
            "structured_case": self.structured_case,
            "new_case_id": self.new_case_bundle.case.case_id,
            "retrieval_query": self.retrieval_query,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "rerank": self.rerank.to_dict(),
            "historical_case_ids": [bundle.case.case_id for bundle in self.historical_cases],
            "historical_review_statuses": [
                bundle.case.review_status for bundle in self.historical_cases
            ],
        }


@dataclass(frozen=True)
class FixedReviewComparison:
    """固定流程上下文加上逐案例比较和历史规则参考。"""

    context: FixedReviewContext
    comparisons: tuple[CaseComparison, ...]
    historical_rule_references: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.context.to_dict(),
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "historical_rule_references": list(self.historical_rule_references),
        }


def run_fixed_review_questions(
    comparison_context: FixedReviewComparison,
    config: GenerationConfig,
    *,
    answered_questions: tuple[str, ...] = (),
    max_questions: int = 10,
) -> tuple[ReviewQuestion, ...]:
    """基于逐案例比较结果生成待核实问题。"""
    return generate_review_questions(
        comparison_context.context.new_case_bundle,
        comparison_context.comparisons,
        config,
        historical_cases=comparison_context.context.historical_cases,
        answered_questions=answered_questions,
        max_questions=max_questions,
    )


def run_fixed_review_report(
    comparison_context: FixedReviewComparison,
    questions: tuple[ReviewQuestion, ...] = (),
):
    """从固定流程中间结果生成最终报告对象。"""
    from .report import build_review_report

    return build_review_report(comparison_context, questions)


def run_fixed_review_context(
    *,
    raw_case_text: str,
    structure_guide: str,
    structure_config: GenerationConfig,
    repository: CaseRepository,
    bm25_index: BM25Index,
    embedding_index: EmbeddingIndex,
    encoder: Encoder,
    rerank_config: GenerationConfig,
    top_k_candidates: int = 5,
    top_k_historical: int = 3,
    new_case_id: str | None = None,
) -> FixedReviewContext:
    """执行固定流程前半段，返回可供比较阶段使用的上下文。"""
    if not isinstance(raw_case_text, str) or not raw_case_text.strip():
        raise ValueError("raw_case_text 不能为空")
    if not structure_guide.strip():
        raise ValueError("structure_guide 不能为空")
    if top_k_candidates <= 0 or top_k_historical <= 0:
        raise ValueError("候选数量必须大于 0")

    run_id = f"REVIEW_{uuid.uuid4().hex[:12].upper()}"
    structured_case = structure_case(
        raw_case_text.strip(),
        structure_guide,
        structure_config,
    )
    new_case_bundle = build_new_case_bundle(
        structured_case,
        raw_text=raw_case_text,
        new_case_id=new_case_id or f"NEW_CASE_{run_id.removeprefix('REVIEW_')}",
    )
    retrieval_query = build_retrieval_text(new_case_bundle)
    candidates = tuple(
        hybrid_retrieve(
            retrieval_query,
            bm25_index,
            embedding_index,
            encoder,
            top_k_bm25=top_k_candidates,
            top_k_embedding=top_k_candidates,
            final_k=top_k_candidates,
        )
    )
    rerank = rerank_candidates(
        retrieval_query,
        candidates,
        rerank_config,
        top_k=top_k_historical,
    )
    historical_case_ids = [case.case_id for case in rerank.ranked_cases[:top_k_historical]]
    historical_cases = load_historical_case_details(repository, historical_case_ids)
    return FixedReviewContext(
        run_id=run_id,
        raw_case_text=raw_case_text.strip(),
        structured_case=structured_case,
        new_case_bundle=new_case_bundle,
        retrieval_query=retrieval_query,
        candidates=candidates,
        rerank=rerank,
        historical_cases=historical_cases,
    )


def run_fixed_review_comparison(
    context: FixedReviewContext,
    config: GenerationConfig,
) -> FixedReviewComparison:
    """对已加载的 Top 3 历史案例执行逐案例比较。"""
    comparisons = compare_case_pairs(
        context.new_case_bundle,
        context.historical_cases,
        config,
    )
    return FixedReviewComparison(
        context=context,
        comparisons=comparisons,
        historical_rule_references=collect_historical_rule_references(comparisons),
    )
