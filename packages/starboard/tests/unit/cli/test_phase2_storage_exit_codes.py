# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (F2): storage / integrity / access failures exit non-zero with their code.

``starboard`` (``_exit_refused``) and ``starboard review`` (``_storage_failure``) both
exit the kernel's ``EXIT_STORAGE_FAILURE`` (7), which is ``exit_codes.STORAGE_FAILURE``
(4 is ``AUTH_ERROR`` here and arg-error on the helper surfaces).
Both map an :class:`AccessRecheckError` (``BLOCKED_ACCESS``), an integrity error and
a missing object to the storage code; ``STORAGE_UNAVAILABLE`` stays a refusal (2).
"""

from __future__ import annotations

import argparse
import json

import pytest
from starboard.cli.cli import exit_codes, review_command
from starboard.cli.cli import main as cli_main
from starboard_core.engagement.access import AccessVerdict
from starboard_core.engagement.sink import (
    EXIT_STORAGE_FAILURE,
    AccessRecheckError,
    StorageUnavailableError,
)
from starboard_core.ports.engagement_storage import (
    StorageAuthError,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageTransientError,
)
from starboard_x.contract import EXIT_AUTH

CASES = [
    (AccessRecheckError("F1", AccessVerdict(False, "revoked")), 7, "BLOCKED_ACCESS"),
    (StorageIntegrityError("md5 mismatch"), 7, "STORAGE_INTEGRITY"),
    (StorageNotFoundError("object gone"), 7, "NOT_FOUND"),
    (StorageUnavailableError("no adapter"), 2, "STORAGE_UNAVAILABLE"),
    # Retryable, nothing refused: 8 on every writer surface (the engagement helper's too).
    (StorageTransientError("HTTP 403 rateLimitExceeded"), 8, "STORAGE_TRANSIENT"),
]


@pytest.mark.unit
@pytest.mark.parametrize(("exc", "exit_code", "code"), CASES)
def test_agent_cli_storage_failure_exit_codes(
    exc: Exception, exit_code: int, code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as info:
        cli_main._exit_refused(exc, as_json=True)
    assert info.value.code == exit_code
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert env["error_type"] == code
    assert env["error"].startswith(f"{code}: ")
    assert env.get("retryable", False) is (code == "STORAGE_TRANSIENT")


@pytest.mark.unit
@pytest.mark.parametrize(("exc", "exit_code", "code"), CASES)
def test_review_storage_failure_exit_codes(
    exc: Exception, exit_code: int, code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(json=True, run_folder=None)
    assert review_command._storage_failure(exc, args) == exit_code
    out = capsys.readouterr()
    assert out.err.startswith(f"{code}: ")
    env = json.loads(out.out)
    assert env["error"].startswith(f"{code}: ")
    if exit_code in (7, 8):  # a storage failure carries its machine code
        assert env["errors"] == [
            {"code": code, "message": env["error"], "retryable": code == "STORAGE_TRANSIENT"}
        ]
    else:  # a refusal does not
        assert "errors" not in env


@pytest.mark.unit
def test_agent_cli_storage_failure_code_does_not_collide() -> None:
    codes = {
        name: value
        for name, value in vars(exit_codes).items()
        if name.isupper() and isinstance(value, int)
    }
    assert codes["STORAGE_FAILURE"] == EXIT_STORAGE_FAILURE == 7
    assert codes["STORAGE_TRANSIENT"] == 8
    assert len(set(codes.values())) == len(codes)


@pytest.mark.unit
def test_review_storage_auth_error_is_an_auth_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Drive auth failure exits the review CLI's auth code (1), not API/storage."""
    args = argparse.Namespace(json=True, run_folder="F1")
    exc = StorageAuthError("gcloud returned an empty access token")
    assert review_command._storage_failure(exc, args) == EXIT_AUTH == 1
    out = capsys.readouterr()
    assert out.err.startswith("AUTH_ERROR: ")
    assert json.loads(out.out)["error"].startswith("AUTH_ERROR: ")


@pytest.mark.unit
def test_exit_codes_all_lists_every_code() -> None:
    codes = {n for n, v in vars(exit_codes).items() if n.isupper() and isinstance(v, int)}
    assert set(exit_codes.__all__) == codes
