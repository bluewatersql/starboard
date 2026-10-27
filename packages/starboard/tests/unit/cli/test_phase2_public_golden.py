# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-2 public goldens: ``starboard --discover`` / ``starboard review`` local bytes.

The fixtures under ``golden/phase2_public/`` were captured from the pre-sink code
(before the phase-2 ``ArtifactSink`` conversion). A public install (no overlay, no
``--run-folder``) must keep writing exactly these bytes. Only the run root, the
trailing window's start/end dates (they move with today) and wall-clock timestamps
are normalised.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.review_command import run_review
from starboard.discovery.engine import EngineResult
from starboard_core.domain.models.discovery.query import PackResult, QueryResult

GOLDEN = Path(__file__).parent / "golden" / "phase2_public"

_VOLATILE = re.compile(r'("(?:created_at|run_date|discovery_generated_at)": )"[^"]*"')
_WINDOW_DATE = re.compile(r'("(?:start|end)": )"\d{4}-\d{2}-\d{2}"')


class GoldenEngine:
    """One pack: a succeeded query with rows and a failed one."""

    def __init__(
        self, sql_executor: Any, llm_client: Any, config: Any, **_kw: Any
    ) -> None:
        self.config = config

    async def run(self, on_progress: Any = None) -> EngineResult:
        ok = QueryResult(
            query_id="C-B01",
            domain="billing",
            data=pl.DataFrame({"x": [1, 2]}),
            row_count=2,
        )
        bad = QueryResult(
            query_id="C-B02", domain="billing", data=None, error="PARSE_SYNTAX_ERROR"
        )
        pack = PackResult(pack_id="billing", domain="billing", results=(ok, bad))
        return EngineResult(trace_id="t", pack_results=[pack])


def discover_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
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


def discover_config() -> MagicMock:
    cfg = MagicMock()
    cfg.discovery_max_parallelism = 4
    cfg.discovery_output_dir = "/tmp/starboard-test-discovery"
    cfg.discovery_llm_model = None
    cfg.discovery_llm_temperature = 0.3
    cfg.discovery_internal_source_account = None
    cfg.discovery_internal_source_workspace_id = None
    return cfg


def normalise(text: str, root: Path) -> str:
    text = _VOLATILE.sub(r'\1"<VOLATILE>"', text.replace(str(root), "<ROOT>"))
    return _WINDOW_DATE.sub(r'\1"<WINDOW_DATE>"', text)


def produce(root: Path) -> dict[str, str]:
    """Run the public discover (--out-dir, --output-path) and review paths under ``root``.

    The caller must have patched ``starboard.bootstrap.DiscoveryEngine`` with
    :class:`GoldenEngine` and pinned the overlay off.
    """
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        asyncio.run(
            cli_main.run_discovery_mode(
                discover_args(out_dir=str(root / "outdir")),
                discover_config(),
                Console(),
            )
        )
        asyncio.run(
            cli_main.run_discovery_mode(
                discover_args(output_path=str(root / "outpath")),
                discover_config(),
                Console(),
            )
        )
        code = run_review(
            [
                "--from-discovery",
                str(root / "outdir"),
                "--out",
                str(root / "rev" / "review.json"),
                "--manifest-out",
                str(root / "rev" / "m.json"),
                "--snapshot-out",
                str(root / "rev" / "s.json"),
            ]
        )
    assert code == 0
    files = {
        p.relative_to(root).as_posix(): normalise(p.read_text(encoding="utf-8"), root)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    files["stdout.txt"] = normalise(stdout.getvalue(), root)
    return files


@pytest.mark.unit
def test_public_bytes_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GoldenEngine)
    got = produce(tmp_path)
    want = {
        p.relative_to(GOLDEN).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(GOLDEN.rglob("*"))
        if p.is_file()
    }
    assert sorted(got) == sorted(want)
    for name, text in want.items():
        assert got[name] == text, name


if (
    __name__ == "__main__"
):  # capture: python -m tests.unit.cli.test_phase2_public_golden
    import tempfile

    import starboard.bootstrap as _bootstrap
    from starboard_core.engagement.overlay import OverlaySignal

    cli_main.detect_overlay = lambda **_kw: OverlaySignal(enabled=False)  # type: ignore[assignment]
    _bootstrap.DiscoveryEngine = GoldenEngine  # type: ignore[assignment,misc]
    with tempfile.TemporaryDirectory() as tmp:
        for rel, text in produce(Path(tmp)).items():
            dest = GOLDEN / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            print(dest, file=sys.stderr)
