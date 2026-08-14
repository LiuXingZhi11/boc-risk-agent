import pytest

from src.validators.rule_validator import validate_rule_hypotheses
from tests.test_structure_validator import valid_structure


def valid_rules() -> dict:
    return {
        "single_case_rule_hypotheses": [{
            "rule_id": "RULE_001",
            "case_id": "CASE_001",
            "rule_hypothesis": "关联关系可能放大风险。",
            "supporting_fact_ids": ["CASE_001_F001", "CASE_001_F002"],
            "uncertainty": "原因仍需核实。",
            "generalization_status": "single_case_hypothesis",
        }],
        "uncertainties": [],
    }


def test_valid_rule_json_passes() -> None:
    validate_rule_hypotheses(valid_rules(), valid_structure())


def test_supporting_fact_ids_must_exist() -> None:
    rules = valid_rules()
    rules["single_case_rule_hypotheses"][0]["supporting_fact_ids"] = ["MISSING"]
    with pytest.raises(ValueError, match="不存在的事实"):
        validate_rule_hypotheses(rules, valid_structure())


def test_rule_case_id_must_exist() -> None:
    rules = valid_rules()
    rules["single_case_rule_hypotheses"][0]["case_id"] = "MISSING_CASE"
    with pytest.raises(ValueError, match="不存在的 case_id"):
        validate_rule_hypotheses(rules, valid_structure())

