# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W8 + W9: --output-path file-vs-directory behaviour and compact stdout.

W8: if --output-path ends in ``.json``, the envelope is written to exactly
    that file (parent dirs created); otherwise the value is a directory and
    the file is named ``discovery-<scope>.json`` inside it.

W9 / Round-3 D2: when --output-path is given and --json, stdout defaults to
    the ``summary`` envelope (no per-pack list, no rows); ``--stdout compact``
    adds the per-pack status list, ``--stdout full`` (or legacy --full-stdout)
    emits the full envelope.
"""

from __future__ import annotations

import argparse
import json

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.main import _compact_stdout_envelope
from starboard.discovery.engine import EngineResult

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeEngine:
    captured: dict = {}

    def __init__(self, sql_executor, llm_client, config) -> None:  # noqa: ANN001
        _FakeEngine.captured = {"config": config}

    async def run(self, on_progress=None):  # noqa: ANN001, ANN201
        return EngineResult(trace_id="test-trace")


def _args(**overrides) -> argparse.Namespace:
    base = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": True,
        "lookback_days": 30,
        "discovery_domains": None,
        "internal_account": None,
        "internal_workspace_id": None,
        "include_deep_dive": False,
        "full_stdout": False,
        "output_path": None,
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
    cfg.discovery_min_dbu_threshold = 0
    cfg.discovery_internal_source_account = None
    cfg.discovery_internal_source_workspace_id = None
    return cfg


# ---------------------------------------------------------------------------
# W8: file vs directory behavior for --output-path
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_path_json_extension_writes_exact_file(monkeypatch, tmp_path, capsys):
    """W8: a path ending in .json is written to exactly that file."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "subdir" / "discovery.json"
    args = _args(
        internal_account="acct-x",
        output_path=str(target),
    )
    await cli_main.run_discovery_mode(args, _config(), Console())

    # The file must exist at the exact path requested.
    assert target.exists(), f"expected file at {target}"
    data = json.loads(target.read_text())
    assert data["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_path_directory_creates_scoped_filename(monkeypatch, tmp_path, capsys):
    """W8: a path without .json extension creates discovery-<scope>.json inside it."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    out_dir = tmp_path / "output"
    args = _args(
        internal_account="acct-y",
        output_path=str(out_dir),
    )
    await cli_main.run_discovery_mode(args, _config(), Console())

    files = list(out_dir.glob("discovery-*.json"))
    assert len(files) == 1, f"expected one discovery-<scope>.json, got {files}"
    data = json.loads(files[0].read_text())
    assert data["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_path_json_extension_no_directory_named_json(monkeypatch, tmp_path):
    """W8 regression: passing /dir/discovery.json must NOT create a directory
    named 'discovery.json'."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "discovery.json"
    args = _args(internal_account="acct-z", output_path=str(target))
    await cli_main.run_discovery_mode(args, _config(), Console())

    assert target.is_file(), "discovery.json should be a file, not a directory"
    assert not target.is_dir()


# ---------------------------------------------------------------------------
# W9: compact stdout vs full stdout
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_output_path_suppresses_rows_on_stdout(monkeypatch, tmp_path, capsys):
    """W9: with --output-path + --json, stdout gets compact summary (no rows)."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "out.json"
    args = _args(internal_account="acct-w", output_path=str(target))
    await cli_main.run_discovery_mode(args, _config(), Console())

    stdout_text = capsys.readouterr().out
    envelope = json.loads(stdout_text)
    # Round-3 D2: default with --output-path is the summary — output_path, no
    # per-pack list, no rows.
    assert envelope["data"]["output_path"] == str(target)
    assert "packs" not in envelope["data"]
    assert "rows" not in stdout_text
    for key in (
        "status", "counts", "coverage_summary", "limit_reached_ids",
        "skipped", "pack_count", "facts",
    ):
        assert key in envelope["data"], key


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stdout_compact_keeps_per_pack_status_list(monkeypatch, tmp_path, capsys):
    """--stdout compact restores the W9 per-pack/per-query status list (no rows)."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "out.json"
    args = _args(internal_account="acct-w", output_path=str(target), stdout_mode="compact")
    await cli_main.run_discovery_mode(args, _config(), Console())

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["data"]["output_path"] == str(target)
    assert "packs" in envelope["data"]
    for pack in envelope["data"]["packs"]:
        for q in pack["queries"]:
            assert "rows" not in q


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stdout_full_flag_emits_full_envelope(monkeypatch, tmp_path, capsys):
    """--stdout full emits the full row-bearing envelope even with --output-path."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "full.json"
    args = _args(internal_account="acct-v", output_path=str(target), stdout_mode="full")
    await cli_main.run_discovery_mode(args, _config(), Console())

    envelope = json.loads(capsys.readouterr().out)
    assert "output_path" not in envelope["data"]
    assert "packs" in envelope["data"]


@pytest.mark.unit
def test_stdout_flag_parses() -> None:
    assert cli_main.parse_args(["--discover"]).stdout_mode is None
    for mode in ("summary", "compact", "full"):
        assert cli_main.parse_args(["--discover", "--stdout", mode]).stdout_mode == mode
    with pytest.raises(SystemExit):
        cli_main.parse_args(["--discover", "--stdout", "bogus"])


@pytest.mark.unit
def test_summary_stdout_envelope_shape() -> None:
    """Summary carries status/paths/counts/coverage summary/facts, no per-pack list."""
    from starboard.cli.cli.main import _summary_stdout_envelope

    full_envelope = {
        "ok": True,
        "domain": "discovery",
        "command": "discover",
        "data": {
            "source": "internal",
            "scope": {"account": "a", "workspace_ids": []},
            "counts": {"total": 3, "succeeded": 1, "skipped": 1, "failed": 1, "filtered": 0},
            "lookback_days": 30,
            "pack_count": 2,
            "packs": [{"pack": "billing", "results": [{"query_id": "C-B01", "rows": [[1]]}]}],
            "coverage": {
                "billing": {"succeeded": 1, "skipped": 0, "failed": 0, "skipped_reasons": []},
                "jobs": {"succeeded": 0, "skipped": 1, "failed": 1, "skipped_reasons": ["x"]},
            },
            "coverage_caveats": ["c1"],
            "limit_reached_ids": ["C-B01"],
            "skipped": [{"query_id": "C-J02", "reason": "unavailable"}],
            "facts": {"total_dbu": 10},
        },
    }
    out = _summary_stdout_envelope(
        full_envelope, {"output_path": "/tmp/d.json", "out_dir": "/tmp"}
    )
    data = out["data"]
    assert out["ok"] is True and out["command"] == "discover"
    assert data["status"] == "partial"  # one failed query
    assert data["output_path"] == "/tmp/d.json" and data["out_dir"] == "/tmp"
    assert "packs" not in data and "coverage" not in data
    assert data["coverage_summary"] == {
        "packs_total": 2,
        "packs_complete": 1,
        "packs_with_gaps": {"jobs": {"succeeded": 0, "skipped": 1, "failed": 1}},
    }
    assert data["limit_reached_ids"] == ["C-B01"]
    assert data["skipped"] == [{"query_id": "C-J02", "reason": "unavailable"}]
    assert data["pack_count"] == 2
    assert data["facts"] == {"total_dbu": 10}
    assert data["coverage_caveats"] == ["c1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_stdout_flag_emits_full_envelope(monkeypatch, tmp_path, capsys):
    """W9: --full-stdout bypasses the compact summary and emits the full envelope."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    target = tmp_path / "full.json"
    args = _args(internal_account="acct-v", output_path=str(target), full_stdout=True)
    await cli_main.run_discovery_mode(args, _config(), Console())

    stdout_text = capsys.readouterr().out
    envelope = json.loads(stdout_text)
    # Full envelope does NOT have an output_path key inside data.
    assert "output_path" not in envelope["data"]
    # Full envelope has packs with results (not compact queries).
    assert "packs" in envelope["data"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_output_path_stdout_is_full_envelope(monkeypatch, capsys):
    """W9: without --output-path, stdout always gets the full envelope."""
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(
        cli_main,
        "AsyncDatabricksClient",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client")),
    )

    args = _args(internal_account="acct-u", output_path=None)
    await cli_main.run_discovery_mode(args, _config(), Console())

    stdout_text = capsys.readouterr().out
    envelope = json.loads(stdout_text)
    # Full envelope: no output_path in data.
    assert "output_path" not in envelope["data"]


# ---------------------------------------------------------------------------
# W9: unit test for _compact_stdout_envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compact_stdout_envelope_shape() -> None:
    """_compact_stdout_envelope produces the required contract shape."""
    full_envelope = {
        "ok": True,
        "domain": "discovery",
        "command": "discover",
        "data": {
            "source": "internal",
            "scope": {"account": "a", "workspace_ids": []},
            "counts": {"total": 2, "succeeded": 1, "skipped": 1, "failed": 0, "filtered": 0},
            "lookback_days": 30,
            "packs": [
                {
                    "pack": "billing",
                    "results": [
                        {
                            "query_id": "C-B01",
                            "status": "succeeded",
                            "row_count": 10,
                            "limit_reached": False,
                            "lookback_days": 30,
                            "rows": [{"x": 1}],
                            "columns": ["x"],
                            "error": None,
                        },
                        {
                            "query_id": "C-B02",
                            "status": "skipped",
                            "row_count": 0,
                            "limit_reached": False,
                            "lookback_days": 90,
                            "rows": [],
                            "columns": [],
                            "error": "unavailable on internal source: not mirrored",
                        },
                    ],
                }
            ],
        },
    }

    compact = _compact_stdout_envelope(full_envelope, "/tmp/out.json")

    assert compact["ok"] is True
    assert compact["domain"] == "discovery"
    assert compact["command"] == "discover"
    d = compact["data"]
    assert d["output_path"] == "/tmp/out.json"
    assert d["source"] == "internal"
    assert d["counts"]["total"] == 2
    assert d["lookback_days"] == 30

    # Per-query entries: status, row_count, limit_reached, lookback_days — no rows.
    qs = d["packs"][0]["queries"]
    assert len(qs) == 2
    assert qs[0] == {
        "query_id": "C-B01",
        "status": "succeeded",
        "row_count": 10,
        "limit_reached": False,
        "lookback_days": 30,
    }
    assert "rows" not in qs[0]

    # limit_reached_ids collects queries that hit their SQL cap.
    assert d["limit_reached_ids"] == []

    # skipped entries.
    assert d["skipped"] == [
        {"query_id": "C-B02", "reason": "unavailable on internal source: not mirrored"}
    ]
