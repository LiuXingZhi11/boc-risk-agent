from __future__ import annotations

from unittest.mock import patch

import pytest

from src.evidence import EvidenceQueryService, EvidenceRepository
from src.llm.generation_config import GenerationConfig
from src.ontology.registry import REGISTRY
from src.ontology.schema import OBJECT_TYPES, ONTOLOGY_VERSION, RELATION_TYPES, validate_relation
from src.profiles import (
    CurrentEnterpriseProfile,
    EvidenceReference,
    HistoricalEnterpriseProfile,
    ProfileItem,
    ProfileRelation,
    ProfileRepository,
    build_profile_from_candidates,
    filter_profile_candidates,
    finalize_profile_review,
    finalize_and_save_profile_review,
    validate_profile_candidates,
)
from src.profiles.extraction import (
    EvidenceSelectionResult,
    PROFILE_DOMAIN_FIELDS,
    build_evidence_selection_messages,
    build_profile_messages,
    extract_profile_candidates,
    filter_domain_candidates,
    _profile_extraction_batches,
)
from src.profiles.candidates import _number_value_in_text, _ratio_value_in_text
from src.profiles.evidence_discovery import build_team_evidence_bundle, search_balanced_evidence
from src.profiles.historical_workflow import HISTORICAL_DOMAIN_QUERIES, HistoricalProfileWorkflow
from src.profiles.current_workflow import CurrentProfileWorkflow
from src.sources import ingest_source
from src.sources.pdf_adapter import PdfSourceAdapter
from src.sources.pdf_chunker import detect_heading_level, split_pdf_pages


def test_html_adapter_extracts_content_and_skips_navigation(tmp_path):
    path = tmp_path / "notice.html"
    path.write_text(
        "<html><body><nav>菜单</nav><h1>处罚决定</h1><p>监管认定存在虚构销售。</p>"
        "<table><tr><th>项目</th><th>金额</th></tr><tr><td>收入</td><td>100</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )

    source, units = ingest_source(path, case_id="ZJ")

    assert source.source_type == "html"
    assert units
    assert all("菜单" not in unit.content for unit in units)
    assert any("虚构销售" in unit.content for unit in units)
    assert any(unit.metadata["block_type"] == "table_row" for unit in units)


def test_pdf_adapter_preserves_page_locations(tmp_path):
    path = tmp_path / "notice.pdf"
    path.write_bytes(b"%PDF-test")

    class Result:
        stdout = "第一页内容\f第二页内容".encode("utf-8")

    with patch("src.sources.pdf_adapter.shutil.which", return_value="pdftotext"), patch(
        "src.sources.pdf_adapter.subprocess.run", return_value=Result()
    ):
        _, units = PdfSourceAdapter().load(path, case_id="ZJ")

    assert len(units) == 1
    assert units[0].location == {"kind": "pdf", "page_start": 1, "page_end": 2}


def test_pdf_chunk_removes_table_of_contents_dot_leaders():
    content = "目录\n一、技术风险 ........ 36\n........................\n36\n二、财务风险 ........ 39\n39"

    chunks = split_pdf_pages([content])

    assert chunks == ()


def test_pdf_chunk_keeps_real_text_with_short_punctuation():
    content = "一、风险因素\n公司存在客户集中度较高风险。\n相关金额为 10.5 万元。"

    chunks = split_pdf_pages([content])

    assert [chunk.content for chunk in chunks] == [content]
    assert chunks[0].section_path == ("一、风险因素",)


def test_pdf_chunk_does_not_treat_financial_decimals_as_toc():
    content = """六、财务分析
项目 2018年度 2017年度 2016年度
营业收入 1,234.56 1,100.25 980.35
毛利率 23.12% 21.05% 19.80%
现金流 500.10 420.20 310.30"""

    chunks = split_pdf_pages([content])

    assert len(chunks) == 1
    assert "1,234.56" in chunks[0].content
    assert chunks[0].section_path == ("六、财务分析",)


def test_pdf_chunk_never_mixes_adjacent_sections_on_same_page():
    page = """1-1-168
（三）公司特许经营权情况
公司不存在特许经营权情况。
六、公司核心技术及研发能力情况
发行人形成了光存储介质核心技术体系。
（一）公司产品核心技术、技术来源及先进性
公司以自主研发创新为主。"""

    chunks = split_pdf_pages([page])

    assert len(chunks) == 3
    assert "特许经营权" in chunks[0].content
    assert "核心技术及研发能力" not in chunks[0].content
    assert "核心技术及研发能力" in chunks[1].content
    assert "产品核心技术" not in chunks[1].content
    assert chunks[2].section_path == (
        "六、公司核心技术及研发能力情况",
        "（一）公司产品核心技术、技术来源及先进性",
    )


def test_pdf_chunk_keeps_standalone_years_inside_tables():
    page = """招股说明书
1-1-142
（二）前五名供应商的采购情况
年度 供应商名称 采购金额 占比
2025
年度
供应商甲 100.00 10.00%
2024
年度
供应商乙 80.00 8.00%
142"""

    chunks = split_pdf_pages([page])
    table_chunk = chunks[-1]

    assert "2025\n年度" in table_chunk.content
    assert "2024\n年度" in table_chunk.content
    assert "1-1-142" not in table_chunk.content
    assert not table_chunk.content.endswith("142")


def test_pdf_chunk_inherits_section_path_across_pages_and_removes_headers():
    pages = [
        "科创板招股说明书\n1-1-169\n六、核心技术\n（一）技术来源\n公司主要采用自主研发。",
        "科创板招股说明书\n1-1-170\n公司继续开发大容量存储技术。",
        "科创板招股说明书\n1-1-171\n1、光存储介质核心技术\n已达到稳定量产能力。",
    ]

    chunks = split_pdf_pages(pages)

    assert len(chunks) == 2
    assert chunks[0].page_start == 1 and chunks[0].page_end == 2
    assert chunks[0].section_path == ("六、核心技术", "（一）技术来源")
    assert "科创板招股说明书" not in chunks[0].content
    assert chunks[1].section_path == (
        "六、核心技术",
        "（一）技术来源",
        "1、光存储介质核心技术",
    )


def test_pdf_chunk_splits_long_section_without_crossing_section_boundary():
    page = "一、技术情况\n" + "第一段技术内容。" * 12 + "\n二、财务情况\n财务内容。"

    chunks = split_pdf_pages([page], max_chars=50)

    assert len(chunks) >= 3
    assert all(
        not ("技术情况" in chunk.content and "财务情况" in chunk.content)
        for chunk in chunks
    )
    assert chunks[-1].section_path == ("二、财务情况",)


def test_pdf_chunk_splits_person_biographies_inside_section():
    pages = [
        """第八节 董事、监事、高级管理人员和员工情况
一、持股变动情况及报酬情况
(一) 现任人员情况
姓名 职务 性别
甲某 董事长 男
乙某 总经理 女
姓名 主要工作经历
甲某
男，中国国籍，1980年出生，本科学历。主要职业经历：曾任甲公司工程师。""",
        """乙某 女，中国国籍，1985年出生，硕士学历。主要职业经历：曾任乙公司经理。
其他情况说明
□适用 √不适用
(二) 董事、高级管理人员报告期内被授予的股权激励情况
□适用 √不适用""",
    ]

    chunks = split_pdf_pages(pages)
    biographies = [chunk for chunk in chunks if chunk.block_type == "person_biography"]

    assert [chunk.person_name for chunk in biographies] == ["甲某", "乙某"]
    assert biographies[0].page_start == 1
    assert biographies[1].page_start == 2
    assert all("股权激励" not in chunk.content for chunk in biographies)
    assert any(
        chunk.section_path[-1].startswith("(二)") and "股权激励" in chunk.content
        for chunk in chunks
    )


def test_pdf_chunk_splits_prose_biographies_with_chinese_punctuation():
    pages = [
        """十一、董事、高级管理人员与核心技术人员
1、董事会成员
公司董事的具体情况如下：
甲某，男，硕士研究生学历。曾任甲公司工程师，现任机械结构负责人。
乙某先生，本科学历。历任乙公司算法工程师，现任算法负责人。
2、审计委员会
审计委员会由三名董事组成。"""
    ]

    chunks = split_pdf_pages(pages)
    biographies = [chunk for chunk in chunks if chunk.block_type == "person_biography"]

    assert [chunk.person_name for chunk in biographies] == ["甲某", "乙某"]
    assert all("审计委员会由" not in chunk.content for chunk in biographies)


def test_pdf_chunk_splits_biographies_after_generic_personnel_heading():
    pages = [
        """三、高级管理人员
序号 姓名 职务
1 甲某 总经理
甲某，男，本科学历。曾任甲公司经理。
乙某，简历详见本节董事会成员。
四、核心技术
公司拥有相关核心技术。"""
    ]

    chunks = split_pdf_pages(pages)
    biographies = [chunk for chunk in chunks if chunk.block_type == "person_biography"]

    assert [chunk.person_name for chunk in biographies] == ["甲某", "乙某"]
    assert all("公司拥有相关核心技术" not in chunk.content for chunk in biographies)


def test_pdf_adapter_exposes_person_biography_metadata(tmp_path):
    path = tmp_path / "annual_report.pdf"
    path.write_bytes(b"%PDF-test")
    pages = [
        "一、人员情况\n(一) 个人简历\n姓名 主要工作经历\n张某\n男，本科学历。"
    ]

    with patch.object(PdfSourceAdapter, "_extract_pages", return_value=pages):
        _, units = PdfSourceAdapter().load(path, case_id="CASE")

    biography = next(unit for unit in units if unit.metadata.get("person_name") == "张某")
    assert biography.metadata["block_type"] == "person_biography"
    assert biography.metadata["title"] == "人员履历：张某"


def test_pdf_heading_rules_cover_common_chinese_levels():
    assert detect_heading_level("第一章 释义") == 1
    assert detect_heading_level("第二节 风险因素") == 2
    assert detect_heading_level("一、核心技术") == 3
    assert detect_heading_level("（一）技术来源") == 4
    assert detect_heading_level("1、光存储技术") == 5
    assert detect_heading_level("1.1 光存储技术") == 5
    assert detect_heading_level("（1）核心技术来源") == 6
    assert detect_heading_level("（6）向股东大会提出提案；") == 6
    assert detect_heading_level("①关键基础材料") == 7
    assert detect_heading_level("公司2024年营业收入增长。") is None
    assert detect_heading_level("23.12%，其中核心技术人员7人") is None
    assert detect_heading_level("2019.12.31资产负债率") is None
    assert detect_heading_level("0、5.89%和3.76%") is None
    assert detect_heading_level(
        "六、期末现金及现金等价物余额 20,731.84 9,846.22 6,156.51"
    ) is None


def test_evidence_repository_round_trip(tmp_path):
    path = tmp_path / "notice.html"
    path.write_text("<p>证据内容</p>", encoding="utf-8")
    source, units = ingest_source(path, case_id="ZJ")
    repository = EvidenceRepository(tmp_path / "evidence.db")
    repository.save_source(source)
    repository.save_units(list(units))

    assert len(repository.list_sources(case_id="ZJ")) == 1
    assert repository.search("证据", case_id="ZJ")[0].evidence_unit_id == units[0].evidence_unit_id


def test_evidence_search_ranks_more_relevant_chunks_before_id_order(tmp_path):
    from src.evidence.models import EvidenceUnit

    repository = EvidenceRepository(tmp_path / "ranked.db")
    units = [
        EvidenceUnit("src:eu_00001", "src", "ZJ", "document_chunk", "风险", content_hash="a"),
        EvidenceUnit("src:eu_00002", "src", "ZJ", "document_chunk", "风险风险风险，正文内容", content_hash="b"),
    ]
    from src.sources.models import SourceAsset
    source = SourceAsset("src", "ZJ", "pdf", "test.pdf", "测试", None, "source", "ready")
    repository.save_source(source)
    repository.save_units(units)

    assert repository.search("风险", case_id="ZJ", limit=2)[0].evidence_unit_id == "src:eu_00002"


def test_profile_reuses_shared_ontology_and_evidence_reference():
    item = ProfileItem(
        item_id="item-1",
        section_id="technology_ip",
        field_id="technology.name",
        value="某项技术",
        value_type="entity_ref",
        information_status="claimed",
        content_role="enterprise_claim",
        evidence_refs=(EvidenceReference("source:eu_00001"),),
    )
    relation = ProfileRelation(
        relation_id="rel-1",
        relation_type="owns",
        source_id="ent-1",
        source_type="Enterprise",
        target_id="tech-1",
        target_type="Technology",
        information_status="claimed",
        content_role="enterprise_claim",
    )
    profile = CurrentEnterpriseProfile(
        profile_id="profile-1",
        case_id="case-1",
        enterprise_name="测试企业",
        items=(item,),
        relations=(relation,),
    )

    assert profile.profile_type == "current"
    assert profile.items[0].evidence_refs[0].evidence_unit_id == "source:eu_00001"
    validate_relation("owns", "Enterprise", "Technology")


def test_core_ontology_v08_adds_general_fields_without_sample_subdivisions():
    assert ONTOLOGY_VERSION == "0.8.0"
    expected = {
        "enterprise.main_business",
        "team.key_person",
        "technology.source",
        "intellectual_property.name",
        "intellectual_property.patent_application_count",
        "intellectual_property.patent_grant_count",
        "intellectual_property.ownership_status",
        "intellectual_property.rights_restriction_status",
        "product.commercialization_stage",
        "finance.net_profit",
        "finance.net_profit_attributable_to_parent",
        "finance.adjusted_net_profit_attributable_to_parent",
        "finance.research_expense",
        "finance.cash_balance",
        "finance.interest_bearing_debt",
        "team.education_structure",
        "team.professional_background",
        "governance.equity_incentive_plan_status",
        "customer_supplier.customer_concentration",
        "customer_supplier.supplier_concentration",
        "customer_supplier.counterparty_name",
        "customer_supplier.transaction_amount",
        "customer_supplier.transaction_ratio",
        "customer_supplier.transaction_content",
        "customer_supplier.related_party_status",
    }

    assert expected <= set(REGISTRY.fields)
    assert {
        "intellectual_property.patent_application_count",
        "intellectual_property.patent_grant_count",
    } <= PROFILE_DOMAIN_FIELDS["technology_and_ip"]
    assert "intellectual_property.domestic_patent_grant_count" not in REGISTRY.fields
    assert "intellectual_property.foreign_invention_patent_count" not in REGISTRY.fields
    assert {"EducationRecord", "ProfessionalExperience"} <= OBJECT_TYPES
    assert "has_education" in RELATION_TYPES
    assert "has_professional_experience" in RELATION_TYPES
    assert {
        "team.education_structure",
        "team.professional_background",
        "governance.equity_incentive_plan_status",
    } <= PROFILE_DOMAIN_FIELDS["team"]
    assert "team.education_background" in REGISTRY.fields
    assert "team.professional_experience" in REGISTRY.fields
    assert "team.education_background" not in PROFILE_DOMAIN_FIELDS["team"]
    assert "team.professional_experience" not in PROFILE_DOMAIN_FIELDS["team"]
    assert PROFILE_DOMAIN_FIELDS["customer_and_supplier"] == {
        "customer_supplier.customer_concentration",
        "customer_supplier.supplier_concentration",
        "customer_supplier.counterparty_name",
        "customer_supplier.transaction_amount",
        "customer_supplier.transaction_ratio",
        "customer_supplier.transaction_content",
        "customer_supplier.related_party_status",
    }
    assert "finance.customer_concentration" in REGISTRY.fields
    assert "finance.customer_concentration" not in PROFILE_DOMAIN_FIELDS["customer_and_supplier"]
    assert "finance.customer_concentration" not in PROFILE_DOMAIN_FIELDS["finance_and_funding"]


def test_v04_person_records_relations_and_equity_incentive_enum_are_controlled():
    validate_relation("has_education", "Person", "EducationRecord")
    validate_relation("has_professional_experience", "Person", "ProfessionalExperience")

    incentive = ProfileItem(
        item_id="equity-incentive",
        section_id="ownership_governance_team",
        field_id="governance.equity_incentive_plan_status",
        value="active",
        value_type="enum",
        information_status="supported",
        content_role="audited_information",
        evidence_refs=(EvidenceReference("source:eu_00001"),),
        reporting_period="2024",
    )

    assert incentive.value == "active"
    with pytest.raises(ValueError, match="值必须是"):
        ProfileItem(
            item_id="equity-incentive-invalid",
            section_id="ownership_governance_team",
            field_id="governance.equity_incentive_plan_status",
            value="yes",
            value_type="enum",
            information_status="supported",
            content_role="audited_information",
            evidence_refs=(EvidenceReference("source:eu_00001"),),
            reporting_period="2024",
        )


def test_v04_customer_and_supplier_concentration_require_period():
    with pytest.raises(ValueError, match="统计期间"):
        ProfileItem(
            item_id="supplier-concentration-no-period",
            section_id="customer_supplier_partners",
            field_id="customer_supplier.supplier_concentration",
            value=0.3727,
            value_type="ratio",
            information_status="supported",
            content_role="audited_information",
            evidence_refs=(EvidenceReference("source:eu_00001"),),
        )

    item = ProfileItem(
        item_id="supplier-concentration",
        section_id="customer_supplier_partners",
        field_id="customer_supplier.supplier_concentration",
        value=0.3727,
        value_type="ratio",
        information_status="supported",
        content_role="audited_information",
        evidence_refs=(EvidenceReference("source:eu_00001"),),
        reporting_period="2019",
        value_scope="前五大供应商/采购额",
    )

    assert item.value == 0.3727


def test_general_patent_count_requires_period_and_accepts_evidence_bound_value():
    with pytest.raises(ValueError, match="统计期间"):
        ProfileItem(
            item_id="patent-count-missing-period",
            section_id="technology_ip",
            field_id="intellectual_property.patent_grant_count",
            value=1102,
            value_type="integer",
            information_status="claimed",
            content_role="enterprise_claim",
            evidence_refs=(EvidenceReference("source:eu_00001"),),
        )

    item = ProfileItem(
        item_id="patent-count",
        section_id="technology_ip",
        field_id="intellectual_property.patent_grant_count",
        value=1102,
        value_type="integer",
        information_status="claimed",
        content_role="enterprise_claim",
        evidence_refs=(EvidenceReference("source:eu_00001"),),
        reporting_period="截至2020-11-30",
    )

    assert item.value == 1102
    assert item.ontology_version == "0.8.0"

    with pytest.raises(ValueError, match="非负整数"):
        ProfileItem(
            item_id="patent-count-text",
            section_id="technology_ip",
            field_id="intellectual_property.patent_grant_count",
            value="1,102项",
            value_type="integer",
            information_status="claimed",
            content_role="enterprise_claim",
            evidence_refs=(EvidenceReference("source:eu_00001"),),
            reporting_period="截至2020-11-30",
        )


def test_technology_candidate_accepts_general_patent_total_and_rejects_ad_hoc_subdivision():
    common = {
        "section_id": "technology_ip",
        "value": 1102,
        "value_type": "integer",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": ["source:eu_00001"],
        "reporting_period": "截至2020-11-30",
    }
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "patent-total",
                    "field_id": "intellectual_property.patent_grant_count",
                },
                {
                    **common,
                    "item_id": "domestic-patent-total",
                    "field_id": "intellectual_property.domestic_patent_grant_count",
                },
            ]
        },
        evidence_unit_ids=("source:eu_00001",),
        profile_type="current",
        allowed_field_ids=PROFILE_DOMAIN_FIELDS["technology_and_ip"],
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["patent-total"]
    assert rejected[0]["candidate_id"] == "domestic-patent-total"


def test_evidence_query_service_supports_shared_tools(tmp_path):
    path = tmp_path / "notice.html"
    path.write_text("<h1>技术</h1><p>核心技术已经形成产品。</p><p>客户集中度较高。</p>", encoding="utf-8")
    source, units = ingest_source(path, case_id="ZJ")
    repository = EvidenceRepository(tmp_path / "evidence.db")
    repository.save_source(source)
    repository.save_units(list(units))
    service = EvidenceQueryService(repository)

    result = service.search_evidence("核心技术", case_id="ZJ")
    related = service.read_related_evidence(result[0].evidence_unit_id)

    assert result
    assert related
    assert service.list_source_structure(source_id=source.source_id)


def test_profile_repository_round_trip(tmp_path):
    profile = CurrentEnterpriseProfile(
        profile_id="profile-1",
        case_id="case-1",
        enterprise_name="测试企业",
        items=(
            ProfileItem(
                item_id="item-1",
                section_id="finance_capital",
                field_id="finance.operating_revenue",
                value=100,
                value_type="money",
                information_status="supported",
                content_role="business_record",
                evidence_refs=(EvidenceReference("source:eu_1"),),
                subject="the_enterprise",
                value_scope="合并口径",
                unit="CNY",
                reporting_period="2024",
            ),
        ),
    )
    repository = ProfileRepository(tmp_path / "profiles.db")
    repository.save(profile)

    loaded = repository.get("profile-1")

    assert loaded is not None
    assert loaded.profile_type == "current"
    assert loaded.items[0].value == 100
    assert loaded.items[0].subject == "the_enterprise"
    assert loaded.items[0].value_scope == "合并口径"
    assert loaded.items[0].unit == "CNY"


def test_profile_repository_lists_filtered_profiles(tmp_path):
    repository = ProfileRepository(tmp_path / "profiles.db")
    repository.save(
        HistoricalEnterpriseProfile(
            profile_id="historical-approved",
            case_id="H1",
            enterprise_name="历史企业",
            review_status="approved",
        )
    )
    repository.save(
        CurrentEnterpriseProfile(
            profile_id="current-pending",
            case_id="C1",
            enterprise_name="当前企业",
        )
    )

    profiles = repository.list(profile_type="historical", review_status="approved")

    assert [profile.profile_id for profile in profiles] == ["historical-approved"]


def test_profile_candidates_are_evidence_bound_and_build_current_profile():
    unit_id = "src:eu_1"
    candidates = {
        "profile_items": [
            {
                "item_id": "item-1",
                "section_id": "technology_ip",
                "field_id": "technology.name",
                "value": "某项技术",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": [unit_id],
            }
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }

    validate_profile_candidates(candidates, evidence_unit_ids=[unit_id], profile_type="current")
    profile = build_profile_from_candidates(
        candidates,
        profile_id="p-1",
        case_id="c-1",
        enterprise_name="测试企业",
        profile_type="current",
    )

    assert profile.profile_type == "current"
    assert profile.items[0].evidence_refs[0].evidence_unit_id == unit_id


def test_profile_candidates_normalize_direct_extraction_alias():
    unit_id = "src:eu_alias"
    candidates = {
        "profile_items": [
            {
                "item_id": "item-alias",
                "section_id": "technology_ip",
                "field_id": "technology.name",
                "value": "某项技术",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": [unit_id],
                "extraction_method": "direct_extraction",
            }
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }

    profile = build_profile_from_candidates(
        candidates,
        profile_id="p-alias",
        case_id="c-alias",
        enterprise_name="测试企业",
        profile_type="current",
    )

    assert profile.items[0].extraction_method == "llm"


def test_invalid_profile_candidate_is_filtered_without_dropping_valid_item():
    data = {
        "profile_items": [
            {
                "item_id": "valid",
                "section_id": "technology_ip",
                "field_id": "technology.name",
                "value": "某项技术",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            },
            {
                "item_id": "invalid",
                "section_id": "technology_ip",
                "field_id": "not_a_real_field",
                "value": "错误字段",
                "value_type": "text",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            },
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    filtered, rejected = filter_profile_candidates(
        data, evidence_unit_ids=["src:eu_1"], profile_type="historical"
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["valid"]
    assert rejected[0]["candidate_id"] == "invalid"


def test_profile_candidates_deduplicate_same_subject_and_merge_evidence():
    common = {
        "subject": "一体化关节集成技术",
        "section_id": "technology_ip",
        "field_id": "technology.source",
        "value": "自研",
        "value_type": "text",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
    }
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "source-1",
                    "evidence_unit_ids": ["src:eu_1"],
                },
                {
                    **common,
                    "item_id": "source-2",
                    "evidence_unit_ids": ["src:eu_2"],
                },
            ]
        },
        evidence_unit_ids=["src:eu_1", "src:eu_2"],
        profile_type="current",
    )

    assert rejected == []
    assert [item["item_id"] for item in filtered["profile_items"]] == ["source-1"]
    assert filtered["profile_items"][0]["evidence_unit_ids"] == [
        "src:eu_1",
        "src:eu_2",
    ]
    assert filtered["deduplicated_candidates"] == [
        {
            "kept_item_id": "source-1",
            "removed_item_id": "source-2",
            "subject": "一体化关节集成技术",
            "field_id": "technology.source",
            "reason": "主体、字段、值和限定条件相同，已合并证据。",
        }
    ]


def test_profile_candidates_reject_relation_to_rejected_item():
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [
                {
                    "item_id": "person-1",
                    "section_id": "team",
                    "field_id": "not_a_real_field",
                    "value": "某负责人",
                    "value_type": "entity_ref",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                }
            ],
            "profile_relations": [
                {
                    "relation_id": "relation-1",
                    "relation_type": "holds_position_in",
                    "source_id": "person-1",
                    "source_type": "Person",
                    "target_id": "the_enterprise",
                    "target_type": "Enterprise",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                }
            ],
        },
        evidence_unit_ids=["src:eu_1"],
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert filtered["profile_relations"] == []
    assert any(
        item["kind"] == "profile_relations"
        and "person-1" in item["reason"]
        for item in rejected
    )


def test_profile_candidates_remap_relation_to_deduplicated_item():
    common = {
        "subject": "一体化关节集成技术",
        "section_id": "technology_ip",
        "field_id": "technology.source",
        "value": "自研",
        "value_type": "text",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
    }
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "technology-1",
                    "evidence_unit_ids": ["src:eu_1"],
                },
                {
                    **common,
                    "item_id": "technology-2",
                    "evidence_unit_ids": ["src:eu_2"],
                },
            ],
            "profile_relations": [
                {
                    "relation_id": "relation-1",
                    "relation_type": "develops",
                    "source_id": "the_enterprise",
                    "source_type": "Enterprise",
                    "target_id": "technology-2",
                    "target_type": "Technology",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_2"],
                }
            ],
        },
        evidence_unit_ids=["src:eu_1", "src:eu_2"],
        profile_type="current",
    )

    assert rejected == []
    assert filtered["profile_relations"][0]["target_id"] == "technology-1"


def test_profile_candidates_keep_same_value_for_different_subjects():
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [
                {
                    "item_id": f"source-{index}",
                    "subject": subject,
                    "section_id": "technology_ip",
                    "field_id": "technology.source",
                    "value": "自研",
                    "value_type": "text",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                }
                for index, subject in enumerate(
                    ("一体化关节集成技术", "机器人激光雷达技术"),
                    start=1,
                )
            ]
        },
        evidence_unit_ids=["src:eu_1"],
        profile_type="current",
    )

    assert rejected == []
    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "source-1",
        "source-2",
    ]
    assert filtered["deduplicated_candidates"] == []


def test_domain_candidates_require_subject_for_new_extractions():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "source-1",
                    "section_id": "technology_ip",
                    "field_id": "technology.source",
                    "value": "自研",
                    "value_type": "text",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                }
            ]
        },
        evidence_unit_ids=["src:eu_1"],
        domain="technology_and_ip",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert filtered["rejected_candidates"][0]["reason"] == "画像项必须包含明确的 subject。"


def test_finance_domain_rejects_missing_period_and_unit_before_review():
    common = {
        "subject": "the_enterprise",
        "section_id": "finance_capital",
        "field_id": "finance.operating_revenue",
        "value": 100.0,
        "value_type": "money",
        "information_status": "supported",
        "content_role": "audited_information",
        "evidence_unit_ids": ["src:finance"],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {"item_id": "missing-period", "unit": "万元", **common},
                {
                    "item_id": "missing-unit",
                    "reporting_period": "2025",
                    **common,
                },
            ]
        },
        evidence_unit_ids=["src:finance"],
        domain="finance_and_funding",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert {
        item["reason"] for item in filtered["rejected_candidates"]
    } == {
        "字段 finance.operating_revenue 必须包含 reporting_period。",
        "字段 finance.operating_revenue 必须包含 unit。",
    }


def test_multi_evidence_summary_requires_excerpt_for_each_evidence_unit():
    evidence_contents = {
        "src:person": "王兴兴拥有机器人研发经验。",
        "src:team": "研发团队中硕士73人，本科98人。",
    }
    common = {
        "subject": "the_enterprise",
        "section_id": "ownership_governance_team",
        "field_id": "team.education_structure",
        "value": "核心团队覆盖硕士和本科教育背景。",
        "value_type": "text",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": ["src:person", "src:team"],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "complete",
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:person",
                            "excerpt": "王兴兴拥有机器人研发经验",
                        },
                        {
                            "evidence_unit_id": "src:team",
                            "excerpt": "研发团队中硕士73人，本科98人",
                        },
                    ],
                },
                {
                    **common,
                    "item_id": "incomplete",
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:person",
                            "excerpt": "王兴兴拥有机器人研发经验",
                        }
                    ],
                },
            ]
        },
        evidence_unit_ids=evidence_contents,
        evidence_contents=evidence_contents,
        domain="team",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["complete"]
    assert filtered["rejected_candidates"][0]["reason"] == (
        "每个 evidence_unit_id 都必须提供对应的证据摘录。"
    )
    profile = build_profile_from_candidates(
        filtered,
        profile_id="team-profile",
        case_id="team-case",
        enterprise_name="测试企业",
        profile_type="current",
    )
    assert [ref.excerpt for ref in profile.items[0].evidence_refs] == [
        "王兴兴拥有机器人研发经验",
        "研发团队中硕士73人，本科98人",
    ]


def test_team_education_undisclosed_value_cannot_be_confirmed():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "education",
                    "subject": "the_enterprise",
                    "section_id": "ownership_governance_team",
                    "field_id": "team.education_structure",
                    "value": "王兴兴为硕士，杨知雨学历未披露",
                    "value_type": "text",
                    "information_status": "confirmed",
                    "content_role": "business_record",
                    "evidence_unit_ids": ["src:team"],
                    "evidence_quotes": [{
                        "evidence_unit_id": "src:team",
                        "excerpt": "王兴兴为硕士",
                    }],
                }
            ]
        },
        evidence_unit_ids=["src:team"],
        evidence_contents={"src:team": "王兴兴为硕士"},
        domain="team",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert "必须表示证据不足" in filtered["rejected_candidates"][0]["reason"]


def test_team_key_person_grounding_repairs_ellipsis_quote():
    evidence_contents = {
        "src:team": "王兴兴作为首席技术官负责研发。\n张阳光作为算法与软件负责人。"
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "person",
                    "subject": "张阳光",
                    "section_id": "ownership_governance_team",
                    "field_id": "team.key_person",
                    "value": "张阳光",
                    "value_type": "entity_ref",
                    "information_status": "confirmed",
                    "content_role": "business_record",
                    "evidence_unit_ids": ["src:team"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:team",
                            "excerpt": "王兴兴……张阳光作为算法与软件负责人。",
                        }
                    ],
                }
            ]
        },
        evidence_unit_ids=evidence_contents,
        evidence_contents=evidence_contents,
        domain="team",
        profile_type="current",
    )

    assert [item["value"] for item in filtered["profile_items"]] == ["张阳光"]
    assert filtered["profile_items"][0]["evidence_quotes"] == [
        {
            "evidence_unit_id": "src:team",
            "excerpt": "张阳光作为算法与软件负责人。",
        }
    ]


def test_enterprise_main_business_grounding_repairs_table_summary_quote():
    evidence_contents = {
        "src:business": "分类\n四足机器人 39,569.16\n人形机器人 54,826.61\n机器人组件 6,157.41"
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "business",
                    "subject": "the_enterprise",
                    "section_id": "basic_information",
                    "field_id": "enterprise.main_business",
                    "value": "四足机器人、人形机器人、机器人组件",
                    "value_type": "text",
                    "information_status": "confirmed",
                    "content_role": "business_record",
                    "evidence_unit_ids": ["src:business"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:business",
                            "excerpt": "分类\n四足机器人 39,569.16 人形机器人 54,826.61 机器人组件 6,157.41",
                        }
                    ],
                }
            ]
        },
        evidence_unit_ids=evidence_contents,
        evidence_contents=evidence_contents,
        domain="enterprise_and_control",
        profile_type="current",
    )

    assert [item["value"] for item in filtered["profile_items"]] == [
        "四足机器人、人形机器人、机器人组件"
    ]
    assert len(filtered["profile_items"][0]["evidence_quotes"]) == 4
    assert any("四足机器人 39,569.16" == quote["excerpt"] for quote in filtered["profile_items"][0]["evidence_quotes"])


def test_finance_semantics_separate_profit_balance_and_cash_flow():
    evidence_contents = {
        "src:finance": (
            "扣除非经常性损益后归属于母公司所有者的净利润为100万元。"
            "期初现金及现金等价物余额为20万元，期末现金及现金等价物余额为30万元。"
            "取得借款收到的现金为0万元。"
        )
    }
    common = {
        "subject": "the_enterprise",
        "section_id": "finance_capital",
        "value_type": "money",
        "information_status": "supported",
        "content_role": "audited_information",
        "evidence_unit_ids": ["src:finance"],
        "unit": "万元",
        "reporting_period": "2025",
    }
    def candidate(item_id, field_id, value, excerpt):
        return {
            **common,
            "item_id": item_id,
            "field_id": field_id,
            "value": value,
            "evidence_quotes": [
                {"evidence_unit_id": "src:finance", "excerpt": excerpt}
            ],
        }

    filtered = filter_domain_candidates(
        {
            "profile_items": [
                candidate(
                    "wrong-profit",
                    "finance.net_profit",
                    100,
                    "扣除非经常性损益后归属于母公司所有者的净利润为100万元",
                ),
                candidate(
                    "adjusted-profit",
                    "finance.adjusted_net_profit_attributable_to_parent",
                    100,
                    "扣除非经常性损益后归属于母公司所有者的净利润为100万元",
                ),
                candidate(
                    "wrong-cash",
                    "finance.cash_balance",
                    20,
                    "期初现金及现金等价物余额为20万元",
                ),
                candidate(
                    "ending-cash",
                    "finance.cash_balance",
                    30,
                    "期末现金及现金等价物余额为30万元",
                ),
                candidate(
                    "wrong-debt",
                    "finance.interest_bearing_debt",
                    0,
                    "取得借款收到的现金为0万元",
                ),
            ]
        },
        evidence_unit_ids=evidence_contents,
        evidence_contents=evidence_contents,
        domain="finance_and_funding",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "adjusted-profit",
        "ending-cash",
    ]
    assert {
        item["reason"] for item in filtered["rejected_candidates"]
    } == {
        "归母或扣非归母净利润不得写入普通净利润字段。",
        "现金余额字段只接受期末现金及现金等价物余额。",
        "借款现金流不得作为有息负债余额。",
    }


def test_finance_accepts_listed_company_shareholder_profit_as_parent_profit():
    unit_id = "src:finance"
    quote = "归属于上市公司股东的净利润为100万元。"
    common = {
        "subject": "the_enterprise",
        "section_id": "finance_capital",
        "value": 100,
        "value_type": "money",
        "information_status": "confirmed",
        "content_role": "audited_information",
        "unit": "万元",
        "reporting_period": "2025年度",
        "evidence_unit_ids": [unit_id],
        "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": quote}],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {**common, "item_id": "wrong", "field_id": "finance.net_profit"},
                {
                    **common,
                    "item_id": "parent",
                    "field_id": "finance.net_profit_attributable_to_parent",
                },
            ]
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: quote},
        domain="finance_and_funding",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["parent"]
    assert "归母或扣非归母净利润不得写入普通净利润字段" in filtered["rejected_candidates"][0]["reason"]


def test_concentration_quotes_are_grounded_from_scope_and_period_data():
    customer_id = "src:customer"
    supplier_id = "src:supplier"
    customer_definition = "公司前五大客户销售金额占营业收入比例情况如下："
    customer_row = "2025年前五大客户合计 20,531.58 12.08%。"
    supplier_definition = "公司前五大供应商采购金额占原材料采购总额比例情况如下："
    supplier_row = "2025年前五大供应商合计 17,890.84 22.54%。"

    def candidate(
        item_id: str,
        field_id: str,
        value: float,
        scope: str,
        evidence_id: str,
        quotes: list[str],
        reporting_period: str = "2025",
    ) -> dict[str, Any]:
        return {
            "item_id": item_id,
            "subject": "the_enterprise",
            "section_id": "customer_supplier_partners",
            "field_id": field_id,
            "value": value,
            "value_type": "ratio",
            "information_status": "claimed",
            "content_role": "enterprise_claim",
            "reporting_period": reporting_period,
            "value_scope": scope,
            "evidence_unit_ids": [evidence_id],
            "evidence_quotes": [
                {"evidence_unit_id": evidence_id, "excerpt": quote}
                for quote in quotes
            ],
        }

    filtered = filter_domain_candidates(
        {
            "profile_items": [
                candidate(
                    "customer-grounded",
                    "customer_supplier.customer_concentration",
                    0.1208,
                    "前五大客户，分母为营业收入",
                    customer_id,
                    [customer_row],
                ),
                candidate(
                    "customer-wrong-value",
                    "customer_supplier.customer_concentration",
                    0.9999,
                    "前五大客户，分母为营业收入",
                    customer_id,
                    [customer_row],
                ),
                candidate(
                    "supplier-grounded",
                    "customer_supplier.supplier_concentration",
                    0.2254,
                    "前五大供应商，分母为原材料采购总额",
                    supplier_id,
                    [supplier_row.replace("采购", "")],
                ),
                candidate(
                    "supplier-wrong-period",
                    "customer_supplier.supplier_concentration",
                    0.2254,
                    "前五大供应商，分母为原材料采购总额",
                    supplier_id,
                    [supplier_row.replace("采购", "")],
                    "2024",
                ),
            ]
        },
        evidence_unit_ids=[customer_id, supplier_id],
        evidence_contents={
            customer_id: f"{customer_definition}\n{customer_row}",
            supplier_id: (
                f"{supplier_definition}\n"
                f"{supplier_row.replace('采购', '')}\n"
                "报告期内该比例分别为22.54%。"
            ),
        },
        domain="customer_and_supplier",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "customer-grounded",
        "supplier-grounded",
    ]
    assert all(
        len(item["evidence_quotes"]) >= 2
        for item in filtered["profile_items"]
    )
    assert {
        item["reason"] for item in filtered["rejected_candidates"]
    } == {
        "客户集中度证据摘录必须包含对应期间和比例值。",
        "供应商集中度证据摘录必须包含对应期间和比例值。",
    }


def test_customer_rows_build_transactions_relations_and_anonymous_gap():
    unit_id = "src:customers"
    content = (
        "报告期内主要客户情况\n"
        "年份 序号 客户名称 销售金额 收入占比\n"
        "2025 年\n"
        "1 京东集团股份有限公司 4,887.32 2.88%\n"
        "2 境外客户 A（亚洲） 4,282.66 2.52%\n"
        "公司与报告期内前五大客户均不存在关联关系。"
    )
    common = {
        "section_id": "customer_supplier_partners",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": [unit_id],
    }
    row = "1 京东集团股份有限公司 4,887.32 2.88%"
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "customer-jd",
                    "subject": "京东集团股份有限公司",
                    "field_id": "customer_supplier.counterparty_name",
                    "value": "京东集团股份有限公司",
                    "value_type": "entity_ref",
                    "evidence_quotes": [
                        {"evidence_unit_id": unit_id, "excerpt": row}
                    ],
                },
                {
                    **common,
                    "item_id": "customer-anonymous",
                    "subject": "境外客户 A（亚洲）",
                    "field_id": "customer_supplier.counterparty_name",
                    "value": "境外客户 A（亚洲）",
                    "value_type": "entity_ref",
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": unit_id,
                            "excerpt": "2 境外客户 A（亚洲） 4,282.66 2.52%",
                        }
                    ],
                },
                {
                    **common,
                    "item_id": "customer-jd-amount",
                    "subject": "京东集团股份有限公司",
                    "field_id": "customer_supplier.transaction_amount",
                    "value": 4887.32,
                    "value_type": "money",
                    "unit": "万元",
                    "reporting_period": "2025",
                    "value_scope": "向主要客户销售金额",
                    "evidence_quotes": [
                        {"evidence_unit_id": unit_id, "excerpt": row}
                    ],
                },
                {
                    **common,
                    "item_id": "customer-jd-ratio",
                    "subject": "京东集团股份有限公司",
                    "field_id": "customer_supplier.transaction_ratio",
                    "value": 0.0288,
                    "value_type": "ratio",
                    "reporting_period": "2025",
                    "value_scope": "主要客户销售金额占营业收入比例",
                    "evidence_quotes": [
                        {"evidence_unit_id": unit_id, "excerpt": row}
                    ],
                },
                {
                    **common,
                    "item_id": "customer-related-status",
                    "subject": "the_enterprise",
                    "field_id": "customer_supplier.related_party_status",
                    "value": "non_related",
                    "value_type": "enum",
                    "reporting_period": "2023-2025",
                    "value_scope": "报告期前五大客户",
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": unit_id,
                            "excerpt": "公司与报告期内前五大客户均不存在关联关系。",
                        }
                    ],
                },
            ],
            "profile_relations": [
                {
                    "relation_id": relation_id,
                    "relation_type": "sells_to",
                    "source_id": "the_enterprise",
                    "source_type": "Enterprise",
                    "target_id": "customer-jd",
                    "target_type": "Organization",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quotes": [
                        {"evidence_unit_id": unit_id, "excerpt": row}
                    ],
                }
                for relation_id in ("sells-jd-2025", "sells-jd-duplicate")
            ],
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="customer_and_supplier",
        profile_type="current",
    )

    assert len(filtered["profile_items"]) == 5
    assert len(filtered["profile_relations"]) == 1
    assert len(filtered["deduplicated_relations"]) == 1
    assert filtered["information_gaps"] == [
        "部分主要客户仅以匿名代称披露，真实法律主体名称未披露。"
    ]
    amount = next(
        item
        for item in filtered["profile_items"]
        if item["item_id"] == "customer-jd-amount"
    )
    assert any("2025" in quote["excerpt"] for quote in amount["evidence_quotes"])
    assert filtered["rejected_candidates"] == []


def test_supplier_row_builds_amount_ratio_content_and_purchase_relation():
    unit_id = "src:suppliers"
    content = (
        "前五名原材料供应商的采购情况\n"
        "年度 供应商名称 采购金额 采购内容 占比\n"
        "2025 年度\n"
        "供应商 I 3,789.07 机械零部件 4.77%"
    )
    row = "供应商 I 3,789.07 机械零部件 4.77%"
    common = {
        "section_id": "customer_supplier_partners",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": [unit_id],
        "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": row}],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "supplier-i",
                    "subject": "供应商 I",
                    "field_id": "customer_supplier.counterparty_name",
                    "value": "供应商 I",
                    "value_type": "entity_ref",
                },
                {
                    **common,
                    "item_id": "supplier-i-amount",
                    "subject": "供应商 I",
                    "field_id": "customer_supplier.transaction_amount",
                    "value": 3789.07,
                    "value_type": "money",
                    "unit": "万元",
                    "reporting_period": "2025",
                    "value_scope": "向主要供应商采购金额",
                },
                {
                    **common,
                    "item_id": "supplier-i-ratio",
                    "subject": "供应商 I",
                    "field_id": "customer_supplier.transaction_ratio",
                    "value": 0.0477,
                    "value_type": "ratio",
                    "reporting_period": "2025",
                    "value_scope": "主要供应商采购金额占原材料采购总额比例",
                },
                {
                    **common,
                    "item_id": "supplier-i-content",
                    "subject": "供应商 I",
                    "field_id": "customer_supplier.transaction_content",
                    "value": "机械零部件",
                    "value_type": "text",
                    "reporting_period": "2025",
                    "value_scope": "向主要供应商采购内容",
                },
            ],
            "profile_relations": [
                {
                    "relation_id": "purchase-i",
                    "relation_type": "purchases_from",
                    "source_id": "the_enterprise",
                    "source_type": "Enterprise",
                    "target_id": "supplier-i",
                    "target_type": "Organization",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quotes": [
                        {"evidence_unit_id": unit_id, "excerpt": row}
                    ],
                }
            ],
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="customer_and_supplier",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "supplier-i",
        "supplier-i-amount",
        "supplier-i-ratio",
        "supplier-i-content",
    ]
    assert [relation["relation_id"] for relation in filtered["profile_relations"]] == [
        "purchase-i"
    ]
    assert filtered["rejected_candidates"] == []


def test_customer_supplier_tables_are_split_into_two_extraction_batches():
    from src.evidence.models import EvidenceUnit

    def unit(evidence_id: str, content: str) -> EvidenceUnit:
        return EvidenceUnit(
            evidence_unit_id=evidence_id,
            source_id="src",
            case_id="case",
            content_type="document_chunk",
            content=content,
            location={"kind": "pdf", "page_start": 1, "page_end": 1},
            content_hash=evidence_id,
        )

    customer = unit(
        "src:customer",
        "主要客户销售情况\n客户名称 销售金额 收入占比\n合计 100 10%",
    )
    supplier = unit(
        "src:supplier",
        "前五大原材料供应商采购情况\n采购金额 占比\n合计 200 20%",
    )
    unrelated = unit("src:other", "采购模式说明")

    batches = _profile_extraction_batches(
        (customer, supplier, unrelated),
        domain="customer_and_supplier",
    )

    assert [(name, [item.evidence_unit_id for item in units]) for name, units in batches] == [
        ("customer", ["src:customer"]),
        ("supplier", ["src:supplier"]),
    ]


def test_counterparty_numeric_matching_handles_alias_suffix_and_trailing_zero():
    assert _number_value_in_text(715.27, "5 境内客户 A1 715.27 1.82%")
    assert _ratio_value_in_text(0.032, "1 境外客户 D 509.50 3.20%")
    assert _ratio_value_in_text(0.065, "供应商 B 1,259.21 电子元器件 6.50%")


def test_technology_domain_enforces_patent_scope_and_semantic_quote():
    unit_id = "src:patent"
    content = (
        "截至2026年1月31日，公司拥有262项专利权，已公开授权的境内专利共计169项，"
        "境外专利共计93项。"
        "专利权不存在质押、查封、冻结或其他权利受到限制的情况。"
    )
    common = {
        "subject": "the_enterprise",
        "section_id": "technology_ip",
        "value_type": "integer",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": [unit_id],
        "evidence_quote_id": unit_id,
        "reporting_period": "截至2026年1月31日",
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "wrong-application",
                    "field_id": "intellectual_property.patent_application_count",
                    "value": 262,
                    "value_scope": "全部",
                    "evidence_quote": "公司拥有262项专利权",
                },
                {
                    **common,
                    "item_id": "grant-total",
                    "field_id": "intellectual_property.patent_grant_count",
                    "value": 262,
                    "value_scope": "全部",
                    "evidence_quote": "公司拥有262项专利权",
                },
                {
                    **common,
                    "item_id": "grant-overseas",
                    "field_id": "intellectual_property.patent_grant_count",
                    "value": 93,
                    "value_scope": "境外",
                    "evidence_quote": "境外专利共计93项",
                },
                {
                    "item_id": "restriction",
                    "subject": "the_enterprise",
                    "section_id": "technology_ip",
                    "field_id": "intellectual_property.rights_restriction_status",
                    "value": "unrestricted",
                    "value_type": "enum",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quote_id": unit_id,
                    "evidence_quote": "专利权不存在质押、查封、冻结或其他权利受到限制的情况",
                },
            ]
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="technology_and_ip",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "grant-total",
        "grant-overseas",
        "restriction",
    ]
    assert "必须明确表达申请" in filtered["rejected_candidates"][0]["reason"]


def test_technology_domain_rejects_new_patents_as_total_scope():
    unit_id = "src:new-patent"
    quote = "报告期内，公司新增专利申请共计459项。"
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "wrong-total",
                    "subject": "the_enterprise",
                    "section_id": "technology_ip",
                    "field_id": "intellectual_property.patent_application_count",
                    "value": 459,
                    "value_type": "integer",
                    "value_scope": "全部",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": quote}],
                    "reporting_period": "2025年度",
                }
            ]
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: quote},
        domain="technology_and_ip",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert "本期新增专利数量不得写为全部或总量" in filtered["rejected_candidates"][0]["reason"]


def test_technology_maturity_requires_named_technology_and_not_only_table_header():
    unit_id = "src:maturity"
    content = "核心技术A 量产或生产开始时间 2024年。"
    common = {
        "section_id": "technology_ip",
        "field_id": "technology.maturity_stage",
        "value": "mature",
        "value_type": "enum",
        "information_status": "confirmed",
        "content_role": "business_record",
        "evidence_unit_ids": [unit_id],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "header-only",
                    "subject": "the_enterprise",
                    "evidence_quotes": [{
                        "evidence_unit_id": unit_id,
                        "excerpt": "量产或生产开始时间",
                    }],
                },
                {
                    **common,
                    "item_id": "named-technology",
                    "subject": "核心技术A",
                    "evidence_quotes": [{
                        "evidence_unit_id": unit_id,
                        "excerpt": content,
                    }],
                },
            ]
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="technology_and_ip",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["named-technology"]
    assert "技术成熟度必须引用具体技术名称" in filtered["rejected_candidates"][0]["reason"]


def test_finance_domain_requires_direct_value_and_derives_research_ratio():
    unit_id = "src:finance"
    content = (
        "2025年度营业收入1,000元。研发费用50元。"
        "第一季度净利润25元，第二季度净利润25元，第三季度净利润25元，第四季度净利润25元。"
    )
    common = {
        "subject": "the_enterprise",
        "section_id": "finance_capital",
        "information_status": "confirmed",
        "content_role": "audited_information",
        "evidence_unit_ids": [unit_id],
        "reporting_period": "2025年度",
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    **common,
                    "item_id": "revenue",
                    "field_id": "finance.operating_revenue",
                    "value": 1000,
                    "value_type": "money",
                    "unit": "元",
                    "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": "营业收入1,000元"}],
                },
                {
                    **common,
                    "item_id": "expense",
                    "field_id": "finance.research_expense",
                    "value": 50,
                    "value_type": "money",
                    "unit": "元",
                    "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": "研发费用50元"}],
                },
                {
                    **common,
                    "item_id": "quarterly-sum",
                    "field_id": "finance.net_profit",
                    "value": 100,
                    "value_type": "money",
                    "unit": "元",
                    "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": "第一季度净利润25元，第二季度净利润25元，第三季度净利润25元，第四季度净利润25元"}],
                },
                {
                    **common,
                    "item_id": "model-ratio",
                    "field_id": "finance.research_expense_ratio",
                    "value": 0.05,
                    "value_type": "ratio",
                    "evidence_quotes": [{"evidence_unit_id": unit_id, "excerpt": "研发费用50元"}],
                },
            ]
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="finance_and_funding",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "revenue",
        "expense",
        "rule_research_expense_ratio_1",
    ]
    ratio = filtered["profile_items"][-1]
    assert ratio["value"] == 0.05
    assert ratio["extraction_method"] == "rule"
    assert {item["reason"] for item in filtered["rejected_candidates"]} == {
        "直接数值必须逐字出现在至少一条证据摘录中。",
        "比例必须由证据直接披露，不得由模型自行计算。",
    }


def test_technology_domain_rejects_owns_for_self_developed_evidence():
    unit_id = "src:technology"
    content = "公司自研形成多项核心技术。一体化关节采用紧凑结构。"
    relation = {
        "source_id": "the_enterprise",
        "source_type": "Enterprise",
        "target_id": "tech-1",
        "target_type": "Technology",
        "information_status": "claimed",
        "content_role": "enterprise_claim",
        "evidence_unit_ids": [unit_id],
        "evidence_quote_id": unit_id,
        "evidence_quote": content,
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "wrong-source",
                    "subject": "一体化关节集成技术",
                    "section_id": "technology_ip",
                    "field_id": "technology.source",
                    "value": "自研",
                    "value_type": "text",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quote_id": unit_id,
                    "evidence_quote": "一体化关节采用紧凑结构",
                },
                {
                    "item_id": "correct-source",
                    "subject": "一体化关节集成技术",
                    "section_id": "technology_ip",
                    "field_id": "technology.source",
                    "value": "自研",
                    "value_type": "text",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": [unit_id],
                    "evidence_quote_id": unit_id,
                    "evidence_quote": "公司自研形成多项核心技术",
                },
            ],
            "profile_relations": [
                {"relation_id": "wrong", "relation_type": "owns", **relation},
                {"relation_id": "correct", "relation_type": "develops", **relation},
            ],
        },
        evidence_unit_ids=[unit_id],
        evidence_contents={unit_id: content},
        domain="technology_and_ip",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "correct-source"
    ]
    assert [item["relation_id"] for item in filtered["profile_relations"]] == [
        "correct"
    ]
    assert {
        item["reason"] for item in filtered["rejected_candidates"]
    } == {
        "自研技术来源必须引用明确的自研、研发或开发表述。",
        "owns 关系必须引用明确的拥有或权属表述。",
    }


def test_profile_prompt_contains_domain_and_evidence_id():
    from src.evidence.models import EvidenceUnit

    evidence = EvidenceUnit(
        evidence_unit_id="src:eu_1",
        source_id="src",
        case_id="c",
        content_type="document_chunk",
        content="企业声称拥有某项技术。",
        location={"kind": "pdf", "page_start": 8, "page_end": 8},
        metadata={
            "title": "核心技术",
            "source_title": "示例科技股份有限公司2024年年度报告",
        },
        source_date="2025-03-01",
        content_hash="hash",
    )
    messages = build_profile_messages([evidence], domain="technology_and_ip", profile_type="historical")

    assert "technology_and_ip" in messages[1]["content"]
    assert "src:eu_1" in messages[1]["content"]
    assert "evidence_unit_ids 只能逐字复制" in messages[1]["content"]
    assert "subject 表示该属性属于谁" in messages[1]["content"]
    assert "evidence_quotes 是对象数组" in messages[1]["content"]
    assert "表格指标同时依赖表头或表前定义与数据行" in messages[1]["content"]
    assert "同一 EvidenceUnit 可以提供多条 evidence_quotes" in messages[1]["content"]
    assert "多年度表格的每个年度候选都必须重复引用口径定义" in messages[1]["content"]
    assert "公司自研、研发或开发形成技术使用 develops" not in messages[1]["content"]
    assert "表格前的总括句" not in messages[1]["content"]
    assert "technology.name" in messages[1]["content"]
    assert "finance.operating_revenue" not in messages[1]["content"]
    assert "- owns:" in messages[1]["content"]
    assert "- financed_by:" not in messages[1]["content"]
    assert "只抽取当前调查领域" in messages[0]["content"]
    assert "===== 材料基本信息 =====" in messages[1]["content"]
    assert "示例科技股份有限公司2024年年度报告" in messages[1]["content"]
    assert '"source_date": "2025-03-01"' in messages[1]["content"]
    assert '"page_start": 8' in messages[1]["content"]
    assert "source_date 仅表示材料日期" in messages[1]["content"]


def test_v05_team_prompt_and_local_queries_expose_aggregate_nonfinancial_fields():
    from src.evidence.models import EvidenceUnit

    evidence = EvidenceUnit(
        evidence_unit_id="src:eu_team",
        source_id="src",
        case_id="c",
        content_type="document_chunk",
        content="核心人员学历、主要职业经历及股权激励计划。",
        location={"kind": "pdf", "page_start": 1, "page_end": 1},
        content_hash="team-hash",
    )
    content = build_profile_messages(
        [evidence], domain="team", profile_type="historical"
    )[1]["content"]

    assert "team.education_structure" in content
    assert "team.professional_background" in content
    assert "governance.equity_incentive_plan_status" in content
    assert "allowed_values=active,approved_not_started" in content
    assert "- has_education:" not in content
    assert "- has_professional_experience:" not in content
    assert "不是要求为所有出现的人员逐一建档" in content
    assert "核心技术人员作为关键人员" in content
    assert "禁止使用省略号" in content
    assert {"学历", "主要工作经历", "股权激励"} <= set(
        HISTORICAL_DOMAIN_QUERIES["team"]
    )
    assert {"前五名客户", "前五名供应商"} <= set(
        HISTORICAL_DOMAIN_QUERIES["customer_and_supplier"]
    )
    assert {"净利润", "研发费用", "主要会计数据"} <= set(
        HISTORICAL_DOMAIN_QUERIES["finance_and_funding"]
    )


def test_domain_extraction_filters_cross_domain_output_and_gap(monkeypatch):
    from src.evidence.models import EvidenceUnit

    evidence = EvidenceUnit(
        evidence_unit_id="src:eu_1",
        source_id="src",
        case_id="c",
        content_type="document_chunk",
        content="公司形成光存储核心技术。",
        location={"kind": "pdf", "page_start": 1, "page_end": 1},
        content_hash="hash",
    )

    def fake_call(messages, config):
        return {
            "profile_items": [
                {
                    "item_id": "tech",
                    "subject": "光存储核心技术",
                    "section_id": "technology_ip",
                    "field_id": "technology.name",
                    "value": "光存储核心技术",
                    "value_type": "entity_ref",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                    "evidence_quote_id": "src:eu_1",
                    "evidence_quote": "公司形成光存储核心技术。",
                },
                {
                    "item_id": "finance",
                    "subject": "the_enterprise",
                    "section_id": "finance_capital",
                    "field_id": "finance.operating_revenue",
                    "value": 100,
                    "value_type": "money",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "unit": "CNY",
                    "reporting_period": "2024",
                    "evidence_unit_ids": ["src:eu_1"],
                    "evidence_quote_id": "src:eu_1",
                    "evidence_quote": "公司形成光存储核心技术。",
                },
            ],
            "profile_relations": [
                {
                    "relation_id": "team",
                    "relation_type": "holds_position_in",
                    "source_id": "person",
                    "source_type": "Person",
                    "target_id": "enterprise",
                    "target_type": "Enterprise",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:eu_1"],
                }
            ],
            "information_gaps": [
                "technology_and_ip: 技术成熟度未披露",
                "finance.operating_revenue: 营业收入未披露",
            ],
            "conflicts": [],
            "unmapped_items": [],
            "api_meta": {},
        }

    monkeypatch.setattr("src.profiles.extraction.call_deepseek", fake_call)
    result = extract_profile_candidates(
        [evidence],
        domain="technology_and_ip",
        profile_type="historical",
        config=GenerationConfig(mode="thinking", max_retries=0),
    )

    assert [item["item_id"] for item in result["profile_items"]] == ["tech"]
    assert result["profile_relations"] == []
    assert result["information_gaps"] == ["技术成熟度未披露"]
    assert {item["kind"] for item in result["rejected_candidates"]} == {
        "profile_items",
        "profile_relations",
        "information_gaps",
    }


def test_outcome_domain_requires_separate_outcome_role(monkeypatch):
    from src.evidence.models import EvidenceUnit

    evidence = EvidenceUnit(
        evidence_unit_id="src:outcome",
        source_id="src",
        case_id="c",
        content_type="document_chunk",
        content="交易所决定终止公司股票上市。",
        location={"kind": "html", "node_path": "block[1]"},
        content_hash="hash",
    )

    def fake_call(messages, config):
        assert "content_role=outcome" in messages[1]["content"]
        return {
            "profile_items": [
                {"item_id": "valid", "subject": "the_enterprise", "section_id": "compliance_legal_risk", "field_id": "risk.matter", "value": "股票终止上市", "value_type": "entity_ref", "information_status": "confirmed", "content_role": "outcome", "evidence_unit_ids": ["src:outcome"], "evidence_quote_id": "src:outcome", "evidence_quote": "交易所决定终止公司股票上市。"},
                {"item_id": "wrong", "subject": "the_enterprise", "section_id": "compliance_legal_risk", "field_id": "risk.matter", "value": "宽泛案件名称", "value_type": "entity_ref", "information_status": "confirmed", "content_role": "regulatory_finding", "evidence_unit_ids": ["src:outcome"], "evidence_quote_id": "src:outcome", "evidence_quote": "交易所决定终止公司股票上市。"},
            ],
            "profile_relations": [], "information_gaps": [], "conflicts": [], "unmapped_items": [], "api_meta": {},
        }

    monkeypatch.setattr("src.profiles.extraction.call_deepseek", fake_call)
    result = extract_profile_candidates([evidence], domain="outcome_and_resolution", profile_type="historical", config=GenerationConfig(mode="thinking", max_retries=0))

    assert [item["item_id"] for item in result["profile_items"]] == ["valid"]
    assert any(item["value"]["item_id"] == "wrong" for item in result["rejected_candidates"])


def test_risk_domain_rejects_authoritative_and_outcome_roles():
    data = {
        "profile_items": [
            {
                "item_id": "risk",
                "subject": "the_enterprise",
                "section_id": "compliance_legal_risk",
                "field_id": "risk.matter",
                "value": "行业竞争风险",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:risk"],
                "evidence_quotes": [{"evidence_unit_id": "src:risk", "excerpt": "行业竞争风险"}],
            },
            {
                "item_id": "finding",
                "subject": "the_enterprise",
                "section_id": "compliance_legal_risk",
                "field_id": "risk.matter",
                "value": "无重大违法违规行为",
                "value_type": "entity_ref",
                "information_status": "confirmed",
                "content_role": "regulatory_finding",
                "evidence_unit_ids": ["src:risk"],
                "evidence_quotes": [{"evidence_unit_id": "src:risk", "excerpt": "无重大违法违规行为"}],
            },
        ],
        "profile_relations": [],
        "information_gaps": [],
    }
    filtered = filter_domain_candidates(
        data,
        evidence_unit_ids=["src:risk"],
        evidence_contents={"src:risk": "行业竞争风险；无重大违法违规行为"},
        domain="risk_matters",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["risk"]
    assert any(
        (item.get("value") or item.get("candidate"))["item_id"] == "finding"
        for item in filtered["rejected_candidates"]
    )


def test_risk_domain_rejects_negated_litigation_statement():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "no-litigation",
                    "subject": "the_enterprise",
                    "section_id": "compliance_legal_risk",
                    "field_id": "risk.matter",
                    "value": "重大诉讼、仲裁事项",
                    "value_type": "entity_ref",
                    "information_status": "confirmed",
                    "content_role": "audited_information",
                    "evidence_unit_ids": ["src:risk"],
                    "evidence_quotes": [{
                        "evidence_unit_id": "src:risk",
                        "excerpt": "□本年度公司有重大诉讼、仲裁事项 √本年度公司无重大诉讼、仲裁事项",
                    }],
                }
            ]
        },
        evidence_unit_ids=["src:risk"],
        evidence_contents={
            "src:risk": "□本年度公司有重大诉讼、仲裁事项 √本年度公司无重大诉讼、仲裁事项"
        },
        domain="risk_matters",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert "无重大或未发生的风险事实不得作为风险事项" in filtered["rejected_candidates"][0]["reason"]


def test_risk_domain_rejects_resolved_litigation_even_if_model_marks_claim():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "case",
                    "subject": "the_enterprise",
                    "section_id": "compliance_legal_risk",
                    "field_id": "risk.matter",
                    "value": "甲公司诉本企业侵权案",
                    "value_type": "entity_ref",
                    "information_status": "claimed",
                    "content_role": "enterprise_claim",
                    "evidence_unit_ids": ["src:case"],
                    "evidence_quotes": [{
                        "evidence_unit_id": "src:case",
                        "excerpt": "法院作出判决，驳回上诉，维持原判。",
                    }],
                }
            ]
        },
        evidence_unit_ids=["src:case"],
        evidence_contents={"src:case": "甲公司诉本企业侵权案。法院作出判决，驳回上诉，维持原判。"},
        domain="risk_matters",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert "不属于风险事项" in filtered["rejected_candidates"][0]["reason"]


def test_enterprise_legal_name_rejects_reference_word():
    data = {
        "profile_items": [
            {
                "item_id": "enterprise",
                "section_id": "basic_information",
                "field_id": "enterprise.legal_name",
                "value": "发行人",
                "value_type": "text",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            }
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }

    filtered, rejected = filter_profile_candidates(
        data, evidence_unit_ids=["src:eu_1"], profile_type="historical"
    )

    assert filtered["profile_items"] == []
    assert "不得使用企业指代词" in rejected[0]["reason"]


def test_technology_domain_rejects_legal_name_information_gap():
    filtered, rejected = filter_profile_candidates(
        {
            "profile_items": [],
            "profile_relations": [],
            "information_gaps": [
                "technology_and_ip: 缺少企业法定名称，无法关联核心技术所有权。"
            ],
            "conflicts": [],
            "unmapped_items": [],
        },
        evidence_unit_ids=[],
        profile_type="current",
        information_gap_prefix="technology_and_ip:",
    )

    assert filtered["information_gaps"] == []
    assert "enterprise_and_control" in rejected[0]["reason"]


def test_candidate_filter_warns_when_assertion_and_gap_cover_same_field():
    data = {
        "profile_items": [
            {
                "item_id": "ownership-1",
                "section_id": "technology_ip",
                "field_id": "technology.ownership_status",
                "value": "self_owned",
                "value_type": "enum",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            }
        ],
        "profile_relations": [],
        "information_gaps": ["technology_and_ip: 技术所有权尚无正式权利证明"],
        "conflicts": [],
        "unmapped_items": [],
    }

    filtered, rejected = filter_profile_candidates(
        data,
        evidence_unit_ids=["src:eu_1"],
        profile_type="historical",
        information_gap_prefix="technology_and_ip:",
    )

    assert not rejected
    assert filtered["consistency_warnings"] == [
        {
            "item_id": "ownership-1",
            "field_id": "technology.ownership_status",
            "information_gap": "技术所有权尚无正式权利证明",
            "reason": "该字段已有明确候选值，但信息缺口同时表示其证据仍不充分。",
        }
    ]


def test_candidate_filter_normalizes_only_missing_source_prefix():
    data = {
        "profile_items": [{
            "item_id": "item-1",
            "section_id": "technology_ip",
            "field_id": "technology.name",
            "value": "某项技术",
            "value_type": "entity_ref",
            "information_status": "claimed",
            "content_role": "enterprise_claim",
            "evidence_unit_ids": ["eu_1"],
        }],
        "profile_relations": [], "information_gaps": [], "conflicts": [], "unmapped_items": [],
    }
    filtered, rejected = filter_profile_candidates(
        data, evidence_unit_ids=["src:eu_1"], profile_type="historical"
    )
    assert not rejected
    assert filtered["profile_items"][0]["evidence_unit_ids"] == ["src:eu_1"]


def test_evidence_selection_prompt_contains_catalog_but_not正文():
    from src.evidence.models import EvidenceUnit
    from src.profiles.extraction import build_evidence_catalog

    evidence = EvidenceUnit(
        evidence_unit_id="src:eu_1",
        source_id="src",
        case_id="c",
        content_type="document_chunk",
        content="正文中包含敏感的具体事实。",
        location={"kind": "html"},
        metadata={
            "title": "处罚决定",
            "source_title": "示例科技股份有限公司2024年年度报告",
            "section_path": ["监管处罚"],
        },
        source_date="2025-03-01",
        content_hash="hash",
    )
    catalog = build_evidence_catalog([evidence], keywords=("处罚",))
    messages = build_evidence_selection_messages(
        catalog, domain="risk_matters", max_selected=3
    )

    assert "src:eu_1" in messages[1]["content"]
    assert "处罚决定" in messages[1]["content"]
    assert "示例科技股份有限公司2024年年度报告" in messages[1]["content"]
    assert "2025-03-01" in messages[1]["content"]
    assert "正文中包含敏感的具体事实" not in messages[1]["content"]


def test_profile_review_is_required_before_formal_profile_status():
    candidates = {
        "profile_items": [
            {
                "item_id": "item-1",
                "section_id": "technology_ip",
                "field_id": "technology.name",
                "value": "某项技术",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            }
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    assert finalize_profile_review(
        candidates,
        evidence_unit_ids=["src:eu_1"],
        decision="reject",
        profile_id="p-1",
        case_id="c-1",
        enterprise_name="测试企业",
        profile_type="historical",
    ) is None
    profile = finalize_profile_review(
        candidates,
        evidence_unit_ids=["src:eu_1"],
        decision="accept",
        profile_id="p-1",
        case_id="c-1",
        enterprise_name="测试企业",
        profile_type="historical",
    )
    assert profile is not None
    assert profile.review_status == "approved"
    assert profile.items[0].review_status == "accepted"


def test_reviewed_profile_can_be_saved(tmp_path):
    candidates = {
        "profile_items": [
            {
                "item_id": "item-1",
                "section_id": "technology_ip",
                "field_id": "technology.name",
                "value": "某项技术",
                "value_type": "entity_ref",
                "information_status": "claimed",
                "content_role": "enterprise_claim",
                "evidence_unit_ids": ["src:eu_1"],
            }
        ],
        "profile_relations": [],
        "information_gaps": [],
        "conflicts": [],
        "unmapped_items": [],
    }
    profile_repository = ProfileRepository(tmp_path / "profiles.db")
    profile = finalize_and_save_profile_review(
        candidates,
        repository=profile_repository,
        evidence_unit_ids=["src:eu_1"],
        decision="accept",
        profile_id="p-1",
        case_id="c-1",
        enterprise_name="测试企业",
        profile_type="historical",
    )
    assert profile_repository.get("p-1") is not None
    assert profile is not None and profile.review_status == "approved"


def test_historical_workflow_reuses_evidence_search_without_calling_api(tmp_path):
    path = tmp_path / "notice.html"
    path.write_text("<h1>处罚决定</h1><p>监管认定存在虚构销售。</p>", encoding="utf-8")
    source, units = ingest_source(path, case_id="ZJ")
    repository = EvidenceRepository(tmp_path / "evidence.db")
    repository.save_source(source)
    repository.save_units(list(units))

    calls = []

    def fake_extractor(evidence_units, **kwargs):
        calls.append((kwargs["domain"], len(evidence_units)))
        return {"profile_items": [], "profile_relations": [], "information_gaps": [], "conflicts": [], "unmapped_items": []}

    def fake_selector(catalog, **kwargs):
        return [catalog[0]["evidence_unit_id"]]

    run = HistoricalProfileWorkflow(
        EvidenceQueryService(repository), extractor=fake_extractor, selector=fake_selector
    ).run(
        case_id="ZJ",
        config=GenerationConfig(mode="thinking", max_retries=0),
        domains=("risk_matters",),
    )

    assert calls == [("risk_matters", 1)]
    assert run.domains[0].candidates is not None
    assert run.domains[0].selected_evidence_unit_ids == (units[0].evidence_unit_id,)


def test_current_workflow_preserves_evidence_selection_api_meta(tmp_path):
    path = tmp_path / "notice.html"
    path.write_text("<h1>核心技术</h1><p>企业披露某项核心技术。</p>", encoding="utf-8")
    source, units = ingest_source(path, case_id="CURRENT")
    repository = EvidenceRepository(tmp_path / "evidence.db")
    repository.save_source(source)
    repository.save_units(list(units))

    def fake_selector(catalog, **kwargs):
        return EvidenceSelectionResult(
            (catalog[0]["evidence_unit_id"],),
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )

    run = CurrentProfileWorkflow(
        EvidenceQueryService(repository),
        selector=fake_selector,
        extractor=lambda evidence_units, **kwargs: {
            "profile_items": [],
            "profile_relations": [],
            "information_gaps": [],
            "conflicts": [],
            "unmapped_items": [],
        },
    ).run(
        case_id="CURRENT",
        config=GenerationConfig(mode="thinking", max_retries=0),
        domains=("technology_and_ip",),
    )

    assert run.domains[0].selection_api_meta["total_tokens"] == 120


def test_balanced_evidence_search_queries_all_keywords_and_prefers_new_sections():
    from src.evidence.models import EvidenceUnit

    def unit(unit_id, title):
        return EvidenceUnit(
            evidence_unit_id=unit_id,
            source_id="src",
            case_id="ZJ",
            content_type="document_chunk",
            content=title,
            location={"kind": "pdf"},
            metadata={"title": title, "section_path": [title]},
            content_hash=unit_id,
        )

    first = unit("src:1", "核心技术")
    same_section = EvidenceUnit(
        evidence_unit_id="src:2",
        source_id="src",
        case_id="ZJ",
        content_type="document_chunk",
        content="核心技术续页",
        location={"kind": "pdf"},
        metadata={"title": "核心技术", "section_path": ["核心技术"]},
        content_hash="src:2",
    )
    patent = unit("src:3", "专利权属")

    class FakeEvidenceService:
        def __init__(self):
            self.calls = []

        def search_evidence(self, query, **kwargs):
            self.calls.append(query)
            return {
                "核心技术": [first, same_section],
                "专利": [first, patent],
            }[query]

    service = FakeEvidenceService()
    result = search_balanced_evidence(
        service,
        case_id="ZJ",
        keywords=("核心技术", "专利"),
        limit=3,
    )

    assert service.calls == ["核心技术", "专利"]
    assert [item.evidence_unit_id for item in result] == ["src:1", "src:3", "src:2"]


def test_team_workflow_uses_complete_local_person_bundle_without_llm_selection():
    from src.evidence.models import EvidenceUnit

    def unit(unit_id, content, *, block_type=None, person_name=None):
        metadata = {"title": content.splitlines()[0], "section_path": ["人员情况"]}
        if block_type:
            metadata["block_type"] = block_type
        if person_name:
            metadata["person_name"] = person_name
        return EvidenceUnit(
            evidence_unit_id=unit_id,
            source_id="src",
            case_id="TEAM",
            content_type="document_chunk",
            content=content,
            location={"kind": "pdf", "page_start": 1, "page_end": 1},
            metadata=metadata,
            content_hash=unit_id,
        )

    roster = unit("src:roster", "姓名 职务 性别\n甲某 核心技术人员 男")
    controller = unit("src:controller", "实际控制人为甲某和乙某。")
    team_summary = unit(
        "src:summary",
        "研发团队概况\n研发人员共20人，其中硕士8人、本科12人。",
    )
    incentive = unit("src:incentive", "股权激励计划：不适用。")
    first = unit(
        "src:p1", "甲某\n男，本科学历。主要职业经历：曾任工程师。",
        block_type="person_biography", person_name="甲某",
    )
    second = unit(
        "src:p2", "乙某 女，硕士学历。主要职业经历：曾任总经理。",
        block_type="person_biography", person_name="乙某",
    )
    unrelated = unit("src:other", "营业收入为100万元。")

    class TeamEvidenceService:
        def list_evidence(self, *, case_id):
            assert case_id == "TEAM"
            return [roster, controller, team_summary, incentive, first, second, unrelated]

    service = TeamEvidenceService()
    bundle = build_team_evidence_bundle(service, case_id="TEAM")
    assert [item.evidence_unit_id for item in bundle] == [
        "src:roster", "src:controller", "src:summary", "src:incentive", "src:p1", "src:p2"
    ]

    extracted = []

    def fake_extractor(evidence_units, **kwargs):
        extracted.extend(evidence_units)
        return {"profile_items": [], "profile_relations": [], "information_gaps": [], "conflicts": [], "unmapped_items": []}

    def forbidden_selector(*args, **kwargs):
        raise AssertionError("team领域不应再调用模型做5条证据选择")

    run = HistoricalProfileWorkflow(
        service, extractor=fake_extractor, selector=forbidden_selector
    ).run(
        case_id="TEAM",
        config=GenerationConfig(mode="thinking", max_retries=0),
        domains=("team",),
        max_selected_evidence_per_domain=1,
    )

    assert [item.evidence_unit_id for item in extracted] == [
        "src:roster", "src:controller", "src:summary", "src:incentive", "src:p1", "src:p2"
    ]
    assert run.domains[0].selection_api_meta == {
        "skipped": True,
        "reason": "team_evidence_bundle_selected_locally",
        "person_units": 2,
    }


def test_current_workflow_keeps_current_semantics_and_reads_selected_units(tmp_path):
    path = tmp_path / "current.html"
    path.write_text("<h1>技术</h1><p>当前企业研发核心技术。</p>", encoding="utf-8")
    source, units = ingest_source(path, case_id="NEW")
    repository = EvidenceRepository(tmp_path / "current.db")
    repository.save_source(source)
    repository.save_units(list(units))

    def fake_selector(catalog, **kwargs):
        return [catalog[0]["evidence_unit_id"]]

    def fake_extractor(evidence_units, **kwargs):
        assert kwargs["profile_type"] == "current"
        return {"profile_items": [], "profile_relations": [], "information_gaps": [], "conflicts": [], "unmapped_items": []}

    run = CurrentProfileWorkflow(
        EvidenceQueryService(repository), selector=fake_selector, extractor=fake_extractor
    ).run(
        case_id="NEW",
        config=GenerationConfig(mode="thinking", max_retries=0),
        query="核心技术",
        domains=("technology_and_ip",),
    )

    assert run.profile_type == "current"
    assert len(run.domains[0].selected_evidence_unit_ids) == 1
    assert "核心技术" in run.domains[0].evidence_units[0].content


def test_profile_candidates_deduplicate_enterprise_and_entity_subject_aliases():
    common = {
        "section_id": "technology_ip",
        "field_id": "technology.name",
        "value": "Tech-A",
        "value_type": "entity_ref",
        "information_status": "confirmed",
        "content_role": "business_record",
        "evidence_quotes": [
            {"evidence_unit_id": "src:tech", "excerpt": "Tech-A"}
        ],
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {"item_id": "item-1", "subject": "the_enterprise", **common},
                {"item_id": "item-2", "subject": "Tech-A", **common},
            ],
            "profile_relations": [],
            "information_gaps": [],
        },
        evidence_unit_ids=["src:tech"],
        evidence_contents={"src:tech": "Tech-A"},
        domain="technology_and_ip",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == ["item-1"]
    assert filtered["profile_items"][0]["evidence_unit_ids"] == ["src:tech"]
    assert filtered["deduplicated_candidates"][0]["removed_item_id"] == "item-2"


def test_product_technology_suffix_is_not_product_just_because_quote_says_product_technology():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "tech-as-product",
                    "subject": "the_enterprise",
                    "section_id": "product_research_commercialization",
                    "field_id": "product.name",
                    "value": "机器人设计技术",
                    "value_type": "entity_ref",
                    "information_status": "confirmed",
                    "content_role": "business_record",
                    "evidence_unit_ids": ["src:product"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:product",
                            "excerpt": "机器人设计技术主要为产品技术。",
                        }
                    ],
                }
            ],
            "profile_relations": [],
            "information_gaps": [],
        },
        evidence_unit_ids=["src:product"],
        evidence_contents={"src:product": "机器人设计技术主要为产品技术。"},
        domain="product_and_project",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert filtered["rejected_candidates"][0]["candidate_id"] == "tech-as-product"


def test_customer_supplier_report_period_header_supports_transaction_row():
    content = "报告期内主要客户情况\n客户名称 销售额 占比\n第一名 100.00 10.00%"
    common = {
        "subject": "第一名",
        "section_id": "customer_supplier_partners",
        "information_status": "confirmed",
        "content_role": "audited_information",
        "evidence_unit_ids": ["src:customer"],
        "evidence_quotes": [
            {"evidence_unit_id": "src:customer", "excerpt": "第一名 100.00 10.00%"}
        ],
        "reporting_period": "2025",
    }
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "customer-amount",
                    "field_id": "customer_supplier.transaction_amount",
                    "value": 100.0,
                    "value_type": "money",
                    "unit": "万元",
                    "value_scope": "向主要客户销售金额",
                    **common,
                },
                {
                    "item_id": "customer-ratio",
                    "field_id": "customer_supplier.transaction_ratio",
                    "value": 0.1,
                    "value_type": "ratio",
                    "value_scope": "占营业收入比例",
                    **common,
                },
            ],
            "profile_relations": [],
            "information_gaps": [],
        },
        evidence_unit_ids=["src:customer"],
        evidence_contents={"src:customer": content},
        domain="customer_and_supplier",
        profile_type="current",
    )

    assert [item["item_id"] for item in filtered["profile_items"]] == [
        "customer-amount",
        "customer-ratio",
    ]
    assert filtered["rejected_candidates"] == []


def test_authoritative_finding_rejects_business_bankruptcy_notice():
    filtered = filter_domain_candidates(
        {
            "profile_items": [
                {
                    "item_id": "bankruptcy-notice",
                    "subject": "the_enterprise",
                    "section_id": "compliance_legal_risk",
                    "field_id": "risk.matter",
                    "value": "收到对方破产重整通知并申报债权",
                    "value_type": "entity_ref",
                    "information_status": "confirmed",
                    "content_role": "judicial_finding",
                    "evidence_unit_ids": ["src:notice"],
                    "evidence_quotes": [
                        {
                            "evidence_unit_id": "src:notice",
                            "excerpt": "公司收到对方破产重整通知并申报债权。",
                        }
                    ],
                }
            ],
            "profile_relations": [],
            "information_gaps": [],
        },
        evidence_unit_ids=["src:notice"],
        evidence_contents={"src:notice": "公司收到对方破产重整通知并申报债权。"},
        domain="authoritative_findings",
        profile_type="current",
    )

    assert filtered["profile_items"] == []
    assert filtered["rejected_candidates"][0]["candidate_id"] == "bankruptcy-notice"
