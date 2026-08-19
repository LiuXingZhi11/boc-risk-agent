from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.platform.mcp.config import load_server_configs
from src.platform.mcp.models import MCPServerConfig, MCPToolInfo, ToolReference
from src.platform.mcp.registry import MCPProviderManager
from src.platform.mcp.tool_catalog import MCPToolCatalog
from src.platform.skills.loader import SkillLoader
from src.platform.skills.registry import SkillRegistry
from src.platform.skills.resolver import SkillResolver
from src.platform.skills.runtime import SkillRuntimeContext
from src.platform.skills.schema import SkillValidationError
from tests.fakes.mcp_server import FakeMCPProvider


def test_mcp_config_is_disabled_by_default() -> None:
    configs = load_server_configs()
    assert {config.server_id for config in configs} == {
        "qcc-company",
        "qcc-risk",
        "qcc-ipr",
    }
    assert all(not config.enabled for config in configs)


def test_mcp_catalog_distinguishes_servers() -> None:
    catalog = MCPToolCatalog()
    catalog.register(MCPToolInfo("server-a", "lookup"))
    catalog.register(MCPToolInfo("server-b", "lookup"))
    assert len(catalog.list_tools()) == 2
    assert catalog.get(ToolReference("server-a", "lookup")).qualified_name == "server-a:lookup"
    with pytest.raises(ValueError, match="重复"):
        catalog.register(MCPToolInfo("server-a", "lookup"))


def test_fake_provider_manager_discovers_and_resolves_tools() -> None:
    config = MCPServerConfig("fake-company", "fake", "fake", enabled=True)
    provider = FakeMCPProvider(
        "fake-company",
        [MCPToolInfo("fake-company", "get_company_registration_info")],
    )
    manager = MCPProviderManager([config], {"fake-company": provider}, enabled=True)

    async def run() -> None:
        await manager.initialize()
        assert (await manager.health_check("fake-company")).status == "ok"
        tools = await manager.get_tools(
            [ToolReference("fake-company", "get_company_registration_info")]
        )
        assert tools == [{"server_id": "fake-company", "name": "get_company_registration_info"}]

    asyncio.run(run())


def _write_skill(root: Path, *, skill_id: str = "demo_skill", enabled: bool = False) -> Path:
    directory = root / skill_id
    directory.mkdir()
    (directory / "skill.yaml").write_text(
        f"""schema_version: 1
id: {skill_id}
name: Demo Skill
version: 0.1.0
description: Demo platform skill
owners: [platform]
enabled: {str(enabled).lower()}
priority: 10
applies_to: [profile.discovery]
activation:
  mode: explicit
prompt:
  file: SKILL.md
tools:
  - server: fake-company
    name: get_company_registration_info
limits:
  max_tool_calls: 3
  timeout_seconds: 60
context:
  required: [company_name]
  optional: []
output:
  type: advisory
persistence:
  external_tool_results: trace_only
""",
        encoding="utf-8",
    )
    (directory / "SKILL.md").write_text("# Demo\n\nUse the declared tool only.\n", encoding="utf-8")
    return directory


def test_skill_registry_and_resolver(tmp_path: Path) -> None:
    _write_skill(tmp_path, enabled=True)
    registry = SkillRegistry(SkillLoader(tmp_path))
    report = registry.refresh()
    assert report.errors == {}
    assert report.loaded == ("demo_skill",)

    plan = SkillResolver(registry).resolve(
        agent_scope="profile.discovery",
        skill_ids=["demo_skill"],
        runtime_context=SkillRuntimeContext(run_id="run-1", company_name="示例企业"),
    )
    assert plan.skill_ids == ("demo_skill",)
    assert plan.tool_refs[0].qualified_name == "fake-company:get_company_registration_info"
    assert '<skill id="demo_skill" version="0.1.0">' in plan.prompt_sections[0]


def test_skill_manifest_errors(tmp_path: Path) -> None:
    directory = _write_skill(tmp_path)
    (directory / "skill.yaml").write_text(
        (directory / "skill.yaml").read_text(encoding="utf-8").replace(
            "max_tool_calls: 3", "max_tool_calls: -1"
        ),
        encoding="utf-8",
    )
    with pytest.raises(SkillValidationError, match="正整数"):
        SkillLoader(tmp_path).load_directory(directory)
