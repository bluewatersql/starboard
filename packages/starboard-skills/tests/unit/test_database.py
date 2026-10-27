"""Unit tests for FIX C — database instances helper.

All Databricks SDK calls are mocked; no network access required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from starboard_skills.helpers import database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_instance(name: str, uid: str, capacity: str, state: str) -> SimpleNamespace:
    """Return a fake DatabaseInstance-like object."""
    inst = SimpleNamespace(name=name, uid=uid, capacity=capacity, state=state)
    inst.as_dict = lambda: {
        "name": name,
        "uid": uid,
        "capacity": capacity,
        "state": state,
    }
    return inst


# ---------------------------------------------------------------------------
# FIX C tests
# ---------------------------------------------------------------------------

def test_instances_returns_list():
    """cmd_instances returns count and a flat list of instance dicts."""
    fake_instances = [
        _make_instance("prod-db-1", "uid-aaa", "X_SMALL", "RUNNING"),
        _make_instance("dev-db-2", "uid-bbb", "SMALL", "STOPPED"),
    ]
    fake_ws = MagicMock()
    fake_ws.database.list_database_instances.return_value = iter(fake_instances)

    with patch("starboard_skills.helpers.database._client", return_value=fake_ws):
        result = database.cmd_instances(SimpleNamespace())

    assert result["count"] == 2
    assert len(result["instances"]) == 2

    first = result["instances"][0]
    assert first["name"] == "prod-db-1"
    assert first["uid"] == "uid-aaa"
    assert first["capacity"] == "X_SMALL"
    assert first["state"] == "RUNNING"


def test_instances_returns_empty_list_when_none():
    """An empty workspace (no Lakebase instances) returns count=0."""
    fake_ws = MagicMock()
    fake_ws.database.list_database_instances.return_value = iter([])

    with patch("starboard_skills.helpers.database._client", return_value=fake_ws):
        result = database.cmd_instances(SimpleNamespace())

    assert result["count"] == 0
    assert result["instances"] == []


def test_instances_api_error_propagates():
    """SDK exceptions are wrapped as HelperError (not swallowed)."""
    from starboard_skills.helpers.contract import HelperError

    fake_ws = MagicMock()
    fake_ws.database.list_database_instances.side_effect = RuntimeError("not found")

    with patch("starboard_skills.helpers.database._client", return_value=fake_ws), pytest.raises(HelperError):
        database.cmd_instances(SimpleNamespace())


def test_database_registered_in_main():
    """The 'database' domain is registered in the CLI parser."""
    from starboard_skills.helpers.__main__ import build_parser

    parser = build_parser()
    # Parse a known-good invocation — if 'database' is not registered argparse will error.
    # We can't actually call cmd_instances (would hit SDK), so just verify parse succeeds.
    # Use parse_known_args to avoid needing a real warehouse; the subcommand parse is enough.
    ns, _ = parser.parse_known_args(["database", "instances"])
    assert ns.domain == "database"
    assert ns.command == "instances"
