from __future__ import annotations

from src.case_analysis import (
    HistoricalCaseAnalysisRepository,
    approve_historical_case_analysis,
    build_case_analysis_messages,
    generate_historical_case_analysis,
)
from src.llm.generation_config import GenerationConfig
from src.profiles import EvidenceReference, HistoricalEnterpriseProfile, ProfileItem, ProfileRepository


def _profile() -> HistoricalEnterpriseProfile:
    return HistoricalEnterpriseProfile(
        profile_id="hist-1", case_id="H1", enterprise_name="示例科技",
        items=(
            ProfileItem(
                item_id="tech", section_id="technology_ip", field_id="technology.name",
                value="核心显示技术", value_type="entity_ref", information_status="claimed",
                content_role="enterprise_claim", evidence_refs=(EvidenceReference("src:eu1", "企业称拥有核心技术"),),
                review_status="accepted",
            ),
            ProfileItem(
                item_id="outcome", section_id="compliance_legal_risk", field_id="risk.matter",
                value="监管处罚并终止审核", value_type="entity_ref", information_status="supported",
                content_role="regulatory_finding", evidence_refs=(EvidenceReference("src:eu2", "监管文件披露处罚结果"),),
                review_status="accepted",
            ),
        ),
        information_gaps=("缺少完整客户验证资料",), review_status="approved",
    )


def _model_result():
    return {
        "case_summary": "企业申报核心技术，后续材料披露监管处罚及审核终止。",
        "outcome_status": "disclosed",
        "outcomes": [
            {"outcome_id": "o1", "outcome_type": "regulatory_action", "description": "监管材料披露企业受到处罚并终止审核。", "source_item_ids": ["outcome"], "source_relation_ids": []},
            {"outcome_id": "bad", "outcome_type": "default_or_distress", "description": "编造结果", "source_item_ids": ["missing"], "source_relation_ids": []},
        ],
        "factors": [
            {"factor_id": "f1", "dimension_id": "technology_and_ip", "title": "核心技术主要来自企业陈述", "finding": "现有画像记录了企业的核心技术主张，但第三方验证材料仍不完整。", "factor_role": "evidence_supported_factor", "source_item_ids": ["tech"], "source_relation_ids": []},
            {"factor_id": "f2", "dimension_id": "authority_outcome_and_evidence", "title": "监管事项", "finding": "监管材料明确披露处罚和审核终止。", "factor_role": "explicit_reason", "source_item_ids": ["outcome"], "source_relation_ids": []},
        ],
        "review_directions": [{"direction_id": "d1", "title": "核实技术验证", "rationale": "避免仅依赖企业陈述。", "related_factor_ids": ["f1"], "verification_questions": ["是否有第三方测试和客户量产验证？"]}],
        "applicability_limits": ["单一历史企业结果不能直接迁移到其他企业。"],
        "api_meta": {"total_tokens": 100},
    }


def test_generation_filters_bad_entries_and_keeps_debug(monkeypatch):
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: _model_result())
    analysis = generate_historical_case_analysis(_profile(), config=GenerationConfig(mode="thinking"))

    assert analysis.outcome_status == "disclosed"
    assert [item.outcome_id for item in analysis.outcomes] == ["o1"]
    assert analysis.outcomes[0].evidence_refs[0].evidence_unit_id == "src:eu2"
    assert len(analysis.factors) == 2
    assert analysis.debug_data["rejected_candidates"][0]["kind"] == "outcome"
    assert analysis.api_meta["total_tokens"] == 100


def test_human_markdown_hides_backend_ids(monkeypatch):
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: _model_result())
    analysis = generate_historical_case_analysis(_profile(), config=GenerationConfig(mode="thinking"))
    markdown = analysis.to_markdown()

    assert "示例科技历史案例分析" in markdown
    assert "后续审查方向" in markdown
    assert "source_item_ids" not in markdown
    assert "src:eu2" not in markdown


def test_missing_authoritative_outcome_becomes_not_disclosed(monkeypatch):
    result = _model_result()
    result["outcomes"] = [{"outcome_id": "x", "outcome_type": "approval_rejected", "description": "审批未通过", "source_item_ids": ["tech"], "source_relation_ids": []}]
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: result)

    analysis = generate_historical_case_analysis(_profile(), config=GenerationConfig(mode="thinking"))

    assert analysis.outcome_status == "not_disclosed"
    assert not analysis.outcomes


def test_supported_chinese_outcome_labels_are_normalized(monkeypatch):
    result = _model_result()
    result["outcome_status"] = "已强制退市"
    result["outcomes"][0]["outcome_type"] = "强制退市"
    result["outcomes"] = result["outcomes"][:1]
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: result)

    analysis = generate_historical_case_analysis(_profile(), config=GenerationConfig(mode="thinking"))

    assert analysis.outcome_status == "disclosed"
    assert analysis.outcomes[0].outcome_type == "restructuring_or_exit"


def test_factor_dimension_is_inferred_from_cited_profile_item(monkeypatch):
    result = _model_result()
    result["factors"] = [result["factors"][0]]
    result["factors"][0]["dimension_id"] = "technology_ownership"
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: result)

    analysis = generate_historical_case_analysis(_profile(), config=GenerationConfig(mode="thinking"))

    assert len(analysis.factors) == 1
    assert analysis.factors[0].dimension_id == "technology_and_ip"


def test_prompt_uses_profile_not_raw_documents():
    messages = build_case_analysis_messages(
        _profile(),
        guide_text="协议",
        material_context={
            "case_id": "H1",
            "enterprise_name": "示例科技",
            "reporting_periods": ["2019"],
            "source_documents": [
                {"document_title": "示例科技2019年年度报告", "source_type": "pdf"}
            ],
        },
    )
    assert "企业称拥有核心技术" not in messages[1]["content"]
    assert '"item_id": "tech"' in messages[1]["content"]
    assert "示例科技2019年年度报告" in messages[1]["content"]
    assert '"reporting_periods": [\n    "2019"' in messages[1]["content"]
    assert "信息缺失" in messages[0]["content"]
    assert "technology_and_ip" in messages[1]["content"]


def test_repository_round_trip_and_approval(tmp_path, monkeypatch):
    profile = _profile()
    database = tmp_path / "case-analysis.db"
    ProfileRepository(database).save(profile)
    monkeypatch.setattr("src.case_analysis.service.call_deepseek", lambda messages, config: _model_result())
    analysis = generate_historical_case_analysis(profile, config=GenerationConfig(mode="thinking"))
    repository = HistoricalCaseAnalysisRepository(database)
    repository.save(analysis)

    loaded = repository.get(analysis.analysis_id)
    assert loaded is not None
    assert loaded.factors[0].evidence_refs[0].evidence_unit_id == "src:eu1"
    assert repository.is_current(loaded, profile)

    approved = approve_historical_case_analysis(loaded)
    repository.save(approved)
    assert repository.get(analysis.analysis_id).review_status == "approved"
