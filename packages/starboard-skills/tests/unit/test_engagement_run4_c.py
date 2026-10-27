"""Run-4 group C fixes to the ``engagement`` verbs (C1, C2, ...)."""

from __future__ import annotations

import json
import signal
from collections.abc import Iterator
from typing import Any

import pytest

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import ok, routed, run, run_sink

# The phase-2 autouse fixtures (fake Drive store, workspace, write sandbox).
store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

BIG = "capture/big.txt"
DOC = {"rows": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}], "meta": {"n": 2}}


@pytest.fixture
def deadline() -> Iterator[None]:
    """Fail (not hang) when a read spins: SIGALRM after 20 s."""

    def boom(*_: Any) -> None:
        raise TimeoutError("engagement read did not finish (spinning)")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(20)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _rf(store: Any, capsys: Any, rel: str, text: str | None = None, doc: Any = None) -> str:
    _, data = routed(capsys)
    rf = data["run_folder_id"]
    sink = run_sink(store, rf)
    if doc is not None:
        sink.put_json(rel, doc)
    else:
        sink.put_text(rel, text or "")
    return rf


# --------------------------------------------------------------------------- #
# C1: tiny --max-bytes budgets never spin
# --------------------------------------------------------------------------- #
class TestTinyMaxBytes:
    @pytest.mark.parametrize("budget", ["1", "2", "3", "7", "8", "10", "100"])
    def test_text_read_terminates(self, capsys, store, deadline, budget):
        rf = _rf(store, capsys, BIG, "abc" * 200)
        code, env, raw = run(
            capsys, "read", "--run-folder", rf, "--path", BIG, "--max-bytes", budget
        )
        if int(budget) < 8:
            # Below the minimum excerpt: a clean USAGE, never a spin.
            assert code == 2 and env["errors"][0]["code"] == "USAGE", raw
        else:
            assert code == 0, raw
            assert len(json.dumps(env["data"]["excerpt"])) <= int(budget)

    @pytest.mark.parametrize("budget", ["1", "2", "3", "7", "8", "10", "100"])
    def test_json_read_terminates(self, capsys, store, deadline, budget):
        rf = _rf(store, capsys, "capture/rows.json", doc=DOC)
        code, env, raw = run(
            capsys, "read", "--run-folder", rf, "--path", "capture/rows.json",
            "--jsonpath", "rows[*].b", "--max-bytes", budget,
        )
        if int(budget) < 8:
            assert code == 2 and env["errors"][0]["code"] == "USAGE", raw
        else:
            assert code == 0, raw
            assert len(json.dumps(env["data"]["excerpt"])) <= int(budget)


# --------------------------------------------------------------------------- #
# C2: --jsonpath has one shape; a missing path is null, a bad expression USAGE
# --------------------------------------------------------------------------- #
class TestJsonpathShape:
    def _read(self, capsys, rf: str, *paths: str):
        argv = ["read", "--run-folder", rf, "--path", "capture/rows.json"]
        for p in paths:
            argv += ["--jsonpath", p]
        return run(capsys, *argv)

    def test_every_missing_path_is_null_with_missing_paths(self, capsys, store):
        rf = _rf(store, capsys, "capture/rows.json", doc=DOC)
        code, env, raw = self._read(capsys, rf, "nope", "meta.n", "rows[5].a")
        assert code == 0, raw
        out = env["data"]
        assert out["excerpt"] == {"nope": None, "meta.n": 2, "rows[5].a": None}
        assert out["missing_paths"] == ["nope", "rows[5].a"]
        assert out["warnings"]

    def test_single_missing_path_is_still_ok(self, capsys, store):
        rf = _rf(store, capsys, "capture/rows.json", doc=DOC)
        code, env, raw = self._read(capsys, rf, "meta.zzz")
        assert code == 0, raw
        assert env["data"]["excerpt"] == {"meta.zzz": None}
        assert env["data"]["missing_paths"] == ["meta.zzz"]

    def test_partial_star_path_nulls_the_missing_items(self, capsys, store):
        doc = {"rows": [{"a": 1}, {"b": 2}, {"a": 3}]}
        rf = _rf(store, capsys, "capture/rows.json", doc=doc)
        code, env, raw = self._read(capsys, rf, "rows[*].a")
        assert code == 0, raw
        assert env["data"]["excerpt"] == {"rows[*].a": [1, None, 3]}
        assert env["data"]["missing_paths"] == ["rows[*].a"]

    def test_present_paths_have_empty_missing_paths(self, capsys, store):
        rf = _rf(store, capsys, "capture/rows.json", doc=DOC)
        code, env, _ = self._read(capsys, rf, "meta.n")
        assert code == 0
        assert env["data"]["missing_paths"] == [] and env["data"]["warnings"] == []

    def test_root_star_recipe_works(self, capsys, store):
        rf = _rf(store, capsys, "capture/rows.json", doc=[{"finding_id": "f1"}, {"finding_id": "f2"}])
        code, env, raw = self._read(capsys, rf, "$[*].finding_id", "[1].finding_id")
        assert code == 0, raw
        assert env["data"]["excerpt"] == {
            "$[*].finding_id": ["f1", "f2"],
            "[1].finding_id": "f2",
        }

    @pytest.mark.parametrize("expr", ["$[?(@.finding_id=='f1')]"])
    def test_filters_are_usage_with_the_recipe(self, capsys, store, expr):
        rf = _rf(store, capsys, "capture/rows.json", doc=DOC)
        code, env, _ = self._read(capsys, rf, expr)
        assert code == 2 and env["errors"][0]["code"] == "USAGE"
        assert "$[*].finding_id" in env["errors"][0]["message"]

    def test_non_json_is_still_usage(self, capsys, store):
        rf = _rf(store, capsys, "capture/rows.json", "not json")
        code, env, _ = self._read(capsys, rf, "a")
        assert code == 2 and env["errors"][0]["code"] == "USAGE"


# --------------------------------------------------------------------------- #
# C7: status reports an artifact rewritten after its commit
# --------------------------------------------------------------------------- #
class TestStatusDrift:
    def test_clean_run_has_no_drift(self, capsys, store, monkeypatch):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        phase2.put(capsys, monkeypatch, rf, "analysis/backlog.json", b'{"items": []}')
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["drift"] == [] and status["warnings"] == []

    def test_rewritten_artifact_is_reported(self, capsys, store, monkeypatch):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        phase2.put(capsys, monkeypatch, rf, "analysis/backlog.json", b'{"items": []}')
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        code, _, raw = phase2.put(
            capsys, monkeypatch, rf, "analysis/backlog.json", b'{"items": [1]}'
        )
        assert code == 0, raw
        status = ok(capsys, "status", "--run-folder", rf)
        (drift,) = status["drift"]
        assert drift["path"] == "analysis/backlog.json"
        assert drift["committed_md5"] != drift["current_md5"]
        assert "analysis/backlog.json" in status["warnings"][0]
        # Re-committing binds the new bytes: the drift clears.
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert ok(capsys, "status", "--run-folder", rf)["drift"] == []


# --------------------------------------------------------------------------- #
# C3: ANSI-coloured tracebacks
# --------------------------------------------------------------------------- #
class TestAnsiSignature:
    TRACE = "\x1b[0;31mRestException\x1b[0m: INTERNAL_ERROR: boom"

    def test_signature_ignores_ansi_escapes(self):
        from starboard_core.engagement.concerns import error_signature, strip_ansi

        assert strip_ansi(self.TRACE) == "RestException: INTERNAL_ERROR: boom"
        assert error_signature(self.TRACE) == "unknown/restexception:internal_error"
        assert error_signature(self.TRACE, category="Spark Error") == (
            "spark_error/restexception:internal_error"
        )
        assert "31m" not in error_signature("\x1b[31;1mValueError\x1b[0m")
