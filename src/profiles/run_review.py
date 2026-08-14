"""把分领域画像抽取结果整理为一次可审核的正式画像候选。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .candidates import is_cross_domain_legal_name_gap


def aggregate_profile_run(run: dict[str, Any]) -> dict[str, Any]:
    """合并各领域候选，并为模型生成的局部 ID 加上领域前缀。"""
    profile_type = run.get("profile_type")
    if profile_type not in {"historical", "current"}:
        raise ValueError("画像运行结果缺少合法的 profile_type。")
    case_id = str(run.get("case_id", "")).strip()
    if not case_id:
        raise ValueError("画像运行结果缺少 case_id。")
    domains = run.get("domains")
    if not isinstance(domains, list):
        raise ValueError("画像运行结果的 domains 必须是数组。")

    candidates: dict[str, list[Any]] = {
        "profile_items": [],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    evidence_ids: set[str] = set()
    diagnostics = {
        "domains_with_candidates": [],
        "rejected_candidates": [],
        "consistency_warnings": [],
        "deduplicated_candidates": [],
        "renamed_duplicate_ids": [],
    }

    for domain_result in domains:
        if not isinstance(domain_result, dict):
            continue
        domain = str(domain_result.get("domain", "unknown"))
        extracted = domain_result.get("candidates")
        if not isinstance(extracted, dict):
            continue
        diagnostics["domains_with_candidates"].append(domain)

        raw_items = extracted.get("profile_items", [])
        item_id_map: dict[str, str] = {}
        used_item_ids: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict) or "item_id" not in raw_item:
                continue
            raw_id = str(raw_item["item_id"])
            scoped_id = _unique_scoped_id(domain, raw_id, used_item_ids)
            item_id_map.setdefault(raw_id, scoped_id)
            if scoped_id != _scoped_id(domain, raw_id):
                diagnostics["renamed_duplicate_ids"].append(
                    {
                        "domain": domain,
                        "kind": "profile_items",
                        "original_id": raw_id,
                        "assigned_id": scoped_id,
                    }
                )
            item = deepcopy(raw_item)
            item["item_id"] = scoped_id
            candidates["profile_items"].append(item)
            evidence_ids.update(_evidence_ids(item))

        used_relation_ids: set[str] = set()
        for raw_relation in extracted.get("profile_relations", []):
            if not isinstance(raw_relation, dict) or "relation_id" not in raw_relation:
                continue
            relation = deepcopy(raw_relation)
            raw_id = str(raw_relation["relation_id"])
            scoped_id = _unique_scoped_id(domain, raw_id, used_relation_ids)
            if scoped_id != _scoped_id(domain, raw_id):
                diagnostics["renamed_duplicate_ids"].append(
                    {
                        "domain": domain,
                        "kind": "profile_relations",
                        "original_id": raw_id,
                        "assigned_id": scoped_id,
                    }
                )
            relation["relation_id"] = scoped_id
            for key in ("source_id", "target_id"):
                raw_id = str(relation.get(key, ""))
                if raw_id in item_id_map:
                    relation[key] = item_id_map[raw_id]
            candidates["profile_relations"].append(relation)
            evidence_ids.update(_evidence_ids(relation))

        for value in extracted.get("information_gaps", []):
            if not isinstance(value, str) or not value.strip():
                continue
            if is_cross_domain_legal_name_gap(value, domain=domain):
                diagnostics["rejected_candidates"].append(
                    {
                        "domain": domain,
                        "kind": "information_gaps",
                        "reason": "企业法定名称属于 enterprise_and_control，不应作为当前领域信息缺口。",
                    }
                )
                continue
            candidates["information_gaps"].append(f"{domain}: {value.strip()}")
        candidates["conflicts"].extend(
            f"{domain}: {value.strip()}"
            for value in extracted.get("conflicts", [])
            if isinstance(value, str) and value.strip()
        )
        for value in extracted.get("unmapped_items", []):
            candidates["unmapped_items"].append({"domain": domain, "value": value})
        for key in (
            "rejected_candidates",
            "consistency_warnings",
            "deduplicated_candidates",
        ):
            diagnostics[key].extend(
                {"domain": domain, **value}
                for value in extracted.get(key, [])
                if isinstance(value, dict)
            )

    return {
        "case_id": case_id,
        "profile_type": profile_type,
        "candidates": candidates,
        "evidence_unit_ids": sorted(evidence_ids),
        "diagnostics": diagnostics,
    }


def _scoped_id(domain: str, value: Any) -> str:
    return f"{domain}:{value}"


def _unique_scoped_id(domain: str, value: Any, used_ids: set[str]) -> str:
    base = _scoped_id(domain, value)
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}:{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _evidence_ids(candidate: dict[str, Any]) -> list[str]:
    values = candidate.get("evidence_unit_ids", [])
    return [value for value in values if isinstance(value, str) and value]
