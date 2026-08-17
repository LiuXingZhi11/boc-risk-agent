from __future__ import annotations

import json

from src.ui.v5_services import (
    approve_peer_cohort,
    approve_profile_review,
    create_peer_cohort,
    ingest_uploaded_source,
    load_profile_review,
    profile_rows,
    run_domain_investigation,
    run_react_domain_investigation,
    run_react_profile_investigation,
    source_rows,
)
from src.profiles.historical_workflow import HistoricalProfileRun


def test_v5_source_workspace_ingests_html(tmp_path):
    database = tmp_path / "v5.db"
    result = ingest_uploaded_source(
        database=database,
        case_id="TECH1",
        upload_root=tmp_path / "uploads",
        filename="notice.html",
        content=b"<h1>core technology</h1><p>company technology</p>",
    )
    rows = source_rows(database, "TECH1")
    assert result["evidence_units"] >= 1
    assert rows[0]["case_id"] == "TECH1"
    assert rows[0]["evidence_units"] == result["evidence_units"]


def test_v5_review_workspace_approves_profile(tmp_path):
    run = {
        "case_id": "TECH1",
        "profile_type": "historical",
        "domains": [
            {
                "domain": "technology_and_ip",
                "candidates": {
                    "profile_items": [
                        {
                            "item_id": "t1",
                            "section_id": "technology_ip",
                            "field_id": "technology.name",
                            "value": "core technology",
                            "value_type": "entity_ref",
                            "information_status": "claimed",
                            "content_role": "enterprise_claim",
                            "evidence_unit_ids": ["src:1"],
                        }
                    ],
                    "profile_relations": [],
                    "information_gaps": [],
                    "conflicts": [],
                    "unmapped_items": [],
                },
            }
        ],
    }
    database = tmp_path / "v5.db"
    bundle = load_profile_review(json.dumps(run, ensure_ascii=False))
    saved = approve_profile_review(
        database=database,
        bundle=bundle,
        profile_id="tech1-profile",
        enterprise_name="Test Technology",
    )
    assert saved["review_status"] == "approved"
    assert profile_rows(database)[0]["profile_id"] == "tech1-profile"


def test_v5_peer_cohort_can_be_created_and_approved(tmp_path):
    database = tmp_path / "v5.db"
    created = create_peer_cohort(
        database=database,
        cohort_id="robotics-v2",
        industry_id="robotics_industry_2026",
        cohort_name="机器人同行样本 V2",
        fiscal_period="2025",
        company_case_ids=("TECH1", "TECH2"),
        selection_rule="已批准企业画像",
    )
    assert created["review_status"] == "pending"

    approved = approve_peer_cohort(database=database, cohort_id="robotics-v2")
    assert approved["review_status"] == "approved"


def test_v5_domain_investigation_uses_historical_workflow(monkeypatch, tmp_path):
    captured = {}

    def fake_run(self, **kwargs):
        captured.update(kwargs)
        return HistoricalProfileRun(case_id=kwargs["case_id"])

    monkeypatch.setattr("src.ui.v5_services.HistoricalProfileWorkflow.run", fake_run)
    result = run_domain_investigation(
        database=tmp_path / "v5.db",
        case_id="TECH1",
        profile_type="historical",
        domains=("technology_and_ip",),
    )
    assert result["case_id"] == "TECH1"
    assert result["profile_type"] == "historical"
    assert captured["domains"] == ("technology_and_ip",)
    assert captured["selection_config"].mode == "thinking"
    assert captured["extraction_config"].mode == "sampling"


def test_v5_react_investigation_uses_controlled_workflow(monkeypatch, tmp_path):
    captured = {}

    def fake_run(self, **kwargs):
        captured.update(kwargs)
        from src.profiles.react_models import ReactProfileRun

        return ReactProfileRun(case_id=kwargs["case_id"])

    monkeypatch.setattr(
        "src.ui.v5_services.ControlledReactProfileWorkflow.run_current_domain",
        fake_run,
    )
    result = run_react_domain_investigation(
        database=tmp_path / "v5.db",
        case_id="TECH1",
        domain="technology_and_ip",
        max_catalog_items=8,
        max_read_units=4,
    )
    assert result["execution_mode"] == "react"
    assert captured["domain"] == "technology_and_ip"
    assert captured["react_config"].mode == "thinking"
    assert captured["extraction_config"].mode == "sampling"
    assert captured["limits"].max_catalog_items == 8
    assert captured["limits"].max_read_units == 4


def test_v5_react_profile_investigation_merges_selected_domains(monkeypatch, tmp_path):
    calls = []

    def fake_domain(**kwargs):
        calls.append(kwargs["domain"])
        return {"domains": [{"domain": kwargs["domain"], "status": "pending_review"}]}

    monkeypatch.setattr("src.ui.v5_services.run_react_domain_investigation", fake_domain)
    result = run_react_profile_investigation(
        database=tmp_path / "v5.db",
        case_id="TECH1",
        domains=("technology_and_ip", "team"),
    )

    assert calls == ["technology_and_ip", "team"]
    assert [item["domain"] for item in result["domains"]] == [
        "technology_and_ip",
        "team",
    ]
