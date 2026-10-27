"""Shared helpers for the phase-4 exit tests (spec §H).

Copied from the phase-3 harness pattern (``engagement_phase3/_support.py``); this
module never imports from ``engagement_phase3``.

Every CLI is driven in-process through its ``main(argv)``. Setup runs inside the
test bodies (never in fixtures), so a missing phase-4 module, verb or key surfaces
as an ``ImportError`` / ``AttributeError`` / assertion, never as a fixture error.
Phase-4 symbols (``starboard_core.engagement.profiles``, ``HelperRun.records_root``,
``publication.allowed_audiences``) are imported inside the test functions.

A scenario run (:class:`Run`) is one of the spec §H ``MODE`` values:

* ``public_local``: overlay off, ``customer_workspace`` with LOCAL storage;
  preflight -> ``verify-identity --run-dir`` -> ``route --run-dir`` under
  ``tmp_path/reports``; no Drive and no Salesforce call;
* ``internal_local``: an internal-only ``--storage local`` run (``LocalDirSink``);
* ``drive_backed``: overlay on, ``customer_workspace`` (or ``internal_only`` ->
  drive_default) against the in-memory Drive fake;
* ``hybrid_drive``: overlay on, ``--source-mode hybrid`` (drive_required).

On the Drive modes every CLI call is checked with :func:`clean` (empty sandbox
diff, one bounded JSON line).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
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

from . import _fixtures

MODES = ("public_local", "internal_local", "drive_backed", "hybrid_drive")
DRIVE_MODES = frozenset({"drive_backed", "hybrid_drive"})
LOCAL_MODES = frozenset({"public_local", "internal_local"})
STDOUT_BUDGET = 24_000
HOST = "https://acme.cloud.databricks.com"
ACCOUNT = _fixtures.ACCOUNT
WS = _fixtures.WS
#: A synthetic operator identity; built by concatenation so no literal email exists.
OPERATOR_EMAIL = "pat.operator" + "@" + "acme.example"
USER_ME = {
    "id": "7001",
    "userName": OPERATOR_EMAIL,
    "emails": [{"value": OPERATOR_EMAIL, "primary": True}],
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
}
FACTS = "discovery/facts.json"
DISCOVERY = "discovery/discovery.json"
MANIFEST = "findings-manifest.json"
VERIFY_DIR = "analysis/verify"
HEALTH_READ = "deliverables/health-read.md"
CASE_REPORT = "deliverables/case-report.md"
QUESTION = "Why did job 42 start failing after 2026-09-22?"
#: The D4-14 gap line of a focused report whose customer leg was not acquired.
NO_CUSTOMER_GAP = "- customer workspace: not acquired (no customer profile)"
#: The action-plan-only checklist items a focused profile skips (spec §B2).
ACTION_PLAN_ONLY = frozenset({"5", "6", "7", "8", "9", "10", "11", "14"})
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+(?:@|%40|＠)[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: E14: test node id -> email-shaped strings in the records an E1-E7 test wrote
#: (filled by the ``_email_collector`` fixture; read by ``test_e14_gates``).
EMAIL_SCAN: dict[str, list[str]] = {}


# --------------------------------------------------------------------------- #
# Fakes (the phase-2/3 shapes)
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
    """An autospec ``WorkspaceClient`` whose named sub-APIs are autospecced too."""
    w = create_autospec(WorkspaceClient, instance=True)
    for name in apis:
        api_type = typing.get_type_hints(getattr(WorkspaceClient, name).fget)["return"]
        setattr(w, name, create_autospec(api_type, instance=True))
    return w


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


def error_text(env: dict[str, Any], raw: str = "") -> str:
    """Every error string of an envelope (plus the raw stdout) as one text."""
    return json.dumps(env.get("errors") or env.get("error") or "") + raw


def clean(sandbox: Any, before: dict, raw: str) -> dict[str, Any]:
    """Covered-run invariants: empty sandbox diff, one compact JSON line <= 24 000 B."""
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert len(raw.encode("utf-8")) <= STDOUT_BUDGET
    assert raw.count("\n") == 1, raw[:400]
    return json.loads(raw)


def all_warnings(doc: Any) -> list[str]:
    """Every string under any ``warnings`` key of ``doc`` (recursively)."""
    out: list[str] = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "warnings" and isinstance(v, list):
                out += [str(w) for w in v]
            else:
                out += all_warnings(v)
    elif isinstance(doc, list):
        for v in doc:
            out += all_warnings(v)
    return out


def item_id(entry: Any) -> str:
    """The stable check id of a ``run check`` entry (``"3:discovery…"`` -> ``"3"``)."""
    text = entry["item"] if isinstance(entry, dict) else str(entry)
    return text.split(":", 1)[0]


def ids(entries: Any) -> set[str]:
    return {item_id(e) for e in entries or ()}


def failed_ids(data: dict[str, Any]) -> set[str]:
    return ids(data.get("failed"))


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


def drive_tree(store: Any, rf: str) -> dict[str, bytes]:
    sink = run_sink(store, rf)
    return {rel: sink.get_bytes(rel) for rel in sink.list("")}


def ticket_ref(
    *,
    input_token: str = "ASQ-000000001",
    ar_key: str = "AR-000000001",
    title: str = "Job reliability",
    resolution: str = "validated",
    reason: str = "single record, account matches",
    **over: Any,
) -> dict[str, Any]:
    """A synthetic ``TicketRef v1`` (the phase-1 overlay validate output shape)."""
    return {
        "schema_version": "1",
        "input_token": input_token,
        "ar_key": ar_key,
        "record_id": "a0X000000000001",
        "object_name": "ApprovalRequest__c",
        "title": title,
        "account_id": ACCOUNT,
        "account_name": "Acme Corp",
        "status_value": "Open",
        "looked_up_at": "2026-10-08T09:00:00+00:00",
        "resolution": resolution,
        "reason": reason,
        **over,
    }


def shared_root(store: Any) -> str:
    """The shared ``ASQs`` Drive (created once per store)."""
    cached = getattr(store, "_e4_shared_root", None)
    if cached:
        return str(cached)
    root = str(
        store.add_shared_drive(
            "asqs-root",
            "ASQs",
            drive_id="d1",
            grants=(Grant("group", "fileOrganizer", "databricks.com"),),
        ).id
    )
    store._e4_shared_root = root
    return root


def ticket_flags(
    store: Any, tmp_path: Path, ref: dict[str, Any] | None = None, *, root: str = ""
) -> tuple[str, ...]:
    """Route flags for a ticket run (the phase-2 exit-7 shape)."""
    root = root or shared_root(store)
    n = len(list(tmp_path.glob("ticket-*.json")))
    path = tmp_path / f"ticket-{n}.json"
    path.write_text(json.dumps({"ticket_ref": ref or ticket_ref()}))
    return (
        "--ticket-ref",
        str(path),
        "--shared-root-id",
        root,
        "--internal-domain",
        "databricks.com",
    )


# --------------------------------------------------------------------------- #
# Scenario runs
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    """One engagement run of a scenario (any mode)."""

    mode: str
    run_id: str
    source_mode: str
    rf: str | None = None
    run_dir: Path | None = None
    case_root: Path | None = None

    @property
    def drive(self) -> bool:
        return self.mode in DRIVE_MODES

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
    monkeypatch: Any = None

    @property
    def reports(self) -> Path:
        return self.tmp_path / "reports"


def _default_source(mode: str) -> str:
    return {
        "public_local": "customer_workspace",
        "internal_local": "internal_only",
        "drive_backed": "customer_workspace",
        "hybrid_drive": "hybrid",
    }[mode]


def preflight_argv(
    ctx: Ctx,
    *,
    task: str,
    task_name: str,
    source_mode: str,
    internal_scope: str | None = None,
) -> list[str]:
    """``engagement preflight`` argv for ``ctx.mode``.

    D4-15: an ``internal_only`` run names its one workspace at preflight
    (``--internal-workspace-id``; ``internal_scope``), which ``route`` copies into
    ``authorized_scope`` (``basis: declared``). A customer leg is scoped by
    ``verify-identity`` instead.
    """
    argv = [
        "preflight",
        "--source-mode",
        source_mode,
        "--task",
        task,
        "--task-name",
        task_name,
        "--account-key",
        ACCOUNT,
        "--account-name",
        "Acme Corp",
    ]
    if internal_scope is not None:
        argv += ["--internal-workspace-id", internal_scope]
    if ctx.mode == "internal_local":
        argv += ["--storage", "local", "--reports-root", str(ctx.reports)]
    elif ctx.mode == "public_local":
        argv += ["--reports-root", str(ctx.reports)]
    return argv


def new_run(
    ctx: Ctx,
    *,
    task: str = "health_check",
    task_name: str = "ws-123",
    route_flags: tuple[str, ...] = (),
    source_mode: str | None = None,
    internal_scope: str | None = WS,
) -> Run:
    """Open and route a run in ``ctx.mode`` (``source_mode`` overrides the default).

    An ``internal_only`` run passes ``--internal-workspace-id internal_scope`` at
    preflight (D4-15; every skill does); ``internal_scope=None`` omits it.
    """
    source = source_mode or _default_source(ctx.mode)
    pre = ok(
        ctx.capsys,
        *preflight_argv(
            ctx,
            task=task,
            task_name=task_name,
            source_mode=source,
            internal_scope=internal_scope if source == "internal_only" else None,
        ),
    )
    if ctx.mode in DRIVE_MODES:
        if source != "internal_only":
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
        return Run(ctx.mode, pre["run_id"], source, rf=route["run_folder_id"])
    if ctx.mode == "internal_local":
        assert pre["storage_decision"] == "internal_only_local"
    else:
        assert pre["destination"] == "local" and pre["covered"] is False
    run_dir = Path(pre["local_run_dir"])
    if source != "internal_only":
        ok(
            ctx.capsys,
            "verify-identity",
            "--run-dir",
            str(run_dir),
            "--profile",
            "acme",
            "--expected-workspace-id",
            WS,
        )
    ok(ctx.capsys, "route", "--run-dir", str(run_dir), *route_flags)
    return Run(
        ctx.mode,
        pre["run_id"],
        source,
        run_dir=run_dir,
        case_root=Path(pre["case_root"]),
    )


def write(ctx: Ctx, run: Run, files: dict[str, Any]) -> None:
    """Host-captured inputs (fixture setup; the run sink on Drive, files locally)."""
    if run.drive:
        assert run.rf
        sink_put(ctx.store, run.rf, files)
        return
    assert run.run_dir
    for rel, data in files.items():
        path = run.run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data))


def write_inputs(
    ctx: Ctx, run: Run, *, facts: dict[str, Any] | None, review: dict[str, Any]
) -> None:
    """The discovery facts (+ its envelope, item 2) and the review findings manifest."""
    files: dict[str, Any] = {MANIFEST: review}
    if facts is not None:
        files[FACTS] = facts
        files[DISCOVERY] = {"data": {"facts": facts}}
    write(ctx, run, files)


def host_put(ctx: Ctx, run: Run, rel: str, text: str) -> dict[str, Any]:
    """A host-written artifact: ``engagement put`` on Drive, a plain file locally."""
    if not run.drive:
        write(ctx, run, {rel: text})
        return {"path": rel}
    assert run.rf and ctx.monkeypatch is not None
    stdin(ctx.monkeypatch, text)
    return engagement_ok(ctx, run, "put", "--run-folder", run.rf, "--path", rel)


def readme(
    ctx: Ctx,
    run: Run,
    *,
    delivery: str = "- deliverables/health-read.md",
    recur: str = "baseline — first run.",
) -> None:
    """A README with the item-1 ``## Delivery`` and ``## Recur`` sections."""
    text = f"# Run {run.run_id}\n\n## Delivery\n\n{delivery}\n\n## Recur\n\n{recur}\n"
    host_put(ctx, run, "README.md", text)


def verify_slice(
    ctx: Ctx,
    run: Run,
    window: tuple[str, str],
    rows: list[dict[str, Any]],
    *,
    suffix: str,
    mirror: bool | None = None,
    limit_reached: bool = False,
    template: str = "vt-job-run-states",
) -> str:
    """``verify run vt-job-run-states`` for job 42; returns the run-relative JSON path.

    ``mirror`` defaults to the run's source: internal-only runs read the mirror
    (``--internal-workspace-id``); customer and hybrid runs read the workspace.
    """
    if mirror is None:
        mirror = run.source_mode == "internal_only"
    ctx.seams.sql = {
        "columns": list(_fixtures.RUN_COLUMNS),
        "rows": [dict(r) for r in rows],
        "limit_reached": limit_reached,
    }
    source = (
        ("--internal-workspace-id", WS)
        if mirror
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
        _fixtures.JOB,
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
    """Commit a Drive run's stage (local runs need no commit)."""
    if run.drive:
        assert run.rf
        engagement_ok(ctx, run, "commit", "--run-folder", run.rf, "--stage", stage)


def run_check(ctx: Ctx, run: Run, *extra: str) -> tuple[int, dict[str, Any], str]:
    """``run check`` (Drive ``--run-folder`` or the local run dir); ``(exit, data, raw)``."""
    target = ("--run-folder", run.rf) if run.drive else (str(run.run_dir),)
    before = ctx.sandbox.snapshot()
    code, env, raw = helper(ctx.capsys, "run", "check", *target, *extra)  # type: ignore[arg-type]
    if run.drive:
        assert sandbox_diff(before, ctx.sandbox.snapshot()) == []
    return code, env.get("data") or {}, raw


def run_recur(
    ctx: Ctx,
    run: Run,
    *extra: str,
    workspace_root: Path | None = None,
    baseline: bool = False,
) -> tuple[int, dict[str, Any], str]:
    """``run recur`` (Drive ``--run-folder``; local ``<run-dir> --workspace-root``)."""
    if run.drive:
        assert run.rf
        target: tuple[str, ...] = ("--run-folder", run.rf)
    else:
        root = workspace_root or run.case_root
        target = (str(run.run_dir), "--workspace-root", str(root))
    argv = ["run", "recur", *target, *extra, *(("--baseline",) if baseline else ())]
    before = ctx.sandbox.snapshot()
    code, env, raw = helper(ctx.capsys, *argv)
    if run.drive:
        assert sandbox_diff(before, ctx.sandbox.snapshot()) == []
    return code, env.get("data") or {}, raw


def read_json(ctx: Ctx, run: Run, rel: str) -> Any:
    """A run artifact (Drive sink or local run dir); a missing one is an assertion."""
    assert has(ctx, run, rel), f"{rel} was not written"
    if run.drive:
        assert run.rf
        return json.loads(run_sink(ctx.store, run.rf).get_bytes(rel))
    assert run.run_dir
    return json.loads((run.run_dir / rel).read_text())


def has(ctx: Ctx, run: Run, rel: str) -> bool:
    if run.drive:
        assert run.rf
        return rel in run_sink(ctx.store, run.rf).list("")
    assert run.run_dir
    return (run.run_dir / rel).is_file()


def records(ctx: Ctx, run: Run) -> SimpleNamespace:
    """The record sets a run wrote (``analysis/*.json``) as dicts."""
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


# --------------------------------------------------------------------------- #
# Host-written bodies
# --------------------------------------------------------------------------- #
def health_body(health: dict[str, Any], *, omit: str | None = None) -> str:
    """A ``deliverables/health-read.md`` that passes the ``health_read`` body rules.

    ``omit`` drops that unknown family from ``Unknowns`` (the falsifying body).
    """
    lines = ["# Health read", "", f"Verdict: {health.get('verdict')}", ""]
    if health.get("verdict") == "insufficient_evidence":
        lines += ["Insufficient evidence", ""]
    lines += [
        "Jobs spend: 600 DBU, about $330 (list-price DBU estimate).",
        "",
        "## Unknowns",
        "",
    ]
    unknown = [
        f["family"]
        for f in health.get("families") or ()
        if f.get("assessment") == "unknown" and f["family"] != omit
    ]
    lines += [f"- {name}: unknown" for name in unknown] or ["- none"]
    return "\n".join(lines) + "\n"


def case_report(
    case_ids: list[str],
    *,
    action_id: str | None = None,
    gaps: tuple[str, ...] = (),
    unknowns: bool = True,
) -> str:
    """A ``deliverables/case-report.md`` (Symptom / Evidence / Cause / Next step / Unknowns)."""
    lines = ["# Case report", ""]
    for cid in case_ids:
        lines += [
            f"## Case {cid}",
            "",
            "### Symptom",
            "",
            "Job 42 failure rate rose from 1% to 8% after 2026-09-22.",
            "",
            "### Evidence",
            "",
            "- analysis/verify/vt-job-run-states-s2.json",
            "",
            "### Cause",
            "",
            "cause_confidence: unassessed",
            "",
            "### Next step",
            "",
            f"- {action_id or 'none'}",
            "",
        ]
    if unknowns:
        lines += ["## Unknowns", "", *(gaps or ("- none",))]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# The J-42 runs
# --------------------------------------------------------------------------- #
def baseline_run(ctx: Ctx, **run_kw: Any) -> Run:
    """Baseline (08-09..09-07): job 42 at 1/100, committed."""
    run = new_run(ctx, **run_kw)
    write_inputs(
        ctx, run, facts=_fixtures.baseline_facts(), review=_fixtures.review_manifest()
    )
    rel = verify_slice(
        ctx, run, _fixtures.BASELINE, _fixtures.baseline_rows(), suffix="base"
    )
    analyze(ctx, run, _fixtures.BASELINE, verify=(rel,))
    commit(ctx, run)
    return run


def current_run(ctx: Ctx, *, commit_it: bool = True, **run_kw: Any) -> Run:
    """Current (09-08..10-07): s1 + s2 slices, job 42 at 8/100."""
    run = new_run(ctx, **run_kw)
    write_inputs(
        ctx, run, facts=_fixtures.current_facts(), review=_fixtures.review_manifest()
    )
    rels = [
        verify_slice(ctx, run, _fixtures.S1, _fixtures.s1_rows(), suffix="s1"),
        verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2"),
    ]
    analyze(ctx, run, _fixtures.CURRENT, verify=tuple(rels))
    if commit_it:
        commit(ctx, run)
    return run


def recovery_run(ctx: Ctx, *, measured: bool = True, **run_kw: Any) -> Run:
    """Next run (10-08..10-08): job 42 at 1/100, or no per-job evidence at all."""
    run = new_run(ctx, **run_kw)
    write_inputs(
        ctx,
        run,
        facts=_fixtures.recovery_facts(per_job=measured),
        review=_fixtures.review_manifest(),
    )
    rels: tuple[str, ...] = ()
    if measured:
        rels = (
            verify_slice(
                ctx, run, _fixtures.RECOVERY, _fixtures.recovery_rows(), suffix="next"
            ),
        )
    analyze(ctx, run, _fixtures.RECOVERY, verify=rels)
    commit(ctx, run)
    return run


def job_obs(
    recs: SimpleNamespace, metric: str, *, entity_id: str = _fixtures.JOB
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


def stdin(monkeypatch: pytest.MonkeyPatch, data: str | bytes) -> None:
    raw = data.encode() if isinstance(data, str) else data
    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(raw)))


def local_files(root: Path) -> list[Path]:
    """Every file under ``root`` (sorted)."""
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


def emails_in(obj: Any) -> list[str]:
    """Email-shaped strings anywhere in ``obj`` (JSON-serialised)."""
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return EMAIL_RE.findall(text)


# --------------------------------------------------------------------------- #
# Publication (Drive runs)
# --------------------------------------------------------------------------- #
def record_evidence(
    ctx: Ctx, run: Run, rel: str, source_kind: str = "customer_workspace"
) -> str:
    """Fixture setup: record one evidence ref in the run's index; returns its ID."""
    from starboard_core.engagement.records import EvidenceRef, StorageRef, evidence_id
    from starboard_core.engagement.sink import sink_evidence

    assert run.rf
    audience = (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )
    ref = EvidenceRef(
        evidence_id=evidence_id(run.run_id, rel, "0" * 32),
        run_id=run.run_id,
        storage_ref=StorageRef(
            path=rel,
            object_id="obj",
            revision="r1",
            md5="0" * 32,
            size=1,
            mime_type="application/json",
        ),
        source_kind=source_kind,
        scope_workspace_ids=(WS,),
        producer="discovery",
        row_count=1,
        truncated=False,
        acquired_at="2026-10-08T09:00:00+00:00",
        audience_class=audience,
        method_version="v1",
    )
    sink_evidence(run_sink(ctx.store, run.rf), [ref])
    return ref.evidence_id


def report(
    ctx: Ctx, run: Run, report_id: str, rel: str, audience: str, *extra: str
) -> tuple[int, dict[str, Any], str]:
    """``engagement report`` on a Drive run -> ``(exit, envelope, raw)``."""
    assert run.rf
    return eng(
        ctx.capsys,
        "report",
        "--run-folder",
        run.rf,
        "--report-id",
        report_id,
        "--audience",
        audience,
        "--path",
        rel,
        *extra,
    )


def revision_flags(run: Run, report_id: str, revision: int) -> tuple[str, ...]:
    assert run.rf
    return (
        "--run-folder",
        run.rf,
        "--report-id",
        report_id,
        "--revision",
        str(revision),
    )


def destination(store: Any, name: str = "Delivered") -> str:
    """An internal Drive folder to deliver into."""
    return str(store.create_folder(store.root_folder_id(), name, {}).id)


def md5(data: str | bytes) -> str:
    raw = data.encode() if isinstance(data, str) else data
    return hashlib.md5(raw).hexdigest()  # noqa: S324 - Drive's content checksum


def run_record(store: Any, rf: str, cls: Any, record_id: str) -> Any:
    """An approval / receipt record of the run, by its ID."""
    sink = run_sink(store, rf)
    for rel in sink.list(""):
        if record_id in rel:
            return cls.from_dict(json.loads(sink.get_bytes(rel)))
    raise AssertionError(f"{record_id} not found under {rf}")
