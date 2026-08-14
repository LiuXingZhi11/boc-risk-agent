from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from src.evidence.models import EvidenceUnit
from src.industry import (
    ControlledReactIndustryWorkflow,
    IndustryBackgroundProfile,
    IndustryInsight,
    IndustryProfileGeneration,
    IndustryProfileRepository,
    IndustryReactLimits,
    IndustryReactRun,
    IndustryReactSession,
    build_industry_react_system_prompt,
    create_industry_react_tools,
)
from src.llm.generation_config import GenerationConfig
from src.profiles import EvidenceReference
from src.ui.v5_services import generate_industry_profile_review


class FakeEvidenceService:
    def __init__(self) -> None:
        self.case_ids = []
        self.units = [
            EvidenceUnit(
                evidence_unit_id=f"industry:eu_{index:05d}",
                source_id="industry-source",
                case_id="INDUSTRY::robotics",
                content_type="document_chunk",
                content=f"行业证据正文 {index}，包含发展阶段和市场信息。",
                location={"page": index},
                metadata={
                    "title": f"行业章节 {index}",
                    "section_path": ["行业研究"],
                },
                content_hash=f"hash-{index}",
            )
            for index in range(1, 4)
        ]

    def search_evidence(self, query: str, *, case_id: str, top_k: int):
        self.case_ids.append(case_id)
        return self.units[:top_k]


def _tools(session):
    return {tool.name: tool for tool in create_industry_react_tools(session)}


def test_industry_react_prompt_requires_eight_single_dimension_searches():
    prompt = build_industry_react_system_prompt(
        industry_id="robotics",
        industry_name="机器人",
        limits=IndustryReactLimits(),
    )

    assert "每次只能提交一个 dimension_id" in prompt
    assert "最多保留两次额外搜索" in prompt
    assert "不同来源和不同章节覆盖" in prompt
    assert "每个维度在预算允许时至少读取 3 条" in prompt
    assert "发展阶段 发展历程 发展现状 成熟度" in prompt
    assert "发展阶段 发展现状 产业化" not in prompt


def test_industry_search_returns_catalog_without_body_and_uses_industry_scope():
    service = FakeEvidenceService()
    session = IndustryReactSession(
        industry_id="robotics",
        industry_name="机器人",
        evidence_service=service,
        limits=IndustryReactLimits(max_catalog_items=2),
    )

    result = json.loads(
        _tools(session)["search_industry_evidence"].invoke(
            {
                "query": "发展阶段、市场规模",
                "dimension_ids": ["development_stage"],
            }
        )
    )

    assert len(result["catalog"]) == 2
    assert "content" not in result["catalog"][0]
    assert "证据正文" not in json.dumps(result, ensure_ascii=False)
    assert set(service.case_ids) == {"INDUSTRY::robotics"}
    assert session.evidence_dimensions["industry:eu_00001"] == {
        "development_stage",
    }


def test_industry_search_rejects_multiple_dimensions():
    session = IndustryReactSession(
        industry_id="robotics",
        industry_name="机器人",
        evidence_service=FakeEvidenceService(),
        limits=IndustryReactLimits(),
    )

    result = json.loads(
        _tools(session)["search_industry_evidence"].invoke(
            {
                "query": "发展阶段 市场规模",
                "dimension_ids": ["development_stage", "market_size_and_growth"],
            }
        )
    )

    assert result["catalog"] == []
    assert "只能指定一个" in result["error"]
    assert session.discovered_units == {}


def test_industry_search_balances_broad_and_specific_terms():
    broad_units = [
        EvidenceUnit(
            evidence_unit_id=f"industry:broad_{index}",
            source_id="industry-source",
            case_id="INDUSTRY::robotics",
            content_type="document_chunk",
            content=f"宽泛行业内容 {index}",
            location={"page": index},
            metadata={"title": f"宽泛章节 {index}", "section_path": [f"章节 {index}"]},
            content_hash=f"broad-hash-{index}",
        )
        for index in range(5)
    ]
    specific_unit = EvidenceUnit(
        evidence_unit_id="industry:specific",
        source_id="industry-source",
        case_id="INDUSTRY::robotics",
        content_type="document_chunk",
        content="具体市场规模内容",
        location={"page": 10},
        metadata={"title": "市场规模", "section_path": ["市场"]},
        content_hash="specific-hash",
    )

    class SearchService:
        def search_evidence(self, query: str, *, case_id: str, top_k: int):
            if query == "宽泛行业":
                return broad_units[:top_k]
            return [specific_unit]

    session = IndustryReactSession(
        industry_id="robotics",
        industry_name="机器人",
        evidence_service=SearchService(),
        limits=IndustryReactLimits(max_catalog_items=3),
    )

    result = json.loads(
        _tools(session)["search_industry_evidence"].invoke(
            {
                "query": "宽泛行业 市场规模",
                "dimension_ids": ["market_size_and_growth"],
            }
        )
    )

    evidence_ids = [item["evidence_unit_id"] for item in result["catalog"]]
    assert evidence_ids == [
        "industry:broad_0",
        "industry:specific",
        "industry:broad_1",
    ]
    search_terms = session.trace[0].input_summary["search_terms"]
    assert search_terms[:2] == ["宽泛行业", "市场规模"]
    assert "细分市场" in search_terms


def test_industry_search_ignores_exact_industry_name_term():
    service = FakeEvidenceService()
    session = IndustryReactSession(
        industry_id="robotics",
        industry_name="人形机器人",
        evidence_service=service,
        limits=IndustryReactLimits(max_catalog_items=2),
    )

    _tools(session)["search_industry_evidence"].invoke(
        {
            "query": "人形机器人 市场规模 增长",
            "dimension_ids": ["market_size_and_growth"],
        }
    )

    search_terms = session.trace[0].input_summary["search_terms"]
    assert search_terms[:2] == ["市场规模", "增长"]
    assert "区域市场" in search_terms


def test_industry_read_only_uses_discovered_ids_and_honors_total_limit():
    session = IndustryReactSession(
        industry_id="robotics",
        industry_name="机器人",
        evidence_service=FakeEvidenceService(),
        limits=IndustryReactLimits(max_catalog_items=3, max_read_units=1),
    )
    tools = _tools(session)
    tools["search_industry_evidence"].invoke(
        {"query": "行业", "dimension_ids": ["development_stage"]}
    )

    result = json.loads(
        tools["read_industry_evidence"].invoke(
            {
                "evidence_unit_ids": [
                    "industry:eu_00001",
                    "unknown",
                    "industry:eu_00002",
                ]
            }
        )
    )

    assert [item["evidence_unit_id"] for item in result["evidence"]] == [
        "industry:eu_00001"
    ]
    assert result["unknown_evidence_unit_ids"] == ["unknown"]
    assert result["not_read_due_to_limit"] == ["industry:eu_00002"]
    assert "证据正文" not in json.dumps(
        session.trace, ensure_ascii=False, default=str
    )


class FakeAgent:
    def __init__(self, tools, *, read: bool) -> None:
        self.tools = {tool.name: tool for tool in tools}
        self.read = read

    def invoke(self, state):
        result = None
        for query, dimension_id in (
            ("发展阶段", "development_stage"),
            ("市场规模", "market_size_and_growth"),
        ):
            result = json.loads(
                self.tools["search_industry_evidence"].invoke(
                    {"query": query, "dimension_ids": [dimension_id]}
                )
            )
        if self.read:
            self.tools["read_industry_evidence"].invoke(
                {
                    "evidence_unit_ids": [
                        result["catalog"][0]["evidence_unit_id"]
                    ]
                }
            )
        return {
            "messages": [
                AIMessage(
                    content="行业证据选择完成",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                    },
                    response_metadata={
                        "model_name": "fake",
                        "finish_reason": "stop",
                    },
                )
            ],
            "run_model_call_count": 3,
        }


def _workflow(*, read: bool, auditor=None):
    captured = {}

    def agent_factory(**kwargs):
        return FakeAgent(kwargs["tools"], read=read)

    def generator(**kwargs):
        captured.update(kwargs)
        profile = IndustryBackgroundProfile(
            profile_id=kwargs["profile_id"],
            industry_id=kwargs["industry_id"],
            industry_name=kwargs["industry_name"],
            source_ids=("industry-source",),
            insights=(),
            review_status="pending",
            api_meta={"model": "fake"},
        )
        return IndustryProfileGeneration(profile)

    workflow = ControlledReactIndustryWorkflow(
        FakeEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
        generator=generator,
        auditor=auditor or (lambda **kwargs: kwargs["generation"]),
    )
    return workflow, captured


def test_industry_react_only_sends_read_units_to_json_generation():
    workflow, captured = _workflow(read=True)
    run = workflow.run(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        react_config=GenerationConfig(model="fake", mode="sampling"),
        extraction_config=GenerationConfig(model="fake", mode="thinking"),
    )

    assert run.execution_mode == "react"
    assert run.status == "pending_review"
    assert run.selected_evidence_unit_ids == ("industry:eu_00001",)
    assert [entry.tool_name for entry in run.react_trace] == [
        "search_industry_evidence",
        "search_industry_evidence",
        "read_industry_evidence",
    ]
    assert [
        unit.evidence_unit_id for unit in captured["bundle"].evidence_units
    ] == ["industry:eu_00001"]
    assert captured["bundle"].dimension_evidence_ids["development_stage"] == (
        "industry:eu_00001",
    )
    assert [item["stage"] for item in run.api_meta] == [
        "industry_react_evidence_discovery",
        "industry_profile_extraction",
        "industry_profile_semantic_audit",
    ]


def test_industry_react_without_read_does_not_run_json_generation():
    workflow, captured = _workflow(read=False)
    run = workflow.run(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        react_config=GenerationConfig(model="fake", mode="sampling"),
        extraction_config=GenerationConfig(model="fake", mode="thinking"),
    )

    assert run.status == "no_evidence"
    assert run.generation is None
    assert captured == {}


def test_industry_react_audit_failure_does_not_return_profile():
    def failing_auditor(**kwargs):
        raise RuntimeError("fake audit failure")

    workflow, _ = _workflow(read=True, auditor=failing_auditor)
    run = workflow.run(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        react_config=GenerationConfig(model="fake", mode="sampling"),
        extraction_config=GenerationConfig(model="fake", mode="thinking"),
    )

    assert run.status == "audit_failed"
    assert run.generation is None
    assert "fake audit failure" in run.error


def test_industry_service_uses_react_and_saves_pending_profile(
    monkeypatch,
    tmp_path,
):
    captured = {}
    profile = IndustryBackgroundProfile(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        source_ids=(),
        insights=(),
        review_status="pending",
        api_meta={"model": "fake"},
    )

    class FakeWorkflow:
        def __init__(self, evidence_service):
            captured["evidence_service"] = evidence_service

        def run(self, **kwargs):
            captured.update(kwargs)
            return IndustryReactRun(
                industry_id="robotics",
                status="pending_review",
                generation=IndustryProfileGeneration(profile),
            )

    monkeypatch.setattr(
        "src.ui.v5_services.ControlledReactIndustryWorkflow",
        FakeWorkflow,
    )
    database = tmp_path / "industry.db"

    result = generate_industry_profile_review(
        database=database,
        profile_id=profile.profile_id,
        industry_id=profile.industry_id,
        industry_name=profile.industry_name,
    )

    assert result["execution_mode"] == "react"
    assert captured["react_config"].mode == "thinking"
    # thinking 请求不会把 temperature 发送给 API；配置对象保留默认值仅用于统一数据结构。
    assert captured["react_config"].temperature == 0.2
    assert captured["react_config"].max_tokens == 24000
    assert captured["extraction_config"].mode == "thinking"
    assert captured["extraction_config"].max_tokens == 24000
    assert captured["limits"].max_model_calls == 8
    assert captured["limits"].max_search_calls == 10
    assert captured["limits"].max_read_calls == 10
    assert captured["limits"].max_read_units == 36
    assert captured["limits"].max_catalog_items == 16
    assert IndustryProfileRepository(database).get(profile.profile_id) == profile


class AllDimensionAgent:
    def __init__(self, tools) -> None:
        self.tools = {tool.name: tool for tool in tools}

    def invoke(self, state):
        result = None
        for dimension_id in (
            "development_stage",
            "market_size_and_growth",
            "technology_routes",
            "value_chain",
            "competition_landscape",
            "commercialization",
            "policy_and_regulation",
            "industry_risks",
        ):
            result = json.loads(
                self.tools["search_industry_evidence"].invoke(
                    {"query": "行业", "dimension_ids": [dimension_id]}
                )
            )
        self.tools["read_industry_evidence"].invoke(
            {"evidence_unit_ids": [result["catalog"][0]["evidence_unit_id"]]}
        )
        return {"messages": [], "run_model_call_count": 3}


def test_industry_react_generates_four_dimension_batches_and_merges():
    calls = []

    def generator(**kwargs):
        dimensions = kwargs["allowed_dimensions"]
        calls.append(dimensions)
        unit = kwargs["bundle"].evidence_units[0]
        insight = IndustryInsight(
            insight_id="insight-1",
            dimension_id=dimensions[0],
            statement=f"行业材料覆盖{dimensions[0]}维度。",
            insight_type="reported_fact",
            evidence_refs=(EvidenceReference(unit.evidence_unit_id, unit.content),),
        )
        profile = IndustryBackgroundProfile(
            profile_id=kwargs["profile_id"],
            industry_id=kwargs["industry_id"],
            industry_name=kwargs["industry_name"],
            source_ids=(unit.source_id,),
            insights=(insight,),
            api_meta={"model": "fake"},
        )
        return IndustryProfileGeneration(profile)

    workflow = ControlledReactIndustryWorkflow(
        FakeEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=lambda **kwargs: AllDimensionAgent(kwargs["tools"]),
        generator=generator,
        auditor=lambda **kwargs: kwargs["generation"],
    )
    run = workflow.run(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        react_config=GenerationConfig(model="fake", mode="sampling"),
        extraction_config=GenerationConfig(model="fake", mode="thinking"),
    )

    assert len(calls) == 4
    assert len(run.generation.profile.insights) == 4
    assert [
        insight.insight_id for insight in run.generation.profile.insights
    ] == [
        "development_stage:insight-1",
        "technology_routes:insight-1",
        "competition_landscape:insight-1",
        "policy_and_regulation:insight-1",
    ]
    assert [status["status"] for status in run.batch_statuses] == [
        "completed",
        "completed",
        "completed",
        "completed",
    ]


def test_industry_batch_failure_keeps_react_trace_and_does_not_return_profile():
    call_count = 0

    def generator(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("fake batch failure")
        unit = kwargs["bundle"].evidence_units[0]
        profile = IndustryBackgroundProfile(
            profile_id=kwargs["profile_id"],
            industry_id=kwargs["industry_id"],
            industry_name=kwargs["industry_name"],
            source_ids=(unit.source_id,),
            insights=(),
            api_meta={"model": "fake"},
        )
        return IndustryProfileGeneration(profile)

    workflow = ControlledReactIndustryWorkflow(
        FakeEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=lambda **kwargs: AllDimensionAgent(kwargs["tools"]),
        generator=generator,
        auditor=lambda **kwargs: kwargs["generation"],
    )
    run = workflow.run(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        react_config=GenerationConfig(model="fake", mode="sampling"),
        extraction_config=GenerationConfig(model="fake", mode="thinking"),
    )

    assert run.status == "extraction_failed"
    assert run.generation is None
    assert run.selected_evidence_unit_ids == ("industry:eu_00001",)
    assert [entry.tool_name for entry in run.react_trace] == [
        *("search_industry_evidence" for _ in range(8)),
        "read_industry_evidence",
    ]
    assert [status["status"] for status in run.batch_statuses] == [
        "completed",
        "failed",
    ]
    assert "fake batch failure" in run.error
