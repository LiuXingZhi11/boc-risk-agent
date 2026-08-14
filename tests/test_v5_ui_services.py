from __future__ import annotations

import json

from src.ui.v5_services import (
    approve_profile_review,
    ingest_uploaded_source,
    load_profile_review,
    profile_rows,
    run_domain_investigation,
    run_react_domain_investigation,
    source_rows,
)
from src.profiles.historical_workflow import HistoricalProfileRun
from src.profiles import (
    ComparisonCardRepository,
    ComparisonDimension,
    CurrentEnterpriseProfile,
    EnterpriseComparisonCard,
    ProfileRepository,
    profile_content_hash,
)
from src.ui.v5_services import run_detailed_review_report
from src.profiles.risk_judgment import CoreRiskJudgment
from src.industry import IndustryBackgroundProfile, IndustryProfileRepository


def test_v5_source_workspace_ingests_html(tmp_path):
    database = tmp_path / "v5.db"
    result = ingest_uploaded_source(
        database=database,
        case_id="TECH1",
        upload_root=tmp_path / "uploads",
        filename="notice.html",
        content="<h1>核心技术</h1><p>公司形成自主技术。</p>".encode("utf-8"),
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
                            "value": "光存储技术",
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
        enterprise_name="测试科技企业",
    )

    assert saved["review_status"] == "approved"
    assert profile_rows(database)[0]["profile_id"] == "tech1-profile"


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
    assert captured["extraction_config"].temperature == 0.1
    assert captured["limits"].max_catalog_items == 8
    assert captured["limits"].max_read_units == 4


def test_v5_detailed_report_skips_comparison_but_generates_risk_when_no_history(monkeypatch, tmp_path):
    database = tmp_path / "v5.db"
    current = CurrentEnterpriseProfile(
        profile_id="current-profile",
        case_id="CURRENT",
        enterprise_name="当前企业",
        review_status="approved",
    )
    ProfileRepository(database).save(current)
    card = EnterpriseComparisonCard(
        card_id="current-card",
        profile_id=current.profile_id,
        case_id=current.case_id,
        enterprise_name=current.enterprise_name,
        profile_type="current",
        ontology_version=current.ontology_version,
        profile_hash=profile_content_hash(current),
        dimensions=(
            ComparisonDimension(
                dimension_id="technology_and_ip",
                summary="当前技术信息有限。",
                comparison_terms=("技术",),
            ),
        ),
        review_status="approved",
    )
    ComparisonCardRepository(database).save(card)
    industry = IndustryBackgroundProfile(
        profile_id="industry-profile",
        industry_id="robotics",
        industry_name="机器人",
        source_ids=(),
        insights=(),
        review_status="approved",
    )
    IndustryProfileRepository(database).save(industry)
    captured = {}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("没有历史候选时不应调用详细比较")

    monkeypatch.setattr("src.ui.v5_services.compare_profile_candidates", fail_if_called)
    def fake_risk_judgment(current, comparison, **kwargs):
        captured.update(kwargs)
        return CoreRiskJudgment(
            current_profile_id=current.profile_id,
            overall_judgment="当前材料有限，核心风险判断仍需更多企业事实支持。",
            key_risks=(),
            mitigating_factors=(),
            uncertainties=("当前材料尚未形成完整企业画像。",),
            verification_priorities=("优先补充能够证明企业核心情况的材料。",),
            evidence_unit_ids=(),
            api_meta={"model": "fake-model"},
            industry_profile_id=kwargs["industry_profile"].profile_id,
            industry_name=kwargs["industry_profile"].industry_name,
        )

    monkeypatch.setattr(
        "src.ui.v5_services.generate_core_risk_judgment",
        fake_risk_judgment,
    )
    result = run_detailed_review_report(
        database=database,
        current_profile_id=current.profile_id,
        current_card_id=card.card_id,
        industry_profile_id=industry.profile_id,
    )

    assert result["detailed_comparison"]["api_meta"]["skipped"] is True
    assert result["report"]["comparisons"] == ()
    assert result["core_risk_judgment"]["api_meta"]["model"] == "fake-model"
    assert captured["industry_profile"].profile_id == industry.profile_id
    assert "## 核心风险判断" in result["report_markdown"]
