"""在混合召回候选范围内调用 DeepSeek 做受约束重排。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Sequence

from src.llm.deepseek_client import call_deepseek
from src.llm.generation_config import GenerationConfig

from .hybrid import HybridResult


logger = logging.getLogger(__name__)
RELEVANCE_LEVELS = {"high", "medium", "low"}


class RerankValidationError(ValueError):
    """模型重排结果不符合协议。"""


@dataclass(frozen=True)
class RerankedCase:
    case_id: str
    rank: int
    relevance: str | None
    similarity_reasons: tuple[str, ...]
    important_differences: tuple[str, ...]
    uncertainties: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "rank": self.rank,
            "relevance": self.relevance,
            "similarity_reasons": list(self.similarity_reasons),
            "important_differences": list(self.important_differences),
            "uncertainties": list(self.uncertainties),
        }


@dataclass(frozen=True)
class RerankResponse:
    ranked_cases: tuple[RerankedCase, ...]
    degraded: bool = False
    error: str | None = None
    api_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ranked_cases": [case.to_dict() for case in self.ranked_cases],
            "degraded": self.degraded,
            "error": self.error,
            "api_meta": self.api_meta,
        }


def rerank_candidates(
    new_case_summary: str | dict[str, Any],
    candidates: Sequence[HybridResult],
    config: GenerationConfig,
    *,
    top_k: int = 3,
) -> RerankResponse:
    """只允许模型在传入候选中重排，失败时退回混合召回顺序。"""
    if not _has_summary(new_case_summary):
        raise ValueError("new_case_summary 不能为空")
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    if config.mode != "thinking" or config.reasoning_effort != "high":
        raise ValueError("DeepSeek 重排必须使用 thinking 模式和 reasoning_effort=high")

    candidate_list = tuple(candidates)
    candidate_by_id: dict[str, HybridResult] = {}
    for candidate in candidate_list:
        if not candidate.case_id.strip():
            raise ValueError("候选案例 case_id 不能为空")
        if candidate.case_id in candidate_by_id:
            raise ValueError(f"候选案例 case_id 重复：{candidate.case_id}")
        candidate_by_id[candidate.case_id] = candidate

    if not candidate_list:
        return RerankResponse(ranked_cases=())

    messages = _build_messages(new_case_summary, candidate_list, top_k=top_k)
    try:
        raw_result = call_deepseek(messages, config)
        ranked_cases, api_meta = _validate_result(
            raw_result,
            candidate_by_id,
            top_k=top_k,
        )
        return RerankResponse(
            ranked_cases=tuple(ranked_cases),
            api_meta=api_meta,
        )
    except Exception as exc:
        logger.warning("DeepSeek 重排失败，退回混合召回顺序：%s", type(exc).__name__)
        return _degraded_response(candidate_list, top_k=top_k, error=str(exc))


def _build_messages(
    new_case_summary: str | dict[str, Any],
    candidates: Sequence[HybridResult],
    *,
    top_k: int,
) -> list[dict[str, str]]:
    system_prompt = (
        "你是金融风险案例检索重排器。只能在给定候选案例范围内排序，不能新增、改写或臆造 case_id。"
        "必须只输出一个合法 JSON 对象，不输出 Markdown 或额外说明。"
    )
    user_payload = {
        "task": "根据新案例摘要，对混合召回候选进行相关性重排。默认返回排名最高的候选，最多返回指定数量。",
        "rules": [
            "相似理由必须基于新案例和候选案例中实际出现的事实。",
            "重要差异必须指出证据中的业务、主体、时间或风险机制差异；证据不足时写入 uncertainties。",
            "主题词相同不能直接证明风险机制相同。",
            "ranked_cases 中的 case_id 只能来自 candidates。",
            "relevance 只能是 high、medium 或 low。",
        ],
        "top_k": top_k,
        "new_case_summary": new_case_summary,
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "output_schema": {
            "ranked_cases": [
                {
                    "case_id": "候选中的 case_id",
                    "rank": 1,
                    "relevance": "high|medium|low",
                    "similarity_reasons": ["基于事实的相似理由"],
                    "important_differences": ["基于事实的重要差异"],
                    "uncertainties": ["证据不足或无法判断的事项"],
                }
            ]
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def _candidate_payload(candidate: HybridResult) -> dict[str, Any]:
    return {
        "case_id": candidate.case_id,
        "case_name": candidate.document.metadata.get("case_name"),
        "retrieval_summary": candidate.document.retrieval_text,
        "retrieval_metadata": candidate.document.metadata,
        "retrieval_trace": {
            "match_type": candidate.match_type,
            "bm25_rank": candidate.bm25_rank,
            "bm25_score": candidate.bm25_score,
            "embedding_rank": candidate.embedding_rank,
            "embedding_score": candidate.embedding_score,
        },
    }


def _validate_result(
    raw_result: dict[str, Any],
    candidate_by_id: dict[str, HybridResult],
    *,
    top_k: int,
) -> tuple[list[RerankedCase], dict[str, Any] | None]:
    if not isinstance(raw_result, dict):
        raise RerankValidationError("重排结果顶层必须是对象")
    ranked = raw_result.get("ranked_cases")
    if not isinstance(ranked, list):
        raise RerankValidationError("重排结果缺少 ranked_cases 数组")
    if len(ranked) > top_k:
        raise RerankValidationError(f"重排结果超过 top_k={top_k}")

    required_keys = {
        "case_id",
        "rank",
        "relevance",
        "similarity_reasons",
        "important_differences",
        "uncertainties",
    }
    seen: set[str] = set()
    result: list[RerankedCase] = []
    for index, item in enumerate(ranked, start=1):
        if not isinstance(item, dict) or set(item) != required_keys:
            raise RerankValidationError(f"第 {index} 个重排项字段不符合协议")
        case_id = item["case_id"]
        if not isinstance(case_id, str) or case_id not in candidate_by_id:
            raise RerankValidationError(f"重排返回了非法或未知 case_id：{case_id!r}")
        if case_id in seen:
            raise RerankValidationError(f"重排返回了重复 case_id：{case_id}")
        seen.add(case_id)
        rank = item["rank"]
        if isinstance(rank, bool) or not isinstance(rank, int) or rank != index:
            raise RerankValidationError("重排 rank 必须从 1 开始连续递增")
        relevance = item["relevance"]
        if relevance not in RELEVANCE_LEVELS:
            raise RerankValidationError(f"relevance 非法：{relevance!r}")
        fields = {}
        for field_name in ("similarity_reasons", "important_differences", "uncertainties"):
            values = item[field_name]
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise RerankValidationError(f"{field_name} 必须是字符串数组")
            fields[field_name] = tuple(values)
        result.append(
            RerankedCase(
                case_id=case_id,
                rank=rank,
                relevance=relevance,
                **fields,
            )
        )

    api_meta = raw_result.get("api_meta")
    if api_meta is not None and not isinstance(api_meta, dict):
        raise RerankValidationError("api_meta 必须是对象")
    return result, api_meta


def _degraded_response(
    candidates: Sequence[HybridResult],
    *,
    top_k: int,
    error: str,
) -> RerankResponse:
    fallback_cases = tuple(
        RerankedCase(
            case_id=candidate.case_id,
            rank=rank,
            relevance=None,
            similarity_reasons=(),
            important_differences=(),
            uncertainties=("DeepSeek 重排失败，当前结果沿用混合召回顺序。",),
        )
        for rank, candidate in enumerate(candidates[:top_k], start=1)
    )
    return RerankResponse(
        ranked_cases=fallback_cases,
        degraded=True,
        error=error,
    )


def _has_summary(summary: str | dict[str, Any]) -> bool:
    if isinstance(summary, str):
        return bool(summary.strip())
    return isinstance(summary, dict) and bool(summary)
