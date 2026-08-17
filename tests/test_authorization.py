from src.authorization import (
    can_edit_business_prompts,
    can_run_approval_section,
    can_run_profile_dimension,
    can_run_profile_domain,
    can_view_field,
    filter_profile_for_role,
    get_role_options,
)
from src.profiles.models import (
    CurrentEnterpriseProfile,
    EvidenceReference,
    ProfileItem,
    ProfileRelation,
)


def _item(item_id: str, field_id: str, value: str, subject: str) -> ProfileItem:
    return ProfileItem(
        item_id=item_id,
        field_id=field_id,
        section_id="ownership_governance_team" if field_id.startswith("team.") else "basic_information",
        value=value,
        value_type="text" if field_id != "team.key_person" else "entity_ref",
        information_status="claimed",
        content_role="enterprise_claim",
        evidence_refs=(EvidenceReference("src:1"),),
        subject=subject,
        review_status="accepted",
    )


def test_roles_and_business_prompt_permissions():
    assert get_role_options() == {
        "general_business": "一般业务人员",
        "senior_business": "高级业务人员",
    }
    assert can_edit_business_prompts("general_business") is False
    assert can_edit_business_prompts("senior_business") is True
    assert can_view_field("general_business", "team.education_structure") is False
    assert can_view_field("general_business", "finance.operating_revenue") is True
    assert can_view_field("senior_business", "team.education_structure") is True


def test_general_business_cannot_run_team_profile_work():
    assert can_run_profile_domain("general_business", "team") is False
    assert can_run_profile_dimension("general_business", "enterprise_and_team") is False
    assert can_run_profile_domain("general_business", "technology_and_ip") is True
    assert can_run_profile_dimension("general_business", "technology_and_ip") is True
    assert can_run_approval_section("general_business", "core_team") is False
    assert can_run_approval_section("general_business", "technology_strength") is True
    assert can_run_approval_section("senior_business", "core_team") is True


def test_profile_filter_removes_sensitive_items_and_dangling_relations():
    enterprise = _item("enterprise-name", "enterprise.main_business", "机器人", "the_enterprise")
    person = _item("person-1", "team.key_person", "张三", "张三")
    relation = ProfileRelation(
        relation_id="position-1",
        relation_type="holds_position_in",
        source_id="person-1",
        source_type="Person",
        target_id="the_enterprise",
        target_type="Enterprise",
        information_status="claimed",
        content_role="enterprise_claim",
        evidence_refs=(EvidenceReference("src:1"),),
    )
    profile = CurrentEnterpriseProfile(
        profile_id="p-1",
        case_id="case-1",
        enterprise_name="测试企业",
        items=(enterprise, person),
        relations=(relation,),
        review_status="approved",
    )

    filtered = filter_profile_for_role(profile, "general_business")
    assert [item.item_id for item in filtered.items] == ["enterprise-name"]
    assert filtered.relations == ()
