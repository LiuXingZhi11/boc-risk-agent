"""把固定审查流程显式适配为 Agent Executor 白名单服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.agent.executor import ExecutorServices
from src.agent.serialization import case_bundle_from_dict, case_bundle_to_dict
from src.llm.generation_config import GenerationConfig
from src.models import CaseBundle
from src.retrieval.documents import RetrievalDocument, build_retrieval_text
from src.retrieval.embedding import EmbeddingIndex, Encoder
from src.retrieval.bm25 import BM25Index
from src.retrieval.hybrid import HybridResult, hybrid_retrieve
from src.retrieval.reranker import RerankResponse, RerankedCase, rerank_candidates
from src.review.comparison import (
    CaseComparison,
    DifferenceFinding,
    RuleApplicability,
    SimilarityFinding,
    collect_historical_rule_references,
    compare_case_pairs,
)
from src.review.fixed_review import (
    FixedReviewComparison,
    FixedReviewContext,
    run_fixed_review_comparison,
    run_fixed_review_context,
    run_fixed_review_questions,
    run_fixed_review_report,
)
from src.review.questions import ReviewQuestion, generate_review_questions
from src.services.structure_service import structure_case
from src.storage.repository import CaseRepository

from src.review.case_context import build_new_case_bundle, load_historical_case_details


@dataclass(frozen=True)
class FixedReviewAgentDependencies:
    """固定审查服务所需依赖；所有依赖由应用层显式注入。"""

    structure_guide: str
    structure_config: GenerationConfig
    rerank_config: GenerationConfig
    comparison_config: GenerationConfig
    question_config: GenerationConfig
    repository: CaseRepository
    bm25_index: BM25Index
    embedding_index: EmbeddingIndex
    encoder: Encoder
    top_k_candidates: int = 5
    top_k_historical: int = 3


def _new_case(state: Mapping[str, Any]) -> CaseBundle:
    data = state.get("new_case_bundle")
    if not isinstance(data, Mapping):
        raise ValueError("Agent 状态缺少 new_case_bundle。")
    return case_bundle_from_dict(data)


def _historical_cases(state: Mapping[str, Any]) -> tuple[CaseBundle, ...]:
    data = state.get("loaded_cases", [])
    if not isinstance(data, list):
        raise ValueError("Agent 状态 loaded_cases 必须是数组。")
    return tuple(case_bundle_from_dict(item) for item in data)


def _rerank_response(state: Mapping[str, Any]) -> RerankResponse:
    data = state.get("rerank")
    if not isinstance(data, Mapping):
        raise ValueError("Agent 状态缺少 rerank。")
    ranked_data = data.get("ranked_cases", [])
    if not isinstance(ranked_data, list):
        raise ValueError("rerank.ranked_cases 必须是数组。")
    ranked = tuple(
        RerankedCase(
            case_id=item["case_id"],
            rank=item["rank"],
            relevance=item.get("relevance"),
            similarity_reasons=tuple(item.get("similarity_reasons", [])),
            important_differences=tuple(item.get("important_differences", [])),
            uncertainties=tuple(item.get("uncertainties", [])),
        )
        for item in ranked_data
    )
    return RerankResponse(
        ranked_cases=ranked,
        degraded=bool(data.get("degraded", False)),
        error=data.get("error"),
        api_meta=data.get("api_meta"),
    )


def _candidate_results(state: Mapping[str, Any]) -> tuple[HybridResult, ...]:
    results: list[HybridResult] = []
    candidates = state.get("candidate_cases", [])
    if not isinstance(candidates, list):
        raise ValueError("Agent 状态 candidate_cases 必须是数组。")
    for item in candidates:
        metadata = item.get("metadata", {}) if isinstance(item, Mapping) else {}
        results.append(
            HybridResult(
                case_id=item["case_id"],
                document=RetrievalDocument(item["case_id"], "", dict(metadata)),
                bm25_rank=item.get("bm25_rank"),
                bm25_score=item.get("bm25_score"),
                embedding_rank=item.get("embedding_rank"),
                embedding_score=item.get("embedding_score"),
                both_hit=item.get("match_type") == "both",
                rank=item.get("rank", 0),
            )
        )
    return tuple(results)


def _comparison_from_dict(data: Mapping[str, Any]) -> CaseComparison:
    return CaseComparison(
        historical_case_id=data["historical_case_id"],
        similarities=tuple(
            SimilarityFinding(
                item["description"],
                tuple(item.get("new_case_fact_ids", [])),
                tuple(item.get("historical_fact_ids", [])),
                item["confidence"],
            )
            for item in data.get("similarities", [])
        ),
        differences=tuple(
            DifferenceFinding(
                item["description"],
                tuple(item.get("new_case_fact_ids", [])),
                tuple(item.get("historical_fact_ids", [])),
                item["importance"],
            )
            for item in data.get("differences", [])
        ),
        applicable_rule_hypotheses=tuple(
            RuleApplicability(item["rule_id"], item["applicability"], item["reason"])
            for item in data.get("applicable_rule_hypotheses", [])
        ),
        uncertainties=tuple(data.get("uncertainties", [])),
        api_meta=data.get("api_meta"),
    )


def _comparisons(state: Mapping[str, Any]) -> tuple[CaseComparison, ...]:
    data = state.get("comparisons", [])
    if not isinstance(data, list):
        raise ValueError("Agent 状态 comparisons 必须是数组。")
    return tuple(_comparison_from_dict(item) for item in data)


def _questions(state: Mapping[str, Any]) -> tuple[ReviewQuestion, ...]:
    data = state.get("review_questions", [])
    if not isinstance(data, list):
        raise ValueError("Agent 状态 review_questions 必须是数组。")
    return tuple(
        ReviewQuestion(
            question_id=item["question_id"],
            question=item["question"],
            reason=item["reason"],
            related_new_fact_ids=tuple(item.get("related_new_fact_ids", [])),
            historical_case_ids=tuple(item.get("historical_case_ids", [])),
            historical_fact_ids=tuple(item.get("historical_fact_ids", [])),
            priority=item["priority"],
            answer_status=item.get("answer_status", "unanswered"),
        )
        for item in data
    )


def _comparison_context(state: Mapping[str, Any]) -> FixedReviewComparison:
    new_case = _new_case(state)
    historical_cases = _historical_cases(state)
    rerank = _rerank_response(state)
    context = FixedReviewContext(
        run_id=state.get("run_id", "AGENT_REVIEW"),
        raw_case_text=state.get("raw_case_text", new_case.case.raw_text),
        structured_case=state.get("structured_new_case") or {},
        new_case_bundle=new_case,
        retrieval_query=state.get("retrieval_query", build_retrieval_text(new_case)),
        candidates=_candidate_results(state),
        rerank=rerank,
        historical_cases=historical_cases,
    )
    comparisons = _comparisons(state)
    return FixedReviewComparison(
        context=context,
        comparisons=comparisons,
        historical_rule_references=tuple(
            state.get("historical_rule_references")
            or collect_historical_rule_references(comparisons)
        ),
    )


def build_fixed_review_executor_services(
    dependencies: FixedReviewAgentDependencies,
) -> ExecutorServices:
    """构造固定审查服务的静态白名单映射。"""

    def structure_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        raw_text = state.get("raw_case_text")
        if not isinstance(raw_text, str):
            raise ValueError("Agent 状态缺少 raw_case_text。")
        structured = structure_case(raw_text, dependencies.structure_guide, dependencies.structure_config)
        bundle = build_new_case_bundle(
            structured,
            raw_text=raw_text,
            new_case_id=f"NEW_CASE_AGENT_{state.get('run_id', 'RUN')}",
        )
        return {
            "structured_new_case": structured,
            "new_case_bundle": case_bundle_to_dict(bundle),
        }

    def search_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        new_case = _new_case(state)
        query = build_retrieval_text(new_case)
        candidates = tuple(
            hybrid_retrieve(
                query,
                dependencies.bm25_index,
                dependencies.embedding_index,
                dependencies.encoder,
                top_k_bm25=dependencies.top_k_candidates,
                top_k_embedding=dependencies.top_k_candidates,
                final_k=dependencies.top_k_candidates,
            )
        )
        rerank = rerank_candidates(
            query,
            candidates,
            dependencies.rerank_config,
            top_k=dependencies.top_k_historical,
        )
        return {
            "retrieval_query": query,
            "candidate_cases": [candidate.to_dict() for candidate in candidates],
            "rerank": rerank.to_dict(),
        }

    def load_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        ids = [item.case_id for item in _rerank_response(state).ranked_cases]
        bundles = load_historical_case_details(
            dependencies.repository,
            ids[: dependencies.top_k_historical],
        )
        return {"loaded_cases": [case_bundle_to_dict(bundle) for bundle in bundles]}

    def compare_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        comparisons = compare_case_pairs(
            _new_case(state),
            _historical_cases(state),
            dependencies.comparison_config,
        )
        return {"comparisons": [comparison.to_dict() for comparison in comparisons]}

    def rules_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        references = collect_historical_rule_references(_comparisons(state))
        return {"historical_rule_references": list(references)}

    def questions_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        questions = generate_review_questions(
            _new_case(state),
            _comparisons(state),
            dependencies.question_config,
            historical_cases=_historical_cases(state),
        )
        return {"review_questions": [question.to_dict() for question in questions]}

    def report_handler(state: Mapping[str, Any]) -> dict[str, Any]:
        report = run_fixed_review_report(_comparison_context(state), _questions(state))
        return {"final_report": report.to_dict()}

    return ExecutorServices(
        {
            "structure_new_case": structure_handler,
            "search_similar_cases": search_handler,
            "load_case_details": load_handler,
            "compare_cases": compare_handler,
            "inspect_rule_hypotheses": rules_handler,
            "generate_review_questions": questions_handler,
            "synthesize_report": report_handler,
            "request_human_input": lambda state: {},
        }
    )


def build_fixed_flow_fallback(
    dependencies: FixedReviewAgentDependencies,
):
    """返回完整固定审查流程的降级回调。"""

    def fallback(state: Mapping[str, Any]) -> dict[str, Any]:
        raw_text = state.get("raw_case_text")
        if not isinstance(raw_text, str):
            raise ValueError("固定流程降级缺少 raw_case_text。")
        context = run_fixed_review_context(
            raw_case_text=raw_text,
            structure_guide=dependencies.structure_guide,
            structure_config=dependencies.structure_config,
            repository=dependencies.repository,
            bm25_index=dependencies.bm25_index,
            embedding_index=dependencies.embedding_index,
            encoder=dependencies.encoder,
            rerank_config=dependencies.rerank_config,
            top_k_candidates=dependencies.top_k_candidates,
            top_k_historical=dependencies.top_k_historical,
        )
        comparison = run_fixed_review_comparison(context, dependencies.comparison_config)
        questions = run_fixed_review_questions(comparison, dependencies.question_config)
        report = run_fixed_review_report(comparison, questions)
        return {
            "structured_new_case": context.structured_case,
            "new_case_bundle": case_bundle_to_dict(context.new_case_bundle),
            "candidate_cases": [candidate.to_dict() for candidate in context.candidates],
            "rerank": context.rerank.to_dict(),
            "loaded_cases": [case_bundle_to_dict(bundle) for bundle in context.historical_cases],
            "comparisons": [item.to_dict() for item in comparison.comparisons],
            "historical_rule_references": list(comparison.historical_rule_references),
            "review_questions": [item.to_dict() for item in questions],
            "final_report": report.to_dict(),
        }

    return fallback
