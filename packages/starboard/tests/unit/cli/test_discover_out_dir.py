# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard --discover --out-dir <dir>`` writes the public run-dir layout.

The layout is the one discovery Step 4 reads: ``discovery.json`` (full
envelope incl. ``data.facts``), ``raw/<pack>.json`` per pack and
``manifest.json`` — identical for the customer and the internal sources.
"""

from __future__ import annotations

import argparse
import json

import polars as pl
import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.discovery.engine import EngineResult
from starboard_core.domain.models.discovery.query import PackResult, QueryResult


class _FakeEngine:
    def __init__(self, sql_executor, llm_client, config) -> None:  # noqa: ANN001
        self._sql_executor = sql_executor

    async def run(self, on_progress=None):  # noqa: ANN001, ANN201
        ok = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"x": [1, 2]}),
            row_count=2,
        )
        pack = PackResult(pack_id="billing", domain="billing", results=(ok,))
        return EngineResult(trace_id="t", pack_results=[pack])


def _args(**overrides) -> argparse.Namespace:
    base = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": True,
        "lookback_days": 30,
        "discovery_domains": None,
        "internal_account": None,
        "internal_workspace_id": "856",
        "include_deep_dive": False,
        "full_stdout": False,
        "output_path": None,
        "out_dir": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _config():
    from unittest.mock import MagicMock

    cfg = MagicMock()
    cfg.discovery_max_parallelism = 4
    cfg.discovery_output_dir = "/tmp/starboard-test-discovery"
    cfg.discovery_llm_model = None
    cfg.discovery_llm_temperature = 0.3
    cfg.discovery_internal_source_account = None
    cfg.discovery_internal_source_workspace_id = None
    return cfg


@pytest.mark.unit
def test_out_dir_flag_parses() -> None:
    args = cli_main.parse_args(["--discover", "--out-dir", "/tmp/x/discovery"])
    assert args.out_dir == "/tmp/x/discovery"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_out_dir_writes_run_layout(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )
    out_dir = tmp_path / "ws-856-2026-10-01" / "discovery"

    await cli_main.run_discovery_mode(
        _args(out_dir=str(out_dir)), _config(), Console()
    )

    envelope = json.loads((out_dir / "discovery.json").read_text())
    assert envelope["ok"] is True
    assert "facts" in envelope["data"]
    assert envelope["data"]["source"] == "internal"

    raw = json.loads((out_dir / "raw" / "billing.json").read_text())
    assert raw["results"][0]["query_id"] == "C-B01"
    assert len(raw["results"][0]["rows"]) == 2

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["manifest"][0]["path"] == "raw/billing.json"
    assert "facts" in manifest

    # --json stdout defaults to the summary (Round-3 D2): no per-pack list, no
    # rows; points at discovery.json + the raw/ layout.
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["data"]["output_path"] == str(out_dir / "discovery.json")
    assert stdout["data"]["out_dir"] == str(out_dir)
    assert stdout["data"]["manifest_path"] == str(out_dir / "manifest.json")
    assert "packs" not in stdout["data"]
    assert "rows" not in json.dumps(stdout)
    assert stdout["data"]["pack_count"] == 1
    assert stdout["data"]["counts"]["succeeded"] == 1
