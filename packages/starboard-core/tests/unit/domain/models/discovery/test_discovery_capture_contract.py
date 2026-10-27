# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The discovery capture contract (run-6b): resume record path, budget exit and code."""

from __future__ import annotations

import pytest
from starboard_core.domain.models.discovery.capture import (
    CAPTURE_INCOMPLETE,
    DEFAULT_MAX_SECONDS,
    EXIT_CAPTURE_INCOMPLETE,
    PROGRESS_PATH,
    CaptureIncomplete,
    is_capture_path,
    resume_command,
)
from starboard_core.engagement.sink import reserved_record


@pytest.mark.unit
def test_budget_exit_is_a_dedicated_code_below_the_host_limit() -> None:
    assert CAPTURE_INCOMPLETE == "CAPTURE_INCOMPLETE"
    assert EXIT_CAPTURE_INCOMPLETE == 9
    assert 0 < DEFAULT_MAX_SECONDS < 600


@pytest.mark.unit
def test_progress_record_is_an_ordinary_run_artifact() -> None:
    assert reserved_record(PROGRESS_PATH) is None
    assert is_capture_path(PROGRESS_PATH)
    assert is_capture_path("capture/queries/CRS-01.arrow")
    assert not is_capture_path("raw/billing.json")
    assert not is_capture_path("captured.json")


@pytest.mark.unit
def test_capture_incomplete_carries_progress_and_is_retryable() -> None:
    exc = CaptureIncomplete(done=12, remaining=7, reused=3)
    assert exc.code == CAPTURE_INCOMPLETE
    assert exc.retryable is True
    assert exc.progress() == {"done": 12, "remaining": 7, "reused": 3}
    assert "12" in str(exc) and "7" in str(exc)
    assert "re-run the same command" in str(exc)


@pytest.mark.unit
def test_capture_incomplete_remaining_unknown_before_selection() -> None:
    exc = CaptureIncomplete(done=0, remaining=None, reused=0)
    assert exc.progress()["remaining"] is None


@pytest.mark.unit
def test_resume_command_quotes_the_same_argv() -> None:
    cmd = resume_command(["starboard"], ["--discover", "--run-folder", "a b"])
    assert cmd == "starboard --discover --run-folder 'a b'"
