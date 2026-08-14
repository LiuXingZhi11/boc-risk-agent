from __future__ import annotations

from src.llm.generation_config import GenerationConfig
from src.retrieval.documents import RetrievalDocument
from src.retrieval.hybrid import HybridResult
from src.retrieval.reranker import rerank_candidates


def candidate(case_id: str) -> HybridResult:
    return HybridResult(
        case_id=case_id,
        document=RetrievalDocument(case_id, f"候选事实：{case_id}", {"case_name": case_id}),
        bm25_rank=1,
        bm25_score=1.0,
        both_hit=True,
        rank=1,
    )


def thinking_config() -> GenerationConfig:
    return GenerationConfig(
        model="deepseek-v4-pro",
        mode="thinking",
        reasoning_effort="high",
        max_retries=0,
    )


def valid_payload() -> dict:
    return {
        "ranked_cases": [
            {
                "case_id": "CASE_002",
                "rank": 1,
                "relevance": "high",
                "similarity_reasons": ["主体关系和资金流向相似"],
                "important_differences": ["目标时间不同"],
                "uncertainties": [],
            },
            {
                "case_id": "CASE_001",
                "rank": 2,
                "relevance": "medium",
                "similarity_reasons": ["都涉及关联交易"],
                "important_differences": [],
                "uncertainties": ["缺少最终损失信息"],
            },
        ],
        "api_meta": {"model": "fake"},
    }


def test_reranker_accepts_valid_candidate_only_response(monkeypatch) -> None:
    captured = {}

    def fake_call(messages, config):
        captured["messages"] = messages
        captured["config"] = config
        return valid_payload()

    monkeypatch.setattr("src.retrieval.reranker.call_deepseek", fake_call)
    result = rerank_candidates(
        "新案例涉及关联交易和资金流向异常",
        [candidate("CASE_001"), candidate("CASE_002")],
        thinking_config(),
    )

    assert result.degraded is False
    assert [item.case_id for item in result.ranked_cases] == ["CASE_002", "CASE_001"]
    assert result.api_meta == {"model": "fake"}
    assert captured["config"].mode == "thinking"
    assert "CASE_001" in captured["messages"][1]["content"]


def test_illegal_case_id_returns_marked_degraded_fallback(monkeypatch) -> None:
    def fake_call(messages, config):
        payload = valid_payload()
        payload["ranked_cases"][0]["case_id"] = "CASE_NOT_IN_CANDIDATES"
        return payload

    monkeypatch.setattr("src.retrieval.reranker.call_deepseek", fake_call)
    result = rerank_candidates(
        "新案例摘要",
        [candidate("CASE_001"), candidate("CASE_002")],
        thinking_config(),
    )

    assert result.degraded is True
    assert [item.case_id for item in result.ranked_cases] == ["CASE_001", "CASE_002"]
    assert result.ranked_cases[0].relevance is None
    assert "非法或未知 case_id" in result.error


def test_api_failure_returns_marked_degraded_fallback(monkeypatch) -> None:
    def fake_call(messages, config):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("src.retrieval.reranker.call_deepseek", fake_call)
    result = rerank_candidates("新案例摘要", [candidate("CASE_001")], thinking_config())

    assert result.degraded is True
    assert result.ranked_cases[0].case_id == "CASE_001"
    assert "network unavailable" in result.error


def test_empty_candidates_do_not_call_model(monkeypatch) -> None:
    def fail_call(messages, config):
        raise AssertionError("empty candidates must not call DeepSeek")

    monkeypatch.setattr("src.retrieval.reranker.call_deepseek", fail_call)
    result = rerank_candidates("新案例摘要", [], thinking_config())

    assert result.ranked_cases == ()
    assert result.degraded is False
