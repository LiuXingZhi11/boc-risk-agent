"""企业画像各调查领域共用的本地证据召回。"""

from __future__ import annotations

from collections.abc import Iterable

from src.evidence.models import EvidenceUnit
from src.evidence.service import EvidenceQueryService


TEAM_PERSON_LIMIT = 30
TEAM_CONTEXT_LIMIT = 8


def search_balanced_evidence(
    evidence_service: EvidenceQueryService,
    *,
    case_id: str,
    keywords: Iterable[str],
    limit: int,
) -> list[EvidenceUnit]:
    """轮询各关键词，并优先保留来自不同章节的证据。"""
    queries = tuple(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
    if limit <= 0 or not queries:
        return []

    buckets = [
        evidence_service.search_evidence(query, case_id=case_id, top_k=limit)
        for query in queries
    ]
    interleaved: list[EvidenceUnit] = []
    seen_ids: set[str] = set()
    positions = [0] * len(buckets)
    while True:
        added = False
        for index, bucket in enumerate(buckets):
            while (
                positions[index] < len(bucket)
                and bucket[positions[index]].evidence_unit_id in seen_ids
            ):
                positions[index] += 1
            if positions[index] >= len(bucket):
                continue
            unit = bucket[positions[index]]
            positions[index] += 1
            seen_ids.add(unit.evidence_unit_id)
            interleaved.append(unit)
            added = True
        if not added:
            break

    diverse: list[EvidenceUnit] = []
    repeated_sections: list[EvidenceUnit] = []
    seen_sections: set[tuple[str, ...]] = set()
    for unit in interleaved:
        section_key = _section_key(unit)
        if section_key in seen_sections:
            repeated_sections.append(unit)
        else:
            diverse.append(unit)
            seen_sections.add(section_key)
    return (diverse + repeated_sections)[:limit]


def build_team_evidence_bundle(
    evidence_service: EvidenceQueryService,
    *,
    case_id: str,
    person_limit: int = TEAM_PERSON_LIMIT,
    context_limit: int = TEAM_CONTEXT_LIMIT,
) -> list[EvidenceUnit]:
    """组合人员名单、团队上下文和人物履历；没有人物结构时返回空列表。"""
    units = evidence_service.list_evidence(case_id=case_id)
    people = [
        unit
        for unit in units
        if unit.metadata.get("block_type") == "person_biography"
    ][:person_limit]
    if not people:
        return []

    context_groups: dict[int, list[EvidenceUnit]] = {index: [] for index in range(5)}
    for unit in units:
        if unit.metadata.get("block_type") == "person_biography":
            continue
        priority = _team_context_priority(unit)
        if priority is not None:
            context_groups[priority].append(unit)
    team_summary = context_groups[2][:2]
    if len(team_summary) < 2:
        team_summary += context_groups[3][: 2 - len(team_summary)]
    context = (
        context_groups[0][:2]
        + context_groups[1][:1]
        + team_summary
        + context_groups[4][:3]
    )[:context_limit]
    selected: list[EvidenceUnit] = []
    seen_ids: set[str] = set()
    for unit in (*context, *people):
        if unit.evidence_unit_id not in seen_ids:
            selected.append(unit)
            seen_ids.add(unit.evidence_unit_id)
    return selected


def _team_context_priority(unit: EvidenceUnit) -> int | None:
    title = str(unit.metadata.get("title", ""))
    structure_text = "\n".join(
        (
            title,
            " ".join(str(value) for value in unit.metadata.get("section_path", [])),
        )
    )
    text = f"{structure_text}\n{unit.content}"
    if "姓名" in text and "职务" in text and any(
        term in text for term in ("核心技术人员", "高级管理人员", "董事长")
    ):
        return 0
    if len(unit.content) <= 600 and (
        "实际控制人情况" in title
        or any(term in unit.content for term in ("实际控制人为", "实际控制人是", "共同实际控制人"))
    ):
        return 1
    if any(
        term in structure_text
        for term in (
            "研发团队概况",
            "核心技术人员情况",
            "人员构成",
            "学历结构",
            "教育结构",
            "专业构成",
        )
    ):
        return 2
    if "研发人员" in unit.content and any(
        term in unit.content for term in ("学历", "员工总数", "人员构成")
    ):
        return 3
    if any(
        term in structure_text
        for term in (
            "股权激励情况",
            "股权激励计划",
            "相关激励事项",
            "临时公告未披露或有后续进展的激励情况",
            "限制性股票",
            "股票期权",
        )
    ):
        return 4
    return None


def _section_key(unit: EvidenceUnit) -> tuple[str, ...]:
    path = tuple(str(part) for part in unit.metadata.get("section_path", []) if part)
    if path:
        return (unit.source_id, *path)
    title = str(unit.metadata.get("title", "")).strip()
    return (unit.source_id, title or unit.evidence_unit_id)
