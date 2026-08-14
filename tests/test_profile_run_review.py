from __future__ import annotations

import json
from pathlib import Path

from src.profiles import (
    ProfileRepository,
    aggregate_profile_run,
    finalize_and_save_profile_review,
)


def _item(item_id, field_id, section_id, value, evidence_id):
    value_type = "entity_ref"
    return {
        "item_id": item_id,
        "section_id": section_id,
        "field_id": field_id,
        "value": value,
        "value_type": value_type,
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": [evidence_id],
    }


def test_aggregate_profile_run_scopes_ids_and_collects_diagnostics():
    run = {
        "case_id": "ZJ",
        "profile_type": "historical",
        "domains": [
            {
                "domain": "technology_and_ip",
                "candidates": {
                    "profile_items": [
                        _item("t1", "technology.name", "technology_ip", "光存储技术", "src:1")
                    ],
                    "profile_relations": [
                        {
                            "relation_id": "r1",
                            "relation_type": "develops",
                            "source_id": "enterprise",
                            "source_type": "Enterprise",
                            "target_id": "t1",
                            "target_type": "Technology",
                            "information_status": "claimed",
                            "content_role": "enterprise_claim",
                            "evidence_unit_ids": ["src:1"],
                        }
                    ],
                    "information_gaps": [
                        "技术权属待核实",
                        "缺少企业法定名称，无法关联核心技术。",
                    ],
                    "conflicts": [],
                    "unmapped_items": [],
                    "rejected_candidates": [{"kind": "profile_items", "reason": "越界"}],
                    "consistency_warnings": [{"item_id": "t1", "reason": "待核实"}],
                },
            },
            {
                "domain": "product_and_project",
                "candidates": {
                    "profile_items": [
                        _item(
                            "t1",
                            "product.name",
                            "product_research_commercialization",
                            "光存储设备",
                            "src:2",
                        )
                    ],
                    "profile_relations": [],
                    "information_gaps": [],
                    "conflicts": [],
                    "unmapped_items": [],
                },
            },
        ],
    }

    bundle = aggregate_profile_run(run)

    assert [item["item_id"] for item in bundle["candidates"]["profile_items"]] == [
        "technology_and_ip:t1",
        "product_and_project:t1",
    ]
    assert bundle["candidates"]["profile_relations"][0]["target_id"] == "technology_and_ip:t1"
    assert bundle["candidates"]["information_gaps"] == [
        "technology_and_ip: 技术权属待核实"
    ]
    assert bundle["evidence_unit_ids"] == ["src:1", "src:2"]
    assert bundle["diagnostics"]["rejected_candidates"][0]["domain"] == "technology_and_ip"
    assert len(bundle["diagnostics"]["rejected_candidates"]) == 2


def test_aggregated_profile_run_can_be_approved_and_saved(tmp_path):
    run = {
        "case_id": "ZJ",
        "profile_type": "historical",
        "domains": [
            {
                "domain": "technology_and_ip",
                "candidates": {
                    "profile_items": [
                        _item("t1", "technology.name", "technology_ip", "光存储技术", "src:1")
                    ],
                    "profile_relations": [],
                    "information_gaps": [],
                    "conflicts": [],
                    "unmapped_items": [],
                },
            }
        ],
    }
    bundle = aggregate_profile_run(run)
    repository = ProfileRepository(tmp_path / "profiles.db")

    profile = finalize_and_save_profile_review(
        bundle["candidates"],
        repository=repository,
        evidence_unit_ids=bundle["evidence_unit_ids"],
        decision="accept",
        profile_id="zj-profile",
        case_id=bundle["case_id"],
        enterprise_name="紫晶存储",
        profile_type=bundle["profile_type"],
    )

    assert profile is not None and profile.review_status == "approved"
    assert repository.get("zj-profile").items[0].item_id == "technology_and_ip:t1"


def test_aggregate_profile_run_repairs_duplicate_model_ids():
    run = {
        "case_id": "ROUYU",
        "profile_type": "current",
        "domains": [
            {
                "domain": "technology_and_ip",
                "candidates": {
                    "profile_items": [
                        _item("ip1", "intellectual_property.name", "technology_ip", "专利组合", "src:1"),
                        {
                            **_item(
                                "ip1",
                                "intellectual_property.patent_grant_count",
                                "technology_ip",
                                1102,
                                "src:1",
                            ),
                            "value_type": "integer",
                        },
                    ],
                    "profile_relations": [
                        {
                            "relation_id": "r1",
                            "relation_type": "claims_to_own",
                            "source_id": "the_enterprise",
                            "source_type": "Enterprise",
                            "target_id": "ip1",
                            "target_type": "IntellectualProperty",
                            "information_status": "claimed",
                            "content_role": "enterprise_claim",
                            "evidence_unit_ids": ["src:1"],
                        }
                    ],
                    "information_gaps": [],
                    "conflicts": [],
                    "unmapped_items": [],
                },
            }
        ],
    }

    bundle = aggregate_profile_run(run)

    assert [item["item_id"] for item in bundle["candidates"]["profile_items"]] == [
        "technology_and_ip:ip1",
        "technology_and_ip:ip1:2",
    ]
    assert bundle["candidates"]["profile_relations"][0]["target_id"] == "technology_and_ip:ip1"
    assert bundle["diagnostics"]["renamed_duplicate_ids"] == [
        {
            "domain": "technology_and_ip",
            "kind": "profile_items",
            "original_id": "ip1",
            "assigned_id": "technology_and_ip:ip1:2",
        }
    ]


def test_fixed_technology_subset_fixture_is_reviewable():
    path = Path(__file__).resolve().parents[1] / "eval_data" / "v5_technology_subset_profile_run.json"
    bundle = aggregate_profile_run(json.loads(path.read_text(encoding="utf-8")))

    assert bundle["profile_type"] == "historical"
    assert len(bundle["candidates"]["profile_items"]) == 3
    assert bundle["evidence_unit_ids"] == ["src_92c9bd753dea8be0:eu_00296"]
