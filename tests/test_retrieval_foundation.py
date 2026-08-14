from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.retrieval.bm25 import build_bm25_index
from src.retrieval.documents import RetrievalDocument, build_retrieval_document, build_retrieval_text
from src.retrieval.embedding import build_embedding_index
from src.retrieval.persistence import load_bm25_index, load_embedding_index, persist_indices


def make_bundle(case_id: str, *, status: str = "approved") -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact(f"{case_id}_F001", "企业存在关联关系", "企业存在关联关系", "relationship", "reported_fact", None, "known_before_target"),
        Fact(f"{case_id}_F002", "贷款资金流向房地产项目", "贷款资金流向房地产项目", "transaction", "reported_fact", None, "known_before_target"),
        Fact(f"{case_id}_F003", "贷款出现风险事件", "贷款出现风险事件", "risk_event", "reported_fact", None, "known_at_target"),
    )
    case = Case(
        case_id=case_id,
        case_name=f"案例 {case_id}",
        raw_text="案例原文",
        target_event=TargetEvent(f"{case_id}_F003"),
        review_status=status,
        created_at=now,
        updated_at=now,
    )
    rule = RuleHypothesis(
        rule_id=f"{case_id}_R001",
        case_id=case_id,
        rule_hypothesis="关联关系与资金流向可能共同形成风险过程",
        supporting_fact_ids=(f"{case_id}_F001", f"{case_id}_F002"),
    )
    return CaseBundle(case=case, facts=facts, rule_hypotheses=(rule,))


class FakeEncoder:
    def encode(self, texts):
        values = []
        for text in texts:
            values.append([
                float("关联" in text),
                float("房地产" in text),
                float("科技" in text),
            ])
        vectors = np.asarray(values, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms != 0)


def test_retrieval_text_is_stable_and_metadata_is_traceable() -> None:
    bundle = make_bundle("CASE_001")
    text = build_retrieval_text(bundle)
    document = build_retrieval_document(bundle)

    assert text == build_retrieval_text(bundle)
    assert "企业存在关联关系" in text
    assert "贷款出现风险事件" in text
    assert "CASE_001_F001" not in text
    assert document.metadata["fact_ids"] == ["CASE_001_F001", "CASE_001_F002", "CASE_001_F003"]


def test_unapproved_case_is_rejected_by_default() -> None:
    with pytest.raises(ValueError, match="尚未审核通过"):
        build_retrieval_document(make_bundle("CASE_001", status="pending"))
    assert build_retrieval_document(
        make_bundle("CASE_001", status="pending"), allow_unapproved=True
    ).case_id == "CASE_001"


def test_bm25_search_and_empty_inputs() -> None:
    documents = [
        build_retrieval_document(make_bundle("CASE_001")),
        RetrievalDocument("CASE_002", "科技企业研发项目", {"case_name": "科技案例"}),
    ]
    index = build_bm25_index(documents)

    results = index.search("关联 房地产 贷款", top_k=2)
    assert results[0].case_id == "CASE_001"
    assert results[0].rank == 1
    assert index.search("", top_k=5) == []
    assert build_bm25_index([]).search("关联") == []


def test_embedding_index_shape_search_and_persistence(tmp_path) -> None:
    documents = [
        build_retrieval_document(make_bundle("CASE_001")),
        RetrievalDocument("CASE_002", "科技企业研发项目", {"case_name": "科技案例"}),
    ]
    encoder = FakeEncoder()
    bm25 = build_bm25_index(documents)
    embedding = build_embedding_index(documents, encoder, model_name="fake-model")

    assert embedding.vectors.shape == (2, 3)
    assert embedding.search("关联 房地产", encoder, top_k=2)[0].case_id == "CASE_001"

    persist_indices(
        tmp_path / "retrieval",
        bm25,
        embedding,
        source_database="test.db",
    )
    loaded_bm25 = load_bm25_index(tmp_path / "retrieval")
    loaded_embedding = load_embedding_index(tmp_path / "retrieval")
    assert loaded_bm25.search("关联", top_k=1)[0].case_id == "CASE_001"
    assert loaded_embedding.vectors.shape == (2, 3)
    assert [doc.case_id for doc in loaded_embedding.documents] == ["CASE_001", "CASE_002"]
