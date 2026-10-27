# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""The public fleet-source timeout base (run-6b): a coded, retryable ``TimeoutError``."""

from __future__ import annotations

import pytest
from starboard_core.ports import FleetSourceTimeout


@pytest.mark.unit
def test_fleet_source_timeout_is_a_coded_retryable_timeout_error() -> None:
    exc = FleetSourceTimeout("lookup did not finish within 300s", hint="re-run")
    assert isinstance(exc, TimeoutError)
    assert exc.code == "SOURCE_TIMEOUT"
    assert exc.retryable is True
    assert exc.hint == "re-run"
    assert str(exc) == "lookup did not finish within 300s"


@pytest.mark.unit
def test_fleet_source_timeout_hint_defaults_to_none() -> None:
    assert FleetSourceTimeout("x").hint is None
