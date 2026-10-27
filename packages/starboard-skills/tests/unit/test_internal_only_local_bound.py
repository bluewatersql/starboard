# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Internal-only local runs: every helper output stays inside the run dir (``local_root``).

``charts render`` finds the descriptor from ``--out`` only, ``notebook render`` refuses an
``--out`` outside the run, every :meth:`HelperRun.write` is bound to the run dir by realpath, and
``run recur`` writes ``trend/history.json`` only under the case root (the run dir's parent).
Public (no overlay) behaviour is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.policy import SourceMode, StorageDecision, StoragePolicy
from starboard_core.engagement.records import AccountRef, RunAuthorization
from starboard_core.engagement.sink import LocalDirSink
from starboard_skills.helpers import charts_render
from starboard_skills.helpers import contract as c

from .conftest import run_main

_ROWS = json.dumps([{"billing_origin_product": "JOBS", "total_dbus": 10}])
_RID = "20261008_12345678-1234-4234-8234-123456789abc"


@pytest.fixture(autouse=True)
def _fake_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")


def _internal_run(base: Path) -> Path:
    rd = base / "case" / "run-1"
    (rd / "analysis").mkdir(parents=True)
    auth = RunAuthorization(
        engagement_id="acme/workspace/ws-123",
        run_id=_RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.INTERNAL_ONLY,
        storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
        audience="internal",
        methodology_version="m1",
        drive=None,
    )
    (rd / "analysis" / "run-authorization.json").write_text(json.dumps(auth.to_dict()))
    return rd


def _bound_run(root: Path) -> c.HelperRun:
    decision = StorageDecision(StoragePolicy.INTERNAL_ONLY_LOCAL, False, "test")

    def no_storage() -> Any:
        raise AssertionError("local writes need no storage")

    return c.HelperRun(decision, LocalDirSink(root, decision=decision), None, no_storage)


def _err(out: str) -> str:
    return str(json.loads(out)["error"])


@pytest.mark.unit
class TestHelperRunBound:
    def test_inside_writes(self, tmp_path: Path) -> None:
        root = tmp_path / "run"
        root.mkdir()
        _bound_run(root).write(root / "charts" / "a.png", b"x")
        assert (root / "charts" / "a.png").read_bytes() == b"x"

    def test_outside_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "run"
        root.mkdir()
        with pytest.raises(c.StorageRefusedError) as info:
            _bound_run(root).write(tmp_path / "elsewhere" / "a.png", b"x")
        assert info.value.message.startswith("OUTSIDE_RUN_DIR: ")
        assert info.value.exit_code == 2
        assert not (tmp_path / "elsewhere").exists()

    def test_symlink_escape_is_refused(self, tmp_path: Path) -> None:
        root, outside = tmp_path / "run", tmp_path / "outside"
        root.mkdir()
        outside.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(c.StorageRefusedError, match="OUTSIDE_RUN_DIR"):
            _bound_run(root).write(root / "link" / "a.png", b"x")
        assert list(outside.iterdir()) == []

    def test_write_record_outside_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "run"
        root.mkdir()
        target = tmp_path / "other" / "analysis" / "findings.json"
        with pytest.raises(c.StorageRefusedError, match="OUTSIDE_RUN_DIR"):
            _bound_run(root).write_record(target, b"[]", "application/json")
        assert not target.exists()

    def test_write_record_inside_writes(self, tmp_path: Path) -> None:
        root = tmp_path / "run"
        root.mkdir()
        _bound_run(root).write_record(
            root / "analysis" / "findings.json", b"[]", "application/json"
        )
        assert (root / "analysis" / "findings.json").read_bytes() == b"[]"


def _charts(data: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    return run_main(
        ["charts", "render", "--kind", "spend-by-product", "--data", str(data), "--out", str(out)],
        capsys,
    )


@pytest.mark.unit
class TestChartsBound:
    def test_inside_run_writes(self, covered_env, capsys) -> None:
        rd = _internal_run(Path.cwd())
        (rd / "charts").mkdir()
        (rd / "charts" / "d.json").write_text(_ROWS)
        code, out = _charts(rd / "charts" / "d.json", rd / "charts" / "spend.png", capsys)
        assert code == 0, out
        assert (rd / "charts" / "spend.png").read_bytes() == b"\x89PNG-fake"

    def test_descriptor_is_not_found_via_data(self, covered_env, capsys) -> None:
        """``--data`` inside the run must not authorize an ``--out`` outside it."""
        rd = _internal_run(Path.cwd())
        (rd / "d.json").write_text(_ROWS)
        out_path = Path.cwd() / "elsewhere" / "spend.png"
        code, out = _charts(rd / "d.json", out_path, capsys)
        assert code == 2, out
        assert _err(out).startswith("LOCAL_STORAGE_REFUSED")
        assert not out_path.exists()

    def test_symlink_out_escape_is_refused(self, covered_env, capsys) -> None:
        rd = _internal_run(Path.cwd())
        (rd / "d.json").write_text(_ROWS)
        outside = Path.cwd() / "outside"
        outside.mkdir()
        (rd / "charts").symlink_to(outside)
        code, out = _charts(rd / "d.json", rd / "charts" / "spend.png", capsys)
        assert code == 2, out
        assert _err(out).startswith("OUTSIDE_RUN_DIR")
        assert list(outside.iterdir()) == []

    def test_public_out_anywhere_unchanged(self, tmp_path, capsys) -> None:
        (tmp_path / "d.json").write_text(_ROWS)
        out_path = tmp_path / "anywhere" / "spend.png"
        code, out = _charts(tmp_path / "d.json", out_path, capsys)
        assert code == 0, out
        assert out_path.read_bytes() == b"\x89PNG-fake"


@pytest.mark.unit
class TestNotebookBound:
    def test_out_outside_the_run_is_refused(self, covered_env, capsys) -> None:
        rd = _internal_run(Path.cwd())
        (rd / "analysis" / "backlog.json").write_text(json.dumps({"items": []}))
        out_dir = Path.cwd() / "elsewhere" / "notebooks"
        code, out = run_main(
            ["notebook", "render", "--backlog", str(rd / "analysis" / "backlog.json"),
             "--out", str(out_dir), "--all"],
            capsys,
        )
        assert code == 2, out
        assert _err(out).startswith("OUTSIDE_RUN_DIR")
        assert not out_dir.exists() and not out_dir.parent.exists()


def _recur_run(base: Path) -> Path:
    rd = _internal_run(base)
    (rd / "findings-manifest.json").write_text(json.dumps({
        "schema_version": "1.0",
        "snapshot_version": "2.0",
        "window": {"start": "2026-09-08", "end": "2026-10-07"},
        "generated_at": "2026-10-08T00:00:00Z",
        "findings": [],
    }))
    return rd


@pytest.mark.unit
class TestRecurBound:
    def test_workspace_root_outside_the_case_root_is_refused(self, covered_env, capsys) -> None:
        rd = _recur_run(Path.cwd())
        trend_root = Path.cwd() / "elsewhere"
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(trend_root), "--baseline"], capsys
        )
        assert code == 2, out
        assert _err(out).startswith("OUTSIDE_RUN_DIR")
        assert not trend_root.exists()
        assert not (rd / "analysis" / "recur-result.json").exists()

    @pytest.mark.parametrize("prior", ["run", "no-manifest"])
    def test_refused_prior_writes_no_analysis(self, prior, covered_env, capsys) -> None:
        rd = _recur_run(Path.cwd())
        bare = Path.cwd() / "case" / "run-0"
        bare.mkdir()
        target = rd if prior == "run" else bare
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent), "--prior", str(target)],
            capsys,
        )
        assert code == 4, out
        # A refused --prior writes nothing: not even an ok:false recur-result.
        written = sorted(p.name for p in (rd / "analysis").iterdir())
        assert written == ["run-authorization.json"]
        assert not (rd.parent / "trend").exists()

    def test_public_workspace_root_anywhere_unchanged(self, tmp_path, capsys) -> None:
        rd = tmp_path / "case" / "run-1"
        (rd / "analysis").mkdir(parents=True)
        (rd / "findings-manifest.json").write_text(
            (_recur_run(tmp_path / "x") / "findings-manifest.json").read_text()
        )
        trend_root = tmp_path / "elsewhere"
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(trend_root), "--baseline"], capsys
        )
        assert code == 0, out
        assert (trend_root / "trend" / "history.json").is_file()

    def test_workspace_root_equal_to_the_case_root_writes(self, covered_env, capsys) -> None:
        rd = _recur_run(Path.cwd())
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent), "--baseline"], capsys
        )
        assert code == 0, out
        assert (rd.parent / "trend" / "history.json").is_file()


@pytest.mark.unit
class TestVerifyBound:
    """sec L2: a local run's ``authorized_scope.workspace_ids`` bounds ``verify run``."""

    @pytest.fixture
    def templates(self, tmp_path: Path) -> str:
        from .test_verify_helper import _TEMPLATES

        p = tmp_path / "verify-sql.md"
        p.write_text(_TEMPLATES, encoding="utf-8")
        return str(p)

    @pytest.fixture
    def fake_sql(self, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
        from starboard_skills.helpers import query as q

        calls: list[Any] = []

        def _sql(args: Any) -> dict[str, Any]:
            calls.append(args)
            return {"columns": ["a"], "rows": [["1"]], "row_count": 1, "limit_reached": False,
                    "state": "SUCCEEDED", "read_only": True}

        monkeypatch.setattr(q, "cmd_sql", _sql)
        return calls

    def _verify(self, rd: Path, templates: str, capsys, *ws: str) -> tuple[int, str]:
        return run_main(
            ["verify", "run", "vt-product-totals", "--templates", templates, *ws,
             "--start", "2026-09-01", "--end", "2026-09-30",
             "--out", str(rd / "analysis" / "verify")],
            capsys,
        )

    @pytest.mark.parametrize("ws", [("--internal-workspace-id", "999"), ("--ws", "999", "--internal-workspace-id", "999")])
    def test_a_workspace_outside_the_scope_is_refused(
        self, covered_env, templates, fake_sql, capsys, ws: tuple[str, ...]
    ) -> None:
        rd = _internal_run(Path.cwd())
        before = sorted(p.relative_to(rd) for p in rd.rglob("*"))
        code, out = self._verify(rd, templates, capsys, *ws)
        assert code == 2, out
        assert "outside the run's authorized scope (123)" in _err(out)
        assert sorted(p.relative_to(rd) for p in rd.rglob("*")) == before
        assert not fake_sql

    def test_the_scoped_workspace_runs(self, covered_env, templates, fake_sql, capsys) -> None:
        rd = _internal_run(Path.cwd())
        code, out = self._verify(rd, templates, capsys, "--internal-workspace-id", "123")
        assert code == 0, out
        assert (rd / "analysis" / "verify" / "vt-product-totals.json").is_file()
