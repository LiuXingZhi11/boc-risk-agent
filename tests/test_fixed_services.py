from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from src.agent.fixed_services import (
    FixedReviewAgentDependencies,
    build_fixed_review_executor_services,
)
from src.agent.serialization import case_bundle_to_dict
from src.llm.generation_config import GenerationConfig
from src.models import Case, CaseBundle, Fact, TargetEvent
from src.retrieval.bm25 import build_bm25_index
from src.retrieval.documents import RetrievalDocument
from src.retrieval.embedding import build_embedding_index
from src.retrieval.hybrid import HybridResult
from src.retrieval.reranker import RerankResponse, RerankedCase
from src.storage.repository import CaseRepository


class FakeEncoder:
    def encode(self, texts):
        return np.ones((len(texts), 2), dtype=np.float32)


def structured_case() -> dict:
    return {
        "case_records": [
            {
                "case_id": "MODEL_CASE",
                "case_name": "新案例",
                "facts": [
                    {
                        "fact_id": "MODEL_F001",
                        "statement": "企业存在关联关系",
                        "source_excerpt": "原文片段",
                        "category": "relationship",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_at_target",
                        "uncertainty": None,
                    },
                ],
                "target_event": {"target_fact_id": "MODEL_F001", "uncertainty": None},
                "uncertainties": [],
            }
        ],
        "uncertainties": [],
    }


def historical_bundle(case_id: str) -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    return CaseBundle(
        case=Case(
            case_id=case_id,
            case_name="历史案例",
            raw_text="历史原文",
            target_event=TargetEvent(f"{case_id}_F001"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=(
            Fact(
                f"{case_id}_F001",
                "历史关联关系",
                "历史片段",
                "relationship",
                "reported_fact",
                None,
                "known_before_target",
            ),
        ),
    )


def dependencies(tmp_path) -> FixedReviewAgentDependencies:
    encoder = FakeEncoder()
    return FixedReviewAgentDependencies(
        structure_guide="结构化指导",
        structure_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        rerank_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        comparison_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        question_config=GenerationConfig(mode="thinking", reasoning_effort="high", max_retries=0),
        repository=CaseRepository(tmp_path / "cases.db"),
        bm25_index=build_bm25_index([]),
        embedding_index=build_embedding_index([], encoder, model_name="fake"),
        encoder=encoder,
    )


def test_structure_service_adapter_returns_json_case_bundle(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.agent.fixed_services.structure_case", lambda *args: structured_case())
    services = build_fixed_review_executor_services(dependencies(tmp_path))

    updates = services.handlers["structure_new_case"](
        {"raw_case_text": "新案例原文", "run_id": "RUN_ADAPTER"}
    )

    assert updates["structured_new_case"]["case_records"]
    assert updates["new_case_bundle"]["case"]["case_id"] == "NEW_CASE_AGENT_RUN_ADAPTER"


def test_search_service_adapter_persists_rerank_json(monkeypatch, tmp_path) -> None:
    dependency = dependencies(tmp_path)
    bundle = historical_bundle("NEW_CASE_AGENT")
    candidate = HybridResult(
        "CASE_H1",
        RetrievalDocument("CASE_H1", "历史检索文本", {"case_name": "历史案例"}),
        bm25_rank=1,
        rank=1,
    )
    monkeypatch.setattr("src.agent.fixed_services.hybrid_retrieve", lambda *args, **kwargs: [candidate])
    monkeypatch.setattr(
        "src.agent.fixed_services.rerank_candidates",
        lambda *args, **kwargs: RerankResponse(
            (RerankedCase("CASE_H1", 1, "high", ("关系相似",), (), ()),)
        ),
    )
    services = build_fixed_review_executor_services(dependency)

    updates = services.handlers["search_similar_cases"](
        {
            "new_case_bundle": case_bundle_to_dict(bundle),
        }
    )

    assert updates["candidate_cases"][0]["case_id"] == "CASE_H1"
    assert updates["rerank"]["ranked_cases"][0]["relevance"] == "high"


def test_load_service_adapter_requires_approved_repository_case(tmp_path) -> None:
    dependency = dependencies(tmp_path)
    dependency.repository.save_case_bundle(historical_bundle("CASE_H1"))
    services = build_fixed_review_executor_services(dependency)

    updates = services.handlers["load_case_details"](
        {
            "rerank": {
                "ranked_cases": [
                    {
                        "case_id": "CASE_H1",
                        "rank": 1,
                        "relevance": "high",
                        "similarity_reasons": [],
                        "important_differences": [],
                        "uncertainties": [],
                    }
                ],
                "degraded": False,
            }
        }
    )

    assert updates["loaded_cases"][0]["case"]["case_id"] == "CASE_H1"
