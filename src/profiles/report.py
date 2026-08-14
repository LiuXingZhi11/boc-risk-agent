"""把已校验的 V5 详细比较确定性汇总为辅助审查报告。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .candidates import is_cross_domain_legal_name_gap
from .detailed_comparison import DetailedComparisonRun, HistoricalProfileComparison
from .models import CurrentEnterpriseProfile
from .risk_judgment import CoreRiskJudgment, RiskJudgmentPoint


DISCLAIMER = (
    "本报告仅汇总当前企业画像与历史企业画像的证据化比较，"
    "用于历史参考和信息核实辅助，不构成授信审批、风险定级或业务决策结论。"
)


@dataclass(frozen=True)
class V5ReviewReport:
    current_profile_id: str
    case_id: str
    enterprise_name: str
    core_risk_judgment: CoreRiskJudgment | None
    summary: str
    comparisons: tuple[HistoricalProfileComparison, ...]
    information_gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    verification_questions: tuple[str, ...]
    evidence_unit_ids: tuple[str, ...]
    industry_evidence_unit_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.enterprise_name}辅助审查报告",
            "",
            self.disclaimer,
        ]
        if self.core_risk_judgment is not None:
            judgment = self.core_risk_judgment
            lines.extend(["", "## 核心风险判断", "", judgment.overall_judgment])
            if judgment.industry_name:
                lines.extend(
                    ["", f"采用的行业背景：{judgment.industry_name}（仅作为行业环境参考）"]
                )
            _append_risk_points(lines, "最需要关注的风险", judgment.key_risks)
            _append_risk_points(lines, "缓释因素", judgment.mitigating_factors)
            _append_strings(lines, "判断中的不确定性", judgment.uncertainties, level=3)
            _append_strings(lines, "优先核实事项", judgment.verification_priorities, level=3)
        lines.extend(["", "## 汇总", "", self.summary])
        for comparison in self.comparisons:
            lines.extend(
                [
                    "",
                    f"## 历史参考：{comparison.historical_enterprise_name}",
                    "",
                    f"召回分数（仅用于候选排序）：{comparison.retrieval_score:.4f}",
                ]
            )
            _append_points(lines, "相似依据", comparison.similarity_basis)
            _append_points(lines, "关键差异", comparison.key_differences)
            _append_points(lines, "历史结果", comparison.historical_outcomes)
            _append_strings(lines, "适用限制", comparison.applicability_limits)
        _append_strings(lines, "当前画像信息缺口", self.information_gaps)
        _append_strings(lines, "当前画像冲突", self.conflicts)
        _append_strings(lines, "待核实问题", self.verification_questions)
        _append_strings(lines, "证据索引", self.evidence_unit_ids)
        _append_strings(lines, "行业背景证据索引", self.industry_evidence_unit_ids)
        return "\n".join(lines).strip() + "\n"


def build_v5_review_report(
    current: CurrentEnterpriseProfile,
    comparison_run: DetailedComparisonRun,
    core_risk_judgment: CoreRiskJudgment | None = None,
) -> V5ReviewReport:
    if current.review_status != "approved":
        raise ValueError("只有 approved 当前画像才能生成报告。")
    if comparison_run.current_profile_id != current.profile_id:
        raise ValueError("详细比较结果与当前画像不匹配。")
    if (
        core_risk_judgment is not None
        and core_risk_judgment.current_profile_id != current.profile_id
    ):
        raise ValueError("核心风险判断与当前画像不匹配。")
    comparisons = comparison_run.comparisons
    similarities = sum(len(item.similarity_basis) for item in comparisons)
    differences = sum(len(item.key_differences) for item in comparisons)
    outcomes = sum(len(item.historical_outcomes) for item in comparisons)
    summary = (
        f"已与 {len(comparisons)} 个历史企业画像完成比较，"
        f"形成 {similarities} 条相似依据、{differences} 条关键差异和"
        f" {outcomes} 条历史结果参考。"
    )
    if not comparisons:
        summary = "当前没有可用的历史企业详细比较结果。"
    questions = _unique(
        question
        for comparison in comparisons
        for question in comparison.verification_questions
    )
    comparison_evidence = (
        evidence_id
        for comparison in comparisons
        for group in (
            comparison.similarity_basis,
            comparison.key_differences,
            comparison.historical_outcomes,
        )
        for point in group
        for evidence_id in point.evidence_unit_ids
    )
    risk_evidence = (
        core_risk_judgment.evidence_unit_ids if core_risk_judgment is not None else ()
    )
    evidence = _unique((*risk_evidence, *comparison_evidence))
    limitations = _unique(
        limitation
        for comparison in comparisons
        for limitation in comparison.applicability_limits
    )
    if not comparisons:
        limitations = ("未获得可用历史比较结果，不能据此推断当前企业风险。",)
    return V5ReviewReport(
        current_profile_id=current.profile_id,
        case_id=current.case_id,
        enterprise_name=current.enterprise_name,
        core_risk_judgment=core_risk_judgment,
        summary=summary,
        comparisons=comparisons,
        information_gaps=tuple(
            gap for gap in current.information_gaps if not is_cross_domain_legal_name_gap(gap)
        ),
        conflicts=current.conflicts,
        verification_questions=questions,
        evidence_unit_ids=evidence,
        industry_evidence_unit_ids=(
            core_risk_judgment.industry_evidence_unit_ids
            if core_risk_judgment is not None
            else ()
        ),
        limitations=limitations,
    )


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _append_points(lines: list[str], title: str, points) -> None:
    if not points:
        return
    lines.extend(["", f"### {title}", ""])
    lines.extend(f"- {point.explanation}" for point in points)


def _append_risk_points(
    lines: list[str], title: str, points: tuple[RiskJudgmentPoint, ...]
) -> None:
    if not points:
        return
    lines.extend(["", f"### {title}", ""])
    lines.extend(f"- **{point.title}**：{point.explanation}" for point in points)


def _append_strings(lines: list[str], title: str, values, *, level: int = 2) -> None:
    if not values:
        return
    lines.extend(["", f"{'#' * level} {title}", ""])
    lines.extend(f"- {value}" for value in values)
