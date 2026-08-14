"""LangChain 驱动的行业背景受控 ReAct 调查。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.evidence.service import EvidenceQueryService
from src.llm.generation_config import GenerationConfig
from src.profiles.react_workflow import (
    build_deepseek_chat_model,
    collect_agent_api_meta,
)

from .extraction import (
    audit_industry_profile_generation,
    generate_industry_background_profile,
)
from .models import (
    INDUSTRY_DIMENSIONS,
    IndustryBackgroundProfile,
    IndustryProfileGeneration,
)
from .react_models import IndustryReactLimits, IndustryReactRun, IndustryReactSession
from .react_tools import create_industry_react_tools
from .retrieval import INDUSTRY_SEARCH_TERMS, IndustryEvidenceBundle


INDUSTRY_EXTRACTION_BATCHES = (
    ("development_stage", "market_size_and_growth"),
    ("technology_routes", "value_chain"),
    ("competition_landscape", "commercialization"),
    ("policy_and_regulation", "industry_risks"),
)


def build_industry_react_system_prompt(
    *,
    industry_id: str,
    industry_name: str,
    limits: IndustryReactLimits,
) -> str:
    dimensions = "、".join(INDUSTRY_DIMENSIONS)
    search_plan = "\n".join(
        f"- dimension_ids：[\"{dimension_id}\"]；可用独立概念词："
        f"{' '.join(INDUSTRY_SEARCH_TERMS[dimension_id])}"
        for dimension_id in INDUSTRY_DIMENSIONS
    )
    return f"""你负责为行业背景画像选择证据。
industry_id：{industry_id}
industry_name：{industry_name}
固定维度：{dimensions}

首次调查必须为八个维度各调用一次 search_industry_evidence，每次只能提交一个 dimension_id：
{search_plan}
query 中的概念词用空格分开，不要把“政策”和“法规”一类独立概念合成一个长词，也不要写 industry_name。
完成八次首次搜索后，根据目录标题和位置选择正文，再调用 read_industry_evidence 分批读取最相关正文。
最多保留两次额外搜索，只在某维度目录少于 4 项、某来源尚未出现、或目录集中在同一章节时，
使用尚未使用的独立概念词补充检索；不要重复相同 query。读取正文时先保证八个维度都覆盖，
再保证不同来源和不同章节覆盖；每个维度在预算允许时至少读取 3 条，同一维度有多个来源或章节时
不要连续读取同一来源同一章节。累计读取 {limits.max_read_units} 条正文后不得继续读取。
证据足够时提前结束，只回复“行业证据选择完成”。
不要生成行业画像 JSON、企业事实、风险结论或审核意见；不要读取其他材料集合。

调用上限：模型 {limits.max_model_calls} 次，搜索 {limits.max_search_calls} 次，读取工具 {limits.max_read_calls} 次，
累计正文 {limits.max_read_units} 条，每次目录最多 {limits.max_catalog_items} 项。
""".strip()


def build_industry_react_agent(
    *,
    model: BaseChatModel,
    tools: list[BaseTool],
    system_prompt: str,
    limits: IndustryReactLimits,
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
                tool_name="search_industry_evidence",
                run_limit=limits.max_search_calls,
                exit_behavior="continue",
            ),
            ToolCallLimitMiddleware(
                tool_name="read_industry_evidence",
                run_limit=limits.max_read_calls,
                exit_behavior="continue",
            ),
        ],
    )


class ControlledReactIndustryWorkflow:
    def __init__(
        self,
        evidence_service: EvidenceQueryService,
        *,
        model_factory: Callable[[GenerationConfig], BaseChatModel] = build_deepseek_chat_model,
        agent_factory: Callable[..., Any] = build_industry_react_agent,
        generator: Callable[..., IndustryProfileGeneration] = generate_industry_background_profile,
        auditor: Callable[..., IndustryProfileGeneration] = audit_industry_profile_generation,
    ) -> None:
        self.evidence_service = evidence_service
        self.model_factory = model_factory
        self.agent_factory = agent_factory
        self.generator = generator
        self.auditor = auditor

    def run(
        self,
        *,
        profile_id: str,
        industry_id: str,
        industry_name: str,
        react_config: GenerationConfig,
        extraction_config: GenerationConfig,
        limits: IndustryReactLimits = IndustryReactLimits(),
        guide_text: str = "",
    ) -> IndustryReactRun:
        session = IndustryReactSession(
            industry_id=industry_id,
            industry_name=industry_name,
            evidence_service=self.evidence_service,
            limits=limits,
        )
        agent = self.agent_factory(
            model=self.model_factory(react_config),
            tools=create_industry_react_tools(session),
            system_prompt=build_industry_react_system_prompt(
                industry_id=industry_id,
                industry_name=industry_name,
                limits=limits,
            ),
            limits=limits,
        )
        state = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "调查八个固定维度并选择行业背景证据。",
                    }
                ]
            }
        )
        api_meta = collect_agent_api_meta(state.get("messages", []))
        for record in api_meta:
            record["stage"] = "industry_react_evidence_discovery"
        if not session.read_units:
            status = (
                "limit_reached"
                if state.get("run_model_call_count", 0) >= limits.max_model_calls
                else "no_evidence"
            )
            return _build_run(session, status=status, api_meta=api_meta)
        bundle = _bundle_from_session(session)
        generations: list[IndustryProfileGeneration] = []
        batch_statuses: list[dict[str, Any]] = []
        for dimensions in INDUSTRY_EXTRACTION_BATCHES:
            batch_bundle = _batch_bundle(bundle, dimensions)
            if not batch_bundle.evidence_units:
                batch_statuses.append(
                    {"dimensions": dimensions, "status": "no_evidence"}
                )
                continue
            try:
                generation = self.generator(
                    profile_id=profile_id,
                    industry_id=industry_id,
                    industry_name=industry_name,
                    bundle=batch_bundle,
                    config=extraction_config,
                    guide_text=guide_text,
                    allowed_dimensions=dimensions,
                )
            except Exception as exc:
                batch_statuses.append(
                    {
                        "dimensions": dimensions,
                        "status": "failed",
                        "error_type": type(exc).__name__,
                    }
                )
                return _build_run(
                    session,
                    status="extraction_failed",
                    api_meta=api_meta,
                    batch_statuses=batch_statuses,
                    error=f"行业画像批次生成失败：{type(exc).__name__}: {exc}",
                )
            generations.append(generation)
            extraction_meta = dict(generation.profile.api_meta)
            extraction_meta.update(
                {
                    "stage": "industry_profile_extraction",
                    "dimensions": dimensions,
                }
            )
            api_meta.append(extraction_meta)
            batch_statuses.append(
                {
                    "dimensions": dimensions,
                    "status": "completed",
                    "insight_count": len(generation.profile.insights),
                }
            )
        generation = _merge_generations(
            generations,
            profile_id=profile_id,
            industry_id=industry_id,
            industry_name=industry_name,
            model=extraction_config.model,
            batch_statuses=batch_statuses,
        )
        try:
            generation = self.auditor(
                generation=generation,
                config=extraction_config,
            )
        except Exception as exc:
            return _build_run(
                session,
                status="audit_failed",
                api_meta=api_meta,
                batch_statuses=batch_statuses,
                error=f"行业画像全局审核失败：{type(exc).__name__}: {exc}",
            )
        audit_meta = dict(generation.profile.api_meta.get("semantic_audit") or {})
        audit_meta["stage"] = "industry_profile_semantic_audit"
        api_meta.append(audit_meta)
        return _build_run(
            session,
            status="pending_review",
            generation=generation,
            api_meta=api_meta,
            batch_statuses=batch_statuses,
        )


def _bundle_from_session(
    session: IndustryReactSession,
) -> IndustryEvidenceBundle:
    return IndustryEvidenceBundle(
        industry_id=session.industry_id,
        evidence_units=tuple(session.read_units.values()),
        dimension_evidence_ids={
            dimension_id: tuple(
                evidence_id
                for evidence_id in session.read_units
                if dimension_id
                in session.evidence_dimensions.get(evidence_id, set())
            )
            for dimension_id in INDUSTRY_DIMENSIONS
        },
    )


def _build_run(
    session: IndustryReactSession,
    *,
    status: str,
    api_meta: list[dict[str, Any]],
    generation: IndustryProfileGeneration | None = None,
    batch_statuses: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> IndustryReactRun:
    return IndustryReactRun(
        industry_id=session.industry_id,
        status=status,
        generation=generation,
        evidence_catalog=tuple(session.catalog_items.values()),
        selected_evidence_unit_ids=tuple(session.read_units),
        react_trace=tuple(session.trace),
        api_meta=tuple(api_meta),
        batch_statuses=tuple(batch_statuses or ()),
        error=error,
    )


def _batch_bundle(
    bundle: IndustryEvidenceBundle,
    dimensions: tuple[str, ...],
) -> IndustryEvidenceBundle:
    evidence_ids = {
        evidence_id
        for dimension_id in dimensions
        for evidence_id in bundle.dimension_evidence_ids.get(dimension_id, ())
    }
    return IndustryEvidenceBundle(
        industry_id=bundle.industry_id,
        evidence_units=tuple(
            unit
            for unit in bundle.evidence_units
            if unit.evidence_unit_id in evidence_ids
        ),
        dimension_evidence_ids={
            dimension_id: tuple(
                evidence_id
                for evidence_id in bundle.dimension_evidence_ids.get(
                    dimension_id, ()
                )
                if evidence_id in evidence_ids
            )
            for dimension_id in dimensions
        },
    )


def _merge_generations(
    generations: list[IndustryProfileGeneration],
    *,
    profile_id: str,
    industry_id: str,
    industry_name: str,
    model: str,
    batch_statuses: list[dict[str, Any]],
) -> IndustryProfileGeneration:
    insights = []
    rejected = []
    seen_ids: set[str] = set()
    for generation in generations:
        rejected.extend(generation.rejected_candidates)
        for insight in generation.profile.insights:
            insight_id = f"{insight.dimension_id}:{insight.insight_id}"
            if insight_id in seen_ids:
                rejected.append(
                    {
                        "insight_id": insight_id,
                        "reason": "同一维度 insight_id 重复。",
                    }
                )
                continue
            insights.append(replace(insight, insight_id=insight_id))
            seen_ids.add(insight_id)
    profile = IndustryBackgroundProfile(
        profile_id=profile_id,
        industry_id=industry_id,
        industry_name=industry_name,
        source_ids=tuple(
            dict.fromkeys(
                source_id
                for generation in generations
                for source_id in generation.profile.source_ids
            )
        ),
        insights=tuple(insights),
        information_gaps=tuple(
            dict.fromkeys(
                gap
                for generation in generations
                for gap in generation.profile.information_gaps
            )
        ),
        review_status="pending",
        model=model,
        api_meta={"batch_statuses": batch_statuses},
    )
    return IndustryProfileGeneration(profile, tuple(rejected))
