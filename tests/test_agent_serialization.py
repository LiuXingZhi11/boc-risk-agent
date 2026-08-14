from __future__ import annotations

from datetime import datetime, timezone

from src.agent.serialization import case_bundle_from_dict, case_bundle_to_dict
from src.models import Case, CaseBundle, Fact, ProcessingRun, RuleHypothesis, TargetEvent


def make_bundle() -> CaseBundle:
    now = datetime.now(timezone.utc).isoformat()
    return CaseBundle(
        case=Case(
            case_id="CASE_SERIALIZE",
            case_name="序列化案例",
            raw_text="原始材料",
            source="test",
            case_type="credit",
            target_event=TargetEvent("CASE_SERIALIZE_F001", "待核实"),
            review_status="approved",
            created_at=now,
            updated_at=now,
        ),
        facts=(
            Fact(
                "CASE_SERIALIZE_F001",
                "企业存在关联关系",
                "材料片段",
                "relationship",
                "reported_fact",
                None,
                "known_before_target",
            ),
        ),
        rule_hypotheses=(
            RuleHypothesis(
                "CASE_SERIALIZE_R001",
                "CASE_SERIALIZE",
                "关联关系需要核实",
                ("CASE_SERIALIZE_F001",),
                review_status="approved",
            ),
        ),
        processing_runs=(
            ProcessingRun(
                "RUN_SERIALIZE",
                "CASE_SERIALIZE",
                "test",
                "fake",
                "thinking",
                "high",
                None,
                1,
                2,
                3,
                "succeeded",
                None,
                now,
            ),
        ),
        api_meta={"stage": "test"},
    )


def test_case_bundle_json_round_trip() -> None:
    bundle = make_bundle()

    restored = case_bundle_from_dict(case_bundle_to_dict(bundle))

    assert restored == bundle
