"""Shared helpers for the phase-3 exit tests (spec §H).

Every CLI is driven in-process through its ``main(argv)``. Setup runs inside the
test bodies (never in fixtures), so a missing phase-3 module or verb surfaces as
an ``ImportError`` / ``AttributeError`` / assertion, never as a fixture error.

A scenario run (:class:`Run`) is either

* ``drive_backed``: preflight -> verify-identity -> route against the in-memory
  Drive fake; inputs are written through the run sink; every CLI call is checked
  with :func:`clean` (empty sandbox diff, one bounded JSON line); or
* ``internal_local``: an internal-only ``--storage local`` run under
  ``tmp_path/reports`` (``LocalDirSink``); inputs are plain files in the run dir and
  prior history is the run's case root (``--workspace-root``).
"""

from __future__ import annotations

import io
import json
import typing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import create_autospec

import pytest
from databricks.sdk import WorkspaceClient
from starboard_core.engagement.commit import latest_manifest, read_descriptor
from starboard_core.engagement.sink import DriveRunSink, reserved_record
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_core.ports.engagement_storage import Grant

from . import _j42

MODES = ("internal_local", "drive_backed")
STDOUT_BUDGET = 24_000
HOST = "https://acme.cloud.databricks.com"
ACCOUNT = _j42.ACCOUNT
WS = _j42.WS
USER_ME = {
    "id": "7001",
    "userName": "pat.operator@acme.example",
    "emails": [{"value": "pat.operator@acme.example", "primary": True}],
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
}
FACTS = "discovery/facts.json"
MANIFEST = "findings-manifest.json"
VERIFY_DIR = "analysis/verify"
QUESTION = "Why did job 42 start failing after 2026-09-22?"


# --------------------------------------------------------------------------- #
# Fakes (the phase-2 shapes)
# --------------------------------------------------------------------------- #
class FakeWorkspace:
    """A workspace client whose ``/Me`` answers for workspace ``123``."""

    def __init__(self, workspace_id: str = WS) -> None:
        self.config = SimpleNamespace(host=HOST, workspace_id=None)
        self.api_client = self
        self._workspace_id = workspace_id

    def do(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        return {**USER_ME, "X-Databricks-Org-Id": self._workspace_id}


class Df:
    """Minimal polars-like duck type (``to_dicts`` / ``columns``)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.columns = list(rows[0]) if rows else []
        self._rows = rows

    def to_dicts(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _qr(query_id: str, domain: str, rows: list[dict[str, Any]] | None) -> Any:
    return SimpleNamespace(
        query_id=query_id,
        domain=domain,
        data=None if rows is None else Df(rows),
        error=None if rows is not None else "PARSE_SYNTAX_ERROR",
        row_count=0 if rows is None else len(rows),
        succeeded=rows is not None,
        skipped=False,
        result_limit=None,
        lookback_days=30,
        execution_time_ms=1.0,
        attempts=1,
        attempt_elapsed_ms=[1.0],
    )


def fake_discovery_result() -> Any:
    billing = SimpleNamespace(
        pack_id="billing",
        domain="billing",
        results=[
            _qr(
                "F-01",
                "billing",
                [
                    {
                        "workspace_id": WS,
                        "billing_origin_product": "JOBS",
                        "usage_unit": "DBU",
                        "window_start": "2026-09-08",
                        "window_end": "2026-10-07",
                        "usage_quantity": Decimal("600.5"),
                    }
                ],
            )
        ],
    )
    return SimpleNamespace(
        trace_id="trace-1",
        elapsed_ms=1.0,
        errors=[],
        audit_result=SimpleNamespace(succeeded=True),
        pack_results=[billing],
        domain_analyses=[],
    )


class GatherEngine:
    def __init__(
        self, sql_executor: Any, llm_client: Any, config: Any, **_kw: Any
    ) -> None:
        self.config = config

    async def run(self, on_progress: Any = None) -> Any:
        from starboard.discovery.engine import EngineResult

        return EngineResult(trace_id="gather", pack_results=[])


class GatherClient:
    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> GatherClient:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return WS


class FakeEngine:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def run(self) -> Any:
        return self._result


def autospec_client(*apis: str) -> Any:
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too.

    The class is bound at import, so a test that patches
    ``databricks.sdk.WorkspaceClient`` can still build a second client.
    """
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


def identity_keys(obj: Any) -> list[str]:
    """Keys that carry a user identity (``*user_name``, ``*user_id``, ``*email*``)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith(("user_name", "user_id")) or "email" in k.lower():
                found.append(k)
            found += identity_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            found += identity_keys(v)
    return found


# --------------------------------------------------------------------------- #
# In-process CLI runners
# --------------------------------------------------------------------------- #
def _last_json(raw: str) -> dict[str, Any]:
    for text in (raw, *reversed([ln for ln in raw.splitlines() if ln.strip()])):
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return {}


def call(
    fn: Any, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict, str]:
    code = 0
    try:
        fn(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    raw = capsys.readouterr().out
    return code, _last_json(raw), raw


def helper(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    """``starboard-helper <argv>`` -> ``(exit, envelope, raw stdout)``."""
    from starboard_skills.helpers.__main__ import main

    return call(main, list(argv), capsys)


def eng(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    """``starboard-helper engagement <argv>``."""
    return helper(capsys, "engagement", *argv)


def ok(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    """``engagement <argv>`` that must exit 0; returns ``data``."""
    code, env, raw = eng(capsys, *argv)
    assert code == 0, raw
    assert env["ok"] is True
    return env["data"]


def module(
    name: str, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, dict, str]:
    """``python -m starboard_x.<name> <argv>``."""
    import importlib

    mod = importlib.import_module(f"starboard_x.{name}.__main__")
    return call(mod.main, list(argv), capsys)


def error_code(env: dict[str, Any]) -> str:
    errors = env.get("errors") or []
    if errors and isinstance(errors[0], dict) and errors[0].get("code"):
        return str(errors[0]["code"])
    return str(env.get("error", "")).split(" ", 1)[0].rstrip(":")


def clean(sandbox: Any, before: dict, raw: str) -> dict[str, Any]:
    """Covered-run invariants: empty sandbox diff, one compact JSON line <= 24 000 B."""
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert len(raw.encode("utf-8")) <= STDOUT_BUDGET
    assert raw.count("\n") == 1, raw[:400]
    return json.loads(raw)


# --------------------------------------------------------------------------- #
# Drive access
# --------------------------------------------------------------------------- #
def run_sink(store: Any, rf: str) -> DriveRunSink:
    auth, _ = read_descriptor(store, rf)
    assert auth.drive is not None
    return DriveRunSink(
        store,
        rf,
        run_id=auth.run_id,
        access_fingerprint=auth.drive.permission_fingerprints[rf],
    )


def manifest(store: Any, rf: str) -> Any:
    return latest_manifest(store, rf)[0]


def sink_put(store: Any, rf: str, files: dict[str, Any]) -> None:
    """Fixture setup only: write straight through the run sink (no CLI)."""
    sink = run_sink(store, rf)
    for rel, data in files.items():
        if reserved_record(rel):
            body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
            sink.put_record(rel, body, "application/json")
        elif isinstance(data, str):
            sink.put_text(rel, data)
        else:
            sink.put_json(rel, data)


def ticket_flags(store: Any, tmp_path: Path) -> tuple[str, ...]:
    """Route flags for an ``AR-000000001`` ticket run (the phase-2 exit-7 shape)."""
    shared = store.add_shared_drive(
        "asqs-root",
        "ASQs",
        drive_id="d1",
        grants=(Grant("group", "fileOrganizer", "databricks.com"),),
    ).id
    ticket = tmp_path / "ticket.json"
    ticket.write_text(
        json.dumps(
            {
                "ticket_ref": {
                    "schema_version": "1",
                    "ar_key": "AR-000000001",
                    "title": "Job reliability",
                    "account_id": ACCOUNT,
                    "account_name": "Acme Corp",
                    "resolution": "validated",
                }
            }
        )
    )
    return (
        "--ticket-ref",
        str(ticket),
        "--shared-root-id",
        shared,
        "--internal-domain",
        "databricks.com",
    )


# --------------------------------------------------------------------------- #
# Scenario runs
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    """One engagement run of a scenario (either mode)."""

    mode: str
    run_id: str
    rf: str | None = None
    run_dir: Path | None = None
    case_root: Path | None = None

    @property
    def drive(self) -> bool:
        return self.mode == "drive_backed"

    def flags(self) -> tuple[str, ...]:
        """The run-selection flags of ``engagement analyze|case|action|play``."""
        if self.drive:
            assert self.rf
            return ("--run-folder", self.rf)
        assert self.run_dir and self.case_root
        return ("--run-dir", str(self.run_dir), "--workspace-root", str(self.case_root))


@dataclass
class Ctx:
    """The fixtures a scenario drives."""

    capsys: Any
    store: Any
    sandbox: Any
    seams: Any
    tmp_path: Path
    mode: str


def new_run(
    ctx: Ctx,
    *,
    task: str = "health_check",
    task_name: str = "ws-123",
    route_flags: tuple[str, ...] = (),
) -> Run:
    """Open a run in ``ctx.mode``."""
    if ctx.mode == "drive_backed":
        pre = ok(
            ctx.capsys,
            "preflight",
            "--source-mode",
            "customer_workspace",
            "--task",
            task,
            "--task-name",
            task_name,
            "--account-key",
            ACCOUNT,
            "--account-name",
            "Acme Corp",
        )
        ok(
            ctx.capsys,
            "verify-identity",
            "--run-id",
            pre["run_id"],
            "--profile",
            "acme",
            "--expected-workspace-id",
            WS,
        )
        route = ok(ctx.capsys, "route", "--run-id", pre["run_id"], *route_flags)
        return Run(ctx.mode, pre["run_id"], rf=route["run_folder_id"])
    pre = ok(
        ctx.capsys,
        "preflight",
        "--source-mode",
        "internal_only",
        "--task",
        task,
        "--task-name",
        task_name,
        "--account-key",
        ACCOUNT,
        "--account-name",
        "Acme Corp",
        "--storage",
        "local",
        "--reports-root",
        str(ctx.tmp_path / "reports"),
        "--internal-workspace-id",
        WS,
    )
    assert pre["storage_decision"] == "internal_only_local"
    run_dir = Path(pre["local_run_dir"])
    ok(ctx.capsys, "route", "--run-dir", str(run_dir))
    return Run(
        ctx.mode, pre["run_id"], run_dir=run_dir, case_root=Path(pre["case_root"])
    )


def write_inputs(
    ctx: Ctx, run: Run, *, facts: dict[str, Any] | None, review: dict[str, Any]
) -> None:
    """The discovery facts and the review findings manifest (host-captured inputs)."""
    files: dict[str, Any] = {MANIFEST: review}
    if facts is not None:
        files[FACTS] = facts
    if run.drive:
        assert run.rf
        sink_put(ctx.store, run.rf, files)
        return
    assert run.run_dir
    for rel, data in files.items():
        path = run.run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))


def verify_slice(
    ctx: Ctx,
    run: Run,
    window: tuple[str, str],
    rows: list[dict[str, Any]],
    *,
    suffix: str,
    mirror: bool = False,
    limit_reached: bool = False,
    template: str = "vt-job-run-states",
) -> str:
    """``verify run vt-job-run-states`` for job 42; returns the run-relative JSON path."""
    ctx.seams.sql = {
        "columns": list(_j42.RUN_COLUMNS),
        "rows": [dict(r) for r in rows],
        "limit_reached": limit_reached,
    }
    source = (
        ("--internal-workspace-id", WS)
        if mirror or not run.drive
        else ("--ws", WS, "--warehouse-id", "wh-1")
    )
    argv = [
        "verify",
        "run",
        template,
        *source,
        "--start",
        window[0],
        "--end",
        window[1],
        "--job-ids",
        _j42.JOB,
        "--limit",
        "20000",
        "--suffix",
        suffix,
    ]
    if run.drive:
        assert run.rf
        argv += ["--run-folder", run.rf]
    else:
        assert run.run_dir
        argv += ["--out", str(run.run_dir / VERIFY_DIR)]
    before = ctx.sandbox.snapshot()
    code, _env, raw = helper(ctx.capsys, *argv)
    assert code == 0, raw
    if run.drive:
        clean(ctx.sandbox, before, raw)
    return f"{VERIFY_DIR}/{template}-{suffix}.json"


def analyze(
    ctx: Ctx,
    run: Run,
    interval: tuple[str, str],
    *,
    verify: tuple[str, ...] = (),
    facts: bool = True,
) -> dict[str, Any]:
    """``engagement analyze`` (exit 0 required); returns the summary ``data``."""
    argv: list[str] = ["analyze", *run.flags(), "--manifest", MANIFEST]
    if facts:
        argv += ["--facts", FACTS]
    for rel in verify:
        argv += ["--verify", rel]
    argv += ["--interval-start", interval[0], "--interval-end", interval[1]]
    return engagement_ok(ctx, run, *argv)


def engagement_ok(ctx: Ctx, run: Run, *argv: str) -> dict[str, Any]:
    """``engagement <argv>`` exit 0; Drive runs also pass :func:`clean`."""
    before = ctx.sandbox.snapshot()
    code, env, raw = eng(ctx.capsys, *argv)
    assert code == 0, raw
    if run.drive:
        clean(ctx.sandbox, before, raw)
    assert env["ok"] is True
    return env["data"]


def commit(ctx: Ctx, run: Run, stage: str = "analysis") -> None:
    """Commit a Drive run's stage (internal-only local runs need no commit)."""
    if run.drive:
        assert run.rf
        engagement_ok(ctx, run, "commit", "--run-folder", run.rf, "--stage", stage)


def read_json(ctx: Ctx, run: Run, rel: str) -> Any:
    """A run artifact (Drive sink or local run dir)."""
    if run.drive:
        assert run.rf
        return json.loads(run_sink(ctx.store, run.rf).get_bytes(rel))
    assert run.run_dir
    return json.loads((run.run_dir / rel).read_text())


def records(ctx: Ctx, run: Run) -> SimpleNamespace:
    """The §B record sets a run wrote (``analysis/*.json``) as dicts."""
    out = SimpleNamespace()
    for name in (
        "observations",
        "findings",
        "health",
        "plays",
        "changes",
        "cases",
        "actions",
    ):
        setattr(out, name, read_json(ctx, run, f"analysis/{name}.json"))
    out.baselines = read_json(ctx, run, "analysis/baseline-selection.json")
    return out


def finding(recs: SimpleNamespace, fid: str) -> dict[str, Any]:
    matches = [f for f in recs.findings if f["finding_id"] == fid]
    assert len(matches) == 1, [f["finding_id"] for f in recs.findings]
    return matches[0]


def family(recs: SimpleNamespace, name: str) -> dict[str, Any]:
    return next(f for f in recs.health["families"] if f["family"] == name)


def job_obs(
    recs: SimpleNamespace, metric: str, *, entity_id: str = _j42.JOB
) -> dict[str, Any]:
    matches = [
        o
        for o in recs.observations
        if o["entity_kind"] == "job"
        and o["entity_id"] == entity_id
        and o["metric"] == metric
    ]
    assert len(matches) == 1, matches
    return matches[0]


def ws_obs(recs: SimpleNamespace, metric: str) -> dict[str, Any]:
    matches = [
        o
        for o in recs.observations
        if o["entity_kind"] == "workspace" and o["metric"] == metric
    ]
    assert len(matches) == 1, matches
    return matches[0]


# --------------------------------------------------------------------------- #
# The J-42 runs
# --------------------------------------------------------------------------- #
def baseline_run(ctx: Ctx) -> Run:
    """Baseline (08-09..09-07): job 42 at 1/100, committed."""
    run = new_run(ctx)
    write_inputs(ctx, run, facts=_j42.baseline_facts(), review=_j42.review_manifest())
    rel = verify_slice(ctx, run, _j42.BASELINE, _j42.baseline_rows(), suffix="base")
    analyze(ctx, run, _j42.BASELINE, verify=(rel,))
    commit(ctx, run)
    return run


def current_run(
    ctx: Ctx,
    *,
    mirror_copy: list[dict[str, Any]] | None = None,
    facts: dict[str, Any] | None = None,
    commit_it: bool = True,
    **run_kw: Any,
) -> Run:
    """Current (09-08..10-07): s1 + s2 slices, job 42 at 8/100."""
    run = new_run(ctx, **run_kw)
    write_inputs(
        ctx, run, facts=facts or _j42.current_facts(), review=_j42.review_manifest()
    )
    rels = [
        verify_slice(ctx, run, _j42.S1, _j42.s1_rows(), suffix="s1"),
        verify_slice(ctx, run, _j42.S2, _j42.s2_rows(), suffix="s2"),
    ]
    if mirror_copy is not None:
        rels.append(
            verify_slice(
                ctx, run, _j42.S2, mirror_copy, suffix="s2-mirror", mirror=True
            )
        )
    analyze(ctx, run, _j42.CURRENT, verify=tuple(rels))
    if commit_it:
        commit(ctx, run)
    return run


def recovery_run(ctx: Ctx, *, measured: bool = True, **run_kw: Any) -> Run:
    """Next run (10-08..10-08): job 42 at 1/100, or no per-job evidence at all."""
    run = new_run(ctx, **run_kw)
    write_inputs(
        ctx,
        run,
        facts=_j42.recovery_facts(per_job=measured),
        review=_j42.review_manifest(),
    )
    rels: tuple[str, ...] = ()
    if measured:
        rels = (
            verify_slice(ctx, run, _j42.RECOVERY, _j42.recovery_rows(), suffix="next"),
        )
    analyze(ctx, run, _j42.RECOVERY, verify=rels)
    commit(ctx, run)
    return run


def fake_run_output(monkeypatch: pytest.MonkeyPatch, *, run_id: int, trace: str) -> Any:
    """An autospec client answering ``job run-output`` for one failed J-42 run."""
    from databricks.sdk.service.jobs import (
        Run as SdkRun,
    )
    from databricks.sdk.service.jobs import (
        RunLifeCycleState,
        RunOutput,
        RunResultState,
        RunState,
        RunTask,
    )

    failed = RunState(
        life_cycle_state=RunLifeCycleState.TERMINATED,
        result_state=RunResultState.FAILED,
        state_message="failed",
    )
    w = autospec_client("jobs")
    w.jobs.get_run.return_value = SdkRun(
        run_id=run_id,
        job_id=42,
        state=failed,
        tasks=[RunTask(task_key="ingest", run_id=run_id + 1, state=failed)],
    )
    w.jobs.get_run_output.return_value = RunOutput(
        error="task failed",
        error_trace=trace,
        logs="driver log\n",
        metadata=SdkRun(run_id=run_id + 1, state=failed),
    )
    monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: w)
    return w


def stdin(monkeypatch: pytest.MonkeyPatch, data: str) -> None:
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(data.encode())))
