"""Fixtures for the phase-2 exit tests (spec P2-G14).

* **Sandbox** (autouse): HOME, TMPDIR and cwd point at fresh dirs under
  ``tmp_path``, so ``write_guard.sandbox_snapshot`` before/after proves
  "zero local files" (control metadata included).
* **Storage** (autouse): an ``InMemoryEngagementStorage`` with fault injection,
  wired through the real ``starboard.engagement_storage`` entry-point loader
  (``sink.load_engagement_storage``); the Drive adapter is never loaded.
* **Overlay**: real detection everywhere (the suite-wide OFF pin is undone).
  ``covered`` (autouse) fakes the overlay with ``STARBOARD_OVERLAY=1``; ``public`` removes the env and hides the internal
  package from ``find_spec`` so detection finds nothing.
* **Seams** (autouse): the workspace client, the discovery engine, the SQL
  runner and the chart renderer are fakes - no network, Drive, Databricks or
  CRM call is made.
"""

from __future__ import annotations

import importlib.util
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement import overlay, sink
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.write_guard import active, default_policy, guarded
from starboard_skills.helpers import charts_render, contract, engagement
from starboard_skills.helpers import query as helper_query
from starboard_skills.helpers.engagement import _envelope

from ..conftest import Sandbox
from ..test_notebook_helper import (
    run_dir,  # noqa: F401  (fixture: notebook backlog + verify pairs)
)
from ._support import (
    FakeEngine,
    FakeWorkspace,
    GatherClient,
    GatherEngine,
    fake_discovery_result,
)


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Any:
    assert not active()
    # The refusal log is process-wide and cleared only when an outermost guard is
    # entered: start each test with an empty one, so a test that never arms the guard
    # does not read an earlier test's refusals from the same worker.
    with guarded(default_policy()):
        pass
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
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_CONFIG_PROFILE",
                 "DATABRICKS_CONFIG_FILE"):
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
    # Only the sandboxed $HOME is scanned for an installed overlay skill.
    monkeypatch.setattr(overlay, "_account_home", lambda: None)


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
    """The Drive fake, reachable only through the storage entry point."""
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    entry = SimpleNamespace(value="tests.engagement_phase2:InMemory", load=lambda: (lambda: s))
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
def public(monkeypatch: pytest.MonkeyPatch, covered: None) -> None:
    """A public install: no overlay env, no internal package, no overlay skill."""
    monkeypatch.delenv(overlay.FORCE_ENV, raising=False)
    real = importlib.util.find_spec

    def find_spec(name: str, *a: Any, **kw: Any) -> Any:
        if name.split(".")[0] == overlay.INTERNAL_PACKAGE:
            return None
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    assert overlay.detect_overlay().enabled is False


@pytest.fixture(autouse=True)
def seams(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Fake every external call: workspace /Me, discovery engines, SQL, chart render."""
    from starboard.cli.cli import main as cli_main
    from starboard_x.discovery import __main__ as disc

    holder = SimpleNamespace(client=FakeWorkspace(), result=fake_discovery_result())
    monkeypatch.setattr(_envelope, "_make_workspace_client", lambda p, h: holder.client)
    monkeypatch.setattr(disc, "build_engine", lambda _args: FakeEngine(holder.result))
    # ``starboard --discover`` (the engagement gather step).
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GatherEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", GatherClient)
    monkeypatch.setattr(
        "starboard.check_connectivity",
        lambda *a, **k: SimpleNamespace(ok=True, kind=None, message="ok"),
    )
    monkeypatch.setattr(
        helper_query,
        "cmd_sql",
        lambda args: {"columns": ["a"], "rows": [["1"]], "row_count": 1,
                      "limit_reached": False, "state": "SUCCEEDED", "read_only": True},
    )
    monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
    monkeypatch.setattr(charts_render, "_vegalite_to_svg", lambda vl: b"<svg>fake</svg>")
    return holder
