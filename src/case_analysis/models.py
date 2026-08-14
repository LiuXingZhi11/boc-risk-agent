"""Evidence-based analysis for one historical enterprise case."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.ontology.schema import COMPARISON_DIMENSION_SECTIONS
from src.profiles.models import EvidenceReference

OUTCOME_STATUSES = {"disclosed", "partially_disclosed", "not_disclosed"}
OUTCOME_TYPES = {"approval_rejected", "approved_with_conditions", "credit_deterioration", "default_or_distress", "operational_failure", "regulatory_action", "judicial_outcome", "restructuring_or_exit", "other"}
FACTOR_ROLES = {"explicit_reason", "evidence_supported_factor", "analyst_hypothesis"}
REVIEW_STATUSES = {"pending", "approved", "rejected"}

DIMENSION_LABELS = {
    "enterprise_and_team": "企业基础、治理与团队",
    "technology_and_ip": "技术与知识产权",
    "product_and_commercialization": "产品、研发、市场与商业化",
    "customer_supplier_and_dependency": "客户、供应商与外部依赖",
    "finance_and_funding": "财务与融资",
    "risk_and_compliance": "风险与合规",
    "authority_outcome_and_evidence": "权威认定、历史结果与证据质量",
}
ROLE_LABELS = {
    "explicit_reason": "材料明确说明的原因",
    "evidence_supported_factor": "证据支持的风险因素",
    "analyst_hypothesis": "待核实的分析假设",
}


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空。")


@dataclass(frozen=True)
class CaseOutcome:
    outcome_id: str
    outcome_type: str
    description: str
    source_item_ids: tuple[str, ...] = field(default_factory=tuple)
    source_relation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _required(self.outcome_id, "outcome_id")
        _required(self.description, "description")
        if self.outcome_type not in OUTCOME_TYPES:
            raise ValueError(f"outcome_type 非法：{self.outcome_type!r}")
        if not self.evidence_refs:
            raise ValueError("历史结果必须绑定证据。")


@dataclass(frozen=True)
class CaseAnalysisFactor:
    factor_id: str
    dimension_id: str
    title: str
    finding: str
    factor_role: str
    source_item_ids: tuple[str, ...] = field(default_factory=tuple)
    source_relation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _required(self.factor_id, "factor_id")
        _required(self.title, "title")
        _required(self.finding, "finding")
        if self.dimension_id not in COMPARISON_DIMENSION_SECTIONS:
            raise ValueError(f"dimension_id 非法：{self.dimension_id!r}")
        if self.factor_role not in FACTOR_ROLES:
            raise ValueError(f"factor_role 非法：{self.factor_role!r}")
        if not self.evidence_refs:
            raise ValueError("案例因素必须绑定证据。")


@dataclass(frozen=True)
class CaseReviewDirection:
    direction_id: str
    title: str
    rationale: str
    related_factor_ids: tuple[str, ...] = field(default_factory=tuple)
    verification_questions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _required(self.direction_id, "direction_id")
        _required(self.title, "title")
        _required(self.rationale, "rationale")
        if not self.verification_questions:
            raise ValueError("核实方向必须包含至少一个问题。")


@dataclass(frozen=True)
class HistoricalCaseAnalysis:
    analysis_id: str
    profile_id: str
    case_id: str
    enterprise_name: str
    ontology_version: str
    profile_hash: str
    case_summary: str
    outcome_status: str
    outcomes: tuple[CaseOutcome, ...] = field(default_factory=tuple)
    factors: tuple[CaseAnalysisFactor, ...] = field(default_factory=tuple)
    review_directions: tuple[CaseReviewDirection, ...] = field(default_factory=tuple)
    applicability_limits: tuple[str, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)
    generation_method: str = "llm"
    model: str | None = None
    review_status: str = "pending"
    api_meta: dict[str, Any] = field(default_factory=dict)
    debug_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("analysis_id", "profile_id", "case_id", "enterprise_name", "profile_hash", "case_summary"):
            _required(getattr(self, name), name)
        if self.outcome_status not in OUTCOME_STATUSES:
            raise ValueError(f"outcome_status 非法：{self.outcome_status!r}")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"review_status 非法：{self.review_status!r}")
        for values, name in ((self.outcomes, "outcome_id"), (self.factors, "factor_id"), (self.review_directions, "direction_id")):
            ids = [getattr(value, name) for value in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} 不得重复。")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_human_dict(self) -> dict[str, Any]:
        return {
            "企业名称": self.enterprise_name,
            "案例概述": self.case_summary,
            "历史结果披露状态": {"disclosed": "已披露", "partially_disclosed": "部分披露", "not_disclosed": "未披露"}[self.outcome_status],
            "历史结果": [item.description for item in self.outcomes],
            "关键因素": [
                {
                    "维度": DIMENSION_LABELS[item.dimension_id],
                    "性质": ROLE_LABELS[item.factor_role],
                    "标题": item.title,
                    "分析": item.finding,
                }
                for item in self.factors
            ],
            "后续审查方向": [
                {"标题": item.title, "说明": item.rationale, "待核实问题": list(item.verification_questions)}
                for item in self.review_directions
            ],
            "适用限制": list(self.applicability_limits),
            "信息缺口": list(self.information_gaps),
        }

    def to_markdown(self) -> str:
        result = self.to_human_dict()
        lines = [f"# {self.enterprise_name}历史案例分析", "", "## 案例概述", "", self.case_summary]
        lines += ["", "## 已披露的历史结果", ""]
        lines += [f"- {value}" for value in result["历史结果"]] or ["- 当前材料未提供可确认的审批、违约、监管或司法结果。"]
        lines += ["", "## 关键因素", ""]
        if self.factors:
            for item in self.factors:
                lines += [f"### {item.title}", "", f"- 维度：{DIMENSION_LABELS[item.dimension_id]}", f"- 性质：{ROLE_LABELS[item.factor_role]}", f"- 分析：{item.finding}", ""]
        else:
            lines += ["- 当前证据不足以形成有依据的关键因素。", ""]
        lines += ["## 后续审查方向", ""]
        for item in self.review_directions:
            lines += [f"### {item.title}", "", item.rationale, ""] + [f"- {question}" for question in item.verification_questions] + [""]
        lines += ["## 适用限制", ""] + ([f"- {value}" for value in self.applicability_limits] or ["- 当前未记录额外适用限制。"])
        lines += ["", "## 画像已记录的信息缺口", ""]
        lines += [f"- {value}" for value in self.information_gaps] or ["- 当前画像未单独记录信息缺口；请结合上述适用限制判断材料完整性。"]
        lines.append("")
        lines += ["> 本分析仅用于历史参考和信息核实辅助，不构成授信审批、风险定级或业务决策结论。"]
        return "\n".join(lines).strip() + "\n"


def approve_historical_case_analysis(analysis: HistoricalCaseAnalysis) -> HistoricalCaseAnalysis:
    data = analysis.to_dict()
    data["review_status"] = "approved"
    data["outcomes"] = analysis.outcomes
    data["factors"] = analysis.factors
    data["review_directions"] = analysis.review_directions
    return HistoricalCaseAnalysis(**data)
