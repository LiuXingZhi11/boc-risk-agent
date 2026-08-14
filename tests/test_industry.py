from __future__ import annotations

from dataclasses import replace

from src.evidence import EvidenceQueryService, EvidenceRepository
from src.industry import (
    INDUSTRY_DIMENSIONS,
    IndustryBackgroundProfile,
    IndustryEvidenceBundle,
    IndustryInsight,
    IndustryProfileGeneration,
    IndustryProfileRepository,
    audit_industry_profile_generation,
    approve_industry_profile,
    build_industry_profile_messages,
    build_industry_evidence_bundle,
    generate_industry_background_profile,
    industry_scope_id,
)
from src.llm.generation_config import GenerationConfig
from src.profiles import EvidenceReference
from src.sources import ingest_source
from src.ui.v5_services import ingest_industry_source, industry_source_rows


def _save_industry_html(tmp_path, database):
    path = tmp_path / "industry.html"
    path.write_text(
        "<h1>产业发展</h1><p>行业处于商业化早期，核心技术仍在持续演进。"
        "市场规模预计继续增长，量产成本和应用验证仍是主要挑战。</p>",
        encoding="utf-8",
    )
    source, units = ingest_source(
        path,
        case_id=industry_scope_id("robotics"),
    )
    source = replace(
        source,
        metadata={
            "material_role": "industry_report",
            "industry_id": "robotics",
            "industry_name": "机器人",
        },
    )
    repository = EvidenceRepository(database)
    repository.save_source(source)
    repository.save_units(list(units))
    return source, units


def test_industry_retrieval_uses_separate_scope(tmp_path):
    database = tmp_path / "industry.db"
    source, _ = _save_industry_html(tmp_path, database)
    enterprise_path = tmp_path / "enterprise.html"
    enterprise_path.write_text(
        "<p>企业材料也提到市场规模和核心技术。</p>",
        encoding="utf-8",
    )
    enterprise_source, enterprise_units = ingest_source(
        enterprise_path,
        case_id="ENTERPRISE-1",
    )
    repository = EvidenceRepository(database)
    repository.save_source(enterprise_source)
    repository.save_units(list(enterprise_units))

    bundle = build_industry_evidence_bundle(
        EvidenceQueryService(repository),
        industry_id="robotics",
    )

    assert bundle.evidence_units
    assert {unit.source_id for unit in bundle.evidence_units} == {source.source_id}
    assert set(bundle.dimension_evidence_ids) == set(INDUSTRY_DIMENSIONS)


def test_industry_generation_filters_invalid_candidates_and_can_be_approved(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "industry.db"
    source, units = _save_industry_html(tmp_path, database)
    bundle = build_industry_evidence_bundle(
        EvidenceQueryService(EvidenceRepository(database)),
        industry_id="robotics",
    )
    evidence_id = bundle.evidence_units[0].evidence_unit_id
    bundle = IndustryEvidenceBundle(
        industry_id=bundle.industry_id,
        evidence_units=bundle.evidence_units,
        dimension_evidence_ids={
            **bundle.dimension_evidence_ids,
            "development_stage": (evidence_id,),
        },
    )
    excerpt = "行业处于商业化早期，核心技术仍在持续演进。"
    result = {
        "insights": [
            {
                "insight_id": "industry-stage",
                "dimension_id": "development_stage",
                "statement": "报告认为该行业仍处于商业化早期阶段。",
                "insight_type": "analysis_judgment",
                "time_scope": None,
                "geographic_scope": None,
                "evidence_unit_ids": [evidence_id],
                "evidence_quotes": [
                    {"evidence_unit_id": evidence_id, "excerpt": excerpt}
                ],
            },
                {
                    "insight_id": "invalid-evidence",
                "dimension_id": "industry_risks",
                "statement": "这一项引用了不存在的证据。",
                "insight_type": "reported_fact",
                "time_scope": None,
                "geographic_scope": None,
                "evidence_unit_ids": ["unknown:evidence"],
                "evidence_quotes": [
                        {"evidence_unit_id": "unknown:evidence", "excerpt": "不存在"}
                    ],
                },
                {
                    "insight_id": "industry-stage",
                    "dimension_id": "development_stage",
                    "statement": "这一项使用了同一维度内的重复技术标识。",
                    "insight_type": "analysis_judgment",
                    "time_scope": None,
                    "geographic_scope": None,
                    "evidence_unit_ids": [evidence_id],
                    "evidence_quotes": [
                        {"evidence_unit_id": evidence_id, "excerpt": excerpt}
                    ],
                },
        ],
        "information_gaps": ["政策与标准信息尚未充分覆盖。"],
        "api_meta": {"model": "fake-model"},
    }
    monkeypatch.setattr(
        "src.industry.extraction.call_deepseek",
        lambda messages, config: result,
    )

    generation = generate_industry_background_profile(
        profile_id="industry-profile-1",
        industry_id="robotics",
        industry_name="机器人",
        bundle=bundle,
        config=GenerationConfig(mode="thinking", max_retries=0),
    )

    assert [insight.insight_id for insight in generation.profile.insights] == [
        "industry-stage"
    ]
    assert generation.rejected_candidates[0]["insight_id"] == "invalid-evidence"
    assert any(
        "insight_id 不得重复" in candidate["reason"]
        for candidate in generation.rejected_candidates
    )
    assert generation.profile.source_ids == (source.source_id,)
    approved = approve_industry_profile(generation.profile)
    assert approved.review_status == "approved"
    assert approved.insights[0].review_status == "accepted"

    repository = IndustryProfileRepository(database)
    repository.save(approved)
    loaded = repository.get(approved.profile_id)
    assert loaded == approved


def test_industry_batch_prompt_defines_only_current_dimensions(tmp_path):
    database = tmp_path / "industry.db"
    _, _ = _save_industry_html(tmp_path, database)
    bundle = build_industry_evidence_bundle(
        EvidenceQueryService(EvidenceRepository(database)),
        industry_id="robotics",
    )

    messages = build_industry_profile_messages(
        industry_name="机器人",
        bundle=bundle,
        allowed_dimensions=("development_stage", "market_size_and_growth"),
    )
    user_message = messages[1]["content"]

    assert "行业发展历程、成熟度和当前所处阶段" in user_message
    assert "市场规模、出货量、增长率" in user_message
    assert "不符合当前维度的证据必须省略" in user_message
    assert "每条要点只表达一个核心事实" in user_message
    assert "每个维度最多输出 4 条" in user_message
    assert "上游原材料与零部件" not in user_message


def test_industry_generation_rejects_evidence_from_another_dimension(
    monkeypatch,
    tmp_path,
):
    database = tmp_path / "industry.db"
    _, units = _save_industry_html(tmp_path, database)
    unit = units[0]
    bundle = IndustryEvidenceBundle(
        industry_id="robotics",
        evidence_units=(unit,),
        dimension_evidence_ids={
            "development_stage": (unit.evidence_unit_id,),
            "market_size_and_growth": (),
        },
    )
    monkeypatch.setattr(
        "src.industry.extraction.call_deepseek",
        lambda messages, config: {
            "insights": [
                {
                    "insight_id": "wrong-dimension-evidence",
                    "dimension_id": "market_size_and_growth",
                    "statement": "材料称该行业市场仍在增长。",
                    "insight_type": "reported_fact",
                    "time_scope": None,
                    "geographic_scope": None,
                    "evidence_unit_ids": [unit.evidence_unit_id],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": unit.evidence_unit_id,
                            "excerpt": "市场规模预计继续增长",
                        }
                    ],
                }
            ],
            "information_gaps": [],
            "api_meta": {"model": "fake"},
        },
    )

    generation = generate_industry_background_profile(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        bundle=bundle,
        config=GenerationConfig(mode="thinking"),
        allowed_dimensions=("development_stage", "market_size_and_growth"),
    )

    assert generation.profile.insights == ()
    assert "未关联到该维度" in generation.rejected_candidates[0]["reason"]


def test_industry_semantic_audit_filters_without_rewriting(monkeypatch):
    reference = EvidenceReference("industry:eu_1", "行业仍处于发展初期。")
    accepted_insight = IndustryInsight(
        insight_id="development_stage:item-1",
        dimension_id="development_stage",
        statement="报告认为行业仍处于发展初期。",
        insight_type="analysis_judgment",
        evidence_refs=(reference,),
    )
    rejected_insight = IndustryInsight(
        insight_id="market_size_and_growth:item-2",
        dimension_id="market_size_and_growth",
        statement="该条实际没有市场规模信息。",
        insight_type="reported_fact",
        evidence_refs=(reference,),
    )
    missing_decision_insight = IndustryInsight(
        insight_id="technology_routes:item-3",
        dimension_id="technology_routes",
        statement="该条没有审核决定。",
        insight_type="reported_fact",
        evidence_refs=(reference,),
    )
    generation = IndustryProfileGeneration(
        IndustryBackgroundProfile(
            profile_id="industry-profile",
            industry_id="robotics",
            industry_name="机器人",
            source_ids=("industry-source",),
            insights=(accepted_insight, rejected_insight, missing_decision_insight),
            api_meta={"batch_statuses": []},
        )
    )
    monkeypatch.setattr(
        "src.industry.extraction.call_deepseek",
        lambda messages, config: {
            "decisions": [
                {
                    "insight_id": accepted_insight.insight_id,
                    "accepted": True,
                    "reason": "维度和证据匹配。",
                },
                {
                    "insight_id": rejected_insight.insight_id,
                    "accepted": False,
                    "reason": "维度不匹配。",
                },
            ],
            "api_meta": {"model": "fake-auditor"},
        },
    )

    audited = audit_industry_profile_generation(
        generation=generation,
        config=GenerationConfig(mode="thinking"),
    )

    assert audited.profile.insights == (accepted_insight,)
    assert audited.profile.insights[0].statement == accepted_insight.statement
    assert audited.rejected_candidates[-1] == {
        "insight_id": missing_decision_insight.insight_id,
        "reason": "全局语义审核未返回接受决定。",
    }
    assert audited.rejected_candidates[-2] == {
        "insight_id": rejected_insight.insight_id,
        "reason": "维度不匹配。",
    }
    assert audited.profile.api_meta["semantic_audit"]["model"] == "fake-auditor"


def test_industry_upload_marks_source_role(tmp_path):
    database = tmp_path / "industry.db"
    result = ingest_industry_source(
        database=database,
        industry_id="robotics",
        industry_name="机器人",
        upload_root=tmp_path / "uploads",
        filename="report.html",
        content="<p>行业发展现状和市场规模。</p>".encode("utf-8"),
    )

    rows = industry_source_rows(database)
    assert result["industry_id"] == "robotics"
    assert rows[0]["industry_name"] == "机器人"
    assert rows[0]["evidence_units"] >= 1
