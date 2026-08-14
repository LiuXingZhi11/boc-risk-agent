from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from src.llm.generation_config import GenerationConfig
from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.retrieval.bm25 import build_bm25_index
from src.retrieval.documents import build_retrieval_document
from src.retrieval.embedding import build_embedding_index
from src.retrieval.reranker import RerankResponse, RerankedCase
from src.review.fixed_review import (
    FixedReviewContext,
    run_fixed_review_comparison,
    run_fixed_review_context,
    run_fixed_review_questions,
)
from src.review.questions import ReviewQuestion
from src.storage.repository import CaseRepository


def structured_new_case() -> dict:
    return {
        "case_records": [
            {
                "case_id": "MODEL_CASE",
                "case_name": "新案例",
                "facts": [
                    {
                        "fact_id": "MODEL_F001",
                        "statement": "企业与关联方存在控制关系",
                        "source_excerpt": "新案例片段一",
                        "category": "relationship",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_before_target",
                        "uncertainty": None,
                    },
                    {
                        "fact_id": "MODEL_F002",
                        "statement": "贷款资金流向房地产项目并出现风险",
                        "source_excerpt": "新案例片段二",
                        "category": "risk_event",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_at_target",
                        "uncertainty": None,
                    },
                ],
                "target_event": {"target_fact_id": "MODEL_F002", "uncertainty": None},
                "uncertainties": [],
            }
        ],
        "uncertainties": [],
    }


def historical_bundle(case_id: str) -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact(f"{case_id}_F001", "历史关联关系", "历史片段一", "relationship", "reported_fact", None, "known_before_target"),
        Fact(f"{case_id}_F002", "历史贷款风险", "历史片段二", "risk_event", "reported_fact", None, "known_at_target"),
    )
    return CaseBundle(
        case=Case(
            case_id=case_id,
            case_name=f"历史案例 {case_id}",
            raw_text="历史原文",
            target_event=TargetEvent(f"{case_id}_F002"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=facts,
        rule_hypotheses=(
            RuleHypothesis(
                rule_id=f"{case_id}_R001",
                case_id=case_id,
                rule_hypothesis="关联关系可能放大风险",
                supporting_fact_ids=(f"{case_id}_F001", f"{case_id}_F002"),
                review_status="approved",
            ),
        ),
    )


class FakeEncoder:
    def encode(self, texts):
        if not texts:
            return np.empty((0, 2), dtype=np.float32)
        values = [[float("关联" in text), float("房地产" in text)] for text in texts]
        vectors = np.asarray(values, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms != 0)


def config() -> GenerationConfig:
    return GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0)


def test_fixed_review_context_orchestrates_and_loads_top_cases(monkeypatch, tmp_path) -> None:
    repository = CaseRepository(tmp_path / "cases.db")
    historical = [historical_bundle("CASE_H1"), historical_bundle("CASE_H2")]
    for bundle in historical:
        repository.save_case_bundle(bundle)
    documents = [build_retrieval_document(bundle) for bundle in historical]
    bm25 = build_bm25_index(documents)
    embedding = build_embedding_index(documents, FakeEncoder(), model_name="fake")

    monkeypatch.setattr(
        "src.review.fixed_review.structure_case",
        lambda raw_text, guide, generation_config: structured_new_case(),
    )

    def fake_rerank(summary, candidates, generation_config, *, top_k):
        return RerankResponse(
            ranked_cases=(
                RerankedCase("CASE_H2", 1, "high", ("关联关系相似",), (), ()),
                RerankedCase("CASE_H1", 2, "medium", ("业务事实部分相似",), (), ()),
            )
        )

    monkeypatch.setattr("src.review.fixed_review.rerank_candidates", fake_rerank)
    context = run_fixed_review_context(
        raw_case_text="新案例原文",
        structure_guide="结构化指导",
        structure_config=config(),
        repository=repository,
        bm25_index=bm25,
        embedding_index=embedding,
        encoder=FakeEncoder(),
        rerank_config=config(),
        top_k_candidates=2,
        top_k_historical=2,
        new_case_id="NEW_CASE_FIXED",
    )

    assert context.new_case_bundle.case.case_id == "NEW_CASE_FIXED"
    assert context.retrieval_query
    assert [item.case_id for item in context.rerank.ranked_cases] == ["CASE_H2", "CASE_H1"]
    assert [bundle.case.case_id for bundle in context.historical_cases] == ["CASE_H2", "CASE_H1"]
    assert context.to_dict()["historical_case_ids"] == ["CASE_H2", "CASE_H1"]


def test_fixed_review_context_allows_empty_retrieval_without_model_call(monkeypatch, tmp_path) -> None:
    repository = CaseRepository(tmp_path / "cases.db")
    monkeypatch.setattr(
        "src.review.fixed_review.structure_case",
        lambda raw_text, guide, generation_config: structured_new_case(),
    )
    monkeypatch.setattr(
        "src.review.fixed_review.rerank_candidates",
        lambda summary, candidates, generation_config, *, top_k: RerankResponse(()),
    )

    context = run_fixed_review_context(
        raw_case_text="新案例原文",
        structure_guide="结构化指导",
        structure_config=config(),
        repository=repository,
        bm25_index=build_bm25_index([]),
        embedding_index=build_embedding_index([], FakeEncoder(), model_name="fake"),
        encoder=FakeEncoder(),
        rerank_config=config(),
    )

    assert context.candidates == ()
    assert context.historical_cases == ()
    assert context.rerank.degraded is False


def test_fixed_review_comparison_collects_rule_references(monkeypatch) -> None:
    context = FixedReviewContext(
        run_id="REVIEW_TEST",
        raw_case_text="新案例原文",
        structured_case=structured_new_case(),
        new_case_bundle=historical_bundle("NEW_CASE_NOT_USED"),
        retrieval_query="查询",
        candidates=(),
        rerank=RerankResponse(()),
        historical_cases=(),
    )
    fake_comparisons = ("comparison",)
    monkeypatch.setattr(
        "src.review.fixed_review.compare_case_pairs",
        lambda new_case, historical_cases, generation_config: fake_comparisons,
    )
    monkeypatch.setattr(
        "src.review.fixed_review.collect_historical_rule_references",
        lambda comparisons: ({"rule_id": "RULE_001"},),
    )

    result = run_fixed_review_comparison(context, config())

    assert result.context is context
    assert result.comparisons == fake_comparisons
    assert result.historical_rule_references == ({"rule_id": "RULE_001"},)


def test_fixed_review_questions_delegates_with_loaded_context(monkeypatch) -> None:
    context = FixedReviewContext(
        run_id="REVIEW_TEST",
        raw_case_text="新案例原文",
        structured_case=structured_new_case(),
        new_case_bundle=historical_bundle("NEW_CASE_NOT_USED"),
        retrieval_query="查询",
        candidates=(),
        rerank=RerankResponse(()),
        historical_cases=(),
    )
    comparison_context = run_fixed_review_comparison(
        context,
        config(),
    )
    expected = (
        ReviewQuestion(
            "QUESTION_001",
            "需要核实的问题",
            "来源于信息缺口",
            (),
            (),
            (),
            "high",
        ),
    )
    monkeypatch.setattr(
        "src.review.fixed_review.generate_review_questions",
        lambda new_case, comparisons, generation_config, **kwargs: expected,
    )

    assert run_fixed_review_questions(comparison_context, config()) == expected
