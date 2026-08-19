from src.config.settings import Settings, get_settings
from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.utils.json_utils import extract_json_from_text, load_json, load_text, save_json
from src.evidence import EvidenceRepository
from src.industry import IndustryProfileRepository
from src.profiles import ProfileRepository
from src.ui.industry_services import generate_industry_profile_review
from src.ui.material_services import ingest_industry_source, ingest_uploaded_source
from src.ui.profile_services import run_react_profile_investigation
from src.ui.rating_configuration_services import create_peer_cohort
from src.ui.rating_direction_services import generate_guideline_section_review
from src.ui.rating_overall_services import generate_standalone_enterprise_overall_assessment_review


def test_all_public_imports() -> None:
    assert all((Settings, get_settings, call_deepseek, GenerationConfig))
    assert all((EvidenceRepository, IndustryProfileRepository, ProfileRepository))
    assert all((load_json, load_text, save_json, extract_json_from_text))
    assert all(
        (
            ingest_uploaded_source,
            ingest_industry_source,
            run_react_profile_investigation,
            generate_industry_profile_review,
            generate_guideline_section_review,
            generate_standalone_enterprise_overall_assessment_review,
            create_peer_cohort,
        )
    )
