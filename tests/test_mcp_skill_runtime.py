from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.platform.mcp.audit import InMemoryAuditSink
from src.platform.mcp.models import MCPServerConfig, MCPToolInfo, ToolReference
from src.platform.mcp.registry import MCPProviderManager
from src.platform.mcp.tool_proxy import MCPToolError, MCPToolProxy, ToolCallBudget
from src.platform.mcp.tool_resolver import MCPToolResolver
from src.platform.skills.agent_adapter import AgentSkillAdapter
from src.platform.skills.loader import SkillLoader
from src.platform.skills.registry import SkillRegistry
from src.platform.skills.runtime import SkillRuntimeContext
from tests.fakes.mcp_server import FakeMCPProvider, FakeRawTool


def _manager(raw_tool: object) -> MCPProviderManager:
    config = MCPServerConfig("fake-company", "fake", "fake", enabled=True)
    provider = FakeMCPProvider(
        "fake-company",
        [MCPToolInfo("fake-company", "lookup", input_schema={"properties": {"q": {}}})],
        {"lookup": raw_tool},
    )
    manager = MCPProviderManager([config], {"fake-company": provider}, enabled=True)
    asyncio.run(manager.initialize())
    return manager


def test_tool_proxy_enforces_budget_and_records_external_trace() -> None:
    sink = InMemoryAuditSink()
    proxy = MCPToolProxy(
        FakeRawTool({"answer": "ok"}),
        MCPToolInfo("fake-company", "lookup"),
        run_id="run-1",
        skill_id="demo_skill",
        skill_version="0.1.0",
        max_tool_calls=1,
        timeout_seconds=1,
        audit_sink=sink,
    )

    async def run() -> None:
        assert await proxy.ainvoke({"q": "test"}) == '{"answer": "ok"}'
        with pytest.raises(MCPToolError, match="调用次数"):
            await proxy.ainvoke({"q": "again"})

    asyncio.run(run())
    assert len(sink.traces) == 2
    assert sink.traces[0].skill_id == "demo_skill"
    assert sink.traces[1].error_code == "BUDGET_EXCEEDED"
    assert "test" not in sink.traces[0].request_summary


def test_tool_proxy_timeout_is_normalized() -> None:
    proxy = MCPToolProxy(
        FakeRawTool("late", delay_seconds=0.05),
        MCPToolInfo("fake-company", "lookup"),
        run_id="run-1",
        skill_id="demo_skill",
        skill_version="0.1.0",
        max_tool_calls=1,
        timeout_seconds=0,
    )

    async def run() -> None:
        with pytest.raises(MCPToolError) as error:
            await proxy.ainvoke({})
        assert error.value.code.value == "TIMEOUT"

    asyncio.run(run())


def test_tool_budget_is_shared_by_multiple_proxies() -> None:
    budget = ToolCallBudget(1)
    first = MCPToolProxy(
        FakeRawTool("first"),
        MCPToolInfo("fake-company", "first"),
        run_id="run-1",
        skill_id="demo_skill",
        skill_version="0.1.0",
        max_tool_calls=1,
        timeout_seconds=1,
        budget=budget,
    )
    second = MCPToolProxy(
        FakeRawTool("second"),
        MCPToolInfo("fake-company", "second"),
        run_id="run-1",
        skill_id="demo_skill",
        skill_version="0.1.0",
        max_tool_calls=1,
        timeout_seconds=1,
        budget=budget,
    )

    async def run() -> None:
        assert await first.ainvoke({}) == "first"
        with pytest.raises(MCPToolError, match="调用次数"):
            await second.ainvoke({})

    asyncio.run(run())


def test_tool_resolver_returns_langchain_tool() -> None:
    resolver = MCPToolResolver(_manager(FakeRawTool({"ok": True})))
    context = SkillRuntimeContext(run_id="run-1", company_name="示例企业")

    async def run() -> None:
        tools = await resolver.resolve(
            [ToolReference("fake-company", "lookup")],
            skill_id="demo_skill",
            skill_version="0.1.0",
            runtime_context=context,
            max_tool_calls=2,
            timeout_seconds=1,
        )
        assert tools[0].name == "fake_company_lookup"
        assert await tools[0].ainvoke({"q": "x"}) == '{"ok": true}'

    asyncio.run(run())


def test_agent_skill_adapter_injects_only_declared_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLS_ENABLED", "true")
    skill_dir = tmp_path / "demo_skill"
    skill_dir.mkdir()
    (skill_dir / "skill.yaml").write_text(
        """schema_version: 1
id: demo_skill
name: Demo
version: 0.1.0
description: Demo
owners: [platform]
enabled: true
applies_to: [profile.discovery]
activation: {mode: explicit}
prompt: {file: SKILL.md}
tools:
  - server: fake-company
    name: lookup
limits: {max_tool_calls: 2, timeout_seconds: 1}
context: {required: [company_name]}
output: {type: advisory}
persistence: {external_tool_results: trace_only}
""",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("Use lookup only.", encoding="utf-8")
    registry = SkillRegistry(SkillLoader(tmp_path))
    registry.refresh()
    manager = _manager(FakeRawTool({"ok": True}))
    adapter = AgentSkillAdapter(registry, MCPToolResolver(manager))

    async def run() -> None:
        extension = await adapter.build_extension(
            agent_scope="profile.discovery",
            skill_ids=["demo_skill"],
            runtime_context=SkillRuntimeContext(run_id="run-1", company_name="示例企业"),
        )
        assert len(extension.tools) == 1
        assert extension.metadata["mcp_tools"] == ["fake-company:lookup"]
        assert "Use lookup only." in extension.system_prompt_suffix

    asyncio.run(run())
