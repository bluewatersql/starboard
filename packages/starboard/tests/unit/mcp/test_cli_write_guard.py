# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G3): ``starboard-mcp`` on an overlay install gates customer-data tools.

Behavioural: every tool, composite and agent call on an overlay install runs under
the armed write guard, so a local write in the call -- even one a library swallowed -- fails
it with ``LOCAL_STORAGE_REFUSED``. A public install runs the call unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.agents.output.llm_responses import ToolResult
from starboard.mcp import cli as mcp_cli
from starboard.mcp import server as mcp_server
from starboard.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard.mcp.server import StarboardMCPServer
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.write_guard import active

_RESULT = ToolResult(tool_call_id="", tool_name="resolve_query", content='{"sql": "1"}')


def _server(execute: Any) -> tuple[StarboardMCPServer, MagicMock]:
    registry = MagicMock()
    registry.execute_tool = AsyncMock(side_effect=execute)
    server = StarboardMCPServer(
        config=MCPServerConfig(
            default_workspace_id="prod",
            workspaces={
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com", token_env="PROD_TOKEN"
                )
            },
        ),
        tool_registry=registry,
    )
    return server, registry


def _overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "detect_overlay",
        lambda **_kw: OverlaySignal(enabled=True, reasons=("test",)),
    )


async def _ok(*_a: object, **_k: object) -> ToolResult:
    return _RESULT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_agent_and_composite_tools_run_under_the_armed_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _overlay(monkeypatch)
    armed: list[bool] = []

    async def clean(*_a: object, **_k: object) -> ToolResult:
        armed.append(active())
        return _RESULT

    class _Response:
        def model_dump(self, **_k: object) -> dict[str, str]:
            return {"answer": "ok"}

    async def execute(**_k: object) -> _Response:
        armed.append(active())
        return _Response()

    server, registry = _server(clean)
    server._agent_executor = MagicMock(execute=execute)

    agent = json.loads(await server._execute_agent_tool("query_agent", {"message": "x"}))
    composite = json.loads(await _call_text(server, "get_job_summary", {"target": "1"}))

    assert "isError" not in agent
    assert "isError" not in composite
    assert registry.execute_tool.await_count >= 1
    assert armed and all(armed)
    assert not active()


async def _call_text(server: StarboardMCPServer, name: str, args: dict[str, Any]) -> str:
    result = await server.mcp.call_tool(name, args)
    blocks = result[0] if isinstance(result, tuple) else result
    return str(blocks[0].text)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("swallow", [True, False])
async def test_overlay_local_write_in_a_tool_call_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, swallow: bool
) -> None:
    _overlay(monkeypatch)
    leak = tmp_path / "leak.json"
    seen: dict[str, bool] = {}

    async def writes(*_a: object, **_k: object) -> ToolResult:
        seen["armed"] = active()
        try:
            leak.write_text("{}")
        except OSError:
            if not swallow:
                raise
        return _RESULT

    server, _ = _server(writes)

    out = json.loads(await server._execute_tool("resolve_query", {"target": "SELECT 1"}))

    assert seen == {"armed": True}
    assert out["isError"] is True
    assert out["code"] == "LOCAL_STORAGE_REFUSED"
    assert not leak.exists()
    assert not active()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_clean_tool_call_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _overlay(monkeypatch)
    seen: dict[str, bool] = {}

    async def clean(*_a: object, **_k: object) -> ToolResult:
        seen["armed"] = active()
        return _RESULT

    server, _ = _server(clean)

    out = json.loads(await server._execute_tool("resolve_query", {"target": "SELECT 1"}))

    assert "isError" not in out
    assert seen == {"armed": True}
    assert not active()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_install_runs_tools_unguarded(tmp_path: Path) -> None:
    seen: dict[str, bool] = {}

    async def writes(*_a: object, **_k: object) -> ToolResult:
        seen["armed"] = active()
        (tmp_path / "out.json").write_text("{}")
        return _RESULT

    server, _ = _server(writes)

    out = json.loads(await server._execute_tool("resolve_query", {"target": "SELECT 1"}))

    assert "isError" not in out
    assert seen == {"armed": False}
    assert (tmp_path / "out.json").exists()


@pytest.mark.unit
def test_server_start_leaves_the_guard_disarmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting the server (overlay or not) arms nothing; only tool calls do."""
    monkeypatch.setattr(mcp_cli, "load_mcp_config", lambda config_path=None: object())
    monkeypatch.setattr(
        mcp_cli, "detect_overlay", lambda **_kw: OverlaySignal(True, ("test",))
    )
    started: list[bool] = []
    monkeypatch.setattr(
        "starboard.mcp.transports.create_stdio_server",
        lambda *_a, **_k: started.append(active()),
    )

    mcp_cli._run_server(argparse.Namespace(config=None, transport="stdio"))

    assert started == [False]
