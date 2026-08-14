from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from src.llm.generation_config import GenerationConfig
from src.ontology.schema import ONTOLOGY_VERSION
from src.profiles import (
    ComparisonCardRepository,
    ComparisonCardSimilarityService,
    ComparisonDimension,
    CurrentEnterpriseProfile,
    EnterpriseComparisonCard,
    EvidenceReference,
    HistoricalEnterpriseProfile,
    ProfileItem,
    ProfileRelation,
    ProfileRepository,
    approve_comparison_card,
    build_comparison_card_messages,
    build_detailed_comparison_messages,
    compare_profile_candidates,
    generate_comparison_card,
    profile_content_hash,
)
from src.profiles.comparison_retrieval import ComparisonCardMatch
from src.profiles.detailed_comparison import _require_chinese, _validate_comparisons


def profile_item(
    item_id: str,
    field_id: str,
    section_id: str,
    value,
    value_type: str,
) -> ProfileItem:
    return ProfileItem(
        item_id=item_id,
        field_id=field_id,
        section_id=section_id,
        value=value,
        value_type=value_type,
        information_status="supported",
        content_role="business_record",
        evidence_refs=(EvidenceReference(f"src:{item_id}"),),
        review_status="accepted",
    )


def approved_profile(profile_type: str = "historical"):
    profile_class = (
        HistoricalEnterpriseProfile
        if profile_type == "historical"
        else CurrentEnterpriseProfile
    )
    return profile_class(
        profile_id=f"{profile_type}-profile",
        case_id=f"{profile_type}-case",
        enterprise_name=f"{profile_type}企业",
        items=(
            profile_item(
                "technology",
                "technology.ownership_status",
                "technology_ip",
                "licensed",
                "enum",
            ),
            profile_item(
                "risk",
                "risk.matter",
                "compliance_legal_risk",
                "专利许可费用风险",
                "entity_ref",
            ),
        ),
        relations=(
            ProfileRelation(
                relation_id="licenses",
                relation_type="licenses",
                source_id="enterprise",
                source_type="Enterprise",
                target_id="technology",
                target_type="Technology",
                information_status="supported",
                content_role="business_record",
                evidence_refs=(EvidenceReference("src:technology"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )


def test_comparison_card_prompt_uses_profile_not_raw_evidence():
    profile = approved_profile()

    context = {
        "case_id": profile.case_id,
        "enterprise_name": profile.enterprise_name,
        "reporting_periods": ["2019"],
        "source_documents": [{"document_title": "历史企业2019年年度报告"}],
    }
    messages = build_comparison_card_messages(profile, material_context=context)

    assert "technology.ownership_status" in messages[1]["content"]
    assert "source_item_ids" in messages[1]["content"]
    assert "evidence_unit_ids" in messages[1]["content"]
    assert "原始长文" not in messages[1]["content"]
    assert "历史企业2019年年度报告" in messages[1]["content"]


def test_detailed_comparison_prompt_requires_chinese_output():
    current = approved_profile("current")
    historical = approved_profile("historical")
    match = ComparisonCardMatch(
        historical_card_id="historical-card",
        historical_profile_id=historical.profile_id,
        historical_case_id=historical.case_id,
        historical_enterprise_name=historical.enterprise_name,
        score=0.5,
        structured_score=0.5,
        bm25_score=0.5,
        embedding_score=None,
        matched_dimensions=("technology_and_ip",),
        matched_features=(),
        matched_terms=(),
        matched_relation_signatures=(),
        evidence_unit_ids=(),
    )

    messages = build_detailed_comparison_messages(
        current,
        [historical],
        [match],
        material_contexts={
            current.profile_id: {"source_documents": [{"document_title": "当前企业材料.pdf"}]},
            historical.profile_id: {"source_documents": [{"document_title": "历史企业材料.pdf"}]},
        },
    )

    assert "必须使用简体中文" in messages[0]["content"]
    assert "不得输出英文句子" in messages[1]["content"]
    assert "不得根据企业名称、技术常识或外部知识" in messages[1]["content"]
    assert "不得扩展到其他领域" in messages[1]["content"]
    assert "当前企业材料.pdf" in messages[1]["content"]
    assert "历史企业材料.pdf" in messages[1]["content"]


def test_detailed_comparison_rejects_english_natural_language():
    with pytest.raises(ValueError, match="必须使用简体中文"):
        _require_chinese(
            "Both enterprises claim to possess proprietary core technologies.",
            "explanation",
        )


def test_generate_comparison_card_derives_features_relations_and_evidence(monkeypatch):
    profile = approved_profile()

    def fake_call(messages, config):
        return {
            "comparison_dimensions": [
                {
                    "dimension_id": "technology_and_ip",
                    "summary": "核心产品依赖外部许可技术。",
                    "comparison_terms": ["外部技术许可", "专利授权"],
                    "source_item_ids": ["technology"],
                    "source_relation_ids": ["licenses"],
                    "information_gaps": [],
                },
                {
                    "dimension_id": "made_up",
                    "summary": "非法维度。",
                    "comparison_terms": ["非法"],
                    "source_item_ids": ["technology"],
                    "source_relation_ids": [],
                },
            ],
            "api_meta": {"total_tokens": 100},
        }

    monkeypatch.setattr("src.profiles.comparison_cards.call_deepseek", fake_call)
    card, api_meta = generate_comparison_card(
        profile,
        config=GenerationConfig(mode="thinking", max_retries=0),
    )

    assert len(card.dimensions) == 1
    dimension = card.dimensions[0]
    assert dimension.structured_features == {
        "technology.ownership_status": "licensed"
    }
    assert dimension.relation_signatures == (
        "Enterprise-licenses-Technology",
    )
    assert dimension.evidence_unit_ids == ("src:technology",)
    assert card.profile_hash == profile_content_hash(profile)
    assert api_meta["total_tokens"] == 100


def test_comparison_card_repository_round_trip_and_stale_detection(tmp_path):
    database = tmp_path / "cards.db"
    profile = approved_profile()
    ProfileRepository(database).save(profile)
    card = approve_comparison_card(
        EnterpriseComparisonCard(
            card_id="card-1",
            profile_id=profile.profile_id,
            case_id=profile.case_id,
            enterprise_name=profile.enterprise_name,
            profile_type=profile.profile_type,
            ontology_version=profile.ontology_version,
            profile_hash=profile_content_hash(profile),
            dimensions=(
                ComparisonDimension(
                    dimension_id="technology_and_ip",
                    summary="依赖外部许可技术。",
                    comparison_terms=("外部许可", "技术依赖"),
                    structured_features={
                        "technology.ownership_status": "licensed"
                    },
                    evidence_unit_ids=("src:technology",),
                ),
            ),
        )
    )
    repository = ComparisonCardRepository(database)
    repository.save(card)

    loaded = repository.get_by_profile(profile.profile_id)

    assert loaded == card
    assert loaded is not None and repository.is_current(loaded, profile)
    changed = HistoricalEnterpriseProfile(
        profile_id=profile.profile_id,
        case_id=profile.case_id,
        enterprise_name=profile.enterprise_name,
        items=profile.items + (
            profile_item(
                "product",
                "product.name",
                "product_research_commercialization",
                "光存储产品",
                "entity_ref",
            ),
        ),
        relations=profile.relations,
        review_status="approved",
    )
    assert not repository.is_current(card, changed)


def card(
    *,
    card_id: str,
    case_id: str,
    profile_id: str,
    profile_type: str,
    ownership: str,
    summary: str,
    terms: tuple[str, ...],
    profile_hash: str | None = None,
) -> EnterpriseComparisonCard:
    return EnterpriseComparisonCard(
        card_id=card_id,
        profile_id=profile_id,
        case_id=case_id,
        enterprise_name=case_id,
        profile_type=profile_type,
        ontology_version=ONTOLOGY_VERSION,
        profile_hash=profile_hash or f"hash-{card_id}",
        review_status="approved",
        dimensions=(
            ComparisonDimension(
                dimension_id="technology_and_ip",
                summary=summary,
                comparison_terms=terms,
                structured_features={
                    "technology.ownership_status": ownership
                },
                relation_signatures=("Enterprise-licenses-Technology",)
                if ownership == "licensed"
                else (),
                evidence_unit_ids=(f"src:{card_id}",),
            ),
        ),
    )


def test_comparison_card_similarity_combines_structure_and_variable_text(tmp_path):
    database = tmp_path / "similarity.db"
    profile_repository = ProfileRepository(database)
    saved_profiles = {}
    for profile_id, case_id, name in (
        ("h1-profile", "H1", "相似企业"),
        ("h2-profile", "H2", "不同企业"),
        ("current-profile", "CURRENT", "当前企业"),
    ):
        profile_class = (
            CurrentEnterpriseProfile
            if profile_id == "current-profile"
            else HistoricalEnterpriseProfile
        )
        saved_profile = profile_class(
                profile_id=profile_id,
                case_id=case_id,
                enterprise_name=name,
                review_status="approved",
            )
        profile_repository.save(saved_profile)
        saved_profiles[profile_id] = saved_profile
    repository = ComparisonCardRepository(database)
    repository.save(
        card(
            card_id="h1",
            case_id="H1",
            profile_id="h1-profile",
            profile_type="historical",
            ownership="licensed",
            summary="产品依赖外部专利池许可并支付授权费用。",
            terms=("专利池", "外部许可", "授权费用"),
            profile_hash=profile_content_hash(saved_profiles["h1-profile"]),
        )
    )
    repository.save(
        card(
            card_id="h2",
            case_id="H2",
            profile_id="h2-profile",
            profile_type="historical",
            ownership="owned",
            summary="企业拥有自主核心技术。",
            terms=("自主技术", "自有专利"),
            profile_hash=profile_content_hash(saved_profiles["h2-profile"]),
        )
    )
    current = card(
        card_id="current",
        case_id="CURRENT",
        profile_id="current-profile",
        profile_type="current",
        ownership="licensed",
        summary="产品使用外部专利许可，存在持续授权费用。",
        terms=("外部许可", "授权费用"),
        profile_hash=profile_content_hash(saved_profiles["current-profile"]),
    )

    results = ComparisonCardSimilarityService(repository).find_similar(current)

    assert results[0].historical_card_id == "h1"
    assert results[0].matched_features == ("technology.ownership_status",)
    assert "外部许可" in results[0].matched_terms
    assert results[0].matched_dimensions == ("technology_and_ip",)
    assert results[0].evidence_unit_ids == ("src:h1",)


def test_similarity_does_not_mix_different_ontology_versions(tmp_path):
    database = tmp_path / "ontology-version.db"
    historical_profile = HistoricalEnterpriseProfile(
        profile_id="historical-v03",
        case_id="H-V03",
        enterprise_name="旧版历史企业",
        ontology_version="0.3.0",
        review_status="approved",
    )
    ProfileRepository(database).save(historical_profile)
    repository = ComparisonCardRepository(database)
    repository.save(
        replace(
            card(
                card_id="historical-v03-card",
                case_id="H-V03",
                profile_id=historical_profile.profile_id,
                profile_type="historical",
                ownership="licensed",
                summary="外部许可技术",
                terms=("外部许可",),
                profile_hash=profile_content_hash(historical_profile),
            ),
            ontology_version="0.3.0",
        )
    )
    current = card(
        card_id="current-v04-card",
        case_id="C-V04",
        profile_id="current-v04",
        profile_type="current",
        ownership="licensed",
        summary="外部许可技术",
        terms=("外部许可",),
    )

    assert ComparisonCardSimilarityService(repository).find_similar(current) == []


def test_similarity_deduplicates_same_enterprise_by_profile_coverage(tmp_path):
    database = tmp_path / "dedupe.db"
    profiles = ProfileRepository(database)
    small = HistoricalEnterpriseProfile(profile_id="small", case_id="H-small", enterprise_name="同一历史企业", review_status="approved")
    complete = HistoricalEnterpriseProfile(profile_id="complete", case_id="H-complete", enterprise_name="同一历史企业", review_status="approved")
    current_profile = CurrentEnterpriseProfile(profile_id="current", case_id="CURRENT", enterprise_name="当前企业", review_status="approved")
    for profile in (small, complete, current_profile):
        profiles.save(profile)
    repository = ComparisonCardRepository(database)
    repository.save(replace(card(card_id="small-card", case_id="H-small", profile_id="small", profile_type="historical", ownership="licensed", summary="外部许可技术", terms=("外部许可",), profile_hash=profile_content_hash(small)), enterprise_name="同一历史企业"))
    complete_card = replace(
        card(card_id="complete-card", case_id="H-complete", profile_id="complete", profile_type="historical", ownership="licensed", summary="外部许可技术", terms=("外部许可",), profile_hash=profile_content_hash(complete)),
        enterprise_name="同一历史企业",
        dimensions=(
            ComparisonDimension(dimension_id="technology_and_ip", summary="外部许可技术", comparison_terms=("外部许可",)),
            ComparisonDimension(dimension_id="risk_and_compliance", summary="存在已披露合规事项", comparison_terms=("合规",)),
        ),
    )
    repository.save(complete_card)
    current = card(card_id="current-card", case_id="CURRENT", profile_id="current", profile_type="current", ownership="licensed", summary="外部许可技术", terms=("外部许可",), profile_hash=profile_content_hash(current_profile))

    results = ComparisonCardSimilarityService(repository).find_similar(current)

    assert [item.historical_card_id for item in results] == ["complete-card"]


class TinyEncoder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            vectors.append(
                [
                    float("外部" in text),
                    float("自主" in text),
                    1.0,
                ]
            )
        return np.asarray(vectors, dtype=np.float32)


def test_comparison_card_similarity_supports_optional_embedding(tmp_path):
    database = tmp_path / "embedding.db"
    profiles = ProfileRepository(database)
    historical_profile = HistoricalEnterpriseProfile(
            profile_id="h-profile",
            case_id="H",
            enterprise_name="历史企业",
            review_status="approved",
        )
    current_profile = CurrentEnterpriseProfile(
            profile_id="c-profile",
            case_id="C",
            enterprise_name="当前企业",
            review_status="approved",
        )
    profiles.save(historical_profile)
    profiles.save(current_profile)
    repository = ComparisonCardRepository(database)
    repository.save(
        card(
            card_id="h",
            case_id="H",
            profile_id="h-profile",
            profile_type="historical",
            ownership="owned",
            summary="依靠外部平台实现关键功能。",
            terms=("平台依赖", "外部能力"),
            profile_hash=profile_content_hash(historical_profile),
        )
    )
    current = card(
        card_id="c",
        case_id="C",
        profile_id="c-profile",
        profile_type="current",
        ownership="licensed",
        summary="核心功能依赖外部服务。",
        terms=("外部服务",),
        profile_hash=profile_content_hash(current_profile),
    )

    results = ComparisonCardSimilarityService(
        repository, encoder=TinyEncoder()
    ).find_similar(current)

    assert results[0].embedding_score is not None


def test_detailed_comparison_validates_ids_and_derives_evidence(monkeypatch):
    current = CurrentEnterpriseProfile(
        profile_id="current-detail",
        case_id="CURRENT",
        enterprise_name="当前企业",
        items=(
            profile_item(
                "current-tech",
                "technology.ownership_status",
                "technology_ip",
                "licensed",
                "enum",
            ),
        ),
        review_status="approved",
    )
    historical = HistoricalEnterpriseProfile(
        profile_id="historical-detail",
        case_id="HISTORY",
        enterprise_name="历史企业",
        items=(
            profile_item(
                "historical-tech",
                "technology.ownership_status",
                "technology_ip",
                "licensed",
                "enum",
            ),
            ProfileItem(
                item_id="historical-outcome",
                field_id="risk.matter",
                section_id="compliance_legal_risk",
                value="监管处罚",
                value_type="entity_ref",
                information_status="confirmed",
                content_role="regulatory_finding",
                evidence_refs=(EvidenceReference("src:outcome"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )
    match = ComparisonCardMatch(
        historical_card_id="h-card",
        historical_profile_id=historical.profile_id,
        historical_case_id=historical.case_id,
        historical_enterprise_name=historical.enterprise_name,
        score=0.8,
        structured_score=0.7,
        bm25_score=0.6,
        embedding_score=None,
        matched_dimensions=("technology_and_ip",),
        matched_features=("technology.ownership_status",),
        matched_terms=(),
        matched_relation_signatures=(),
        evidence_unit_ids=("src:historical-tech",),
    )

    def fake_call(messages, config):
        return {
            "comparisons": [
                {
                    "historical_profile_id": historical.profile_id,
                    "similarity_basis": [
                        {
                            "dimension_id": "technology_and_ip",
                            "explanation": "双方均使用外部许可技术。",
                            "current_item_ids": ["current-tech", "invented"],
                            "historical_item_ids": ["historical-tech"],
                            "current_relation_ids": [],
                            "historical_relation_ids": [],
                        }
                    ],
                    "key_differences": [],
                    "historical_outcomes": [
                        {
                            "dimension_id": "authority_outcome_and_evidence",
                            "explanation": "历史企业后续受到监管处罚。",
                            "current_item_ids": [],
                            "historical_item_ids": ["historical-outcome"],
                            "current_relation_ids": [],
                            "historical_relation_ids": [],
                        }
                    ],
                    "applicability_limits": ["当前材料尚未出现同类监管结论。"],
                    "verification_questions": ["技术许可协议是否持续有效？"],
                }
            ],
            "api_meta": {"total_tokens": 200},
        }

    monkeypatch.setattr(
        "src.profiles.detailed_comparison.call_deepseek", fake_call
    )
    run = compare_profile_candidates(
        current,
        [historical],
        [match],
        config=GenerationConfig(mode="thinking", max_retries=0),
    )

    comparison = run.comparisons[0]
    assert comparison.retrieval_score == 0.8
    assert comparison.similarity_basis[0].current_item_ids == ("current-tech",)
    assert comparison.similarity_basis[0].evidence_unit_ids == (
        "src:current-tech",
        "src:historical-tech",
    )
    assert comparison.historical_outcomes[0].evidence_unit_ids == (
        "src:outcome",
    )
    assert run.api_meta["total_tokens"] == 200


def test_detailed_comparison_derives_outcomes_and_filters_historical_transfer():
    base_current = approved_profile("current")
    current = CurrentEnterpriseProfile(
        profile_id=base_current.profile_id,
        case_id=base_current.case_id,
        enterprise_name=base_current.enterprise_name,
        items=base_current.items,
        relations=base_current.relations,
        information_gaps=("technology_and_ip: 缺少企业法定名称",),
        review_status="approved",
    )
    historical = HistoricalEnterpriseProfile(
        profile_id="historical-outcome-profile",
        case_id="HISTORY",
        enterprise_name="历史企业",
        items=(
            ProfileItem(
                item_id="outcome",
                field_id="risk.matter",
                section_id="compliance_legal_risk",
                value="股票终止上市",
                value_type="entity_ref",
                information_status="confirmed",
                content_role="outcome",
                evidence_refs=(EvidenceReference("src:outcome"),),
                review_status="accepted",
            ),
        ),
        review_status="approved",
    )
    match = ComparisonCardMatch(
        historical_card_id="h", historical_profile_id=historical.profile_id,
        historical_case_id="HISTORY", historical_enterprise_name="历史企业",
        score=0.5, structured_score=0.0, bm25_score=0.5, embedding_score=None,
        matched_dimensions=(), matched_features=(), matched_terms=(),
        matched_relation_signatures=(), evidence_unit_ids=(),
    )
    raw = [{
        "historical_profile_id": historical.profile_id,
        "similarity_basis": [], "key_differences": [], "historical_outcomes": [],
        "applicability_limits": [],
        "verification_questions": [
            "请补充企业法定名称。",
            "应警惕技术欺诈风险。",
            "是否有第三方测试材料？",
        ],
    }]

    comparison = _validate_comparisons(current, (historical,), (match,), raw)[0]

    assert comparison.historical_outcomes[0].explanation == "股票终止上市"
    assert comparison.historical_outcomes[0].evidence_unit_ids == ("src:outcome",)
    assert comparison.verification_questions == ("是否有第三方测试材料？",)
