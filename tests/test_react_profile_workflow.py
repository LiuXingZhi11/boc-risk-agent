from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import patch

from langchain_core.messages import AIMessage

from src.config.settings import Settings
from src.evidence.models import EvidenceUnit
from src.llm.generation_config import GenerationConfig
from src.profiles.extraction import (
    PROFILE_DOMAINS,
    build_relation_repair_messages,
    filter_domain_candidates,
)
from src.profiles.react_models import ReactLimits
from src.profiles.react_tools import build_react_search_keywords, expand_risk_heading_units
from src.profiles.react_workflow import (
    ControlledReactProfileWorkflow,
    REACT_SUPPORTED_DOMAINS,
    build_deepseek_chat_model,
    build_repaired_relations,
    build_recovery_focus,
    build_recovery_requests,
    build_react_agent,
    build_react_system_prompt,
    merge_recovery_candidates,
    normalize_relation_decision_quotes,
    restore_recovery_relation_types,
    select_relation_repair_evidence,
    summarize_relation_repair_decision,
)
from src.profiles.run_review import aggregate_profile_run


def test_react_supports_every_current_profile_domain_one_at_a_time():
    assert REACT_SUPPORTED_DOMAINS == PROFILE_DOMAINS


def test_risk_search_keywords_prioritize_risk_sections_before_event_materials():
    keywords = build_react_search_keywords("risk_matters", "知识产权")

    assert keywords[:5] == (
        "可能面对的风险",
        "风险因素",
        "主要风险",
        "经营风险",
        "技术风险",
    )
    assert keywords.index("诉讼") > keywords.index("知识产权")


def test_risk_heading_is_expanded_to_its_detail_sections():
    heading = EvidenceUnit(
        evidence_unit_id="src:82",
        source_id="src",
        case_id="CASE-1",
        content_type="document_chunk",
        content="(四)可能面对的风险\n√适用 □不适用",
        location={"page": 35},
        metadata={"section_path": ["管理层讨论", "可能面对的风险"]},
        content_hash="82",
    )
    detail = EvidenceUnit(
        evidence_unit_id="src:83",
        source_id="src",
        case_id="CASE-1",
        content_type="document_chunk",
        content="市场竞争可能加剧，并对经营业绩产生不利影响。",
        location={"page": 35},
        metadata={"section_path": ["管理层讨论", "可能面对的风险", "市场竞争风险"]},
        content_hash="83",
    )
    other = EvidenceUnit(
        evidence_unit_id="src:84",
        source_id="src",
        case_id="CASE-1",
        content_type="document_chunk",
        content="重大诉讼事项。",
        location={"page": 70},
        metadata={"section_path": ["重要事项", "诉讼"]},
        content_hash="84",
    )

    class Service:
        def list_evidence(self, *, case_id):
            assert case_id == "CASE-1"
            return [heading, detail, other]

    from src.profiles.react_models import ReactToolSession

    session = ReactToolSession(
        case_id="CASE-1",
        domain="risk_matters",
        evidence_service=Service(),
        limits=ReactLimits(max_catalog_items=10),
    )

    result = expand_risk_heading_units(session, [heading, other])

    assert [unit.evidence_unit_id for unit in result] == ["src:83", "src:84"]


class FakeEvidenceService:
    def __init__(self) -> None:
        self.unit = EvidenceUnit(
            evidence_unit_id="src:eu_00001",
            source_id="src",
            case_id="CASE-1",
            content_type="document_chunk",
            content="公司形成柔性显示核心技术。",
            location={"page": 1},
            metadata={"title": "核心技术", "section_path": ["技术与知识产权"]},
            content_hash="hash-1",
        )

    def search_evidence(self, query: str, *, case_id: str, top_k: int):
        return [self.unit]


def _candidate() -> dict:
    return {
        "item_id": "tech-1",
        "section_id": "technology_ip",
        "field_id": "technology.name",
        "value": "柔性显示技术",
        "value_type": "entity_ref",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": ["src:eu_00001"],
    }


def _extraction_result(*, with_candidate: bool = True) -> dict:
    return {
        "profile_items": [_candidate()] if with_candidate else [],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
        "consistency_warnings": [],
        "rejected_candidates": [] if with_candidate else [{"kind": "profile_items"}],
        "api_meta": {
            "stage": "profile_extraction",
            "model": "fake",
            "total_tokens": 20,
        },
    }


class FakeAgent:
    def __init__(self, tools, *, read: bool) -> None:
        self.tools = {item.name: item for item in tools}
        self.read = read

    def invoke(self, state):
        self.tools["search_evidence"].invoke({"query": "柔性显示"})
        if self.read:
            self.tools["read_evidence"].invoke(
                {"evidence_unit_ids": ["src:eu_00001"]}
            )
        return {
            "messages": [
                AIMessage(
                    content="证据选择完成",
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


def _workflow(*, read: bool = True, extracted: dict | None = None):
    captured = {}

    def agent_factory(**kwargs):
        return FakeAgent(kwargs["tools"], read=read)

    def extractor(evidence_units, **kwargs):
        captured["evidence_units"] = tuple(evidence_units)
        captured.update(kwargs)
        return extracted or _extraction_result()

    workflow = ControlledReactProfileWorkflow(
        FakeEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
        extractor=extractor,
    )
    return workflow, captured


def _config() -> GenerationConfig:
    return GenerationConfig(model="fake", mode="sampling", max_tokens=100)


def test_react_selects_evidence_then_runs_json_extractor_and_aggregates():
    workflow, captured = _workflow()

    result = workflow.run_current_domain(
        case_id="CASE-1",
        domain="technology_and_ip",
        config=_config(),
        guide_text="抽取协议",
    )

    domain = result.domains[0]
    assert domain.status == "pending_review"
    assert domain.selected_evidence_unit_ids == ("src:eu_00001",)
    assert [entry.tool_name for entry in domain.react_trace] == [
        "search_evidence",
        "read_evidence",
    ]
    assert captured["evidence_units"][0].evidence_unit_id == "src:eu_00001"
    assert captured["profile_type"] == "current"
    assert captured["guide_text"] == "抽取协议"
    assert [item["stage"] for item in domain.api_meta] == [
        "react_evidence_discovery",
        "profile_extraction",
    ]
    serialized = json.loads(json.dumps(asdict(result), ensure_ascii=False))
    bundle = aggregate_profile_run(serialized)
    assert (
        bundle["candidates"]["profile_items"][0]["item_id"]
        == "technology_and_ip:tech-1"
    )


def test_react_without_read_evidence_ends_without_running_extractor():
    workflow, captured = _workflow(read=False)

    result = workflow.run_current_domain(
        case_id="CASE-1",
        domain="technology_and_ip",
        config=_config(),
    )

    assert result.domains[0].status == "no_evidence"
    assert result.domains[0].candidates is None
    assert captured == {}


def test_react_json_extractor_can_return_no_valid_candidates():
    workflow, _ = _workflow(extracted=_extraction_result(with_candidate=False))

    result = workflow.run_current_domain(
        case_id="CASE-1",
        domain="technology_and_ip",
        config=_config(),
    )

    assert result.domains[0].status == "no_valid_candidates"
    assert len(result.domains[0].candidates["rejected_candidates"]) == 1


def test_recovery_requests_include_relation_object_and_missing_terms():
    requests = build_recovery_requests(
        {
            "profile_items": [
                {
                    "item_id": "prod-go1",
                    "field_id": "product.name",
                    "value": "Go1",
                },
            ],
            "rejected_candidates": [
                {
                    "kind": "profile_relations",
                    "reason": "证据只表达销售，未表达研发或开发",
                    "candidate": {
                        "relation_id": "rel-go1",
                        "relation_type": "develops",
                        "source_id": "the_enterprise",
                        "target_id": "prod-go1",
                    },
                }
            ],
        }
    )

    assert requests[0]["kind"] == "profile_relations"
    assert requests[0]["field_or_relation"] == "develops"
    assert requests[0]["subject"] == "企业"
    assert requests[0]["object"] == "Go1"
    assert requests[0]["reason"] == "证据只表达销售，未表达研发或开发"
    assert requests[0]["search_terms"] == ["Go1", "自研", "研发", "开发"]
    assert requests[0]["candidate_id"] == "rel-go1"
    assert requests[0]["source_id"] == "the_enterprise"
    assert requests[0]["target_id"] == "prod-go1"
    assert requests[0]["source_type"] == "Enterprise"
    assert requests[0]["target_type"] == "ProductService"
    focus = build_recovery_focus(requests)
    assert "rel-go1" in focus
    assert "prod-go1" in focus
    assert "连续 evidence_quote" in focus


def test_recovery_relation_missing_endpoint_types_is_restored_and_revalidated():
    request = {
        "kind": "profile_relations",
        "field_or_relation": "develops",
        "subject": "企业",
        "object": "Go1",
        "candidate_id": "rel-go1",
        "source_id": "the_enterprise",
        "target_id": "prod-go1",
        "source_type": "Enterprise",
        "target_type": "ProductService",
    }
    recovery = {
        "profile_items": [],
        "profile_relations": [],
        "rejected_candidates": [
            {
                "kind": "profile_relations",
                "candidate_id": "rel-go1",
                "reason": "画像关系候选缺少必要字段。",
                "candidate": {
                    "relation_id": "rel-go1",
                    "relation_type": "develops",
                    "source_id": "the_enterprise",
                    "target_id": "prod-go1",
                    "information_status": "confirmed",
                    "content_role": "business_record",
                    "evidence_unit_ids": ["src:eu_go1"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:eu_go1",
                            "excerpt": "公司自研量产了消费级四足机器人 Go1。",
                        }
                    ],
                },
            }
        ],
    }
    restored = restore_recovery_relation_types(recovery, [request])
    assert restored["profile_relations"][0]["source_type"] == "Enterprise"
    assert restored["profile_relations"][0]["target_type"] == "ProductService"
    assert restored["rejected_candidates"] == []
    restored["rejected_candidates"] = [
        {
            "kind": "profile_relations",
            "candidate_id": "recovery:rel-go1",
            "reason": "销售证据不能证明研发关系。",
            "candidate": {
                "relation_id": "recovery:rel-go1",
                "relation_type": "develops",
                "source_id": "the_enterprise",
                "target_id": "recovery:prod-go1",
            },
        }
    ]
    restored["profile_relations"].insert(
        0,
        {
            "relation_id": "rel-go1",
            "relation_type": "develops",
            "source_id": "the_enterprise",
            "source_type": "Enterprise",
            "target_id": "prod-go1",
            "target_type": "ProductService",
            "information_status": "confirmed",
            "content_role": "business_record",
            "evidence_unit_ids": ["src:eu_first"],
            "evidence_quotes": [
                {
                    "evidence_unit_id": "src:eu_first",
                    "excerpt": "2021年 Go1 进入大众市场。",
                }
            ],
        },
    )

    first = {
        "profile_items": [
            {
                "item_id": "prod-go1",
                "subject": "the_enterprise",
                "section_id": "product_research_commercialization",
                "field_id": "product.name",
                "value": "Go1",
                "value_type": "entity_ref",
                "information_status": "confirmed",
                "content_role": "business_record",
                "evidence_unit_ids": ["src:eu_first"],
                "evidence_quotes": [
                    {"evidence_unit_id": "src:eu_first", "excerpt": "Go1"}
                ],
            }
        ],
        "profile_relations": [],
        "rejected_candidates": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    merged = merge_recovery_candidates(
        first,
        restored,
        evidence_unit_ids=("src:eu_first", "src:eu_go1"),
        evidence_contents={
            "src:eu_first": "2021年 Go1 进入大众市场。",
            "src:eu_go1": "公司自研量产了消费级四足机器人 Go1。",
        },
        domain="product_and_project",
    )
    assert [item["target_id"] for item in merged["profile_relations"]] == ["prod-go1"]
    assert merged["rejected_candidates"] == []


def test_relation_repair_prompt_is_narrow_and_preserves_relation_ids():
    messages = build_relation_repair_messages(
        [
            EvidenceUnit(
                evidence_unit_id="src:eu_go1",
                source_id="src",
                case_id="CASE-RECOVERY",
                content_type="document_chunk",
                content="公司自研量产了消费级四足机器人 Go1。",
                location={"page": 97},
                metadata={"title": "四足机器人"},
                content_hash="go1",
            )
        ],
        requests=[
            {
                "kind": "profile_relations",
                "candidate_id": "rel-go1",
                "field_or_relation": "develops",
                "source_id": "the_enterprise",
                "source_type": "Enterprise",
                "target_id": "prod-go1",
                "target_type": "ProductService",
                "subject": "企业",
                "object": "Go1",
            }
        ],
        domain="product_and_project",
    )
    assert len(messages) == 2
    assert "rel-go1" in messages[1]["content"]
    assert "只处理给定请求中的关系" in messages[0]["content"]
    assert "profile_items" in messages[0]["content"]
    assert "relation_decisions" in messages[0]["content"]
    assert "profile_relations" in messages[0]["content"]
    assert "语法作用范围" in messages[0]["content"]
    assert "研发量产多款产品" not in messages[0]["content"]
    assert "销售、价格或面市" not in messages[0]["content"]
    assert "自研量产了消费级四足机器人 Go1" in messages[1]["content"]


def test_relation_decision_reuses_original_relation_structure():
    relations = build_repaired_relations(
        [
            {
                "candidate_id": "rel-go1",
                "supported": True,
                "evidence_unit_ids": ["src:eu_go1"],
                "evidence_quotes": [
                    {
                        "evidence_unit_id": "src:eu_go1",
                        "excerpt": "公司自研量产了消费级四足机器人 Go1。",
                    }
                ],
            }
        ],
        [
            {
                "kind": "profile_relations",
                "candidate_id": "rel-go1",
                "field_or_relation": "develops",
                "source_id": "the_enterprise",
                "source_type": "Enterprise",
                "target_id": "prod-go1",
                "target_type": "ProductService",
                "information_status": "confirmed",
                "content_role": "business_record",
            }
        ],
    )
    assert relations[0]["relation_id"] == "rel-go1"
    assert relations[0]["target_id"] == "prod-go1"
    assert relations[0]["target_type"] == "ProductService"
    assert relations[0]["evidence_unit_ids"] == ["src:eu_go1"]
    assert relations[0]["_relation_scope_verified"] is True


def test_single_evidence_relation_decision_wraps_string_quotes():
    decision = {
        "evidence_unit_ids": ["src:eu_go1"],
        "evidence_quotes": ["公司研发量产了多款机器人，如消费级四足机器人 Go1。"],
    }
    assert normalize_relation_decision_quotes(decision) == [
        {
            "evidence_unit_id": "src:eu_go1",
            "excerpt": "公司研发量产了多款机器人，如消费级四足机器人 Go1。",
        }
    ]


def test_multiple_evidence_relation_decision_keeps_ambiguous_string_quotes():
    quotes = ["第一段摘录", "第二段摘录"]
    decision = {
        "evidence_unit_ids": ["src:eu_1", "src:eu_2"],
        "evidence_quotes": quotes,
    }
    assert normalize_relation_decision_quotes(decision) == quotes


def test_relation_repair_selects_only_recovery_evidence_with_target_name():
    sales = EvidenceUnit(
        evidence_unit_id="src:eu_sales",
        source_id="src",
        case_id="CASE-RECOVERY",
        content_type="document_chunk",
        content="2021 年该产品进入大众消费市场。",
        location={"page": 103},
        metadata={"title": "市场开拓期"},
        content_hash="sales",
    )
    research = EvidenceUnit(
        evidence_unit_id="src:eu_go1",
        source_id="src",
        case_id="CASE-RECOVERY",
        content_type="document_chunk",
        content="公司研发量产了多款机器人，如消费级四足机器人 Go1。",
        location={"page": 97},
        metadata={"title": "四足机器人"},
        content_hash="go1",
    )
    selected = select_relation_repair_evidence(
        [sales, research],
        {"object": "Go1"},
    )
    assert [unit.evidence_unit_id for unit in selected] == ["src:eu_go1"]


def test_relation_repair_summary_distinguishes_model_and_filter_results():
    request = {"candidate_id": "rel-go1"}
    unsupported = summarize_relation_repair_decision(
        [{"candidate_id": "rel-go1", "supported": False, "evidence_unit_ids": []}],
        request,
        {"profile_relations": [], "rejected_candidates": []},
    )
    rejected = summarize_relation_repair_decision(
        [
            {
                "candidate_id": "rel-go1",
                "supported": True,
                "evidence_unit_ids": ["src:eu_go1"],
            }
        ],
        request,
        {
            "profile_relations": [],
            "rejected_candidates": [
                {"candidate_id": "rel-go1", "reason": "摘录不是连续原文。"}
            ],
        },
    )
    accepted = summarize_relation_repair_decision(
        [{"candidate_id": "rel-go1", "supported": True, "evidence_unit_ids": ["src:eu_go1"]}],
        request,
        {
            "profile_relations": [{"relation_id": "rel-go1"}],
            "rejected_candidates": [],
        },
    )
    assert unsupported["result"] == "model_unsupported"
    assert rejected["result"] == "filter_rejected"
    assert rejected["filter_reason"] == "摘录不是连续原文。"
    assert accepted["result"] == "accepted"


def test_develops_relation_requires_same_clause_until_model_scope_is_verified():
    base_item = {
        "item_id": "prod-go1",
        "subject": "Go1",
        "section_id": "product_research_commercialization",
        "field_id": "product.name",
        "value": "Go1",
        "value_type": "entity_ref",
        "information_status": "confirmed",
        "content_role": "business_record",
        "evidence_unit_ids": ["src:eu_product"],
        "evidence_quotes": [
            {"evidence_unit_id": "src:eu_product", "excerpt": "Go1"}
        ],
    }
    relation = {
        "relation_id": "rel-go1",
        "relation_type": "develops",
        "source_id": "the_enterprise",
        "source_type": "Enterprise",
        "target_id": "prod-go1",
        "target_type": "ProductService",
        "information_status": "confirmed",
        "content_role": "business_record",
        "evidence_unit_ids": ["src:eu_product"],
    }
    mixed = filter_domain_candidates(
        {
            "profile_items": [base_item],
            "profile_relations": [
                {
                    **relation,
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:eu_product",
                            "excerpt": (
                                "2020 年公司自研量产新一代四足机器人 A1，"
                                "2021 年 Go1 以 1.6 万元零售定价进入大众消费市场。"
                            ),
                        }
                    ],
                }
            ],
        },
        evidence_unit_ids=["src:eu_product"],
        domain="product_and_project",
        profile_type="current",
        evidence_contents={
            "src:eu_product": (
                "2020 年公司自研量产新一代四足机器人 A1，"
                "2021 年 Go1 以 1.6 万元零售定价进入大众消费市场。"
            )
        },
    )
    assert mixed["profile_relations"] == []
    assert any(
        "未直接支持目标对象" in rejection["reason"]
        for rejection in mixed["rejected_candidates"]
    )

    list_sentence = filter_domain_candidates(
        {
            "profile_items": [base_item],
            "profile_relations": [
                {
                    **relation,
                    "_relation_scope_verified": True,
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:eu_product",
                            "excerpt": (
                                "公司自 2017 年以来先后研发量产了多款四足机器人，"
                                "如 2021 年第一代消费级四足机器人 Go1。"
                            ),
                        }
                    ],
                }
            ],
        },
        evidence_unit_ids=["src:eu_product"],
        domain="product_and_project",
        profile_type="current",
        evidence_contents={
            "src:eu_product": (
                "公司自 2017 年以来先后研发量产了多款四足机器人，"
                "如 2021 年第一代消费级四足机器人 Go1。"
            )
        },
    )
    assert [item["target_id"] for item in list_sentence["profile_relations"]] == [
        "prod-go1"
    ]


class RecoveryEvidenceService:
    def __init__(self) -> None:
        self.first = EvidenceUnit(
            evidence_unit_id="src:eu_first",
            source_id="src",
            case_id="CASE-RECOVERY",
            content_type="document_chunk",
            content="2021年 Go1 进入大众市场。",
            location={"page": 103},
            metadata={"title": "市场开拓期", "section_path": ["市场演变"]},
            content_hash="first",
        )
        self.go1 = EvidenceUnit(
            evidence_unit_id="src:eu_go1",
            source_id="src",
            case_id="CASE-RECOVERY",
            content_type="document_chunk",
            content="公司自研量产了消费级四足机器人 Go1。",
            location={"page": 97},
            metadata={"title": "四足机器人", "section_path": ["主要产品"]},
            content_hash="go1",
        )

    def search_evidence(self, query: str, *, case_id: str, top_k: int):
        if "研发量产" in query or "自研" in query:
            return [self.go1, self.first]
        return [self.first]


class RecoveryAgent:
    def __init__(self, tools, *, recovery: bool) -> None:
        self.tools = {item.name: item for item in tools}
        self.recovery = recovery

    def invoke(self, state):
        if self.recovery:
            self.tools["search_evidence"].invoke({"query": "Go1 研发量产 自研 开发"})
            self.tools["read_evidence"].invoke(
                {"evidence_unit_ids": ["src:eu_go1", "src:eu_first"]}
            )
        else:
            self.tools["search_evidence"].invoke({"query": "Go1 销售"})
            self.tools["read_evidence"].invoke({"evidence_unit_ids": ["src:eu_first"]})
        return {
            "messages": [
                AIMessage(
                    content="证据选择完成",
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    response_metadata={"model_name": "fake", "finish_reason": "stop"},
                )
            ]
        }


def test_react_recovery_reads_new_chunk_and_recovers_relation():
    extraction_calls: list[tuple[tuple[str, ...], str]] = []

    def extractor(evidence_units, **kwargs):
        ids = tuple(unit.evidence_unit_id for unit in evidence_units)
        extraction_calls.append((ids, kwargs.get("focus_instructions", "")))
        if len(extraction_calls) == 1:
            return {
                "profile_items": [
                    {
                        "item_id": "prod-go1",
                        "subject": "the_enterprise",
                        "section_id": "product_research_commercialization",
                        "field_id": "product.name",
                        "value": "Go1",
                        "value_type": "entity_ref",
                        "information_status": "confirmed",
                        "content_role": "business_record",
                        "evidence_unit_ids": ["src:eu_first"],
                        "evidence_quotes": [{"evidence_unit_id": "src:eu_first", "excerpt": "Go1"}],
                    }
                ],
                "profile_relations": [],
                "information_gaps": [],
                "conflicts": [],
                "unmapped_items": [],
                "rejected_candidates": [
                    {
                        "kind": "profile_relations",
                        "candidate_id": "rel-go1",
                        "reason": "证据只表达销售，未表达研发或开发",
                        "candidate": {
                            "relation_id": "rel-go1",
                            "relation_type": "develops",
                            "source_id": "the_enterprise",
                            "target_id": "prod-go1",
                            "information_status": "confirmed",
                            "content_role": "business_record",
                            "evidence_unit_ids": ["src:eu_first"],
                            "evidence_quotes": [{"evidence_unit_id": "src:eu_first", "excerpt": "Go1"}],
                        },
                    }
                ],
                "api_meta": {"stage": "profile_extraction", "total_tokens": 20},
            }
        assert "实际作用范围" in kwargs["focus_instructions"]
        return {
            "profile_items": [],
            "profile_relations": [],
            "information_gaps": [],
            "conflicts": [],
            "unmapped_items": [],
            "rejected_candidates": [],
            "api_meta": {"stage": "profile_extraction", "total_tokens": 20},
        }

    def agent_factory(**kwargs):
        return RecoveryAgent(kwargs["tools"], recovery="失败画像候选" in kwargs["system_prompt"])

    workflow = ControlledReactProfileWorkflow(
        RecoveryEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
        extractor=extractor,
    )
    with patch(
        "src.profiles.react_workflow.call_deepseek",
        return_value={
            "relation_decisions": [
                {
                    "candidate_id": "rel-go1",
                    "supported": True,
                    "evidence_unit_ids": ["src:eu_go1"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:eu_go1",
                            "excerpt": "公司自研量产了消费级四足机器人 Go1。",
                        }
                    ],
                }
            ],
            "api_meta": {"model": "fake", "total_tokens": 12},
        },
    ) as repair_call:
        result = workflow.run_current_domain(
            case_id="CASE-RECOVERY",
            domain="product_and_project",
            config=_config(),
            limits=ReactLimits(max_recovery_rounds=1),
        )

    domain = result.domains[0]
    assert [item["relation_type"] for item in domain.candidates["profile_relations"]] == ["develops"]
    assert domain.candidates["rejected_candidates"] == []
    assert "src:eu_go1" in domain.selected_evidence_unit_ids
    assert extraction_calls[1][1]
    assert any(entry.input_summary.get("phase") == "react_evidence_recovery" for entry in domain.react_trace)
    assert repair_call.call_count == 1
    repair_messages = repair_call.call_args.args[0]
    assert "src:eu_go1" in repair_messages[1]["content"]
    assert "src:eu_first" not in repair_messages[1]["content"]
    repair_meta = next(
        item for item in domain.api_meta if item.get("stage") == "profile_relation_repair"
    )
    assert repair_meta["relation_decision"] == {
        "candidate_id": "rel-go1",
        "supported": True,
        "evidence_unit_ids": ["src:eu_go1"],
        "result": "accepted",
        "filter_reason": "",
    }
    assert all(
        "_relation_scope_verified" not in relation
        for relation in domain.candidates["profile_relations"]
    )


def test_react_recovery_respects_total_read_unit_budget():
    extractor_calls: list[tuple[str, ...]] = []

    def extractor(evidence_units, **kwargs):
        extractor_calls.append(tuple(unit.evidence_unit_id for unit in evidence_units))
        return {
            "profile_items": [],
            "profile_relations": [],
            "information_gaps": [],
            "conflicts": [],
            "unmapped_items": [],
            "rejected_candidates": [
                {
                    "kind": "profile_items",
                    "candidate_id": "missing-product",
                    "reason": "需要补充产品证据。",
                    "candidate": {
                        "item_id": "missing-product",
                        "field_id": "product.name",
                        "value": "Go1",
                    },
                }
            ],
        }

    agent_factory_calls = 0

    def agent_factory(**kwargs):
        nonlocal agent_factory_calls
        agent_factory_calls += 1
        return RecoveryAgent(
            kwargs["tools"],
            recovery="失败画像候选" in kwargs["system_prompt"],
        )

    workflow = ControlledReactProfileWorkflow(
        RecoveryEvidenceService(),
        model_factory=lambda config: object(),
        agent_factory=agent_factory,
        extractor=extractor,
    )

    result = workflow.run_current_domain(
        case_id="CASE-RECOVERY",
        domain="product_and_project",
        config=_config(),
        limits=ReactLimits(
            max_read_units=1,
            max_total_read_units=1,
        ),
    )

    domain = result.domains[0]
    assert domain.selected_evidence_unit_ids == ("src:eu_first",)
    assert extractor_calls == [("src:eu_first",)]
    assert agent_factory_calls == 1


def test_build_react_agent_has_two_tools_and_run_limits_without_response_format():
    limits = ReactLimits()
    tools = [object(), object()]
    with patch("src.profiles.react_workflow.create_agent", return_value="agent") as mocked:
        result = build_react_agent(
            model=object(), tools=tools, system_prompt="prompt", limits=limits
        )

    assert result == "agent"
    kwargs = mocked.call_args.kwargs
    assert kwargs["tools"] == tools
    assert "response_format" not in kwargs
    assert "checkpointer" not in kwargs
    assert len(kwargs["middleware"]) == 3
    assert kwargs["middleware"][0].run_limit == limits.max_model_calls
    assert [item.tool_name for item in kwargs["middleware"][1:]] == [
        "search_evidence",
        "read_evidence",
    ]


def test_react_prompt_only_requests_evidence_selection():
    prompt = build_react_system_prompt(
        case_id="CASE-1",
        domain="technology_and_ip",
        query="专利权属",
        limits=ReactLimits(),
    )

    assert "累计正文 8 条" in prompt
    assert "专利权属" in prompt
    assert "证据选择完成" in prompt
    assert "不要生成画像" in prompt
    assert "technology.name" not in prompt


def test_build_deepseek_chat_model_preserves_generation_modes():
    settings = Settings(
        api_key="test-key",
        base_url="https://example.invalid",
        model="ignored",
    )
    with patch("src.profiles.react_workflow.get_settings", return_value=settings):
        thinking = build_deepseek_chat_model(
            GenerationConfig(
                model="deepseek-v4-pro",
                mode="thinking",
                max_tokens=100,
            )
        )
        sampling = build_deepseek_chat_model(
            GenerationConfig(
                model="deepseek-chat",
                mode="sampling",
                temperature=0.3,
                max_tokens=100,
            )
        )

    assert thinking.model_name == "deepseek-v4-pro"
    assert thinking.temperature is None
    assert thinking.reasoning_effort == "high"
    assert thinking.extra_body == {"thinking": {"type": "enabled"}}
    assert thinking.request_timeout == 180
    assert sampling.model_name == "deepseek-chat"
    assert sampling.temperature == 0.3
    assert sampling.reasoning_effort is None
    assert sampling.extra_body == {"thinking": {"type": "disabled"}}
    assert sampling.request_timeout == 180
