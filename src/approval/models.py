"""同行比较与审批报告的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.profiles.models import EvidenceReference


REVIEW_STATUSES = {"pending", "approved", "rejected"}
NUMERIC_COMPARISON_DIRECTIONS = {"higher_is_better", "lower_is_better"}


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _validate_review_status(review_status: str) -> None:
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"invalid review_status: {review_status!r}")


@dataclass(frozen=True)
class PeerCohort:
    cohort_id: str
    industry_id: str
    cohort_name: str
    fiscal_period: str
    company_case_ids: tuple[str, ...]
    selection_rule: str
    source_ids: tuple[str, ...] = field(default_factory=tuple)
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in (
            "cohort_id",
            "industry_id",
            "cohort_name",
            "fiscal_period",
            "selection_rule",
        ):
            _require_text(getattr(self, field_name), field_name)
        if len(self.company_case_ids) < 2:
            raise ValueError("a peer cohort requires at least two companies")
        if len(self.company_case_ids) != len(set(self.company_case_ids)):
            raise ValueError("company_case_ids must not contain duplicates")
        for case_id in self.company_case_ids:
            _require_text(case_id, "company_case_ids item")
        for source_id in self.source_ids:
            _require_text(source_id, "source_ids item")
        _validate_review_status(self.review_status)


@dataclass(frozen=True)
class ComparableMetricDefinition:
    metric_id: str
    approval_direction_id: str
    approval_point_id: str
    name: str
    comparison_direction: str
    unit: str
    value_scope: str
    missing_value_rule: str = "exclude"
    tie_rule: str = "dense_rank"
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in (
            "metric_id",
            "approval_direction_id",
            "approval_point_id",
            "name",
            "unit",
            "value_scope",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.comparison_direction not in NUMERIC_COMPARISON_DIRECTIONS:
            raise ValueError(
                "comparison_direction must be higher_is_better or lower_is_better"
            )
        if self.missing_value_rule != "exclude":
            raise ValueError("the first ranking slice only supports exclude")
        if self.tie_rule != "dense_rank":
            raise ValueError("the first ranking slice only supports dense_rank")
        _validate_review_status(self.review_status)


@dataclass(frozen=True)
class ComparableMetricValue:
    cohort_id: str
    metric_id: str
    case_id: str
    value: float
    reporting_period: str
    unit: str
    source_profile_id: str
    source_item_id: str
    evidence_refs: tuple[EvidenceReference, ...]
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in (
            "cohort_id",
            "metric_id",
            "case_id",
            "reporting_period",
            "unit",
            "source_profile_id",
            "source_item_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("value must be a number")
        if not self.evidence_refs:
            raise ValueError("a metric value requires evidence references")
        _validate_review_status(self.review_status)


@dataclass(frozen=True)
class MetricProfileFieldBinding:
    metric_id: str
    section_id: str
    field_id: str

    def __post_init__(self) -> None:
        _require_text(self.metric_id, "metric_id")
        _require_text(self.section_id, "section_id")
        _require_text(self.field_id, "field_id")


@dataclass(frozen=True)
class RankingResult:
    cohort_id: str
    metric_id: str
    case_id: str
    value: float
    sample_size: int
    rank: int
    rank_points: int

    def __post_init__(self) -> None:
        for field_name in ("cohort_id", "metric_id", "case_id"):
            _require_text(getattr(self, field_name), field_name)
        if self.sample_size < 1 or not 1 <= self.rank <= self.sample_size:
            raise ValueError("rank must be within sample_size")
        if self.rank_points != self.sample_size - self.rank + 1:
            raise ValueError("rank_points must match the dense rank formula")


@dataclass(frozen=True)
class ApprovalPoint:
    approval_point_id: str
    title: str
    enterprise_observation: str
    industry_benchmark: str | None
    peer_comparison: str | None
    judgment: str
    ranking_results: tuple[RankingResult, ...] = field(default_factory=tuple)
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    information_gaps: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in (
            "approval_point_id",
            "title",
            "enterprise_observation",
            "judgment",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not self.evidence_refs:
            raise ValueError("an approval point requires evidence references")


@dataclass(frozen=True)
class ApprovalPointDefinition:
    approval_point_id: str
    approval_direction_id: str
    title: str
    enterprise_field_ids: tuple[str, ...] = field(default_factory=tuple)
    metric_ids: tuple[str, ...] = field(default_factory=tuple)
    industry_dimension_ids: tuple[str, ...] = field(default_factory=tuple)
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in ("approval_point_id", "approval_direction_id", "title"):
            _require_text(getattr(self, field_name), field_name)
        if not self.enterprise_field_ids and not self.metric_ids:
            raise ValueError(
                "an approval point definition requires enterprise fields or metrics"
            )
        for field_name in (
            "enterprise_field_ids",
            "metric_ids",
            "industry_dimension_ids",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            for value in values:
                _require_text(value, f"{field_name} item")
        _validate_review_status(self.review_status)


@dataclass(frozen=True)
class DomainApprovalReport:
    report_id: str
    cohort_id: str
    case_id: str
    domain_id: str
    one_sentence_summary: str
    approval_points: tuple[ApprovalPoint, ...]
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in (
            "report_id",
            "cohort_id",
            "case_id",
            "domain_id",
            "one_sentence_summary",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not self.approval_points:
            raise ValueError("a domain approval report requires approval points")
        point_ids = [point.approval_point_id for point in self.approval_points]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("approval_point_id must not contain duplicates")
        _validate_review_status(self.review_status)


@dataclass(frozen=True)
class CompositeApprovalReport:
    report_id: str
    cohort_id: str
    case_id: str
    overall_judgment: str
    key_risks: tuple[str, ...]
    mitigating_factors: tuple[str, ...]
    judgment_boundaries: tuple[str, ...]
    verification_priorities: tuple[str, ...]
    source_domain_report_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in ("report_id", "cohort_id", "case_id", "overall_judgment"):
            _require_text(getattr(self, field_name), field_name)
        if not self.source_domain_report_ids:
            raise ValueError("a composite report requires domain reports")
        if len(self.source_domain_report_ids) != len(set(self.source_domain_report_ids)):
            raise ValueError("source_domain_report_ids must not contain duplicates")
        if not self.evidence_refs:
            raise ValueError("a composite report requires evidence references")
        _validate_review_status(self.review_status)


RATING_LEVELS = {"A", "B", "C", "D"}
FINAL_DIRECTION_STATUSES = {
    "passed",
    "conditional_passed",
    "failed",
    "insufficient_information",
}
FINAL_RECOMMENDATIONS = {
    "proceed_with_caution",
    "proceed_with_review",
    "conditional_proceed",
    "do_not_proceed",
}


@dataclass(frozen=True)
class FinalDirectionResult:
    section_id: str
    constraint_level: str
    status: str
    summary: str
    strong_constraint_trigger_code: str | None = None
    strong_constraint_trigger_evidence_unit_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in ("section_id", "constraint_level", "status", "summary"):
            _require_text(getattr(self, field_name), field_name)
        if self.constraint_level not in {"strong", "weak"}:
            raise ValueError("constraint_level must be strong or weak")
        if self.status not in FINAL_DIRECTION_STATUSES:
            raise ValueError("invalid final direction status")
        if self.strong_constraint_trigger_code is not None:
            _require_text(self.strong_constraint_trigger_code, "strong_constraint_trigger_code")
        for evidence_unit_id in self.strong_constraint_trigger_evidence_unit_ids:
            _require_text(evidence_unit_id, "strong constraint trigger evidence")


@dataclass(frozen=True)
class OverallAssessmentRationale:
    dimension_id: str
    title: str
    judgment: str

    def __post_init__(self) -> None:
        for field_name in ("dimension_id", "title", "judgment"):
            _require_text(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class EnterpriseOverallAssessment:
    assessment_id: str
    cohort_id: str
    case_id: str
    rating_level: str
    overall_judgment: str
    rating_rationale: tuple[OverallAssessmentRationale, ...]
    core_risks: tuple[str, ...]
    mitigating_factors: tuple[str, ...]
    rating_boundaries: tuple[str, ...]
    verification_priorities: tuple[str, ...]
    source_direction_report_ids: tuple[str, ...]
    source_direction_ranking_sections: tuple[str, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    recommendation: str = "conditional_proceed"
    strong_constraint_failed_count: int = 0
    weak_constraint_failed_count: int = 0
    direction_results: tuple[FinalDirectionResult, ...] = field(default_factory=tuple)
    is_experimental: bool = False
    review_status: str = "pending"

    def __post_init__(self) -> None:
        for field_name in (
            "assessment_id",
            "cohort_id",
            "case_id",
            "overall_judgment",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.rating_level not in RATING_LEVELS:
            raise ValueError("rating_level must be one of A, B, C, D")
        if self.recommendation not in FINAL_RECOMMENDATIONS:
            raise ValueError("invalid final recommendation")
        if self.strong_constraint_failed_count < 0 or self.weak_constraint_failed_count < 0:
            raise ValueError("failed constraint counts must not be negative")
        if self.direction_results:
            section_ids = [item.section_id for item in self.direction_results]
            if len(section_ids) != len(set(section_ids)):
                raise ValueError("final direction results must not repeat sections")
        if not self.rating_rationale:
            raise ValueError("an overall assessment requires rating rationale")
        report_ids = self.source_direction_report_ids
        if not report_ids or len(report_ids) != len(set(report_ids)):
            raise ValueError("source_direction_report_ids must be non-empty and unique")
        ranking_sections = self.source_direction_ranking_sections
        if len(ranking_sections) != len(set(ranking_sections)):
            raise ValueError("source_direction_ranking_sections must be unique")
        if not self.evidence_refs:
            raise ValueError("an overall assessment requires evidence references")
        _validate_review_status(self.review_status)
        if self.is_experimental and self.review_status == "approved":
            raise ValueError("an experimental overall assessment cannot be approved")
