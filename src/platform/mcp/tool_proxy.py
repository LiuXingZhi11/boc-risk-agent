"""把外部 MCP Tool 包装成受控的 LangChain Tool。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model

from src.config.settings import get_settings
from src.evidence.external_models import ExternalEvidenceTrace

from .audit import InMemoryAuditSink, ToolCallAudit
from .models import MCPErrorCode, MCPToolInfo


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MCPToolError(RuntimeError):
    def __init__(self, code: MCPErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ToolCallBudget:
    limit: int
    used: int = 0

    def consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


class MCPToolProxy:
    def __init__(
        self,
        raw_tool: Any,
        info: MCPToolInfo,
        *,
        run_id: str,
        skill_id: str,
        skill_version: str,
        max_tool_calls: int,
        timeout_seconds: int,
        max_result_chars: int = 12000,
        subject_name: str | None = None,
        subject_identifier: str | None = None,
        audit_sink: InMemoryAuditSink | None = None,
        budget: ToolCallBudget | None = None,
    ) -> None:
        self.raw_tool = raw_tool
        self.info = info
        self.run_id = run_id
        self.skill_id = skill_id
        self.skill_version = skill_version
        self.max_tool_calls = max_tool_calls
        self.timeout_seconds = timeout_seconds
        self.max_result_chars = max_result_chars
        self.subject_name = subject_name
        self.subject_identifier = subject_identifier
        self.audit_sink = audit_sink or InMemoryAuditSink()
        self.budget = budget or ToolCallBudget(max_tool_calls)

    async def ainvoke(self, payload: Mapping[str, Any] | str) -> str:
        trace_id = str(uuid.uuid4())
        started_at = _now()
        request_summary = _summarize_request(payload)
        if not self.budget.consume():
            self._record(
                trace_id=trace_id,
                started_at=started_at,
                status="failed",
                error_code=MCPErrorCode.BUDGET_EXCEEDED,
                request_summary=request_summary,
            )
            raise MCPToolError(MCPErrorCode.BUDGET_EXCEEDED, "MCP Tool 调用次数已达到上限")
        try:
            result = await asyncio.wait_for(
                self._invoke_raw(payload),
                timeout=self.timeout_seconds,
            )
            text = _redact_secrets(_serialize(result))
            original_chars = len(text)
            truncated = original_chars > self.max_result_chars
            if truncated:
                text = json.dumps(
                    {
                        "truncated": True,
                        "content": text[: self.max_result_chars],
                        "original_chars": original_chars,
                    },
                    ensure_ascii=False,
                )
            self._record(
                trace_id=trace_id,
                started_at=started_at,
                status="completed",
                error_code=None,
                request_summary=request_summary,
                result_summary={
                    "chars": original_chars,
                    "truncated": truncated,
                },
                raw_result_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
            return text
        except asyncio.TimeoutError as exc:
            self._record(
                trace_id=trace_id,
                started_at=started_at,
                status="failed",
                error_code=MCPErrorCode.TIMEOUT,
                request_summary=request_summary,
            )
            raise MCPToolError(MCPErrorCode.TIMEOUT, "MCP Tool 调用超时") from exc
        except MCPToolError:
            raise
        except Exception as exc:
            self._record(
                trace_id=trace_id,
                started_at=started_at,
                status="failed",
                error_code=MCPErrorCode.UNKNOWN,
                request_summary=request_summary,
            )
            raise MCPToolError(MCPErrorCode.UNKNOWN, "MCP Tool 调用失败") from exc

    async def _invoke_raw(self, payload: Mapping[str, Any] | str) -> Any:
        if hasattr(self.raw_tool, "ainvoke"):
            result = self.raw_tool.ainvoke(payload)
        elif hasattr(self.raw_tool, "invoke"):
            result = await asyncio.to_thread(self.raw_tool.invoke, payload)
        elif callable(self.raw_tool):
            result = self.raw_tool(payload)
        else:
            raise TypeError("MCP Tool backend 不可调用")
        if inspect.isawaitable(result):
            return await result
        return result

    def as_langchain_tool(self) -> BaseTool:
        async def invoke(**kwargs: Any) -> str:
            return await self.ainvoke(kwargs)

        tool_name = re.sub(r"[^a-zA-Z0-9_]+", "_", self.info.qualified_name)
        kwargs: dict[str, Any] = {
            "coroutine": invoke,
            "name": tool_name,
            "description": self.info.description or self.info.qualified_name,
            "metadata": {
                "mcp_qualified_name": self.info.qualified_name,
                "skill_id": self.skill_id,
                "skill_version": self.skill_version,
            },
        }
        args_schema = _build_args_schema(tool_name, self.info.input_schema)
        if args_schema is not None:
            kwargs["args_schema"] = args_schema
        return StructuredTool.from_function(**kwargs)

    def _record(
        self,
        *,
        trace_id: str,
        started_at: str,
        status: str,
        error_code: MCPErrorCode | None,
        request_summary: dict[str, Any],
        result_summary: dict[str, Any] | None = None,
        raw_result_hash: str | None = None,
    ) -> None:
        completed_at = _now()
        self.audit_sink.record_audit(
            ToolCallAudit(
                trace_id=trace_id,
                qualified_tool_name=self.info.qualified_name,
                status=status,
                error_code=error_code.value if error_code else None,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
        self.audit_sink.record_trace(
            ExternalEvidenceTrace(
                trace_id=trace_id,
                run_id=self.run_id,
                skill_id=self.skill_id,
                skill_version=self.skill_version,
                provider="mcp",
                server_id=self.info.server_id,
                tool_name=self.info.name,
                subject_name=self.subject_name,
                subject_identifier=self.subject_identifier,
                requested_at=started_at,
                completed_at=completed_at,
                status=status,
                request_summary=request_summary,
                result_summary=result_summary,
                raw_result_hash=raw_result_hash,
                error_code=error_code.value if error_code else None,
            )
        )


def _serialize(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _summarize_request(value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {"keys": sorted(str(key) for key in value)}
    return {"type": type(value).__name__}


def _redact_secrets(value: str) -> str:
    secrets = [
        os.getenv("QCC_API_KEY", ""),
        get_settings().api_key or "",
    ]
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value


def _build_args_schema(name: str, schema: dict[str, Any]) -> type[Any] | None:
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if not isinstance(properties, dict) or not properties:
        return None
    required = set(schema.get("required", ())) if isinstance(schema, dict) else set()
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name in properties:
        fields[str(field_name)] = (Any, ... if field_name in required else None)
    return create_model(f"{name.title().replace('_', '')}Input", **fields)
