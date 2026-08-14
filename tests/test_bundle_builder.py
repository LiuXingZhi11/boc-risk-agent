import json

from src.storage.bundle_builder import build_case_bundles, split_case_texts


def structured_output() -> dict:
    return {
        "case_records": [
            {
                "case_id": "CASE_001",
                "case_name": "测试案例",
                "source": None,
                "target_event": {"target_fact_id": "CASE_001_F002", "uncertainty": ""},
                "facts": [
                    {
                        "fact_id": "CASE_001_F001",
                        "statement": "存在关联关系",
                        "source_excerpt": "存在关联关系",
                        "category": "relationship",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_before_target",
                        "uncertainty": "",
                    },
                    {
                        "fact_id": "CASE_001_F002",
                        "statement": "发生风险事件",
                        "source_excerpt": "发生风险事件",
                        "category": "risk_event",
                        "assertion_type": "reported_fact",
                        "event_time": None,
                        "knowledge_status": "known_at_target",
                        "uncertainty": "",
                    },
                ],
                "uncertainties": [],
            }
        ],
        "uncertainties": [],
        "api_meta": {"stage": "structure", "model": "deepseek-v4-pro", "generation_mode": "thinking", "reasoning_effort": "high"},
    }


def rules_output() -> dict:
    return {
        "single_case_rule_hypotheses": [
            {
                "rule_id": "RULE_001",
                "case_id": "CASE_001",
                "rule_hypothesis": "关联关系可能放大风险",
                "supporting_fact_ids": ["CASE_001_F001", "CASE_001_F002"],
                "uncertainty": "仍需核实",
                "generalization_status": "single_case_hypothesis",
            }
        ],
        "uncertainties": [],
        "api_meta": {"stage": "rules", "model": "deepseek-v4-pro", "generation_mode": "thinking", "reasoning_effort": "high"},
    }


def test_split_case_texts_keeps_case_sections() -> None:
    result = split_case_texts("# 批次\n\n## CASE_001：案例一\n内容一\n\n## CASE_002: 案例二\n内容二")

    assert result["CASE_001"].endswith("内容一")
    assert result["CASE_002"].endswith("内容二")


def test_build_case_bundles_preserves_api_meta_as_processing_runs() -> None:
    bundles = build_case_bundles(
        structured_output(),
        rules_output(),
        raw_text="## CASE_001：测试案例\n案例原文",
        source="test",
    )

    assert len(bundles) == 1
    assert bundles[0].case.raw_text.endswith("案例原文")
    assert {run.stage for run in bundles[0].processing_runs} == {"structure", "rules"}
