from datetime import datetime, timezone

import pytest

from src.models import Case, CaseBundle, Fact, ProcessingRun, RuleHypothesis, TargetEvent
from src.storage.repository import CaseNotFoundError, CaseRepository, DuplicateCaseError, RepositoryError


def make_bundle(case_id: str = "CASE_001", *, run_id: str = "RUN_001") -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    facts = (
        Fact(
            fact_id=f"{case_id}_F001",
            statement="存在关联关系",
            source_excerpt="存在关联关系",
            category="relationship",
            assertion_type="reported_fact",
            event_time=None,
            knowledge_status="known_before_target",
        ),
        Fact(
            fact_id=f"{case_id}_F002",
            statement="发生目标事件",
            source_excerpt="发生目标事件",
            category="risk_event",
            assertion_type="reported_fact",
            event_time=None,
            knowledge_status="known_at_target",
        ),
    )
    case = Case(
        case_id=case_id,
        case_name="测试案例",
        raw_text="案例原文",
        source="测试来源",
        case_type="credit",
        target_event=TargetEvent(f"{case_id}_F002", "仍需核实"),
        created_at=now,
        updated_at=now,
    )
    rule = RuleHypothesis(
        rule_id=f"{case_id}_RULE_001",
        case_id=case_id,
        rule_hypothesis="关联关系可能放大风险",
        supporting_fact_ids=(f"{case_id}_F001", f"{case_id}_F002"),
    )
    run = ProcessingRun(
        run_id=run_id,
        case_id=case_id,
        stage="structure",
        model="deepseek-v4-pro",
        generation_mode="thinking",
        reasoning_effort="high",
        temperature=None,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        status="succeeded",
        error_message=None,
        created_at=now,
    )
    return CaseBundle(case=case, facts=facts, rule_hypotheses=(rule,), processing_runs=(run,))


def test_save_and_read_case_bundle_preserves_references_and_runs(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "risk_cases.db")
    bundle = make_bundle()

    repository.save_case_bundle(bundle)
    loaded = repository.get_case_bundle("CASE_001")

    assert loaded is not None
    assert loaded.case.target_event is not None
    assert loaded.case.target_event.uncertainty == "仍需核实"
    assert [fact.fact_id for fact in loaded.facts] == ["CASE_001_F001", "CASE_001_F002"]
    assert loaded.rule_hypotheses[0].supporting_fact_ids == (
        "CASE_001_F001",
        "CASE_001_F002",
    )
    assert loaded.processing_runs[0].total_tokens == 30


def test_duplicate_case_fails_and_replace_is_transactional(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "risk_cases.db")
    repository.save_case_bundle(make_bundle())

    with pytest.raises(DuplicateCaseError):
        repository.save_case_bundle(make_bundle(run_id="RUN_DUPLICATE"))

    replacement = make_bundle(run_id="RUN_REPLACED")
    repository.save_case_bundle(replacement, replace=True)
    loaded = repository.get_case_bundle("CASE_001")
    assert loaded is not None
    assert [run.run_id for run in loaded.processing_runs] == ["RUN_REPLACED"]


def test_case_bundle_write_rolls_back_when_processing_run_fails(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "risk_cases.db")
    repository.save_case_bundle(make_bundle())

    with pytest.raises(RepositoryError):
        repository.save_case_bundle(make_bundle("CASE_002", run_id="RUN_001"))

    assert repository.get_case_bundle("CASE_002") is None
    assert repository.case_exists("CASE_001")


def test_case_listing_status_update_and_delete(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "risk_cases.db")
    repository.save_case_bundle(make_bundle())
    repository.save_case_bundle(make_bundle("CASE_002", run_id="RUN_002"))

    assert [case.case_id for case in repository.list_cases()] == ["CASE_001", "CASE_002"]
    repository.update_case_review_status("CASE_001", "approved")
    assert [case.case_id for case in repository.list_cases(review_status="approved")] == ["CASE_001"]

    repository.delete_case("CASE_001")
    assert repository.get_case_bundle("CASE_001") is None
    assert repository.get_processing_runs("CASE_001") == []
    with pytest.raises(CaseNotFoundError):
        repository.delete_case("CASE_001")


def test_save_processing_run_allows_unattached_run(tmp_path) -> None:
    repository = CaseRepository(tmp_path / "risk_cases.db")
    now = datetime.now(timezone.utc).isoformat()
    run = ProcessingRun(
        run_id="RUN_STANDALONE",
        case_id=None,
        stage="pipeline",
        model=None,
        generation_mode=None,
        reasoning_effort=None,
        temperature=None,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        status="failed",
        error_message="测试失败",
        created_at=now,
    )

    repository.save_processing_run(run)
    assert repository.get_processing_runs("MISSING_CASE") == []
