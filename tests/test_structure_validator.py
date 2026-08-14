from copy import deepcopy

import pytest

from src.validators.structure_validator import validate_structured_cases


def valid_structure() -> dict:
    return {
        "case_records": [{
            "case_id": "CASE_001",
            "case_name": "测试案例",
            "source": None,
            "target_event": {"target_fact_id": "CASE_001_F002", "uncertainty": ""},
            "facts": [
                {
                    "fact_id": "CASE_001_F001",
                    "statement": "企业存在关联关系。",
                    "source_excerpt": "企业存在关联关系",
                    "category": "relationship",
                    "assertion_type": "reported_fact",
                    "event_time": None,
                    "knowledge_status": "known_before_target",
                    "uncertainty": "",
                },
                {
                    "fact_id": "CASE_001_F002",
                    "statement": "企业发生风险事件。",
                    "source_excerpt": "企业发生风险事件",
                    "category": "risk_event",
                    "assertion_type": "reported_fact",
                    "event_time": None,
                    "knowledge_status": "known_at_target",
                    "uncertainty": "",
                },
            ],
            "uncertainties": [],
        }],
        "uncertainties": [],
    }


def test_valid_structured_json_passes() -> None:
    data = valid_structure()
    validate_structured_cases(data)
    assert data["case_records"][0]["case_id"] == "CASE_001"


def test_invalid_assertion_type_fails() -> None:
    data = valid_structure()
    data["case_records"][0]["facts"][0]["assertion_type"] = "invalid"
    with pytest.raises(ValueError, match="assertion_type 非法"):
        validate_structured_cases(data)


def test_target_fact_id_missing_fails() -> None:
    data = valid_structure()
    data["case_records"][0]["target_event"]["target_fact_id"] = "MISSING"
    with pytest.raises(ValueError, match="target_fact_id 不属于"):
        validate_structured_cases(data)


def test_target_fact_id_must_be_known_at_target() -> None:
    data = valid_structure()
    data["case_records"][0]["target_event"]["target_fact_id"] = "CASE_001_F001"
    with pytest.raises(ValueError, match="known_at_target"):
        validate_structured_cases(data)

