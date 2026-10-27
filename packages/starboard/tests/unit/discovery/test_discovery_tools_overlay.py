# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G3): on an overlay install the discovery tools never write locally.

Each call runs under the armed write guard (as the MCP server and the goal agent
run them): a local write would fail the block, so a clean exit proves the tool
skipped it, and the response says so instead of naming a local path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starboard.tools.adapters import discovery_tools
from starboard.tools.adapters.discovery_tools import DiscoveryTools
from starboard_core.engagement.enforce import guarded_run
from starboard_core.engagement.overlay import OverlaySignal

from tests.unit.discovery.test_discovery_tools import (
    MockSQLExecutor,
    _make_domain_analysis,
    _make_pack_result,
)


@pytest.fixture
def overlay(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        discovery_tools,
        "detect_overlay",
        lambda **_kw: OverlaySignal(enabled=True, reasons=("test",)),
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def _tools_with_packs(*domains: str) -> DiscoveryTools:
    tools = DiscoveryTools(
        sql_executor=MockSQLExecutor(), llm_client=MagicMock(), env_config=None
    )
    await tools.discover_active_products()
    await tools.run_discovery_queries()
    for domain in domains:
        tools._pack_results.append(_make_pack_result(domain))  # type: ignore[union-attr]
    return tools


def _analyzer(mock_cls: Any) -> None:
    mock_cls.return_value.analyze_domain = AsyncMock(
        side_effect=lambda d, *a, **kw: _make_domain_analysis(d),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@patch("starboard.tools.adapters.discovery_tools.DomainAnalyzer")
async def test_overlay_batch_analysis_writes_no_domain_files(
    mock_cls: Any, overlay: Path
) -> None:
    _analyzer(mock_cls)
    tools = await _tools_with_packs("billing", "jobs")

    with guarded_run():
        result = await tools.analyze_discovery_domain(domains=["billing", "jobs"])

    assert result["status"] == "completed"
    assert result["discovery_output_path"] is None
    assert result["detail_note"].startswith("LOCAL_STORAGE_REFUSED")
    assert all("detail_file" not in r for r in result["domain_results"])
    assert list(overlay.iterdir()) == []


@pytest.mark.unit
@pytest.mark.asyncio
@patch("starboard.tools.adapters.discovery_tools.DomainAnalyzer")
async def test_overlay_single_analysis_writes_no_domain_file(
    mock_cls: Any, overlay: Path
) -> None:
    _analyzer(mock_cls)
    tools = await _tools_with_packs("billing")

    with guarded_run():
        result = await tools.analyze_discovery_domain(domain="billing")

    assert result["status"] == "completed"
    assert "detail_file" not in result
    assert result["detail_note"].startswith("LOCAL_STORAGE_REFUSED")
    assert list(overlay.iterdir()) == []


@pytest.mark.unit
@pytest.mark.asyncio
@patch("starboard.tools.adapters.discovery_tools.DomainAnalyzer")
async def test_overlay_background_analysis_writes_no_domain_files(
    mock_cls: Any, overlay: Path
) -> None:
    _analyzer(mock_cls)
    tools = await _tools_with_packs("billing", "jobs")

    with guarded_run():
        await tools.start_discovery_analysis(domains=["billing", "jobs"])
        assert tools._bg_task is not None
        await tools._bg_task

    assert tools._domain_file_paths == {}
    assert len(tools._bg_completed) == 2
    assert list(overlay.iterdir()) == []


@pytest.mark.unit
@pytest.mark.asyncio
@patch("starboard.tools.adapters.discovery_tools.ReportAssembler")
async def test_overlay_synthesis_writes_no_report_files(
    mock_assembler: Any, overlay: Path
) -> None:
    mock_assembler.return_value.assemble = AsyncMock(return_value=MagicMock())
    tools = await _tools_with_packs("billing")
    tools._domain_analyses = [_make_domain_analysis("billing")]
    tools._output_formatter = MagicMock(to_markdown=MagicMock(return_value="# R"))

    with guarded_run():
        result = await tools.synthesize_discovery_report()

    assert result["status"] == "completed"
    assert result["output_files"] == []
    assert result["discovery_output_path"] is None
    assert result["detail_note"].startswith("LOCAL_STORAGE_REFUSED")
    tools._output_formatter.write_to_directory.assert_not_called()
    assert tools.get_discovery_markdown() == "# R"
    assert list(overlay.iterdir()) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_full_workspace_discovery_is_refused(overlay: Path) -> None:
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    with guarded_run():
        result = await tools.run_workspace_discovery()

    assert result["status"] == "error"
    assert result["error_code"] == "LOCAL_STORAGE_REFUSED"
    assert "--run-folder" in result["error"]
    assert list(overlay.iterdir()) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_data_only_workspace_discovery_still_runs(overlay: Path) -> None:
    tools = DiscoveryTools(sql_executor=MockSQLExecutor(), env_config=None)

    with guarded_run():
        result = await tools.run_workspace_discovery(data_only=True)

    assert result["status"] in ("completed", "completed_with_errors")
    assert list(overlay.iterdir()) == []
