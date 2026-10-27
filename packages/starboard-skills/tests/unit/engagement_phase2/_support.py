"""Shared helpers for the phase-2 exit tests (spec P2-G14).

Every CLI is driven in-process through its ``main(argv)``:

* ``starboard-helper`` (engagement, verify, notebook, charts, run)
* ``python -m starboard_x.discovery``
* ``python -m starboard_x.review``

Storage is the in-memory Drive fake, wired through the
``starboard.engagement_storage`` entry point (see ``conftest.py``).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.commit import latest_manifest, read_descriptor
from starboard_core.engagement.records import (
    EvidenceRef,
    Observation,
    StorageRef,
    evidence_id,
    observation_id,
)
from starboard_core.engagement.sink import DriveRunSink, reserved_record
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_core.ports.engagement_storage import Grant

STDOUT_BUDGET = 24_000
HOST = "https://acme.cloud.databricks.com"
ACCOUNT = "001ABC"
WS = "123"
USER_ME = {
    "id": "7001",
    "userName": "pat.operator@acme.example",
    "emails": [{"value": "pat.operator@acme.example", "primary": True}],
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
}
INTERNAL = (Grant("user", "owner", "databricks.com"),)
WIDE = (Grant("user", "owner", "databricks.com"), Grant("anyone", "reader"))

PREFLIGHT = (
    "preflight",
    "--source-mode",
    "customer_workspace",
    "--task",
    "health_check",
    "--task-name",
    "ws-123",
    "--account-key",
    ACCOUNT,
    "--account-name",
    "Acme Corp",
)

REVIEW_ROWS = {
    "W-W02": [
        {"warehouse_id": "wh-idle", "idle_running_hours": 12.0, "auto_stop_waste_pct": 80.0}
    ],
    "C-Q02": [{"statement_id": "stmt-prune", "pruning_ratio": 0.02, "read_partitions": 500}],
}
CHART_ROWS = [{"billing_origin_product": "JOBS", "total_dbus": 10}]


# --------------------------------------------------------------------------- #
# Fakes
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


def _qr(query_id: str, domain: str, rows: list[dict[str, Any]] | None, **kw: Any) -> Any:
    return SimpleNamespace(
        query_id=query_id,
        domain=domain,
        data=None if rows is None else Df(rows),
        error=kw.pop("error", None),
        row_count=0 if rows is None else len(rows),
        succeeded=rows is not None,
        skipped=False,
        result_limit=None,
        lookback_days=30,
        execution_time_ms=12.34,
        attempts=1,
        attempt_elapsed_ms=[12.34],
    )


def fake_discovery_result() -> Any:
    """Two packs, three queries (one failed) - the discovery writer fixture shape."""
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
                        "window_start": "2026-09-01",
                        "window_end": "2026-09-30",
                        "usage_quantity": Decimal("600.5"),
                    }
                ],
            ),
            _qr("F-02", "billing", None, error="PARSE_SYNTAX_ERROR"),
        ],
    )
    gov = SimpleNamespace(
        pack_id="Governance (UC)",
        domain="governance",
        results=[
            _qr(
                "G-01",
                "governance",
                [{"catalog": "main", "tables": 3}, {"catalog": "dev", "tables": 1}],
            )
        ],
    )
    return SimpleNamespace(
        trace_id="trace-1",
        elapsed_ms=1.0,
        errors=["F-02: PARSE_SYNTAX_ERROR"],
        audit_result=SimpleNamespace(succeeded=True),
        pack_results=[billing, gov],
        domain_analyses=[],
    )


class GatherEngine:
    """``starboard --discover`` engine fake: one billing pack (one ok, one failed query).

    ``window`` (``{"start", "end"}``) stamps F-01 with a measured window; ``None``
    leaves the facts window to the trailing default."""

    window: dict[str, str] | None = None

    def __init__(self, sql_executor: Any, llm_client: Any, config: Any, **_kw: Any) -> None:
        self.config = config

    async def run(self, on_progress: Any = None) -> Any:
        import polars as pl
        from starboard.discovery.engine import EngineResult
        from starboard_core.domain.models.discovery.query import PackResult, QueryResult

        row: dict[str, list[Any]] = {
            "workspace_id": [WS], "billing_origin_product": ["JOBS"],
            "usage_unit": ["DBU"], "usage_quantity": [600.5],
        }
        if self.window is not None:
            row["window_start"] = [self.window["start"]]
            row["window_end"] = [self.window["end"]]
        good = QueryResult(
            query_id="F-01", domain="billing", data=pl.DataFrame(row), row_count=1
        )
        bad = QueryResult(query_id="F-02", domain="billing", data=None,
                          error="PARSE_SYNTAX_ERROR")
        pack = PackResult(pack_id="billing", domain="billing", results=(good, bad))
        return EngineResult(trace_id="gather", pack_results=[pack])


class GatherClient:
    """``AsyncDatabricksClient`` fake answering for workspace ``123``."""

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


# --------------------------------------------------------------------------- #
# In-process CLI runners
# --------------------------------------------------------------------------- #
def _last_json(raw: str) -> dict[str, Any]:
    """The envelope: the whole stdout (public pretty JSON) or its last line."""
    for text in (raw, *reversed([ln for ln in raw.splitlines() if ln.strip()])):
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        if isinstance(doc, dict):
            return doc
    return {}


def _call(fn: Any, argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
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

    return _call(main, list(argv), capsys)


def eng(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    """``starboard-helper engagement <argv>``."""
    return helper(capsys, "engagement", *argv)


def ok(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    """``engagement <argv>`` that must exit 0; returns ``data``."""
    code, env, raw = eng(capsys, *argv)
    assert code == 0, raw
    assert env["ok"] is True
    return env["data"]


def discovery(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    from starboard_x.discovery import __main__ as disc

    return _call(disc.main, list(argv), capsys)


def review(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    from starboard_x.review import __main__ as rev

    return _call(rev.main, list(argv), capsys)


def _bytes(data: Any) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data, sort_keys=True).encode("utf-8")


def put(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    rf: str,
    files: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Host-authored artifacts via ``engagement put --run-folder RF --path REL`` (stdin)."""
    import io

    out: dict[str, dict[str, Any]] = {}
    for rel, data in files.items():
        monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(_bytes(data))))
        out[rel] = ok(capsys, "put", "--run-folder", rf, "--path", rel)
    return out


def starboard(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict, str]:
    """``starboard <argv>`` (the experience CLI; the engagement gather step)."""
    from starboard.cli.cli import main as cli_main

    return _call(cli_main.main, list(argv), capsys)


def routed(capsys: pytest.CaptureFixture[str], *route_flags: str) -> tuple[dict, dict]:
    """preflight -> verify-identity -> route; returns ``(preflight, route)`` data."""
    pre = ok(capsys, *PREFLIGHT)
    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
    return pre, ok(capsys, "route", "--run-id", pre["run_id"], *route_flags)


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


def drive_tree(store: Any, rf: str) -> dict[str, bytes]:
    sink = run_sink(store, rf)
    return {rel: sink.get_bytes(rel) for rel in sink.list("")}


def manifest(store: Any, rf: str) -> Any:
    return latest_manifest(store, rf)[0]


def assert_refs_verified(store: Any, rf: str) -> None:
    """Every manifest ref names live content whose md5 matches the ref."""
    import hashlib

    m = manifest(store, rf)
    for ref in m.refs:
        data = b"".join(store.get_stream(ref.object_id))
        assert hashlib.md5(data).hexdigest() == ref.md5, ref.path  # noqa: S324


def sink_put(store: Any, rf: str, files: dict[str, Any]) -> dict[str, StorageRef]:
    """Fixture setup only: write straight through the run sink (no CLI).

    Kernel records go through ``put_record`` (the setup stands in for the kernel
    writer).
    """
    sink = run_sink(store, rf)
    out: dict[str, StorageRef] = {}
    for rel, data in files.items():
        if reserved_record(rel):
            if isinstance(data, str):
                data = data.encode()
            elif not isinstance(data, bytes):
                data = json.dumps(data).encode()
            out[rel] = sink.put_record(rel, data, "application/json")
        elif isinstance(data, bytes):
            out[rel] = sink.put_bytes(rel, data, "application/octet-stream")
        elif isinstance(data, str):
            out[rel] = sink.put_text(rel, data)
        else:
            out[rel] = sink.put_json(rel, data)
    return out


def upload_dir(store: Any, rf: str, root: Path, *, skip: tuple[str, ...] = ()) -> None:
    files = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).as_posix() not in skip
    }
    sink_put(store, rf, files)


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #
def clean(sandbox: Any, before: dict, raw: str) -> dict[str, Any]:
    """Covered-run invariants: empty sandbox diff, one compact JSON line <= 24 000 B."""
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert len(raw.encode("utf-8")) <= STDOUT_BUDGET
    assert raw.count("\n") == 1, raw[:400]
    assert "\n  " not in raw
    return json.loads(raw)


def error_code(env: dict[str, Any]) -> str:
    """The refusal code of a helper (``errors[0].code``) or starboard_x (``error``) envelope."""
    errors = env.get("errors") or []
    if errors and isinstance(errors[0], dict) and errors[0].get("code"):
        return str(errors[0]["code"])
    return str(env.get("error", "")).split(" ", 1)[0].rstrip(":")


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def evidence(run_id: str, path: str, source_kind: str = "customer_workspace") -> EvidenceRef:
    audience = "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    return EvidenceRef(
        evidence_id=evidence_id(run_id, path, "0" * 32),
        run_id=run_id,
        storage_ref=StorageRef(
            path=path, object_id="obj", revision="r1", md5="0" * 32, size=1,
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


def observation(
    run_id: str,
    entity_id: str = "job-1",
    *,
    value: float | None = 1.0,
    start: str = "2026-10-01",
    end: str = "2026-10-31",
    source_kind: str = "customer_workspace",
    state: str = "measured",
    as_of: str = "2026-11-01T00:00:00+00:00",
) -> Observation:
    audience = "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    key = (ACCOUNT, WS, "other", "job", entity_id, "dbus", start, end, "v1")
    measured = state == "measured"
    return Observation(
        observation_id=observation_id(key),
        run_id=run_id,
        account_key=ACCOUNT,
        workspace_id=WS,
        family="other",
        entity_kind="job",
        entity_id=entity_id,
        metric="dbus",
        value=value if measured else None,
        unit="DBU",
        grain="interval",
        method_version="v1",
        interval_start=start,
        interval_end=end,
        as_of=as_of,
        coverage="complete",
        coverage_fraction=None,
        state=state,
        unknown_reason=None if measured else "evidence_lost",
        evidence_ids=(),
        source_kind=source_kind,
        audience_class=audience,
    )
