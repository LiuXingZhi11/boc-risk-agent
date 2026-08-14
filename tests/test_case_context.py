from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from src.models import Case, CaseBundle, Fact, RuleHypothesis, TargetEvent
from src.review.case_context import (
    HistoricalCaseLoadError,
    NewCaseBuildError,
    build_new_case_bundle,
    load_historical_case_details,
)
from src.storage.repository import CaseRepository


def structured_new_case() -> dict:
    return {
        "case_records": [
            {
                "case_id": "CASE_MODEL_OUTPUT",
                "case_name": "新案例测试",
                "facts": [
                    {
                        "fact_id": "MODEL_F001",
                        "statement": "企业与关联方存在控制关系",
                        "source_excerpt": "材料原文一",
                        "category": "relationship",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_before_target",
                        "uncertainty": None,
                    },
                    {
                        "fact_id": "MODEL_F002",
                        "statement": "贷款资金流向房地产项目并形成风险",
                        "source_excerpt": "材料原文二",
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
        "api_meta": {"stage": "structure"},
    }


def historical_bundle(case_id: str, status: str = "approved") -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact(
            f"{case_id}_F001",
            "历史企业存在关联关系",
            "历史材料片段",
            "relationship",
            "reported_fact",
            None,
            "known_before_target",
        ),
        Fact(
            f"{case_id}_F002",
            "历史贷款出现风险",
            "历史风险材料片段",
            "risk_event",
            "reported_fact",
            None,
            "known_at_target",
        ),
    )
    case = Case(
        case_id=case_id,
        case_name=f"历史案例 {case_id}",
        raw_text="历史案例原文",
        source="test",
        case_type="credit",
        target_event=TargetEvent(f"{case_id}_F002"),
        review_status=status,
        created_at=now,
        updated_at=now,
    )
    rule = RuleHypothesis(
        rule_id=f"{case_id}_R001",
        case_id=case_id,
        rule_hypothesis="关联关系可能放大信用风险",
        supporting_fact_ids=(f"{case_id}_F001", f"{case_id}_F002"),
        review_status="approved",
    )
    return CaseBundle(case=case, facts=facts, rule_hypotheses=(rule,))


def test_build_new_case_bundle_uses_independent_ids() -> None:
    source = structured_new_case()
    bundle = build_new_case_bundle(source, raw_text="新案例原文", new_case_id="NEW_CASE_TEST")

    assert bundle.case.case_id == "NEW_CASE_TEST"
    assert bundle.case.review_status == "pending"
    assert [fact.fact_id for fact in bundle.facts] == [
        "NEW_CASE_TEST_F001",
        "NEW_CASE_TEST_F002",
    ]
    assert bundle.case.target_event.target_fact_id == "NEW_CASE_TEST_F002"
    assert bundle.facts[0].source_excerpt == "材料原文一"
    assert bundle.rule_hypotheses == ()
    assert source["case_records"][0]["case_id"] == "CASE_MODEL_OUTPUT"


def test_new_case_requires_one_valid_case_record() -> None:
    with pytest.raises(NewCaseBuildError, match="不能为空"):
        build_new_case_bundle(structured_new_case(), raw_text="")

    two_cases = structured_new_case()
    second_case = deepcopy(two_cases["case_records"][0])
    second_case["case_id"] = "CASE_MODEL_OUTPUT_2"
    second_case["facts"][0]["fact_id"] = "MODEL_F101"
    second_case["facts"][1]["fact_id"] = "MODEL_F102"
    second_case["target_event"]["target_fact_id"] = "MODEL_F102"
    two_cases["case_records"].append(second_case)
    with pytest.raises(NewCaseBuildError, match="只能处理一个"):
        build_new_case_bundle(two_cases, raw_text="新案例原文")

    with pytest.raises(NewCaseBuildError, match="必须以 NEW_CASE_"):
        build_new_case_bundle(structured_new_case(), raw_text="新案例原文", new_case_id="CASE_001")


def test_load_historical_case_details_preserves_order_and_full_evidence(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "cases.db")
    repository.save_case_bundle(historical_bundle("CASE_002"))
    repository.save_case_bundle(historical_bundle("CASE_001"))

    bundles = load_historical_case_details(repository, ["CASE_002", "CASE_001"])

    assert [bundle.case.case_id for bundle in bundles] == ["CASE_002", "CASE_001"]
    assert bundles[0].facts[0].source_excerpt == "历史材料片段"
    assert bundles[0].rule_hypotheses[0].rule_id == "CASE_002_R001"
    assert bundles[0].case.target_event.target_fact_id == "CASE_002_F002"


def test_load_historical_case_details_rejects_missing_duplicate_and_unapproved(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "cases.db")
    repository.save_case_bundle(historical_bundle("CASE_PENDING", status="pending"))

    with pytest.raises(HistoricalCaseLoadError, match="尚未审核通过"):
        load_historical_case_details(repository, ["CASE_PENDING"])
    with pytest.raises(HistoricalCaseLoadError, match="不存在"):
        load_historical_case_details(repository, ["CASE_MISSING"])
    with pytest.raises(HistoricalCaseLoadError, match="不得重复"):
        load_historical_case_details(repository, ["CASE_PENDING", "CASE_PENDING"])

    bundles = load_historical_case_details(
        repository,
        ["CASE_PENDING"],
        require_approved=False,
    )
    assert bundles[0].case.review_status == "pending"
