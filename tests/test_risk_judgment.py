from __future__ import annotations

import pytest

from src.llm.generation_config import GenerationConfig
from src.profiles import CurrentEnterpriseProfile, EvidenceReference, ProfileItem
from src.profiles.detailed_comparison import DetailedComparisonRun
from src.profiles.risk_judgment import (
    build_core_risk_judgment_messages,
    generate_core_risk_judgment,
)
from src.industry import IndustryBackgroundProfile, IndustryInsight


def _current_profile() -> CurrentEnterpriseProfile:
    return CurrentEnterpriseProfile(
        profile_id="current-1",
        case_id="CURRENT",
        enterprise_name="当前科技企业",
        items=(
            ProfileItem(
                item_id="technology-1",
                section_id="technology_ip",
                field_id="technology.name",
                value="自研控制技术",
                value_type="entity_ref",
                information_status="supported",
                content_role="external_observation",
                evidence_refs=(EvidenceReference("source:1"),),
                review_status="accepted",
            ),
        ),
        information_gaps=("核心技术权属证明材料不完整。",),
        conflicts=("不同材料对技术授权期限的表述不一致。",),
        review_status="approved",
    )


def _model_result() -> dict:
    return {
        "overall_judgment": "现有材料显示企业具备技术基础，但技术权属和授权期限仍是最需要核实的风险重点。",
        "key_risks": [
            {
                "title": "技术权属仍需核实",
                "explanation": "权属证明不完整且授权期限表述不一致，可能影响对核心技术稳定性的判断。",
                "current_item_ids": ["technology-1"],
                "current_relation_ids": [],
                "information_gap_numbers": [1],
                "conflict_numbers": [1],
            },
            {
                "title": "没有来源的判断",
                "explanation": "这一判断引用了输入中不存在的画像项，因此不能保留。",
                "current_item_ids": ["unknown-item"],
                "current_relation_ids": [],
                "information_gap_numbers": [],
                "conflict_numbers": [],
            },
        ],
        "mitigating_factors": [
            {
                "title": "已有技术基础",
                "explanation": "现有材料已经提供一项获得支持的技术事实，可作为进一步核实的基础。",
                "current_item_ids": ["technology-1"],
                "current_relation_ids": [],
                "information_gap_numbers": [],
                "conflict_numbers": [],
            },
            {
                "title": "仅由缺口推断的缓释因素",
                "explanation": "这一项没有当前企业事实支持，因此不能作为缓释因素。",
                "current_item_ids": [],
                "current_relation_ids": [],
                "information_gap_numbers": [1],
                "conflict_numbers": [],
            },
        ],
        "uncertainties": ["技术权属和授权期限尚未形成一致、完整的证据链。"],
        "verification_priorities": ["优先取得权属证明和有效授权文件并核对期限。"],
        "api_meta": {"model": "fake-model"},
    }


def test_core_risk_judgment_validates_sources_and_collects_evidence(monkeypatch):
    monkeypatch.setattr(
        "src.profiles.risk_judgment.call_deepseek",
        lambda messages, config: _model_result(),
    )
    current = _current_profile()
    judgment = generate_core_risk_judgment(
        current,
        DetailedComparisonRun(current.profile_id, (), {}),
        config=GenerationConfig(mode="thinking", max_retries=0),
    )

    assert [point.title for point in judgment.key_risks] == ["技术权属仍需核实"]
    assert [point.title for point in judgment.mitigating_factors] == ["已有技术基础"]
    assert judgment.key_risks[0].supporting_information_gaps == (
        "核心技术权属证明材料不完整。",
    )
    assert judgment.evidence_unit_ids == ("source:1",)
    assert judgment.api_meta == {"model": "fake-model"}


def test_core_risk_prompt_keeps_history_as_context_only():
    current = _current_profile()
    messages = build_core_risk_judgment_messages(
        current,
        DetailedComparisonRun(current.profile_id, (), {}),
    )

    assert "历史企业结果写成当前企业事实" in messages[0]["content"]
    assert "风险分数或授信审批意见" in messages[0]["content"]
    assert '"number": 1' in messages[1]["content"]


def test_core_risk_judgment_requires_chinese_overall_text(monkeypatch):
    result = _model_result()
    result["overall_judgment"] = "risk only"
    monkeypatch.setattr(
        "src.profiles.risk_judgment.call_deepseek",
        lambda messages, config: result,
    )
    current = _current_profile()

    with pytest.raises(ValueError, match="简体中文"):
        generate_core_risk_judgment(
            current,
            DetailedComparisonRun(current.profile_id, (), {}),
            config=GenerationConfig(mode="thinking", max_retries=0),
        )


def test_industry_context_cannot_replace_current_enterprise_basis(monkeypatch):
    current = _current_profile()
    industry = IndustryBackgroundProfile(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        source_ids=("industry-source",),
        insights=(
            IndustryInsight(
                insight_id="industry-risk",
                dimension_id="industry_risks",
                statement="行业报告认为商业化仍面临成本挑战。",
                insight_type="analysis_judgment",
                evidence_refs=(EvidenceReference("industry:1", "商业化仍面临成本挑战"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )
    result = _model_result()
    result["key_risks"] = [
        {
            "title": "企业事实与行业背景共同提示",
            "explanation": "企业技术权属材料不完整，行业环境进一步说明持续核实的重要性。",
            "current_item_ids": ["technology-1"],
            "current_relation_ids": [],
            "information_gap_numbers": [1],
            "conflict_numbers": [],
            "industry_insight_ids": ["industry-risk"],
        },
        {
            "title": "只有行业背景",
            "explanation": "这一项没有任何当前企业依据，因此不能保留。",
            "current_item_ids": [],
            "current_relation_ids": [],
            "information_gap_numbers": [],
            "conflict_numbers": [],
            "industry_insight_ids": ["industry-risk"],
        },
    ]
    monkeypatch.setattr(
        "src.profiles.risk_judgment.call_deepseek",
        lambda messages, config: result,
    )

    judgment = generate_core_risk_judgment(
        current,
        DetailedComparisonRun(current.profile_id, (), {}),
        config=GenerationConfig(mode="thinking", max_retries=0),
        industry_profile=industry,
    )

    assert [point.title for point in judgment.key_risks] == [
        "企业事实与行业背景共同提示"
    ]
    assert judgment.key_risks[0].industry_insight_ids == ("industry-risk",)
    assert judgment.industry_evidence_unit_ids == ("industry:1",)
    assert judgment.industry_name == "机器人"
