"""确定性汇总固定审查报告和证据索引。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .fixed_review import FixedReviewComparison
from .questions import ReviewQuestion


DISCLAIMER = "本结果用于历史案例参考和信息核实辅助，不构成授信审批、风险定级或业务决策结论。"
FORBIDDEN_REPORT_FIELDS = {
    "approval",
    "approval_decision",
    "credit_decision",
    "risk_level",
    "risk_rating",
    "business_decision",
}


class ReportValidationError(ValueError):
    """报告结构或证据索引不符合约束。"""


@dataclass(frozen=True)
class ReviewReport:
    run_id: str
    new_case_summary: dict[str, Any]
    similar_cases: tuple[dict[str, Any], ...]
    cross_case_findings: tuple[dict[str, Any], ...]
    important_differences: tuple[dict[str, Any], ...]
    historical_rule_references: tuple[dict[str, Any], ...]
    questions_to_verify: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]
    evidence_index: dict[str, dict[str, Any]]
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "new_case_summary": self.new_case_summary,
            "similar_cases": list(self.similar_cases),
            "cross_case_findings": list(self.cross_case_findings),
            "important_differences": list(self.important_differences),
            "historical_rule_references": list(self.historical_rule_references),
            "questions_to_verify": list(self.questions_to_verify),
            "limitations": list(self.limitations),
            "evidence_index": self.evidence_index,
            "disclaimer": self.disclaimer,
        }


def build_review_report(
    comparison_context: FixedReviewComparison,
    questions: Sequence[ReviewQuestion] = (),
) -> ReviewReport:
    """从已校验的比较结果确定性生成报告，不新增模型事实。"""
    context = comparison_context.context
    comparisons_by_case_id = {
        comparison.historical_case_id: comparison
        for comparison in comparison_context.comparisons
    }
    historical_by_case_id = {
        bundle.case.case_id: bundle for bundle in context.historical_cases
    }
    insufficient_new_case_evidence = _is_severely_incomplete(context.new_case_bundle)
    similar_cases: list[dict[str, Any]] = []
    for reranked in context.rerank.ranked_cases:
        comparison = comparisons_by_case_id.get(reranked.case_id)
        historical = historical_by_case_id.get(reranked.case_id)
        similar_cases.append(
            {
                "historical_case_id": reranked.case_id,
                "case_name": historical.case.case_name if historical else None,
                "rank": reranked.rank,
                "relevance": None if insufficient_new_case_evidence else reranked.relevance,
                "similarity_reasons": list(reranked.similarity_reasons),
                "important_differences": list(reranked.important_differences),
                "uncertainties": list(reranked.uncertainties),
                "comparison_available": comparison is not None,
                "relevance_limited_by_evidence": insufficient_new_case_evidence,
            }
        )

    cross_case_findings = _collect_findings(comparison_context, "similarities")
    important_differences = _collect_findings(comparison_context, "differences")
    limitations = _build_limitations(comparison_context)
    report = ReviewReport(
        run_id=context.run_id,
        new_case_summary=_new_case_summary(context.new_case_bundle),
        similar_cases=tuple(similar_cases),
        cross_case_findings=tuple(cross_case_findings),
        important_differences=tuple(important_differences),
        historical_rule_references=tuple(comparison_context.historical_rule_references),
        questions_to_verify=tuple(question.to_dict() for question in questions),
        limitations=tuple(limitations),
        evidence_index=_build_evidence_index(comparison_context),
    )
    validate_review_report(report)
    return report


def validate_review_report(report: ReviewReport) -> None:
    payload = report.to_dict()
    if report.disclaimer != DISCLAIMER:
        raise ReportValidationError("报告免责声明不符合协议")
    _assert_no_forbidden_fields(payload)
    for question in report.questions_to_verify:
        if question.get("answer_status") != "unanswered":
            raise ReportValidationError("报告不得包含已回答的待核实问题")
    for evidence_id, evidence in report.evidence_index.items():
        if evidence_id != evidence.get("evidence_id"):
            raise ReportValidationError(f"evidence_index 键和值不一致：{evidence_id}")


def _new_case_summary(bundle: Any) -> dict[str, Any]:
    return {
        "case_id": bundle.case.case_id,
        "case_name": bundle.case.case_name,
        "target_fact_id": (
            bundle.case.target_event.target_fact_id if bundle.case.target_event else None
        ),
        "facts": [
            {
                "fact_id": fact.fact_id,
                "statement": fact.statement,
                "knowledge_status": fact.knowledge_status,
            }
            for fact in bundle.facts
        ],
    }


def _collect_findings(
    comparison_context: FixedReviewComparison,
    field_name: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for comparison in comparison_context.comparisons:
        source_findings = getattr(comparison, field_name)
        for finding in source_findings:
            item = finding.to_dict()
            key = (
                comparison.historical_case_id,
                item.get("description"),
                tuple(item.get("new_case_fact_ids", [])),
                tuple(item.get("historical_fact_ids", [])),
            )
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                {
                    "historical_case_id": comparison.historical_case_id,
                    **item,
                }
            )
    return findings


def _build_limitations(comparison_context: FixedReviewComparison) -> list[str]:
    context = comparison_context.context
    limitations = ["历史案例和规则假设仅作参考，不代表新案例事实成立。"]
    if _is_severely_incomplete(context.new_case_bundle):
        limitations.append(
            "新案例可用事实严重不足，报告不展示历史案例相关性等级，不能据此判断风险机制相似。"
        )
    if not context.candidates:
        limitations.append("本次检索没有召回历史案例，报告未编造历史案例内容。")
    if context.rerank.degraded:
        limitations.append("DeepSeek 重排未成功，历史案例顺序沿用混合召回结果。")
    if not comparison_context.comparisons:
        limitations.append("当前没有可用的逐案例比较结果。")
    if not context.historical_cases:
        limitations.append("当前没有加载任何历史案例完整详情。")
    return limitations


def _is_severely_incomplete(bundle: Any) -> bool:
    """对事实极少的新案例关闭模型相关性等级展示。"""
    if len(bundle.facts) <= 1:
        return True
    known_statuses = {fact.knowledge_status for fact in bundle.facts}
    return len(bundle.facts) <= 2 and known_statuses.issubset(
        {"known_at_target", "time_unknown"}
    )


def _build_evidence_index(
    comparison_context: FixedReviewComparison,
) -> dict[str, dict[str, Any]]:
    context = comparison_context.context
    evidence: dict[str, dict[str, Any]] = {}
    for bundle, role in (
        (context.new_case_bundle, "new_case"),
        *((historical, "historical_case") for historical in context.historical_cases),
    ):
        for fact in bundle.facts:
            evidence[fact.fact_id] = {
                "evidence_id": fact.fact_id,
                "case_id": bundle.case.case_id,
                "case_role": role,
                "type": "fact",
                "statement": fact.statement,
                "source_excerpt": fact.source_excerpt,
                "knowledge_status": fact.knowledge_status,
            }
        if role == "historical_case":
            for rule in bundle.rule_hypotheses:
                evidence[rule.rule_id] = {
                    "evidence_id": rule.rule_id,
                    "case_id": bundle.case.case_id,
                    "case_role": role,
                    "type": "historical_rule_reference",
                    "rule_hypothesis": rule.rule_hypothesis,
                    "supporting_fact_ids": list(rule.supporting_fact_ids),
                }
    return evidence


def _assert_no_forbidden_fields(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_REPORT_FIELDS.intersection(value)
        if forbidden:
            raise ReportValidationError(f"报告包含禁止字段：{sorted(forbidden)}")
        for item in value.values():
            _assert_no_forbidden_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_forbidden_fields(item)
