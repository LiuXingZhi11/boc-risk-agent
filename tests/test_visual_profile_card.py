from __future__ import annotations

from src.evidence.models import EvidenceUnit
from src.profiles import (
    EvidenceReference,
    HistoricalEnterpriseProfile,
    ProfileItem,
    build_enterprise_visual_card,
)


def _item(item_id: str, field_id: str, section_id: str, value: object, role: str, *, period: str | None = None) -> ProfileItem:
    return ProfileItem(
        item_id=item_id,
        field_id=field_id,
        section_id=section_id,
        value=value,
        value_type="ratio" if field_id == "finance.customer_concentration" else "entity_ref",
        information_status="confirmed" if role == "regulatory_finding" else "claimed",
        content_role=role,
        evidence_refs=(EvidenceReference("src:eu_1"),),
        reporting_period=period,
        review_status="accepted",
    )


def test_visual_card_groups_facts_labels_evidence_and_historical_outcomes():
    profile = HistoricalEnterpriseProfile(
        profile_id="h1",
        case_id="case-h1",
        enterprise_name="历史企业",
        review_status="approved",
        information_gaps=("缺少独立验证",),
        items=(
            _item("tech", "technology.name", "technology_ip", "核心技术", "enterprise_claim"),
            _item("risk", "risk.matter", "compliance_legal_risk", "信息披露违法", "regulatory_finding"),
            _item("result", "risk.matter", "compliance_legal_risk", "终止上市", "outcome"),
            _item("ratio", "finance.customer_concentration", "finance_capital", 0.7236, "enterprise_claim", period="2024"),
        ),
    )
    evidence = EvidenceUnit(
        evidence_unit_id="src:eu_1",
        source_id="src",
        case_id="case-h1",
        content_type="document_chunk",
        content="监管文件正文",
        location={"kind": "pdf", "page_start": 4, "page_end": 4},
        metadata={"title": "监管决定书"},
        content_hash="hash",
    )

    card = build_enterprise_visual_card(profile, evidence_by_id={evidence.evidence_unit_id: evidence})

    technology = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    finance = next(item for item in card.dimensions if item.dimension_id == "finance_and_funding")
    assert technology.facts[0].field_label == "核心技术"
    assert technology.facts[0].evidence[0].location == "PDF 第 4 页"
    assert finance.facts[0].value == "72.36%"
    assert card.authority_fact_count == 2
    assert [item.value for item in card.historical_outcomes] == ["终止上市"]
    assert card.information_gaps == ("缺少独立验证",)


def test_current_visual_card_does_not_expose_historical_outcomes_area():
    from src.profiles import CurrentEnterpriseProfile

    profile = CurrentEnterpriseProfile(
        profile_id="c1",
        case_id="case-c1",
        enterprise_name="当前企业",
        items=(_item("tech", "technology.name", "technology_ip", "核心技术", "enterprise_claim"),),
    )

    assert build_enterprise_visual_card(profile).historical_outcomes == ()


def test_visual_card_does_not_repeat_ratio_unit():
    profile = HistoricalEnterpriseProfile(
        profile_id="h2",
        case_id="case-h2",
        enterprise_name="历史企业",
        items=(
            ProfileItem(
                item_id="ratio",
                field_id="finance.customer_concentration",
                section_id="finance_capital",
                value="72.36%",
                value_type="ratio",
                information_status="claimed",
                content_role="enterprise_claim",
                evidence_refs=(EvidenceReference("src:eu_1"),),
                reporting_period="2024",
                unit="%",
            ),
        ),
    )

    card = build_enterprise_visual_card(profile)

    finance = next(item for item in card.dimensions if item.dimension_id == "finance_and_funding")
    assert finance.facts[0].value == "72.36%"


def test_visual_card_keeps_hierarchical_count_scopes_together():
    from src.profiles import CurrentEnterpriseProfile

    def patent(item_id: str, value: int, scope: str) -> ProfileItem:
        return ProfileItem(
            item_id=item_id,
            field_id="intellectual_property.patent_grant_count",
            section_id="technology_ip",
            value=value,
            value_type="integer",
            information_status="claimed",
            content_role="enterprise_claim",
            evidence_refs=(EvidenceReference("src:eu_patent"),),
            subject="the_enterprise",
            value_scope=scope,
            reporting_period="截至 2026 年 1 月 31 日",
            review_status="accepted",
        )

    profile = CurrentEnterpriseProfile(
        profile_id="c-patent",
        case_id="case-patent",
        enterprise_name="当前企业",
        items=(
            patent("total", 262, "全部"),
            patent("domestic", 169, "境内"),
            patent("overseas", 93, "境外"),
            patent("design", 73, "境内外观设计"),
            patent("invention", 20, "境内发明专利"),
            patent("utility", 76, "境内实用新型"),
        ),
    )

    card = build_enterprise_visual_card(profile)
    technology = next(item for item in card.dimensions if item.dimension_id == "technology_and_ip")
    topic = next(item for item in technology.topics if item.topic_id == "ip_protection")
    assert "总计262项" in topic.summary
    assert "境内169项（包括境内外观设计73项、境内发明专利20项、境内实用新型76项）" in topic.summary
    assert "境外93项" in topic.summary
    assert "169、73、20、76、93、262" not in topic.summary
