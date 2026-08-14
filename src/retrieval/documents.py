"""案例检索文档构建。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.models import CaseBundle


@dataclass(frozen=True)
class RetrievalDocument:
    case_id: str
    retrieval_text: str
    metadata: dict[str, Any]


def build_retrieval_text(bundle: CaseBundle) -> str:
    """从案例包构造稳定、面向业务的检索文本。"""
    target_fact_id = bundle.case.target_event.target_fact_id if bundle.case.target_event else None
    facts_by_id = {fact.fact_id: fact for fact in bundle.facts}
    sections: list[tuple[str, list[str]]] = [("案例名称", [bundle.case.case_name])]

    if target_fact_id and target_fact_id in facts_by_id:
        sections.append(("主要风险事件", [facts_by_id[target_fact_id].statement]))

    categories = {
        "关键主体关系": {"relationship", "entity_attribute"},
        "关键业务事实": {"action", "transaction", "business_observation", "review_action"},
        "关键财务事实": {"financial_observation"},
        "其他关键事实": {"context", "outcome", "risk_event", "other"},
    }
    for label, allowed in categories.items():
        statements = [
            fact.statement
            for fact in bundle.facts
            if fact.category in allowed and fact.fact_id != target_fact_id
        ]
        if statements:
            sections.append((label, statements))

    rules = [rule.rule_hypothesis for rule in bundle.rule_hypotheses]
    if rules:
        sections.append(("单案例风险机制假设", rules))

    return "\n".join(
        f"{label}：\n" + "\n".join(f"- {value}" for value in values)
        for label, values in sections
        if values
    )


def build_retrieval_document(
    bundle: CaseBundle,
    *,
    allow_unapproved: bool = False,
) -> RetrievalDocument:
    """构造正式检索文档；默认只允许已审核案例。"""
    if bundle.case.review_status != "approved" and not allow_unapproved:
        raise ValueError(
            f"案例 {bundle.case.case_id} 尚未审核通过，不能进入正式检索索引。"
        )
    return RetrievalDocument(
        case_id=bundle.case.case_id,
        retrieval_text=build_retrieval_text(bundle),
        metadata={
            "case_name": bundle.case.case_name,
            "target_fact_id": (
                bundle.case.target_event.target_fact_id
                if bundle.case.target_event
                else None
            ),
            "fact_ids": [fact.fact_id for fact in bundle.facts],
            "rule_ids": [rule.rule_id for rule in bundle.rule_hypotheses],
            "review_status": bundle.case.review_status,
        },
    )
