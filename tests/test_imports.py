from src.config.settings import Settings, get_settings
from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.services.rule_service import extract_rule_hypotheses
from src.services.structure_service import structure_case
from src.utils.json_utils import extract_json_from_text, load_json, load_text, save_json
from src.validators.rule_validator import validate_rule_hypotheses
from src.validators.structure_validator import validate_structured_cases


def test_all_public_imports() -> None:
    assert all((Settings, get_settings, call_deepseek, GenerationConfig))
    assert all((extract_rule_hypotheses, structure_case))
    assert all((validate_structured_cases, validate_rule_hypotheses))
    assert all((load_json, load_text, save_json, extract_json_from_text))

