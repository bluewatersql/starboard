"""P2-G14 exit test 2 - refusals on a covered run.

Each local flag (``--out /tmp/x``, ``--log-file``, ``--session``, ``--stdout``, a
local intake path, ``--storage local``) exits 2 with ``LOCAL_STORAGE_REFUSED``;
the sandbox stays clean and nothing reaches Drive. ``/tmp/x`` is spelled as the
sandboxed ``TMPDIR`` root, so a leak would show in the sandbox diff.

Also pinned: a missing storage adapter is ``STORAGE_UNAVAILABLE``, and the helper exit-code map (2 refusal, 3 auth,
4 storage/access, 5 identity mismatch).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement import sink
from starboard_core.engagement.write_guard import refused_events, sandbox_diff

from ..test_verify_helper import _TEMPLATES
from ._support import (
    CHART_ROWS,
    PREFLIGHT,
    REVIEW_ROWS,
    STDOUT_BUDGET,
    WIDE,
    FakeWorkspace,
    discovery,
    eng,
    error_code,
    helper,
    review,
    routed,
    starboard,
)

VERIFY = ("verify", "run", "vt-product-totals", "--ws", "123", "--start", "2026-09-01",
          "--end", "2026-09-30", "--warehouse-id", "wh-1")


@pytest.fixture
def inputs(tmp_path: Path) -> SimpleNamespace:
    """Local input files outside the sandbox roots (reading them is not the leak)."""
    templates = tmp_path / "verify-sql.md"
    templates.write_text(_TEMPLATES, encoding="utf-8")
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps(REVIEW_ROWS))
    data = tmp_path / "spend.json"
    data.write_text(json.dumps(CHART_ROWS))
    return SimpleNamespace(templates=str(templates), rows=str(rows), data=str(data))


# (case id, runner, argv builder(rf, tmp, inputs), offending flag)
Case = tuple[str, Callable[..., Any], Callable[[str, Path, Any], list[str]], str]
CASES: list[Case] = [
    ("verify --out /tmp/x", helper,
     lambda rf, tmp, i: [*VERIFY, "--templates", i.templates, "--run-folder", rf,
                         "--out", str(tmp / "x")], "--out"),
    ("notebook --out /tmp/x", helper,
     lambda rf, tmp, i: ["notebook", "render", "--all", "--run-folder", rf,
                         "--out", str(tmp / "x")], "--out"),
    ("charts --out /tmp/x (no run folder)", helper,
     lambda rf, tmp, i: ["charts", "render", "--kind", "spend-by-product", "--data",
                         i.data, "--out", str(tmp / "x.png")], "--run-folder"),
    ("query sql --out /tmp/x (no run folder)", helper,
     lambda rf, tmp, i: ["query", "sql", "--sql", "select 1", "--warehouse-id", "w",
                         "--out", str(tmp / "x.json")], "--run-folder"),
    ("discovery --out-dir /tmp/x (no run folder)", discovery,
     lambda rf, tmp, i: ["run", "--data-only", "--out-dir", str(tmp / "x")], "--run-folder"),
    ("starboard agent --log-file", starboard,
     lambda rf, tmp, i: ["--goal", "Tune", "--json", "--log-file", str(tmp / "x.log")],
     "--log-file"),
    ("starboard --discover --log-file", starboard,
     lambda rf, tmp, i: ["--discover", "--data-only", "--json", "--run-folder", rf,
                         "--log-file", str(tmp / "x.log")], "--log-file"),
    ("starboard agent --session", starboard,
     lambda rf, tmp, i: ["--goal", "Tune", "--json", "--session", "s1"], "--session"),
    ("helper --stdout", helper,
     lambda rf, tmp, i: [*VERIFY, "--templates", i.templates, "--run-folder", rf,
                         "--stdout"], "--stdout"),
    ("discovery --stdout", discovery,
     lambda rf, tmp, i: ["run", "--data-only", "--run-folder", rf, "--stdout"], "--stdout"),
    ("review --rows <local intake>", review,
     lambda rf, tmp, i: ["score", "--run-folder", rf, "--rows", i.rows, "--workspace",
                         "acme"], "--rows"),
    ("starboard review --from-discovery <local intake>", starboard,
     lambda rf, tmp, i: ["review", "--from-discovery", i.rows, "--run-folder", rf],
     "--from-discovery"),
    ("starboard agent --input-file <local intake>", starboard,
     lambda rf, tmp, i: ["--goal", "Tune", "--json", "--run-folder", rf, "--input-file",
                         i.rows], "--input-file"),
    ("preflight --storage local", eng,
     lambda rf, tmp, i: [*PREFLIGHT, "--storage", "local"], ""),
]


@pytest.mark.unit
class TestLocalFlagRefusals:
    """Spec P2-G14 item 2: every local flag on a covered run exits 2 with its code."""

    @pytest.mark.parametrize(("name", "fn", "argv", "flag"), CASES, ids=[c[0] for c in CASES])
    def test_local_flag_exits_2_with_its_code_and_leaves_no_trace(
        self, name, fn, argv, flag, capsys, store, sandbox, inputs
    ) -> None:
        _, route = routed(capsys)
        tmp = sandbox.roots[2]
        before, objects = sandbox.snapshot(), store.object_count
        code, env, raw = fn(capsys, *argv(route["run_folder_id"], tmp, inputs))
        assert code == 2, raw
        assert error_code(env) == "LOCAL_STORAGE_REFUSED", raw
        assert flag in raw
        assert sandbox_diff(before, sandbox.snapshot()) == []
        assert store.object_count == objects
        assert len(raw.encode("utf-8")) <= STDOUT_BUDGET
        assert refused_events() == ()  # refused up front, not by the guard at write time


@pytest.mark.unit
class TestExitCodeMap:
    """Engagement exit codes: 2 refusal, 3 auth, 4 storage, 5 identity, 6 workspace API."""

    def test_missing_storage_adapter_is_storage_unavailable(
        self, capsys, monkeypatch, sandbox
    ) -> None:
        monkeypatch.setattr(sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: []))
        before = sandbox.snapshot()
        code, env, _ = eng(capsys, *PREFLIGHT)
        assert code == 2 and error_code(env) == "STORAGE_UNAVAILABLE"
        assert sandbox_diff(before, sandbox.snapshot()) == []

    def test_storage_auth_failure_exits_3(self, capsys, store) -> None:
        store.auth_failed = True
        code, env, _ = eng(capsys, *PREFLIGHT)
        assert code == 3 and error_code(env) == "AUTH_REQUIRED"

    def test_broadened_acl_exits_4_blocked_access(self, capsys, store) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        store.set_access(rf, grants=WIDE)
        code, env, _ = eng(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert code == 4 and error_code(env) == "BLOCKED_ACCESS"

    def test_identity_mismatch_exits_5(self, capsys, store, seams) -> None:
        pre = eng(capsys, *PREFLIGHT)[1]["data"]
        seams.client = FakeWorkspace(workspace_id="999")
        code, env, _ = eng(capsys, "verify-identity", "--run-id", pre["run_id"],
                           "--profile", "acme")
        assert code == 5, env
        assert env["ok"] is False
