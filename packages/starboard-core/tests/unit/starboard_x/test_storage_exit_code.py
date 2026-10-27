# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The storage-failure exit code is 7 and collides with no ``starboard_x`` code."""

from __future__ import annotations

import pytest
from starboard_core.engagement.sink import EXIT_STORAGE_FAILURE
from starboard_x import _cli, contract


@pytest.mark.unit
def test_storage_failure_exit_is_7() -> None:
    assert EXIT_STORAGE_FAILURE == 7
    assert _cli.StorageFailureError.exit_code == 7


@pytest.mark.unit
def test_storage_failure_exit_collides_with_no_starboard_x_code() -> None:
    taken = {
        v
        for mod in (contract, _cli)
        for k, v in vars(mod).items()
        if k.startswith("EXIT_") and k != "EXIT_STORAGE_FAILURE" and isinstance(v, int)
    }
    assert EXIT_STORAGE_FAILURE not in taken


@pytest.mark.unit
def test_transient_storage_failure_exits_8_and_is_retryable(capsys) -> None:
    """``STORAGE_TRANSIENT`` is exit 8 + ``retryable`` on the ``starboard_x`` surface."""
    import argparse
    import json

    from starboard_core.engagement.sink import EXIT_STORAGE_TRANSIENT, storage_exit_code
    from starboard_core.ports.engagement_storage import StorageTransientError

    assert EXIT_STORAGE_TRANSIENT == 8
    assert storage_exit_code("STORAGE_TRANSIENT") == 8
    assert storage_exit_code("BLOCKED_ACCESS") == EXIT_STORAGE_FAILURE

    err = _cli.StorageFailureError("STORAGE_TRANSIENT: rate limited", code="STORAGE_TRANSIENT")
    assert (err.exit_code, err.retryable) == (8, True)
    assert _cli.StorageFailureError("NOT_FOUND: gone", code="NOT_FOUND").exit_code == 7

    def func(args: argparse.Namespace) -> None:
        raise StorageTransientError("HTTP 403 rateLimitExceeded")

    parser = _cli.ArgumentParser(prog="x")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("go").set_defaults(func=func)
    with pytest.raises(SystemExit) as info:
        _cli.run(domain="x", parser=parser, argv=["go"])
    assert info.value.code == 8
    env = json.loads(capsys.readouterr().out)
    assert env["errors"] == [
        {"code": "STORAGE_TRANSIENT", "message": env["error"], "retryable": True}
    ]
