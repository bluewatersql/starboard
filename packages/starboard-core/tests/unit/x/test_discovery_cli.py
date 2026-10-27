# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``python -m starboard_x.discovery`` CLI (Phase-2 D4).

The discovery engine lives in the heavier ``starboard`` server package, so the
CLI imports it lazily inside :func:`build_engine`. These tests mock that seam:
they never require a live workspace and prove the deterministic (data-only,
no-LLM) path is what runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_CORE_DIR = Path(__file__).parents[3]


# Pins the internal-overlay detection seam in the subprocess. The dev venv has
# the internal package installed, so the real detector may report "enabled".
_PIN_OVERLAY = """
import starboard_x.discovery.__main__ as _disc_pin
from starboard_core.engagement.overlay import OverlaySignal as _OverlaySignal

_disc_pin.detect_overlay = lambda **_kw: _OverlaySignal(
    enabled={enabled}, reasons=("test",) if {enabled} else ()
)
"""


def _run_program(
    body: str, *, overlay: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run ``body`` in a fresh interpreter with the overlay seam pinned."""
    body = _PIN_OVERLAY.format(enabled=overlay) + body
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )


@pytest.fixture(autouse=True)
def _public_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """In-process tests run as a public install unless they opt in."""
    from starboard_core.engagement.overlay import OverlaySignal
    from starboard_x.discovery import __main__ as disc

    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )


@pytest.mark.unit
class TestDiscoveryRunDataOnly:
    """``run --data-only`` mocks the engine and emits a data-only envelope."""

    def test_run_emits_envelope_no_llm(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc


class FakeQR:
    def __init__(self, ok):
        self.succeeded = ok


class FakePack:
    pack_id = "billing"
    results = [FakeQR(True), FakeQR(False)]


class FakeAudit:
    succeeded = True


class FakeResult:
    trace_id = "trace-xyz"
    elapsed_ms = 42.0
    errors = []
    audit_result = FakeAudit()
    pack_results = [FakePack()]
    domain_analyses = []   # data-only: no LLM analysis ran


class FakeEngine:
    def __init__(self):
        self.used_llm = False

    async def run(self):
        return FakeResult()


captured = {}


def fake_build(args):
    captured["data_only_flag"] = args.data_only
    captured["packs"] = args.packs
    return FakeEngine()


disc.build_engine = fake_build

try:
    disc.main(["run", "--data-only", "--packs", "billing"])
except SystemExit as exc:
    # main() prints the envelope, then exits; propagate the code for the test.
    assert captured["data_only_flag"] is True, captured
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is True
        assert env["domain"] == "discovery"
        assert env["command"] == "run"
        data = env["data"]
        assert data["data_only"] is True
        # No LLM analysis on the data-only path: deterministic per-domain summary only.
        [summary] = data["domain_analyses"]
        assert summary["kind"] == "data_only_summary"
        assert summary["domain"] == "billing"
        assert (summary["queries"], summary["succeeded"], summary["failed"]) == (
            2,
            1,
            1,
        )
        assert "grade" not in summary and "findings" not in summary
        assert data["trace_id"] == "trace-xyz"
        assert data["pack_count"] == 1
        assert data["packs"][0]["pack"] == "billing"
        assert data["packs"][0]["queries"] == 2
        assert data["packs"][0]["succeeded"] == 1

    def test_run_emits_actual_query_data(self) -> None:
        # --data-only must return the actual rows (not just counts) so a host
        # agent can analyze the deterministic data directly.
        body = """
import sys

import starboard_x.discovery.__main__ as disc


class FakeDF:
    columns = ["region", "dbus"]

    def to_dicts(self):
        return [{"region": "us", "dbus": 10}, {"region": "eu", "dbus": 20}]


class FakeQR:
    query_id = "C-B01"
    domain = "billing"
    succeeded = True
    error = None
    row_count = 2
    data = FakeDF()


class FakePack:
    pack_id = "billing"
    results = [FakeQR()]


class FakeResult:
    trace_id = "t"
    elapsed_ms = 1.0
    errors = []
    audit_result = None
    pack_results = [FakePack()]
    domain_analyses = []


class FakeEngine:
    async def run(self):
        return FakeResult()


disc.build_engine = lambda args: FakeEngine()

try:
    disc.main(["run", "--data-only"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        q = env["data"]["packs"][0]["results"][0]
        assert q["query_id"] == "C-B01"
        assert q["columns"] == ["region", "dbus"]
        assert q["rows"] == [
            {"region": "us", "dbus": 10},
            {"region": "eu", "dbus": 20},
        ]
        assert q["truncated"] is False

    def test_build_engine_failure_is_auth_error(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc
from starboard_x.contract import AuthError


def boom(args):
    raise AuthError("could not build a Databricks client: no host configured")


disc.build_engine = boom

try:
    disc.main(["run", "--data-only"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 1, proc.stdout  # auth
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert "client" in env["error"]


@pytest.mark.unit
class TestDiscoveryRunAuthTargeting:
    """``run`` accepts and threads --profile / --host / --warehouse-id."""

    def test_parser_accepts_profile_host_warehouse(self) -> None:
        from starboard_x.discovery import __main__ as disc

        ns = disc.build_parser().parse_args(
            [
                "run",
                "--profile",
                "e2-demo-field-eng",
                "--host",
                "https://ws.cloud.databricks.com",
                "--warehouse-id",
                "abc123",
            ]
        )
        assert ns.profile == "e2-demo-field-eng"
        assert ns.host == "https://ws.cloud.databricks.com"
        assert ns.warehouse_id == "abc123"

    def test_build_engine_threads_profile_and_warehouse(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
import os
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

os.environ.pop("DATABRICKS_CONFIG_PROFILE", None)
base_cfg = MagicMock(name="base_cfg")
overridden_cfg = MagicMock(name="overridden_cfg")
base_cfg.model_copy.return_value = overridden_cfg

with (
    patch.object(bs, "get_config", return_value=base_cfg),
    patch.object(bs, "AsyncDatabricksClient") as Client,
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig", MagicMock()),
    patch.object(bs, "DiscoveryEngine") as DiscoveryEngine,
):
    ns = argparse.Namespace(
        lookback_days=30,
        max_parallelism=4,
        packs=None,
        profile="e2-demo-field-eng",
        host=None,
        warehouse_id="wh-xyz",
    )
    engine = disc.build_engine(ns)

    # --profile is applied via the resolver's env source.
    assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "e2-demo-field-eng"
    # --warehouse-id overrides the resolved config.
    assert base_cfg.model_copy.call_args.kwargs["update"] == {
        "databricks_warehouse_id": "wh-xyz"
    }
    # The client is built from the overridden config and attached to the engine.
    assert Client.call_args.kwargs["cfg"] is overridden_cfg
    assert getattr(engine, disc._CLIENT_ATTR) is Client.return_value
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_build_engine_host_drops_ambient_profile(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
import os
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

os.environ["DATABRICKS_CONFIG_PROFILE"] = "default-profile"
base_cfg = MagicMock(name="base_cfg")

with (
    patch.object(bs, "get_config", return_value=base_cfg),
    patch.object(bs, "AsyncDatabricksClient"),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig", MagicMock()),
    patch.object(bs, "DiscoveryEngine"),
):
    ns = argparse.Namespace(
        lookback_days=30,
        max_parallelism=4,
        packs=None,
        profile=None,
        host="https://customer.cloud.databricks.com",
        warehouse_id=None,
    )
    disc.build_engine(ns)

    # An explicit --host without --profile drops the ambient profile (F8a).
    assert "DATABRICKS_CONFIG_PROFILE" not in os.environ
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_unknown_packs_value_is_arg_error(self) -> None:
        # An unknown --packs selector must fail fast with arg-error (exit 4) and
        # list the valid selectors, instead of silently running everything.
        pytest.importorskip("starboard.bootstrap")
        body = """
import sys

import starboard_x.discovery.__main__ as disc

try:
    disc.main(["run", "--data-only", "--packs", "finops_billing", "jobs"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 4, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert "finops_billing" in env["error"]
        assert "jobs" not in env["error"].split("value(s):")[1].split(".")[0]

    def test_run_initializes_client_before_run(self) -> None:
        # The run path must enter the client's async context (auth + warehouse
        # resolution) BEFORE executing the engine — otherwise queries fail with
        # "No SQL warehouse configured".
        body = """
import sys

import starboard_x.discovery.__main__ as disc

events = []


class FakeClient:
    async def __aenter__(self):
        events.append("aenter")
        return self

    async def __aexit__(self, *a):
        events.append("aexit")
        return False


class FakeResult:
    trace_id = "t"
    elapsed_ms = 1.0
    errors = []
    audit_result = None
    pack_results = []
    domain_analyses = []


class FakeEngine:
    async def run(self):
        events.append("run")
        return FakeResult()


def fake_build(args):
    engine = FakeEngine()
    setattr(engine, disc._CLIENT_ATTR, FakeClient())
    return engine


disc.build_engine = fake_build

try:
    disc.main(["run"])
except SystemExit as exc:
    assert events == ["aenter", "run", "aexit"], events
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"

    def test_client_init_failure_is_auth_error(self) -> None:
        # A failure while entering the client's async context (auth / config /
        # warehouse resolution) maps to the exit-1 auth code.
        body = """
import sys

import starboard_x.discovery.__main__ as disc


class FakeClient:
    async def __aenter__(self):
        raise RuntimeError("no such profile configured")

    async def __aexit__(self, *a):
        return False


class FakeEngine:
    async def run(self):
        raise AssertionError("engine.run must not be reached on auth failure")


def fake_build(args):
    engine = FakeEngine()
    setattr(engine, disc._CLIENT_ATTR, FakeClient())
    return engine


disc.build_engine = fake_build

try:
    disc.main(["run"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 1, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert "authenticate" in env["error"]


@pytest.mark.unit
class TestDiscoveryBuilderEnforcesDataOnly:
    """The real ``build_engine`` forces ``data_only=True`` + ``llm_client=None``."""

    def test_build_engine_data_only_and_no_llm(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine") as DiscoveryEngine,
):
    ns = argparse.Namespace(lookback_days=30, max_parallelism=4, packs=None)
    disc.build_engine(ns)

    assert EngineConfig.call_args.kwargs["data_only"] is True, EngineConfig.call_args
    assert DiscoveryEngine.call_args.kwargs["llm_client"] is None, (
        DiscoveryEngine.call_args
    )
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout


@pytest.mark.unit
class TestDiscoveryPlan:
    """``plan`` runs audit-only and returns the recommended-domains envelope."""

    def test_plan_emits_recommended_domains(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc


class FakeDomain:
    def __init__(self, domain, packs, dbus):
        self.domain = domain
        self.packs = packs
        self.dbus = dbus


class FakeSelection:
    recommended = [FakeDomain("query_perf", ["query_perf"], 9000.0)]
    always_recommended = ["billing", "governance"]
    contextual = ["migration"]


class FakePlan:
    products = {"SQL": 9000.0}
    selection = FakeSelection()
    audit_succeeded = True
    trace_id = "plan-trace"


class FakeEngine:
    async def plan(self):
        return FakePlan()


disc.build_engine = lambda args: FakeEngine()

try:
    disc.main(["plan", "--lookback-days", "30"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is True
        assert env["command"] == "plan"
        data = env["data"]
        assert data["lookback_days"] == 30
        assert "products" in data
        assert data["products"] == {"SQL": 9000.0}
        assert data["recommended"][0]["domain"] == "query_perf"
        assert data["recommended"][0]["dbus"] == 9000.0
        assert data["always_recommended"] == ["billing", "governance"]
        assert data["contextual"] == ["migration"]
        assert data["audit_succeeded"] is True


@pytest.mark.unit
class TestDiscoveryRunOnly:
    def test_parser_accepts_only(self) -> None:
        from starboard_x.discovery import __main__ as disc

        ns = disc.build_parser().parse_args(["run", "--only", "jobs", "query_perf"])
        assert ns.only == ["jobs", "query_perf"]

    def test_only_and_packs_are_mutually_exclusive(self) -> None:
        # argparse mutual-exclusion routes through ArgError -> exit 4.
        body = """
import sys
import starboard_x.discovery.__main__ as disc
try:
    disc.main(["run", "--only", "jobs", "--packs", "billing"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 4, proc.stdout

    def test_only_threads_exact_packs(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine"),
):
    ns = argparse.Namespace(
        lookback_days=30, max_parallelism=4, packs=None, only=["jobs"],
        profile=None, host=None, warehouse_id=None,
    )
    disc.build_engine(ns)
    assert EngineConfig.call_args.kwargs["exact_packs"] == ["jobs"], EngineConfig.call_args
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_unknown_only_value_is_arg_error(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import sys
import starboard_x.discovery.__main__ as disc
try:
    disc.main(["run", "--only", "not_a_pack"])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 4, proc.stdout
        env = json.loads(proc.stdout)
        assert "not_a_pack" in env["error"]


@pytest.mark.unit
class TestDiscoveryOutDir:
    def test_out_dir_writes_raw_files_and_manifest(self, tmp_path) -> None:
        body = f"""
import sys

import starboard_x.discovery.__main__ as disc


class FakeDF:
    columns = ["region", "dbus"]

    def to_dicts(self):
        return [{{"region": "us", "dbus": 10}}]


class FakeQR:
    query_id = "J-01"
    domain = "jobs"
    succeeded = True
    error = None
    row_count = 1
    data = FakeDF()


class FakePack:
    pack_id = "jobs"
    domain = "jobs"
    results = [FakeQR()]


class FakeResult:
    trace_id = "t"
    elapsed_ms = 1.0
    errors = []
    audit_result = None
    pack_results = [FakePack()]
    domain_analyses = []


class FakeEngine:
    async def run(self):
        return FakeResult()


disc.build_engine = lambda args: FakeEngine()

try:
    disc.main(["run", "--only", "jobs", "--out-dir", {str(tmp_path)!r}])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        data = env["data"]
        # stdout carries the compact manifest, NOT the full rows.
        assert "packs" not in data
        assert data["manifest"][0]["pack"] == "jobs"
        assert data["manifest"][0]["rows_total"] == 1
        assert data["manifest"][0]["path"] == "raw/jobs.json"
        # the rows live on disk
        raw = json.loads((tmp_path / "raw" / "jobs.json").read_text())
        assert raw["results"][0]["rows"] == [{"region": "us", "dbus": 10}]

    def test_out_dir_files_keyed_by_pack_id_not_domain(self, tmp_path) -> None:
        # Two packs sharing a domain must NOT overwrite each other.
        import types

        def _pk(pack_id, domain):
            qr = types.SimpleNamespace(
                query_id="Q",
                domain=domain,
                succeeded=True,
                error=None,
                row_count=0,
                data=None,
            )
            return types.SimpleNamespace(pack_id=pack_id, domain=domain, results=[qr])

        class FakeResult:
            trace_id = "t"
            elapsed_ms = 1.0
            errors = []
            audit_result = None
            pack_results = [
                _pk("governance", "governance"),
                _pk("networking", "governance"),
            ]
            domain_analyses = []

        import starboard_x.discovery.__main__ as disc

        data = disc.write_result_files(FakeResult(), str(tmp_path))
        packs = {m["pack"] for m in data["manifest"]}
        assert packs == {"governance", "networking"}
        assert (tmp_path / "raw" / "governance.json").exists()
        assert (tmp_path / "raw" / "networking.json").exists()


@pytest.mark.unit
class TestDiscoveryDepLight:
    """Importing the discovery CLI must not pull the server package / SDK."""

    def test_module_import_is_dep_light(self) -> None:
        body = """
import importlib
import sys

importlib.import_module("starboard_x.discovery.__main__")

leaked = sorted(
    m for m in sys.modules
    if m == "starboard"
    or m.startswith("starboard.")
    or m == "databricks"
    or m.startswith("databricks.")
    or m == "openai"
)
assert not leaked, f"discovery CLI import leaked heavy deps: {leaked}"
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout


@pytest.mark.unit
class TestDiscoveryNoCacheAndOutputPath:
    """W33: --no-cache and --output-path parity with starboard --discover."""

    def test_parser_accepts_no_cache(self) -> None:
        from starboard_x.discovery import __main__ as disc

        ns = disc.build_parser().parse_args(["run", "--no-cache"])
        assert ns.no_cache is True

    def test_no_cache_default_false(self) -> None:
        from starboard_x.discovery import __main__ as disc

        ns = disc.build_parser().parse_args(["run"])
        assert ns.no_cache is False

    def test_parser_accepts_output_path(self) -> None:
        from starboard_x.discovery import __main__ as disc

        ns = disc.build_parser().parse_args(["run", "--output-path", "/tmp/out.json"])
        assert ns.output_path == "/tmp/out.json"

    def test_output_path_json_writes_file_and_compact_stdout(self, tmp_path) -> None:
        body = f"""
import json
import sys

import starboard_x.discovery.__main__ as disc


class FakeResult:
    trace_id = "t"
    elapsed_ms = 1.0
    errors = []
    audit_result = None
    pack_results = []
    domain_analyses = []


disc.build_engine = lambda args: type("E", (), {{"run": lambda self: (_ for _ in ()).throw(AssertionError)}})()

# Bypass engine run by patching asyncio.run
import asyncio
asyncio.run = lambda coro: (coro.close() or FakeResult())

out = {str(tmp_path / "result.json")!r}
try:
    disc.main(["run", "--output-path", out])
except SystemExit as exc:
    sys.exit(exc.code)
"""
        proc = _run_program(body)
        # File must exist and stdout must be a compact JSON summary (in the data block)
        out_file = tmp_path / "result.json"
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        envelope = __import__("json").loads(proc.stdout)
        assert envelope["ok"] is True
        # _cmd_run returns the compact manifest dict; _cli.run wraps it in data.
        data = envelope["data"]
        assert "output_path" in data
        assert "bytes" in data
        assert out_file.exists()

    def test_output_path_directory_delegates_to_out_dir(self, tmp_path) -> None:
        from starboard_x.discovery import __main__ as disc

        class FakeResult:
            trace_id = "t"
            elapsed_ms = 1.0
            errors = []
            audit_result = None
            pack_results = []
            domain_analyses = []

        # write_result_files with empty pack_results creates the raw dir
        data = disc.write_result_files(FakeResult(), str(tmp_path))
        # should return a manifest (not crash)
        assert "manifest" in data


RUN_ID = "20261008_3f2b8c1e-9d4a-4e6b-8a2f-1c3d5e7f9a0b"


def _identity(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "provisional_account_key": "acme",
        "provisional_account_name": "Acme Corp",
        "provisional_source": "operator",
        "expected_workspace_id": "123",
        "expected_host": None,
        "observed_workspace_id": "123",
        "observed_host": "https://acme.cloud.databricks.com",
        "principal_id": "7781234",
        "principal_kind": "user",
        "checked_at": "2026-10-08T09:00:00+00:00",
        "status": "verified",
        "reasons": [],
    }
    record.update(overrides)
    return record


def _write_authorization(
    run_dir: Path,
    workspace_ids: object,
    *,
    identity: dict[str, object] | None = None,
    run_id: str = RUN_ID,
) -> Path:
    """Write ``analysis/run-authorization.json`` plus a matching identity check."""
    analysis = run_dir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    if identity is None:
        first = (
            workspace_ids[0]
            if isinstance(workspace_ids, list) and workspace_ids
            else "123"
        )
        identity = _identity(
            expected_workspace_id=str(first), observed_workspace_id=str(first)
        )
    (analysis / "identity-check.json").write_text(json.dumps(identity))
    path = analysis / "run-authorization.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "authorized_scope": {
                    "account_key": "acme",
                    "workspace_ids": workspace_ids,
                },
            }
        )
    )
    return path


@pytest.mark.unit
class TestDiscoveryAuthorization:
    """``--authorization <run-dir|file>`` limits discovery to the authorized scope."""

    def test_reads_run_dir_descriptor(self, tmp_path: Path) -> None:
        from starboard_x.discovery import __main__ as disc

        _write_authorization(tmp_path, ["123"])
        assert disc.load_authorized_workspace_ids(str(tmp_path)) == ("123",)

    def test_reads_descriptor_file(self, tmp_path: Path) -> None:
        from starboard_x.discovery import __main__ as disc

        path = _write_authorization(tmp_path, ["123"])
        assert disc.load_authorized_workspace_ids(str(path)) == ("123",)

    @pytest.mark.parametrize(
        "workspace_ids", [[], ["12a"], [123], "123", None, ["1' OR '1'='1"]]
    )
    def test_invalid_workspace_ids_are_arg_errors(
        self, tmp_path: Path, workspace_ids: object
    ) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        _write_authorization(tmp_path, workspace_ids)
        with pytest.raises(ArgError):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_missing_file_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        with pytest.raises(ArgError, match="run-authorization.json"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_bad_json_and_missing_scope_are_arg_errors(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        path = _write_authorization(tmp_path, ["123"])
        path.write_text("{not json")
        with pytest.raises(ArgError):
            disc.load_authorized_workspace_ids(str(tmp_path))
        path.write_text(json.dumps({"run_id": RUN_ID}))
        with pytest.raises(ArgError, match="authorized_scope"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_file_outside_run_layout_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        path = _write_authorization(tmp_path, ["123"])
        stray = tmp_path / "descriptor.json"
        stray.write_bytes(path.read_bytes())
        with pytest.raises(ArgError, match="run-authorization.json"):
            disc.load_authorized_workspace_ids(str(stray))

    def test_missing_identity_check_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        _write_authorization(tmp_path, ["123"])
        (tmp_path / "analysis" / "identity-check.json").unlink()
        with pytest.raises(ArgError, match="verify-identity"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_unparseable_identity_check_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        _write_authorization(tmp_path, ["123"])
        (tmp_path / "analysis" / "identity-check.json").write_text("{nope")
        with pytest.raises(ArgError, match="identity"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_unverified_identity_check_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        mismatch = _identity(
            observed_workspace_id="999",
            status="mismatch",
            reasons=["workspace id differs: expected 123, observed 999"],
        )
        _write_authorization(tmp_path, ["123"], identity=mismatch)
        with pytest.raises(ArgError, match="mismatch"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_identity_run_id_mismatch_is_arg_error(self, tmp_path: Path) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        other = "20261008_0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d"
        _write_authorization(tmp_path, ["123"], identity=_identity(run_id=other))
        with pytest.raises(ArgError, match="run"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    @pytest.mark.parametrize("workspace_ids", [["123", "456"], ["456"], ["456", "123"]])
    def test_scope_must_equal_verified_workspace(
        self, tmp_path: Path, workspace_ids: list[str]
    ) -> None:
        from starboard_x.contract import ArgError
        from starboard_x.discovery import __main__ as disc

        _write_authorization(tmp_path, workspace_ids, identity=_identity())
        with pytest.raises(ArgError, match="123"):
            disc.load_authorized_workspace_ids(str(tmp_path))

    def test_parser_accepts_authorization_on_run_and_plan(self) -> None:
        from starboard_x.discovery import __main__ as disc

        parser = disc.build_parser()
        assert parser.parse_args(["run", "--authorization", "d"]).authorization == "d"
        assert parser.parse_args(["plan", "--authorization", "d"]).authorization == "d"
        assert parser.parse_args(["run"]).authorization is None

    def test_missing_authorization_exits_arg_error_before_any_client(
        self, tmp_path: Path
    ) -> None:
        body = f"""
import starboard_x.discovery.__main__ as disc
disc.main(["run", "--data-only", "--authorization", {str(tmp_path)!r}])
"""
        proc = _run_program(body)
        assert proc.returncode == 4, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert "run-authorization.json" in env["error"]

    def test_build_engine_threads_authorized_scope_and_probe(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("starboard.bootstrap")
        _write_authorization(tmp_path, ["123"])
        body = f"""
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine") as DiscoveryEngine,
):
    ns = argparse.Namespace(
        lookback_days=30, max_parallelism=4, packs=None,
        authorization={str(tmp_path)!r},
    )
    disc.build_engine(ns)
    assert EngineConfig.call_args.kwargs["authorized_workspace_ids"] == ("123",)
    assert callable(DiscoveryEngine.call_args.kwargs["workspace_id_probe"])
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_no_authorization_leaves_scope_unset(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine"),
):
    ns = argparse.Namespace(lookback_days=30, max_parallelism=4, packs=None)
    disc.build_engine(ns)
    assert EngineConfig.call_args.kwargs["authorized_workspace_ids"] is None
print("OK")
"""
        proc = _run_program(body)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_unauthorized_workspace_is_auth_error(self) -> None:
        body = """
import sys

import starboard_x.discovery.__main__ as disc


from starboard_core.engagement.row_scope import WorkspaceAuthorizationError


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class FakeEngine:
    async def run(self):
        raise WorkspaceAuthorizationError(
            "connected workspace 999 is not in the run's authorized scope"
        )


def fake_build(args):
    engine = FakeEngine()
    setattr(engine, disc._CLIENT_ATTR, FakeClient())
    return engine


disc.build_engine = fake_build
disc.main(["run", "--data-only"])
"""
        proc = _run_program(body)
        assert proc.returncode == 1, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert "authorized scope" in env["error"]

    @pytest.mark.parametrize("verb", ["run", "plan"])
    def test_os_permission_error_is_not_reported_as_authorization(
        self, verb: str
    ) -> None:
        body = f"""
import sys

import starboard_x.discovery.__main__ as disc


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class FakeEngine:
    async def run(self):
        raise PermissionError(13, "Permission denied", "/tmp/out")

    async def plan(self):
        raise PermissionError(13, "Permission denied", "/tmp/out")


def fake_build(args):
    engine = FakeEngine()
    setattr(engine, disc._CLIENT_ATTR, FakeClient())
    return engine


disc.build_engine = fake_build
disc.main([{verb!r}])
"""
        proc = _run_program(body)
        assert proc.returncode == 3, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["error"].startswith("API error"), env["error"]
        assert "Permission denied" in env["error"]


@pytest.mark.unit
class TestDiscoveryOverlayRequiresAuthorization:
    """On an internal-overlay install, customer discovery is covered: ``--run-folder``.

    ``build_engine`` itself still demands a descriptor when called without one.
    """

    @pytest.mark.parametrize("verb", ["run", "plan"])
    def test_overlay_without_run_folder_is_refused_before_any_client(
        self, verb: str
    ) -> None:
        # Phase 2: a covered (overlay) customer run must write to the Drive run
        # folder, so the local-descriptor hint is superseded by --run-folder.
        body = f"""
import sys

import starboard_x.discovery.__main__ as disc

try:
    disc.main([{verb!r}])
except SystemExit as exc:
    leaked = sorted(m for m in sys.modules if m == "starboard" or m.startswith("starboard."))
    print("LEAKED=" + ",".join(leaked), file=sys.stderr)
    sys.exit(exc.code)
"""
        proc = _run_program(body, overlay=True)
        assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        env = json.loads(proc.stdout)
        assert env["ok"] is False
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED"), env["error"]
        assert "--run-folder" in env["error"]
        # Refused before the server package (and so any Databricks client) loads.
        assert "LEAKED=\n" in proc.stderr, proc.stderr

    def test_overlay_with_authorization_builds_scoped_engine(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("starboard.bootstrap")
        _write_authorization(tmp_path, ["123"])
        body = f"""
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine"),
):
    ns = argparse.Namespace(
        lookback_days=30, max_parallelism=4, packs=None,
        authorization={str(tmp_path)!r},
    )
    disc.build_engine(ns)
    assert EngineConfig.call_args.kwargs["authorized_workspace_ids"] == ("123",)
print("OK")
"""
        proc = _run_program(body, overlay=True)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout

    def test_public_without_authorization_builds_unscoped_engine(self) -> None:
        pytest.importorskip("starboard.bootstrap")
        body = """
import argparse
from unittest.mock import MagicMock, patch

import starboard.bootstrap as bs
import starboard_x.discovery.__main__ as disc

with (
    patch.object(bs, "get_config", return_value=MagicMock()),
    patch.object(bs, "AsyncDatabricksClient", MagicMock()),
    patch.object(bs, "AsyncSQLExecutor", MagicMock()),
    patch.object(bs, "EngineConfig") as EngineConfig,
    patch.object(bs, "DiscoveryEngine"),
):
    ns = argparse.Namespace(lookback_days=30, max_parallelism=4, packs=None)
    disc.build_engine(ns)
    assert EngineConfig.call_args.kwargs["authorized_workspace_ids"] is None
print("OK")
"""
        proc = _run_program(body, overlay=False)
        assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        assert "OK" in proc.stdout
