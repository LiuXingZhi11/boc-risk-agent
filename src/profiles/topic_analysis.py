"""企业画像主题分析层。

事实抽取完成后，本模块把已审核的画像事实组织为主题事实包，
通过受控 ReAct 让模型按主题读取事实，再生成可回溯的画像分析。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig
from src.prompts import render_prompt_section
from src.profiles.visual_card import CardDimension, CardFact, CardTopic, EnterpriseVisualCard
from src.utils.json_utils import extract_json_from_text


@dataclass(frozen=True)
class TopicAnalysisLimits:
    """分析层的单领域调用和读取上限。"""

    max_model_calls: int = 6
    max_topic_reads: int = 12
    max_facts_per_read: int = 30
    max_evidence_chars: int = 800


@dataclass(frozen=True)
class TopicAnalysisTrace:
    tool_name: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]


@dataclass
class TopicAnalysisSession:
    dimension: CardDimension
    limits: TopicAnalysisLimits
    read_facts: dict[str, CardFact] = field(default_factory=dict)
    read_topic_ids: list[str] = field(default_factory=list)
    trace: list[TopicAnalysisTrace] = field(default_factory=list)


@dataclass(frozen=True)
class TopicAnalysisRun:
    dimension_id: str
    status: str
    result: dict[str, Any] | None = None
    read_topic_ids: tuple[str, ...] = ()
    react_trace: tuple[TopicAnalysisTrace, ...] = ()
    api_meta: tuple[dict[str, Any], ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_topic_catalog(dimension: CardDimension) -> list[dict[str, Any]]:
    """只返回主题目录，供分析 Agent 决定读取顺序。"""
    return [
        {
            "topic_id": topic.topic_id,
            "title": topic.title,
            "summary": topic.summary,
            "fact_count": len(topic.facts),
            "record_count": len(topic.records),
        }
        for topic in dimension.topics
    ]


def build_topic_fact_payload(
    topic: CardTopic,
    *,
    start: int = 0,
    limit: int | None = None,
    max_evidence_chars: int = 800,
) -> dict[str, Any]:
    """构造一个主题的结构化事实包；分页只按事实切分，不丢弃事实。"""
    facts = topic.facts[start:] if limit is None else topic.facts[start : start + limit]
    evidence: dict[str, dict[str, Any]] = {}
    fact_payload: list[dict[str, Any]] = []
    for fact in facts:
        evidence_refs = []
        for ref in fact.evidence:
            evidence_refs.append(ref.evidence_unit_id)
            evidence.setdefault(
                ref.evidence_unit_id,
                {
                    "evidence_unit_id": ref.evidence_unit_id,
                    "source_title": ref.source_title,
                    "location": ref.location,
                    "excerpt": ref.excerpt[:max_evidence_chars]
                    if ref.excerpt
                    else "",
                },
            )
        fact_payload.append(
            {
                "fact_id": fact.item_id,
                "field_id": fact.field_id,
                "field": fact.field_label,
                "value": fact.value,
                "subject": fact.subject,
                "reporting_period": fact.reporting_period,
                "value_scope": fact.value_scope,
                "role": fact.role,
                "status": fact.status,
                "context": fact.context,
                "evidence_refs": evidence_refs,
            }
        )
    next_start = start + len(facts)
    return {
        "topic_id": topic.topic_id,
        "title": topic.title,
        "summary": topic.summary,
        "records": list(topic.records),
        "facts": fact_payload,
        "evidence": list(evidence.values()),
        "start": start,
        "next_start": next_start,
        "has_more": next_start < len(topic.facts),
        "total_fact_count": len(topic.facts),
    }


def build_domain_analysis_packet(card: EnterpriseVisualCard, dimension_id: str) -> dict[str, Any]:
    """构造完整的领域分析包，保留全部已归并事实。"""
    dimension = _find_dimension(card, dimension_id)
    return {
        "case_id": card.case_id,
        "enterprise_name": card.enterprise_name,
        "dimension_id": dimension.dimension_id,
        "dimension": dimension.label,
        "topic_catalog": build_topic_catalog(dimension),
        "topics": [build_topic_fact_payload(topic) for topic in dimension.topics],
    }


def build_topic_analysis_system_prompt(
    *,
    enterprise_name: str,
    dimension: CardDimension,
    limits: TopicAnalysisLimits,
) -> str:
    catalog = json.dumps(build_topic_catalog(dimension), ensure_ascii=False, indent=2)
    business_rules = render_prompt_section(
        "logic/企业画像逻辑规则.md",
        "主题分析",
        {
            "enterprise_name": enterprise_name,
            "dimension_label": dimension.label,
            "max_model_calls": limits.max_model_calls,
            "max_topic_reads": limits.max_topic_reads,
            "max_facts_per_read": limits.max_facts_per_read,
        },
    )
    return (
        f"{business_rules}\n\n"
        f"运行时主题目录：\n{catalog}\n\n"
        f"企业：{enterprise_name}\n领域：{dimension.label}\n"
        f"模型调用上限：{limits.max_model_calls}；主题读取上限：{limits.max_topic_reads}；"
        f"每次最多读取事实：{limits.max_facts_per_read}。"
    ).strip()


def build_topic_analysis_final_messages(
    *,
    card: EnterpriseVisualCard,
    dimension: CardDimension,
    limits: TopicAnalysisLimits,
) -> list[dict[str, str]]:
    """为 ReAct 读取结果构造独立的 JSON 合成请求。"""
    system = build_topic_analysis_system_prompt(
        enterprise_name=card.enterprise_name,
        dimension=dimension,
        limits=limits,
    )
    packet = build_domain_analysis_packet(card, dimension.dimension_id)
    user = (
        "ReAct 已完成本领域全部主题的事实读取。请根据下方完整主题事实包生成最终主题分析。"
        "只输出合法 JSON 对象，不要输出说明文字、Markdown 或代码块；不得补充事实。\n\n"
        f"完整主题事实包：\n{json.dumps(packet, ensure_ascii=False, indent=2)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _coerce_topic_analysis_list(value: Any) -> list[Any] | None:
    if isinstance(value, list):
        normalized: list[Any] = []
        for item in value:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            item = dict(item)
            if "topic_id" not in item:
                for key in ("id", "topic", "主题编号", "主题ID"):
                    if item.get(key):
                        item["topic_id"] = item[key]
                        break
            normalized.append(item)
        return normalized
    if isinstance(value, str):
        try:
            return _coerce_topic_analysis_list(json.loads(value))
        except (TypeError, json.JSONDecodeError):
            return None
    if not isinstance(value, dict):
        return None
    if "topic_id" in value:
        return [value]
    for key in (
        "topic_analyses",
        "topic_analysis",
        "analyses",
        "topics",
        "topic_results",
        "主题分析",
        "主题分析结果",
        "主题结论",
    ):
        if key in value:
            nested = _coerce_topic_analysis_list(value[key])
            if nested is not None:
                return nested
    items = []
    for topic_id, analysis in value.items():
        if isinstance(analysis, dict):
            item = dict(analysis)
            item.setdefault("topic_id", topic_id)
            items.append(item)
        elif isinstance(analysis, str) and analysis.strip():
            items.append({"topic_id": topic_id, "conclusion": analysis.strip()})
    return items or None


_DOMAIN_SUMMARY_KEYS = (
    "domain_summary",
    "overall_summary",
    "overall_conclusion",
    "domain_conclusion",
    "overall_assessment",
    "summary",
    "analysis",
    "judgment",
    "conclusion",
    "领域摘要",
    "领域总结",
    "领域结论",
    "总体结论",
    "整体结论",
    "整体分析",
    "本领域结论",
    "总体摘要",
    "整体摘要",
)
_TOPIC_CONCLUSION_KEYS = (
    "conclusion",
    "topic_conclusion",
    "topic_summary",
    "summary",
    "analysis",
    "judgment",
    "主题结论",
    "主题摘要",
    "分析结论",
    "结论",
    "总结",
)
_SIGNAL_KEYS = ("key_signals", "signals", "key_points", "关键特征", "关键信号")


def _first_nonempty_text(mapping: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _text_values(mapping: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            values.extend(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
    return list(dict.fromkeys(values))


def normalize_topic_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    """统一模型的等价字段，并只从已返回内容补齐领域摘要。"""
    normalized = dict(result)
    analyses = _coerce_topic_analysis_list(normalized.get("topic_analyses"))
    if analyses is None:
        for key in (
            "topic_analysis",
            "analyses",
            "topics",
            "topic_results",
            "主题分析",
            "主题分析结果",
            "主题结论",
        ):
            analyses = _coerce_topic_analysis_list(normalized.get(key))
            if analyses is not None:
                break
    if analyses is not None:
        normalized["topic_analyses"] = analyses
    if isinstance(normalized.get("topic_analyses"), list):
        normalized["topic_analyses"] = [
            (
                {
                    **analysis,
                    "conclusion": (
                        _first_nonempty_text(analysis, _TOPIC_CONCLUSION_KEYS)
                        or "；".join(_text_values(analysis, _SIGNAL_KEYS)[:3])
                    ),
                }
                if isinstance(analysis, dict)
                else analysis
            )
            for analysis in normalized["topic_analyses"]
        ]
    summary = _first_nonempty_text(normalized, _DOMAIN_SUMMARY_KEYS)
    if not summary:
        conclusions = [
            analysis.get("conclusion", "").strip()
            for analysis in normalized.get("topic_analyses", [])
            if isinstance(analysis, dict)
            and isinstance(analysis.get("conclusion"), str)
            and analysis.get("conclusion", "").strip()
        ]
        summary = "；".join(dict.fromkeys(conclusions))
    if not summary:
        summary = "；".join(_text_values(normalized, _SIGNAL_KEYS)[:3])
    if not summary:
        summary = "基于当前已读取事实，暂未形成可归纳的本领域结论，需补充或核实相关信息。"
    normalized["domain_summary"] = summary
    return normalized


def create_topic_analysis_tools(session: TopicAnalysisSession) -> list[BaseTool]:
    """创建只读主题事实工具。"""

    topic_map = {topic.topic_id: topic for topic in session.dimension.topics}

    @tool
    def read_topic(topic_id: str, start: int = 0) -> str:
        """读取一个画像主题的结构化事实；事实较多时用 start 读取下一页。"""
        if session.limits.max_topic_reads <= len(session.trace):
            return json.dumps({"error": "topic_read_limit_reached"}, ensure_ascii=False)
        topic = topic_map.get(topic_id)
        if topic is None:
            return json.dumps({"error": "unknown_topic", "topic_id": topic_id}, ensure_ascii=False)
        payload = build_topic_fact_payload(
            topic,
            start=max(start, 0),
            limit=session.limits.max_facts_per_read,
            max_evidence_chars=session.limits.max_evidence_chars,
        )
        for fact in topic.facts[payload["start"] : payload["next_start"]]:
            session.read_facts[fact.item_id] = fact
        if topic_id not in session.read_topic_ids:
            session.read_topic_ids.append(topic_id)
        session.trace.append(
            TopicAnalysisTrace(
                tool_name="read_topic",
                input_summary={"topic_id": topic_id, "start": start},
                output_summary={
                    "fact_count": len(payload["facts"]),
                    "has_more": payload["has_more"],
                    "evidence_count": len(payload["evidence"]),
                },
            )
        )
        return json.dumps(payload, ensure_ascii=False)

    return [read_topic]


def build_topic_analysis_agent(
    *,
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    limits: TopicAnalysisLimits,
) -> Any:
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[
            ModelCallLimitMiddleware(
                run_limit=limits.max_model_calls,
                exit_behavior="end",
            ),
            ToolCallLimitMiddleware(
                tool_name="read_topic",
                run_limit=limits.max_topic_reads,
                exit_behavior="continue",
            ),
        ],
    )


class ControlledReactTopicAnalysisWorkflow:
    """单领域企业画像分析；输入是主题事实，不重新检索原始 PDF。"""

    def __init__(
        self,
        *,
        model_factory: Callable[[GenerationConfig], BaseChatModel],
        agent_factory: Callable[..., Any] = build_topic_analysis_agent,
        final_generator: Callable[[list[dict[str, str]], GenerationConfig], dict[str, Any]] = call_deepseek,
    ) -> None:
        self.model_factory = model_factory
        self.agent_factory = agent_factory
        self.final_generator = final_generator

    def run(
        self,
        *,
        card: EnterpriseVisualCard,
        dimension_id: str,
        config: GenerationConfig,
        limits: TopicAnalysisLimits = TopicAnalysisLimits(),
    ) -> TopicAnalysisRun:
        dimension = _find_dimension(card, dimension_id)
        session = TopicAnalysisSession(dimension=dimension, limits=limits)
        agent = self.agent_factory(
            model=self.model_factory(config),
            tools=create_topic_analysis_tools(session),
            system_prompt=build_topic_analysis_system_prompt(
                enterprise_name=card.enterprise_name,
                dimension=dimension,
                limits=limits,
            ),
            limits=limits,
        )
        state: dict[str, Any] = {}
        try:
            state = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": f"请分析企业画像领域：{dimension.label}。",
                        }
                    ]
                }
            )
        except Exception as exc:
            if set(session.read_topic_ids) != {topic.topic_id for topic in dimension.topics}:
                return TopicAnalysisRun(
                    dimension_id=dimension_id,
                    status="failed",
                    read_topic_ids=tuple(session.read_topic_ids),
                    react_trace=tuple(session.trace),
                    error=f"{type(exc).__name__}: {exc}",
                )

        result: dict[str, Any] | None = None
        api_meta: tuple[dict[str, Any], ...] = ()
        try:
            if state:
                result = normalize_topic_analysis_result(_parse_agent_result(state))
                validate_topic_analysis_result(result, session)
                api_meta = tuple(_collect_api_meta(state))
        except Exception:
            result = None

        if result is None:
            try:
                if set(session.read_topic_ids) != {topic.topic_id for topic in dimension.topics}:
                    raise ValueError("ReAct 未读取当前领域的全部主题，无法进行 JSON 合成。")
                final_raw = self.final_generator(
                    build_topic_analysis_final_messages(
                        card=card,
                        dimension=dimension,
                        limits=limits,
                    ),
                    config,
                )
                final_raw = normalize_topic_analysis_result(dict(final_raw))
                meta = final_raw.pop("api_meta", None)
                if isinstance(meta, dict):
                    api_meta = (meta,)
                validate_topic_analysis_result(final_raw, session)
                result = final_raw
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                return TopicAnalysisRun(
                    dimension_id=dimension_id,
                    status="failed",
                    read_topic_ids=tuple(session.read_topic_ids),
                    react_trace=tuple(session.trace),
                    error=error,
                )

        if result is None:
            return TopicAnalysisRun(
                dimension_id=dimension_id,
                status="failed",
                read_topic_ids=tuple(session.read_topic_ids),
                react_trace=tuple(session.trace),
                error="主题分析未生成结果。",
            )
        return TopicAnalysisRun(
            dimension_id=dimension_id,
            status="completed",
            result=result,
            read_topic_ids=tuple(session.read_topic_ids),
            react_trace=tuple(session.trace),
            api_meta=api_meta,
        )


def validate_topic_analysis_result(
    result: dict[str, Any],
    session: TopicAnalysisSession,
) -> None:
    """校验模型没有引用未读取的主题、事实或证据。"""
    if not isinstance(result.get("domain_summary"), str) or not result["domain_summary"].strip():
        raise ValueError("domain_summary 不能为空。")
    allowed_fact_ids = set(session.read_facts)
    allowed_evidence_ids = {
        evidence.evidence_unit_id
        for fact in session.read_facts.values()
        for evidence in fact.evidence
    }
    allowed_topic_ids = {topic.topic_id for topic in session.dimension.topics}
    fact_ids_by_topic = {
        topic.topic_id: {fact.item_id for fact in topic.facts}
        for topic in session.dimension.topics
    }
    if set(session.read_topic_ids) != allowed_topic_ids:
        missing_topics = sorted(allowed_topic_ids - set(session.read_topic_ids))
        raise ValueError(f"领域主题尚未全部读取：{missing_topics}")
    expected_fact_ids = {
        fact.item_id
        for topic in session.dimension.topics
        for fact in topic.facts
    }
    if allowed_fact_ids != expected_fact_ids:
        missing_facts = sorted(expected_fact_ids - allowed_fact_ids)
        raise ValueError(f"领域事实尚未全部读取：{missing_facts[:10]}")
    analyses = result.get("topic_analyses")
    if not isinstance(analyses, list):
        raise ValueError("topic_analyses 必须是数组。")
    analyzed_topic_ids = {
        analysis.get("topic_id")
        for analysis in analyses
        if isinstance(analysis, dict)
    }
    if analyzed_topic_ids != allowed_topic_ids:
        raise ValueError("topic_analyses 必须覆盖当前领域的全部主题。")
    for analysis in analyses:
        if not isinstance(analysis, dict):
            raise ValueError("主题分析必须是对象。")
        topic_id = analysis.get("topic_id")
        if topic_id not in allowed_topic_ids or topic_id not in session.read_topic_ids:
            raise ValueError(f"主题未读取或编号非法：{topic_id!r}")
        fact_refs = analysis.get("fact_refs", [])
        if not isinstance(fact_refs, list) or any(ref not in allowed_fact_ids for ref in fact_refs):
            raise ValueError(f"{topic_id} 的 fact_refs 含有未读取引用。")
        if any(ref not in fact_ids_by_topic[topic_id] for ref in fact_refs):
            raise ValueError(f"{topic_id} 的 fact_refs 必须来自该主题事实。")
        evidence_refs = analysis.get("evidence_refs", [])
        if not isinstance(evidence_refs, list) or any(
            ref not in allowed_evidence_ids for ref in evidence_refs
        ):
            raise ValueError(f"{topic_id} 的 evidence_refs 含有未读取引用。")
    top_refs = result.get("evidence_refs", [])
    if not isinstance(top_refs, list) or any(ref not in allowed_evidence_ids for ref in top_refs):
        raise ValueError("领域 evidence_refs 含有未读取引用。")


def apply_topic_analysis(
    card: EnterpriseVisualCard,
    run: TopicAnalysisRun,
) -> EnterpriseVisualCard:
    """把已校验的分析结果叠加到阅读卡；不改变底层事实。"""
    if run.status != "completed" or not run.result:
        return card
    by_topic = {
        item["topic_id"]: item
        for item in run.result.get("topic_analyses", [])
        if isinstance(item, dict) and item.get("topic_id")
    }
    dimensions: list[CardDimension] = []
    for dimension in card.dimensions:
        if dimension.dimension_id != run.dimension_id:
            dimensions.append(dimension)
            continue
        topics: list[CardTopic] = []
        for topic in dimension.topics:
            analysis = by_topic.get(topic.topic_id)
            if not analysis:
                topics.append(topic)
                continue
            topics.append(
                replace(
                    topic,
                    analysis=analysis.get("conclusion", ""),
                    key_signals=tuple(analysis.get("key_signals", [])),
                    information_boundaries=tuple(analysis.get("information_boundaries", [])),
                    analysis_evidence_refs=tuple(analysis.get("evidence_refs", [])),
                    analysis_status="completed",
                )
            )
        dimensions.append(
            CardDimension(
                dimension_id=dimension.dimension_id,
                label=dimension.label,
                facts=dimension.facts,
                claim_count=dimension.claim_count,
                authority_count=dimension.authority_count,
                topics=tuple(topics),
            )
        )
    return replace(card, dimensions=tuple(dimensions))


def _find_dimension(card: EnterpriseVisualCard, dimension_id: str) -> CardDimension:
    for dimension in card.dimensions:
        if dimension.dimension_id == dimension_id:
            return dimension
    raise ValueError(f"画像领域不存在：{dimension_id}")


def _parse_agent_result(state: dict[str, Any]) -> dict[str, Any]:
    messages = state.get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        text = _message_text(content)
        if text:
            parsed = extract_json_from_text(text)
            if _looks_like_topic_analysis_result(parsed):
                return parsed
    structured = state.get("structured_response")
    if _looks_like_topic_analysis_result(structured):
        return structured
    raise ValueError("分析 Agent 没有返回可解析的 JSON。")


def _looks_like_topic_analysis_result(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(
        set(value).intersection(
            {
                *_DOMAIN_SUMMARY_KEYS,
                "topic_analyses",
                "topic_analysis",
                "analyses",
                "topics",
                "topic_results",
                "主题分析",
                "主题分析结果",
                "主题结论",
            }
        )
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            value = block.get("text") or block.get("content")
            if isinstance(value, str):
                parts.append(value)
    return "".join(parts).strip()


def _collect_api_meta(state: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in state.get("messages", []):
        response_metadata = getattr(message, "response_metadata", None)
        if isinstance(response_metadata, dict) and response_metadata:
            result.append(dict(response_metadata))
    return result
