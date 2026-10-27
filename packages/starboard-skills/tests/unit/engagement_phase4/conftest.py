"""Fixtures for the phase-4 exit tests (spec §H).

Copied from the phase-3 exit suite's pattern (``engagement_phase3/conftest.py``);
nothing here imports from ``engagement_phase3``.

* **Sandbox** (autouse): HOME, TMPDIR and cwd point at fresh dirs under
  ``tmp_path``, so ``write_guard.sandbox_snapshot`` before/after proves
  "zero local files" on Drive-backed runs.
* **Storage** (autouse): an ``InMemoryEngagementStorage`` wired through the real
  ``starboard.engagement_storage`` entry-point loader; Drive is never reached.
* **Overlay** (autouse): real detection, forced ON with ``STARBOARD_OVERLAY=1``.
* **Seams** (autouse): the workspace client, discovery engines, the SQL runner
  and the chart renderer are fakes. ``seams.sql`` is the row set the next
  ``verify run`` returns (columns + rows + ``limit_reached``).
* **public**: overlay OFF, no internal package, a Drive entry point that fails
  on any load and a ticket resolver that fails on any call.
* **Email collector** (autouse): after each E1-E7 test, every stored Drive
  object (content and revisions) and every file under ``tmp_path`` is scanned
  for email-shaped strings into ``_support.EMAIL_SCAN`` (E14 asserts it).
* **mode** / **ctx**: spec §H ``MODE`` (``public_local`` | ``internal_local`` |
  ``drive_backed`` | ``hybrid_drive``); ``ctx`` applies ``public`` for
  ``public_local``.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement import overlay, sink
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.write_guard import active
from starboard_skills.helpers import charts_render, contract, engagement
from starboard_skills.helpers import query as helper_query
from starboard_skills.helpers.engagement import _envelope

from ..conftest import Sandbox
from ._support import (
    EMAIL_RE,
    EMAIL_SCAN,
    MODES,
    Ctx,
    FakeEngine,
    FakeWorkspace,
    GatherClient,
    GatherEngine,
    fake_discovery_result,
)


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Any:
    assert not active()
    yield
    assert not active()


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    roots = tuple(tmp_path / name for name in ("home", "cwd", "tmp"))
    for root in roots:
        root.mkdir()
    monkeypatch.setenv("HOME", str(roots[0]))
    monkeypatch.setenv("TMPDIR", str(roots[2]))
    monkeypatch.setattr(tempfile, "tempdir", str(roots[2]))
    monkeypatch.chdir(roots[1])
    for name in (
        "DATABRICKS_HOST",
        "DATABRICKS_TOKEN",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_CONFIG_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    return Sandbox(roots)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any outbound socket connect is a test failure (no Databricks/Drive/CRM)."""

    def deny(self: socket.socket, address: Any) -> None:
        raise AssertionError(f"network call attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)


@pytest.fixture(autouse=True)
def _real_overlay(_public_overlay: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the suite-wide OFF pin: every CLI runs the real ``detect_overlay``."""
    monkeypatch.setattr(contract, "_detect_overlay", lambda: overlay.detect_overlay())
    monkeypatch.setattr(overlay, "_account_home", lambda: None)


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
    """The Drive fake, reachable only through the storage entry point."""
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    entry = SimpleNamespace(
        value="tests.engagement_phase4:InMemory", load=lambda: lambda: s
    )
    monkeypatch.setattr(
        sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
    )
    monkeypatch.delenv(engagement.SHARED_REGISTRY_ENV, raising=False)
    return s


@pytest.fixture(autouse=True)
def covered(monkeypatch: pytest.MonkeyPatch, _real_overlay: None) -> None:
    """Overlay ON (env-forced)."""
    monkeypatch.setenv(overlay.FORCE_ENV, "1")


@pytest.fixture
def drive_calls() -> list[str]:
    """Every attempted Drive / Salesforce reach on a ``public`` install."""
    return []


@pytest.fixture
def public(
    monkeypatch: pytest.MonkeyPatch,
    covered: None,
    store: InMemoryEngagementStorage,
    drive_calls: list[str],
) -> None:
    """A public install: no overlay env, no internal package, no overlay skill.

    The Drive storage entry point and the ticket resolver fail on any use, so a
    public-local run proves it never reaches Drive or Salesforce.
    """
    monkeypatch.delenv(overlay.FORCE_ENV, raising=False)
    real = importlib.util.find_spec

    def find_spec(name: str, *a: Any, **kw: Any) -> Any:
        if name.split(".")[0] == overlay.INTERNAL_PACKAGE:
            return None
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)

    def no_drive() -> Any:
        drive_calls.append("drive storage entry point loaded")
        raise AssertionError("public-local run reached the Drive storage entry point")

    entry = SimpleNamespace(value="tests.engagement_phase4:NoDrive", load=no_drive)
    monkeypatch.setattr(
        sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
    )
    try:
        ticket = importlib.import_module(f"{overlay.INTERNAL_PACKAGE}.ticket")
    except ImportError:
        ticket = None
    if ticket is not None:
        for name in ("main", "validate_ticket", "parse_ticket_tokens", "skip_ticket"):
            if hasattr(ticket, name):

                def deny(*_a: Any, _name: str = name, **_k: Any) -> Any:
                    drive_calls.append(f"ticket.{_name}")
                    raise AssertionError(f"public-local run called ticket.{_name}")

                monkeypatch.setattr(ticket, name, deny)
    assert overlay.detect_overlay().enabled is False


@pytest.fixture(autouse=True)
def seams(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake every external call; ``seams.sql`` feeds the next ``verify run``."""
    from starboard.cli.cli import main as cli_main
    from starboard_x.discovery import __main__ as disc

    holder = SimpleNamespace(
        client=FakeWorkspace(),
        result=fake_discovery_result(),
        sql={"columns": ["a"], "rows": [["1"]], "limit_reached": False},
    )

    def cmd_sql(args: Any) -> dict[str, Any]:
        rows = list(holder.sql["rows"])
        return {
            "columns": list(holder.sql["columns"]),
            "rows": rows,
            "row_count": len(rows),
            "limit_reached": bool(holder.sql.get("limit_reached")),
            "state": "SUCCEEDED",
            "read_only": True,
        }

    monkeypatch.setattr(_envelope, "_make_workspace_client", lambda p, h: holder.client)
    monkeypatch.setattr(disc, "build_engine", lambda _args: FakeEngine(holder.result))
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GatherEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", GatherClient)
    monkeypatch.setattr(
        "starboard.check_connectivity",
        lambda *a, **k: SimpleNamespace(ok=True, kind=None, message="ok"),
    )
    monkeypatch.setattr(helper_query, "cmd_sql", cmd_sql)
    monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
    monkeypatch.setattr(
        charts_render, "_vegalite_to_svg", lambda vl: b"<svg>fake</svg>"
    )
    return holder


_SCANNED_MODULES = re.compile(r"\.test_e0[1-7]_")


def _scan_records(store: InMemoryEngagementStorage, tmp_path: Path) -> list[str]:
    hits: list[str] = []
    for key, entry in list(store._entries.items()):
        blobs = [entry.content, *entry.revisions.values()]
        for blob in blobs:
            if blob:
                text = blob.decode("utf-8", "replace")
                hits += [f"drive:{key}:{m}" for m in EMAIL_RE.findall(text)]
    for path in sorted(p for p in tmp_path.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8", "replace")
        rel = path.relative_to(tmp_path).as_posix()
        hits += [f"local:{rel}:{m}" for m in EMAIL_RE.findall(text)]
    return hits


@pytest.fixture(autouse=True)
def _email_collector(
    request: pytest.FixtureRequest,
    store: InMemoryEngagementStorage,
    tmp_path: Path,
) -> Any:
    """Record E1-E7 email hits for E14; never fails the test it wraps."""
    yield
    if not _SCANNED_MODULES.search(request.node.module.__name__):
        return
    try:
        EMAIL_SCAN[request.node.nodeid] = _scan_records(store, tmp_path)
    except Exception as exc:  # noqa: BLE001 - a scan error must not fail E1-E7
        EMAIL_SCAN[request.node.nodeid] = [f"scan error: {exc!r}"]


@pytest.fixture(params=MODES)
def mode(request: pytest.FixtureRequest) -> str:
    """Spec §H ``MODE`` (override with ``@pytest.mark.parametrize("mode", ...)``)."""
    return str(request.param)


@pytest.fixture
def ctx(
    request: pytest.FixtureRequest,
    mode: str,
    capsys: pytest.CaptureFixture[str],
    store: InMemoryEngagementStorage,
    sandbox: Sandbox,
    seams: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Ctx:
    """The scenario context; ``public_local`` also applies the ``public`` fixture."""
    if mode == "public_local":
        request.getfixturevalue("public")
    return Ctx(capsys, store, sandbox, seams, tmp_path, mode, monkeypatch)
