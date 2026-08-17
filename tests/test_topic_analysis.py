from __future__ import annotations

import json

import pytest

from src.profiles import (
    CurrentEnterpriseProfile,
    EvidenceReference,
    ProfileItem,
    ProfileRepository,
    TopicAnalysisLimits,
    apply_topic_analysis,
    build_domain_analysis_packet,
    build_enterprise_visual_card,
    build_topic_fact_payload,
    normalize_topic_analysis_result,
    validate_topic_analysis_result,
)
from src.profiles.topic_analysis_repository import ProfileTopicAnalysisRepository
from src.profiles.topic_analysis import (
    ControlledReactTopicAnalysisWorkflow,
    TopicAnalysisSession,
    create_topic_analysis_tools,
)
from src.llm.generation_config import GenerationConfig


def _item(item_id: str, value: str, evidence_id: str = "e-1") -> ProfileItem:
    return ProfileItem(
        item_id=item_id,
        field_id="technology.name",
        section_id="technology_ip",
        value=value,
        value_type="entity_ref",
        information_status="confirmed",
        content_role="enterprise_claim",
        evidence_refs=(EvidenceReference(evidence_id, excerpt=f"证据：{value}"),),
        review_status="accepted",
    )


def _card():
    profile = CurrentEnterpriseProfile(
        profile_id="p-analysis",
        case_id="case-analysis",
        enterprise_name="测试企业",
        items=tuple(_item(f"tech-{index}", f"技术{index}", f"e-{index}") for index in range(3)),
    )
    return build_enterprise_visual_card(profile)


def test_topic_fact_payload_can_read_all_facts_in_pages():
    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    topic = dimension.topics[0]
    first = build_topic_fact_payload(topic, start=0, limit=2)
    second = build_topic_fact_payload(topic, start=2, limit=2)
    assert first["has_more"] is True
    assert [item["fact_id"] for item in first["facts"] + second["facts"]] == [
        fact.item_id for fact in topic.facts
    ]


def test_normalize_topic_analysis_result_accepts_common_summary_aliases():
    result = normalize_topic_analysis_result(
        {"topics": [{"topic_id": "topic-1", "summary": "主题结论"}]}
    )

    assert result["topic_analyses"][0]["conclusion"] == "主题结论"
    assert result["domain_summary"] == "主题结论"


def test_normalize_topic_analysis_result_converts_topic_mapping_to_list():
    result = normalize_topic_analysis_result(
        {"topic_analyses": {"topic-1": {"summary": "主题结论"}}}
    )

    assert result["topic_analyses"] == [
        {"topic_id": "topic-1", "summary": "主题结论", "conclusion": "主题结论"}
    ]


def test_normalize_topic_analysis_result_handles_empty_summary_and_aliases():
    result = normalize_topic_analysis_result(
        {
            "domain_summary": "",
            "topic_analyses": [
                {
                    "topic_id": "topic-1",
                    "topic_summary": "技术体系已有明确布局。",
                }
            ],
        }
    )

    assert result["domain_summary"] == "技术体系已有明确布局。"
    assert result["topic_analyses"][0]["conclusion"] == "技术体系已有明确布局。"


def test_normalize_topic_analysis_result_uses_neutral_boundary_when_no_summary():
    result = normalize_topic_analysis_result(
        {"domain_summary": None, "topic_analyses": [{"topic_id": "topic-1"}]}
    )

    assert result["domain_summary"].startswith("基于当前已读取事实")


def test_normalize_topic_analysis_result_accepts_nested_and_chinese_topic_aliases():
    result = normalize_topic_analysis_result(
        {
            "领域总结": "技术领域总体稳定。",
            "主题分析": {
                "technology_system": "形成核心技术体系。",
            },
        }
    )

    assert result["domain_summary"] == "技术领域总体稳定。"
    assert result["topic_analyses"] == [
        {"topic_id": "technology_system", "conclusion": "形成核心技术体系。"}
    ]


def test_domain_analysis_packet_contains_structured_topics_and_facts():
    packet = build_domain_analysis_packet(_card(), "technology_and_ip")
    assert packet["dimension_id"] == "technology_and_ip"
    assert packet["topics"]
    assert packet["topics"][0]["facts"][0]["fact_id"]
    assert packet["topics"][0]["evidence"][0]["evidence_unit_id"]


def test_topic_tool_reads_pages_and_tracks_trace():
    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    session = TopicAnalysisSession(
        dimension=dimension,
        limits=TopicAnalysisLimits(max_topic_reads=2, max_facts_per_read=1),
    )
    tool = create_topic_analysis_tools(session)[0]
    topic_id = dimension.topics[0].topic_id
    first = tool.invoke({"topic_id": topic_id, "start": 0})
    second = tool.invoke({"topic_id": topic_id, "start": 1})
    assert '"has_more": true' in first
    assert '"facts": []' not in second
    assert len(session.read_facts) == 2
    assert len(session.trace) == 2


def test_analysis_validation_rejects_unread_fact_reference():
    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    session = TopicAnalysisSession(dimension=dimension, limits=TopicAnalysisLimits())
    topic = dimension.topics[0]
    session.read_topic_ids.append(topic.topic_id)
    session.read_facts.update({fact.item_id: fact for fact in topic.facts})
    result = {
        "domain_summary": "有分析",
        "topic_analyses": [
            {
                "topic_id": topic.topic_id,
                "conclusion": "结论",
                "key_signals": [],
                "information_boundaries": [],
                "fact_refs": ["not-read"],
                "evidence_refs": [],
            }
        ],
        "information_boundaries": [],
        "evidence_refs": [],
    }
    with pytest.raises(ValueError, match="未读取引用"):
        validate_topic_analysis_result(result, session)


def test_apply_topic_analysis_keeps_facts_and_adds_conclusion():
    from src.profiles.topic_analysis import TopicAnalysisRun

    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    topic = dimension.topics[0]
    run = TopicAnalysisRun(
        dimension_id=dimension.dimension_id,
        status="completed",
        result={
            "domain_summary": "整体分析",
            "topic_analyses": [
                {
                    "topic_id": topic.topic_id,
                    "conclusion": "企业形成了技术布局。",
                    "key_signals": ["技术方向较集中"],
                    "information_boundaries": ["未披露持续投入"],
                    "fact_refs": [topic.facts[0].item_id],
                    "evidence_refs": [topic.facts[0].evidence[0].evidence_unit_id],
                }
            ],
            "information_boundaries": [],
            "evidence_refs": [topic.facts[0].evidence[0].evidence_unit_id],
        },
    )
    analyzed = apply_topic_analysis(card, run)
    analyzed_topic = next(
        item
        for dimension in analyzed.dimensions
        for item in dimension.topics
        if item.topic_id == topic.topic_id
    )
    assert analyzed_topic.analysis == "企业形成了技术布局。"
    assert len(analyzed_topic.facts) == len(topic.facts)
    assert analyzed_topic.analysis_status == "completed"


def test_topic_analysis_repository_round_trip(tmp_path):
    database = tmp_path / "analysis.db"
    profile = CurrentEnterpriseProfile(
        profile_id="p1",
        case_id="case-analysis",
        enterprise_name="测试企业",
        review_status="approved",
        items=tuple(_item(f"tech-{index}", f"技术{index}", f"e-{index}") for index in range(3)),
    )
    ProfileRepository(database).save(profile)
    repository = ProfileTopicAnalysisRepository(database)
    repository.save(
        profile_id="p1",
        dimension_id="technology_and_ip",
        result={"domain_summary": "结论", "topic_analyses": []},
        status="completed",
        model="deepseek-v4-flash",
        api_meta=[{"total_tokens": 12}],
        react_trace=[{"tool_name": "read_topic"}],
    )
    saved = repository.get("p1", "technology_and_ip")
    assert saved is not None
    assert saved["result"]["domain_summary"] == "结论"
    assert saved["react_trace"][0]["tool_name"] == "read_topic"


def test_controlled_topic_analysis_reads_and_validates_all_topics():
    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")

    def agent_factory(*, model, tools, system_prompt, limits):
        class FakeAgent:
            def invoke(self, state):
                reader = tools[0]
                analyses = []
                evidence_refs = []
                for topic in dimension.topics:
                    start = 0
                    while True:
                        payload = json.loads(
                            reader.invoke({"topic_id": topic.topic_id, "start": start})
                        )
                        evidence_refs.extend(
                            item["evidence_unit_id"] for item in payload["evidence"]
                        )
                        if not payload["has_more"]:
                            break
                        start = payload["next_start"]
                    analyses.append(
                        {
                            "topic_id": topic.topic_id,
                            "conclusion": "基于事实形成的分析。",
                            "key_signals": [],
                            "information_boundaries": [],
                            "fact_refs": [fact.item_id for fact in topic.facts],
                            "evidence_refs": list(
                                dict.fromkeys(
                                    evidence.evidence_unit_id
                                    for fact in topic.facts
                                    for evidence in fact.evidence
                                )
                            ),
                        }
                    )
                result = {
                    "domain_summary": "领域分析",
                    "topic_analyses": analyses,
                    "information_boundaries": [],
                    "evidence_refs": list(dict.fromkeys(evidence_refs)),
                }
                return {"messages": [{"content": json.dumps(result, ensure_ascii=False)}]}

        return FakeAgent()

    workflow = ControlledReactTopicAnalysisWorkflow(
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
    )
    run = workflow.run(
        card=card,
        dimension_id="technology_and_ip",
        config=GenerationConfig(model="deepseek-v4-flash"),
    )
    assert run.status == "completed"
    assert run.read_topic_ids == (dimension.topics[0].topic_id,)


def test_controlled_topic_analysis_uses_json_synthesis_when_agent_reply_is_plain_text():
    card = _card()
    dimension = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")

    def agent_factory(*, model, tools, system_prompt, limits):
        class FakeAgent:
            def invoke(self, state):
                reader = tools[0]
                for topic in dimension.topics:
                    reader.invoke({"topic_id": topic.topic_id, "start": 0})
                return {"messages": [{"content": "分析已完成。"}]}

        return FakeAgent()

    def final_generator(messages, config):
        return {
            "topic_analyses": [
                {
                    "topic_id": topic.topic_id,
                    "conclusion": "基于已读取事实形成的分析。",
                    "key_signals": [],
                    "information_boundaries": [],
                    "fact_refs": [fact.item_id for fact in topic.facts],
                    "evidence_refs": list(
                        dict.fromkeys(
                            evidence.evidence_unit_id
                            for fact in topic.facts
                            for evidence in fact.evidence
                        )
                    ),
                }
                for topic in dimension.topics
            ],
            "information_boundaries": [],
            "evidence_refs": list(
                dict.fromkeys(
                    evidence.evidence_unit_id
                    for topic in dimension.topics
                    for fact in topic.facts
                    for evidence in fact.evidence
                )
            ),
        }

    workflow = ControlledReactTopicAnalysisWorkflow(
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
        final_generator=final_generator,
    )
    run = workflow.run(
        card=card,
        dimension_id="technology_and_ip",
        config=GenerationConfig(model="deepseek-v4-flash"),
    )

    assert run.status == "completed"
    assert run.result["domain_summary"] == "基于已读取事实形成的分析。"
