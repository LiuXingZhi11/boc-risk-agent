"""同行比较与审批报告的 SQLite 存储。"""

from __future__ import annotations

import json
from pathlib import Path

from src.profiles.models import EvidenceReference
from src.storage.database import connect_database, init_database

from .models import (
    ApprovalPoint,
    ApprovalPointDefinition,
    ComparableMetricDefinition,
    ComparableMetricValue,
    CompositeApprovalReport,
    DomainApprovalReport,
    EnterpriseOverallAssessment,
    FinalDirectionResult,
    MetricProfileFieldBinding,
    OverallAssessmentRationale,
    PeerCohort,
    RankingResult,
)
from .direction_ranking import (
    DirectionRankPoint,
    DirectionRankingGroup,
    DirectionRankingResult,
)


class ApprovalRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        init_database(self.db_path)

    def save_cohort(self, cohort: PeerCohort) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO peer_cohorts (
                    cohort_id, industry_id, cohort_name, fiscal_period,
                    company_case_ids_json, selection_rule, source_ids_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cohort_id) DO UPDATE SET
                    industry_id = excluded.industry_id,
                    cohort_name = excluded.cohort_name,
                    fiscal_period = excluded.fiscal_period,
                    company_case_ids_json = excluded.company_case_ids_json,
                    selection_rule = excluded.selection_rule,
                    source_ids_json = excluded.source_ids_json,
                    review_status = excluded.review_status
                """,
                (
                    cohort.cohort_id,
                    cohort.industry_id,
                    cohort.cohort_name,
                    cohort.fiscal_period,
                    json.dumps(cohort.company_case_ids, ensure_ascii=False),
                    cohort.selection_rule,
                    json.dumps(cohort.source_ids, ensure_ascii=False),
                    cohort.review_status,
                ),
            )

    def get_cohort(self, cohort_id: str) -> PeerCohort | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM peer_cohorts WHERE cohort_id = ?", (cohort_id,)
            ).fetchone()
        return _cohort_from_row(row) if row else None

    def list_cohorts(self) -> list[PeerCohort]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM peer_cohorts ORDER BY cohort_id"
            ).fetchall()
        return [_cohort_from_row(row) for row in rows]

    def save_metric_definition(self, definition: ComparableMetricDefinition) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO comparable_metric_definitions (
                    metric_id, approval_direction_id, approval_point_id, name,
                    comparison_direction, unit, value_scope, missing_value_rule,
                    tie_rule, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metric_id) DO UPDATE SET
                    approval_direction_id = excluded.approval_direction_id,
                    approval_point_id = excluded.approval_point_id,
                    name = excluded.name,
                    comparison_direction = excluded.comparison_direction,
                    unit = excluded.unit,
                    value_scope = excluded.value_scope,
                    missing_value_rule = excluded.missing_value_rule,
                    tie_rule = excluded.tie_rule,
                    review_status = excluded.review_status
                """,
                (
                    definition.metric_id,
                    definition.approval_direction_id,
                    definition.approval_point_id,
                    definition.name,
                    definition.comparison_direction,
                    definition.unit,
                    definition.value_scope,
                    definition.missing_value_rule,
                    definition.tie_rule,
                    definition.review_status,
                ),
            )

    def save_metric_binding(self, binding: MetricProfileFieldBinding) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO metric_profile_field_bindings (
                    metric_id, section_id, field_id
                ) VALUES (?, ?, ?)
                """,
                (binding.metric_id, binding.section_id, binding.field_id),
            )

    def get_metric_binding(self, metric_id: str) -> MetricProfileFieldBinding | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM metric_profile_field_bindings WHERE metric_id = ?",
                (metric_id,),
            ).fetchone()
        return MetricProfileFieldBinding(**dict(row)) if row else None

    def get_metric_definition(self, metric_id: str) -> ComparableMetricDefinition | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM comparable_metric_definitions WHERE metric_id = ?",
                (metric_id,),
            ).fetchone()
        return ComparableMetricDefinition(**dict(row)) if row else None

    def list_metric_definitions(
        self, approval_direction_id: str | None = None
    ) -> list[ComparableMetricDefinition]:
        query = "SELECT * FROM comparable_metric_definitions"
        params: list[str] = []
        if approval_direction_id is not None:
            query += " WHERE approval_direction_id = ?"
            params.append(approval_direction_id)
        query += " ORDER BY metric_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [ComparableMetricDefinition(**dict(row)) for row in rows]

    def save_metric_value(self, metric_value: ComparableMetricValue) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO comparable_metric_values (
                    cohort_id, metric_id, case_id, value, reporting_period,
                    unit, source_profile_id, source_item_id, evidence_refs_json,
                    review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metric_value.cohort_id,
                    metric_value.metric_id,
                    metric_value.case_id,
                    metric_value.value,
                    metric_value.reporting_period,
                    metric_value.unit,
                    metric_value.source_profile_id,
                    metric_value.source_item_id,
                    _dump_evidence_refs(metric_value.evidence_refs),
                    metric_value.review_status,
                ),
            )

    def list_metric_values(
        self, cohort_id: str, metric_id: str
    ) -> list[ComparableMetricValue]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM comparable_metric_values
                WHERE cohort_id = ? AND metric_id = ?
                ORDER BY case_id
                """,
                (cohort_id, metric_id),
            ).fetchall()
        return [_metric_value_from_row(row) for row in rows]

    def list_cohort_metric_values(self, cohort_id: str) -> list[ComparableMetricValue]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM comparable_metric_values
                WHERE cohort_id = ?
                ORDER BY metric_id, case_id
                """,
                (cohort_id,),
            ).fetchall()
        return [_metric_value_from_row(row) for row in rows]

    def save_approval_point_definition(
        self, definition: ApprovalPointDefinition
    ) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO approval_point_definitions (
                    approval_point_id, approval_direction_id, title,
                    enterprise_field_ids_json, metric_ids_json,
                    industry_dimension_ids_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.approval_point_id,
                    definition.approval_direction_id,
                    definition.title,
                    json.dumps(definition.enterprise_field_ids, ensure_ascii=False),
                    json.dumps(definition.metric_ids, ensure_ascii=False),
                    json.dumps(definition.industry_dimension_ids, ensure_ascii=False),
                    definition.review_status,
                ),
            )

    def list_approval_point_definitions(
        self, approval_direction_id: str
    ) -> list[ApprovalPointDefinition]:
        with connect_database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM approval_point_definitions
                WHERE approval_direction_id = ?
                ORDER BY approval_point_id
                """,
                (approval_direction_id,),
            ).fetchall()
        return [_approval_point_definition_from_row(row) for row in rows]

    def get_approval_point_definition(
        self, approval_point_id: str
    ) -> ApprovalPointDefinition | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM approval_point_definitions WHERE approval_point_id = ?",
                (approval_point_id,),
            ).fetchone()
        return _approval_point_definition_from_row(row) if row else None

    def save_domain_report(self, report: DomainApprovalReport) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO domain_approval_reports (
                    report_id, cohort_id, case_id, domain_id, one_sentence_summary,
                    approval_points_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.cohort_id,
                    report.case_id,
                    report.domain_id,
                    report.one_sentence_summary,
                    json.dumps(
                        [_approval_point_to_dict(point) for point in report.approval_points],
                        ensure_ascii=False,
                    ),
                    report.review_status,
                ),
            )

    def get_domain_report(self, report_id: str) -> DomainApprovalReport | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM domain_approval_reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        return _domain_report_from_row(row) if row else None

    def list_domain_reports(
        self,
        *,
        cohort_id: str | None = None,
        case_id: str | None = None,
        domain_id: str | None = None,
        review_status: str | None = None,
    ) -> list[DomainApprovalReport]:
        query = "SELECT * FROM domain_approval_reports WHERE 1 = 1"
        params: list[str] = []
        for column, value in (
            ("cohort_id", cohort_id),
            ("case_id", case_id),
            ("domain_id", domain_id),
            ("review_status", review_status),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        query += " ORDER BY report_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_domain_report_from_row(row) for row in rows]

    def save_direction_ranking(self, result: DirectionRankingResult) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO direction_ranking_results (
                    cohort_id, section_id, comparable_company_count,
                    ranking_groups_json, not_comparable_case_ids_json,
                    rank_points_json, source_section_report_ids_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.cohort_id,
                    result.section_id,
                    result.comparable_company_count,
                    json.dumps(
                        [
                            {
                                "rank": group.rank,
                                "case_ids": list(group.case_ids),
                                "comparison_reason": group.comparison_reason,
                            }
                            for group in result.ranking_groups
                        ],
                        ensure_ascii=False,
                    ),
                    json.dumps(result.not_comparable_case_ids, ensure_ascii=False),
                    json.dumps(
                        [point.__dict__ for point in result.rank_points],
                        ensure_ascii=False,
                    ),
                    json.dumps(result.source_section_report_ids, ensure_ascii=False),
                    result.review_status,
                ),
            )

    def get_direction_ranking(
        self, cohort_id: str, section_id: str
    ) -> DirectionRankingResult | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM direction_ranking_results
                WHERE cohort_id = ? AND section_id = ?
                """,
                (cohort_id, section_id),
            ).fetchone()
        return _direction_ranking_from_row(row) if row else None

    def list_direction_rankings(
        self, cohort_id: str, *, review_status: str | None = None
    ) -> list[DirectionRankingResult]:
        query = "SELECT * FROM direction_ranking_results WHERE cohort_id = ?"
        params: list[str] = [cohort_id]
        if review_status is not None:
            query += " AND review_status = ?"
            params.append(review_status)
        query += " ORDER BY section_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_direction_ranking_from_row(row) for row in rows]

    def save_composite_report(self, report: CompositeApprovalReport) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO composite_approval_reports (
                    report_id, cohort_id, case_id, overall_judgment,
                    key_risks_json, mitigating_factors_json, judgment_boundaries_json,
                    verification_priorities_json, source_domain_report_ids_json,
                    evidence_refs_json, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.cohort_id,
                    report.case_id,
                    report.overall_judgment,
                    json.dumps(report.key_risks, ensure_ascii=False),
                    json.dumps(report.mitigating_factors, ensure_ascii=False),
                    json.dumps(report.judgment_boundaries, ensure_ascii=False),
                    json.dumps(report.verification_priorities, ensure_ascii=False),
                    json.dumps(report.source_domain_report_ids, ensure_ascii=False),
                    _dump_evidence_refs(report.evidence_refs),
                    report.review_status,
                ),
            )

    def get_composite_report(self, report_id: str) -> CompositeApprovalReport | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM composite_approval_reports WHERE report_id = ?",
                (report_id,),
            ).fetchone()
        return _composite_report_from_row(row) if row else None

    def list_composite_reports(
        self, *, cohort_id: str | None = None, case_id: str | None = None
    ) -> list[CompositeApprovalReport]:
        query = "SELECT * FROM composite_approval_reports WHERE 1 = 1"
        params: list[str] = []
        for column, value in (("cohort_id", cohort_id), ("case_id", case_id)):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        query += " ORDER BY report_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_composite_report_from_row(row) for row in rows]

    def save_overall_assessment(self, assessment: EnterpriseOverallAssessment) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO enterprise_overall_assessments (
                    assessment_id, cohort_id, case_id, rating_level, overall_judgment,
                    rating_rationale_json, core_risks_json, mitigating_factors_json,
                    rating_boundaries_json, verification_priorities_json,
                    source_direction_report_ids_json,
                    source_direction_ranking_sections_json, evidence_refs_json,
                    recommendation, strong_constraint_failed_count,
                    weak_constraint_failed_count, direction_results_json,
                    is_experimental, review_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.assessment_id,
                    assessment.cohort_id,
                    assessment.case_id,
                    assessment.rating_level,
                    assessment.overall_judgment,
                    json.dumps(
                        [item.__dict__ for item in assessment.rating_rationale],
                        ensure_ascii=False,
                    ),
                    json.dumps(assessment.core_risks, ensure_ascii=False),
                    json.dumps(assessment.mitigating_factors, ensure_ascii=False),
                    json.dumps(assessment.rating_boundaries, ensure_ascii=False),
                    json.dumps(assessment.verification_priorities, ensure_ascii=False),
                    json.dumps(assessment.source_direction_report_ids, ensure_ascii=False),
                    json.dumps(
                        assessment.source_direction_ranking_sections,
                        ensure_ascii=False,
                    ),
                    _dump_evidence_refs(assessment.evidence_refs),
                    assessment.recommendation,
                    assessment.strong_constraint_failed_count,
                    assessment.weak_constraint_failed_count,
                    json.dumps(
                        [item.__dict__ for item in assessment.direction_results],
                        ensure_ascii=False,
                    ),
                    int(assessment.is_experimental),
                    assessment.review_status,
                ),
            )

    def get_overall_assessment(
        self, assessment_id: str
    ) -> EnterpriseOverallAssessment | None:
        with connect_database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM enterprise_overall_assessments
                WHERE assessment_id = ?
                """,
                (assessment_id,),
            ).fetchone()
        return _overall_assessment_from_row(row) if row else None

    def list_overall_assessments(
        self,
        *,
        cohort_id: str | None = None,
        case_id: str | None = None,
        review_status: str | None = None,
    ) -> list[EnterpriseOverallAssessment]:
        query = "SELECT * FROM enterprise_overall_assessments WHERE 1 = 1"
        params: list[str] = []
        for column, value in (
            ("cohort_id", cohort_id),
            ("case_id", case_id),
            ("review_status", review_status),
        ):
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)
        query += " ORDER BY assessment_id"
        with connect_database(self.db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [_overall_assessment_from_row(row) for row in rows]


def _cohort_from_row(row) -> PeerCohort:
    return PeerCohort(
        cohort_id=row["cohort_id"],
        industry_id=row["industry_id"],
        cohort_name=row["cohort_name"],
        fiscal_period=row["fiscal_period"],
        company_case_ids=tuple(json.loads(row["company_case_ids_json"])),
        selection_rule=row["selection_rule"],
        source_ids=tuple(json.loads(row["source_ids_json"])),
        review_status=row["review_status"],
    )


def _metric_value_from_row(row) -> ComparableMetricValue:
    return ComparableMetricValue(
        cohort_id=row["cohort_id"],
        metric_id=row["metric_id"],
        case_id=row["case_id"],
        value=row["value"],
        reporting_period=row["reporting_period"],
        unit=row["unit"],
        source_profile_id=row["source_profile_id"],
        source_item_id=row["source_item_id"],
        evidence_refs=_load_evidence_refs(row["evidence_refs_json"]),
        review_status=row["review_status"],
    )


def _approval_point_definition_from_row(row) -> ApprovalPointDefinition:
    return ApprovalPointDefinition(
        approval_point_id=row["approval_point_id"],
        approval_direction_id=row["approval_direction_id"],
        title=row["title"],
        enterprise_field_ids=tuple(json.loads(row["enterprise_field_ids_json"])),
        metric_ids=tuple(json.loads(row["metric_ids_json"])),
        industry_dimension_ids=tuple(json.loads(row["industry_dimension_ids_json"])),
        review_status=row["review_status"],
    )


def _approval_point_to_dict(point: ApprovalPoint) -> dict[str, object]:
    return {
        "approval_point_id": point.approval_point_id,
        "title": point.title,
        "enterprise_observation": point.enterprise_observation,
        "industry_benchmark": point.industry_benchmark,
        "peer_comparison": point.peer_comparison,
        "judgment": point.judgment,
        "ranking_results": [result.__dict__ for result in point.ranking_results],
        "evidence_refs": [reference.__dict__ for reference in point.evidence_refs],
        "information_gaps": list(point.information_gaps),
    }


def _domain_report_from_row(row) -> DomainApprovalReport:
    return DomainApprovalReport(
        report_id=row["report_id"],
        cohort_id=row["cohort_id"],
        case_id=row["case_id"],
        domain_id=row["domain_id"],
        one_sentence_summary=row["one_sentence_summary"],
        approval_points=tuple(
            ApprovalPoint(
                **{
                    **raw,
                    "ranking_results": tuple(
                        RankingResult(**result) for result in raw["ranking_results"]
                    ),
                    "evidence_refs": tuple(
                        EvidenceReference(**reference)
                        for reference in raw["evidence_refs"]
                    ),
                    "information_gaps": tuple(raw["information_gaps"]),
                }
            )
            for raw in json.loads(row["approval_points_json"])
        ),
        review_status=row["review_status"],
    )


def _direction_ranking_from_row(row) -> DirectionRankingResult:
    return DirectionRankingResult(
        cohort_id=row["cohort_id"],
        section_id=row["section_id"],
        comparable_company_count=row["comparable_company_count"],
        ranking_groups=tuple(
            DirectionRankingGroup(
                rank=group["rank"],
                case_ids=tuple(group["case_ids"]),
                comparison_reason=group["comparison_reason"],
            )
            for group in json.loads(row["ranking_groups_json"])
        ),
        not_comparable_case_ids=tuple(
            json.loads(row["not_comparable_case_ids_json"])
        ),
        rank_points=tuple(
            DirectionRankPoint(**point)
            for point in json.loads(row["rank_points_json"])
        ),
        source_section_report_ids=tuple(
            json.loads(row["source_section_report_ids_json"])
        ),
        review_status=row["review_status"],
    )


def _composite_report_from_row(row) -> CompositeApprovalReport:
    return CompositeApprovalReport(
        report_id=row["report_id"],
        cohort_id=row["cohort_id"],
        case_id=row["case_id"],
        overall_judgment=row["overall_judgment"],
        key_risks=tuple(json.loads(row["key_risks_json"])),
        mitigating_factors=tuple(json.loads(row["mitigating_factors_json"])),
        judgment_boundaries=tuple(json.loads(row["judgment_boundaries_json"])),
        verification_priorities=tuple(
            json.loads(row["verification_priorities_json"])
        ),
        source_domain_report_ids=tuple(
            json.loads(row["source_domain_report_ids_json"])
        ),
        evidence_refs=_load_evidence_refs(row["evidence_refs_json"]),
        review_status=row["review_status"],
    )


def _overall_assessment_from_row(row) -> EnterpriseOverallAssessment:
    return EnterpriseOverallAssessment(
        assessment_id=row["assessment_id"],
        cohort_id=row["cohort_id"],
        case_id=row["case_id"],
        rating_level=row["rating_level"],
        overall_judgment=row["overall_judgment"],
        rating_rationale=tuple(
            OverallAssessmentRationale(**item)
            for item in json.loads(row["rating_rationale_json"])
        ),
        core_risks=tuple(json.loads(row["core_risks_json"])),
        mitigating_factors=tuple(json.loads(row["mitigating_factors_json"])),
        rating_boundaries=tuple(json.loads(row["rating_boundaries_json"])),
        verification_priorities=tuple(
            json.loads(row["verification_priorities_json"])
        ),
        source_direction_report_ids=tuple(
            json.loads(row["source_direction_report_ids_json"])
        ),
        source_direction_ranking_sections=tuple(
            json.loads(row["source_direction_ranking_sections_json"])
        ),
        evidence_refs=_load_evidence_refs(row["evidence_refs_json"]),
        recommendation=row["recommendation"],
        strong_constraint_failed_count=row["strong_constraint_failed_count"],
        weak_constraint_failed_count=row["weak_constraint_failed_count"],
        direction_results=tuple(
            FinalDirectionResult(
                **{
                    **item,
                    "strong_constraint_trigger_evidence_unit_ids": tuple(
                        item.get("strong_constraint_trigger_evidence_unit_ids", [])
                    ),
                }
            )
            for item in json.loads(row["direction_results_json"])
        ),
        is_experimental=bool(row["is_experimental"]),
        review_status=row["review_status"],
    )


def _dump_evidence_refs(evidence_refs: tuple[EvidenceReference, ...]) -> str:
    return json.dumps([reference.__dict__ for reference in evidence_refs], ensure_ascii=False)


def _load_evidence_refs(raw: str) -> tuple[EvidenceReference, ...]:
    return tuple(EvidenceReference(**reference) for reference in json.loads(raw))
