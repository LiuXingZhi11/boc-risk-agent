"""Streamlit 页面使用的应用层服务；页面不直接访问 SQLite。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.agent.fixed_services import (
    FixedReviewAgentDependencies,
    build_fixed_flow_fallback,
    build_fixed_review_executor_services,
)
from src.config.settings import get_settings
from src.graphs.agent_graph import build_agent_graph
from src.graphs.ingestion_graph import build_ingestion_graph
from src.llm.generation_config import GenerationConfig
from src.retrieval.embedding import LocalEmbeddingModel
from src.retrieval.persistence import load_bm25_index, load_embedding_index
from src.review.fixed_review import (
    run_fixed_review_comparison,
    run_fixed_review_context,
    run_fixed_review_questions,
    run_fixed_review_report,
)
from src.storage.repository import CaseRepository
from src.utils.json_utils import load_text


@dataclass(frozen=True)
class ReviewRuntime:
    graph: Any
    thread_id: str


def generation_config(max_tokens: int = 18000) -> GenerationConfig:
    settings = get_settings()
    return GenerationConfig(
        model=settings.model,
        mode="thinking",
        reasoning_effort="high",
        max_tokens=max_tokens,
    )


def repository(db_path: str | Path) -> CaseRepository:
    return CaseRepository(db_path)


def case_rows(db_path: str | Path, query: str = "", review_status: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized_query = query.strip().lower()
    for case in repository(db_path).list_cases(review_status=review_status):
        if normalized_query and normalized_query not in case.case_name.lower() and normalized_query not in case.case_id.lower():
            continue
        rows.append(
            {
                "case_id": case.case_id,
                "case_name": case.case_name,
                "source": case.source,
                "case_type": case.case_type,
                "review_status": case.review_status,
                "created_at": case.created_at,
                "updated_at": case.updated_at,
            }
        )
    return rows


def case_detail(db_path: str | Path, case_id: str) -> dict[str, Any] | None:
    bundle = repository(db_path).get_case_bundle(case_id)
    if bundle is None:
        return None
    return {
        "case": {
            "case_id": bundle.case.case_id,
            "case_name": bundle.case.case_name,
            "source": bundle.case.source,
            "case_type": bundle.case.case_type,
            "review_status": bundle.case.review_status,
            "raw_text": bundle.case.raw_text,
        },
        "facts": [
            {
                "fact_id": fact.fact_id,
                "statement": fact.statement,
                "category": fact.category,
                "assertion_type": fact.assertion_type,
                "knowledge_status": fact.knowledge_status,
                "source_excerpt": fact.source_excerpt,
            }
            for fact in bundle.facts
        ],
        "rule_hypotheses": [
            {
                "rule_id": rule.rule_id,
                "rule_hypothesis": rule.rule_hypothesis,
                "supporting_fact_ids": list(rule.supporting_fact_ids),
                "review_status": rule.review_status,
            }
            for rule in bundle.rule_hypotheses
        ],
        "processing_runs": [
            {
                "run_id": run.run_id,
                "stage": run.stage,
                "model": run.model,
                "generation_mode": run.generation_mode,
                "reasoning_effort": run.reasoning_effort,
                "status": run.status,
                "total_tokens": run.total_tokens,
                "error_message": run.error_message,
                "created_at": run.created_at,
            }
            for run in bundle.processing_runs
        ],
    }


def build_review_runtime(
    *,
    database: str | Path,
    index_dir: str | Path,
    structure_guide: str | Path,
    thread_id: str,
    device: str = "cpu",
    max_tokens: int = 18000,
) -> ReviewRuntime:
    settings = get_settings()
    structure_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=max_tokens,
    )
    thinking_config = generation_config(max_tokens)
    repo = repository(database)
    bm25 = load_bm25_index(index_dir)
    embedding = load_embedding_index(index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding.model_name,
        cache_dir=settings.model_cache_dir,
        device=device,
    )
    guide = load_text(structure_guide)
    dependencies = FixedReviewAgentDependencies(
        structure_guide=guide,
        structure_config=structure_config,
        rerank_config=thinking_config,
        comparison_config=thinking_config,
        question_config=thinking_config,
        repository=repo,
        bm25_index=bm25,
        embedding_index=embedding,
        encoder=encoder,
    )
    graph = build_agent_graph(
        planner_config=thinking_config,
        services=build_fixed_review_executor_services(dependencies),
        fixed_flow_fallback=build_fixed_flow_fallback(dependencies),
        checkpointer=MemorySaver(),
    )
    return ReviewRuntime(graph=graph, thread_id=thread_id)


def run_fixed_review(
    *,
    raw_case_text: str,
    database: str | Path,
    index_dir: str | Path,
    structure_guide: str | Path,
    device: str = "cpu",
    max_tokens: int = 18000,
) -> dict[str, Any]:
    """运行固定审查流程，供页面调用。"""
    settings = get_settings()
    structure_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=max_tokens,
    )
    thinking_config = generation_config(max_tokens)
    repo = repository(database)
    bm25 = load_bm25_index(index_dir)
    embedding = load_embedding_index(index_dir)
    encoder = LocalEmbeddingModel(
        model_name=embedding.model_name,
        cache_dir=settings.model_cache_dir,
        device=device,
    )
    context = run_fixed_review_context(
        raw_case_text=raw_case_text,
        structure_guide=load_text(structure_guide),
        structure_config=structure_config,
        repository=repo,
        bm25_index=bm25,
        embedding_index=embedding,
        encoder=encoder,
        rerank_config=thinking_config,
    )
    comparison = run_fixed_review_comparison(context, thinking_config)
    questions = run_fixed_review_questions(comparison, thinking_config)
    return run_fixed_review_report(comparison, questions).to_dict()


def _public_json(value: Any) -> Any:
    """把 LangGraph 返回值转换成页面可安全展示的 JSON 基础类型。"""
    if isinstance(value, dict):
        return {str(key): _public_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    interrupt_value = getattr(value, "value", None)
    return _public_json(interrupt_value) if interrupt_value is not None else str(value)


def _ingestion_graph(
    *,
    database: str | Path,
    checkpoint: str | Path,
    structure_guide: str | Path,
    rule_guide: str | Path,
):
    settings = get_settings()
    structure_config = GenerationConfig(
        model=settings.model,
        mode="sampling",
        temperature=0.1,
        max_tokens=18000,
    )
    rule_config = generation_config()
    context = SqliteSaver.from_conn_string(str(checkpoint))
    saver = context.__enter__()
    graph = build_ingestion_graph(
        structure_guide=load_text(structure_guide),
        rule_guide=load_text(rule_guide),
        structure_config=structure_config,
        rule_config=rule_config,
        database_path=str(database),
        checkpointer=saver,
    )
    return graph, context


def start_ingestion(
    *,
    database: str | Path,
    checkpoint: str | Path,
    structure_guide: str | Path,
    rule_guide: str | Path,
    thread_id: str,
    raw_case_text: str,
    source: str | None,
) -> dict[str, Any]:
    graph, context = _ingestion_graph(
        database=database,
        checkpoint=checkpoint,
        structure_guide=structure_guide,
        rule_guide=rule_guide,
    )
    try:
        result = graph.invoke(
            {"thread_id": thread_id, "raw_case_text": raw_case_text, "source": source},
            {"configurable": {"thread_id": thread_id}},
        )
        return _public_json(result)
    finally:
        context.__exit__(None, None, None)


def resume_ingestion(
    *,
    database: str | Path,
    checkpoint: str | Path,
    structure_guide: str | Path,
    rule_guide: str | Path,
    thread_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    graph, context = _ingestion_graph(
        database=database,
        checkpoint=checkpoint,
        structure_guide=structure_guide,
        rule_guide=rule_guide,
    )
    try:
        result = graph.invoke(
            Command(resume=payload),
            {"configurable": {"thread_id": thread_id}},
        )
        return _public_json(result)
    finally:
        context.__exit__(None, None, None)
