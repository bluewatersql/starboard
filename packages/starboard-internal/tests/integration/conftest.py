# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared skip-guards for the Internal-env integration tests.

Each guard is a ``pytest.mark.skipif`` that skips the whole test when the
adapter's required internal env is absent — so ``pytest`` reports SKIP (not
error/xfail) on any environment that has not wired the internal backend.
"""

from __future__ import annotations

import os

import pytest
from starboard_internal._config import (
    DbrDoctorConfig,
    FleetSqlConfig,
    GenieConfig,
    LogsSummariserConfig,
)


def _missing(*names: str) -> bool:
    return any(not os.environ.get(name) for name in names)


requires_logs_summariser = pytest.mark.skipif(
    _missing(*LogsSummariserConfig.REQUIRED),
    reason="logs-summariser internal env not wired (set STARBOARD_INTERNAL_LOGS_SUMMARISER_*)",
)

requires_dbr_doctor = pytest.mark.skipif(
    _missing(*DbrDoctorConfig.REQUIRED),
    reason="dbr-doctor internal env not wired (set STARBOARD_INTERNAL_DBR_DOCTOR_*)",
)

requires_fleet_sql = pytest.mark.skipif(
    _missing(*FleetSqlConfig.REQUIRED),
    reason="centralized-tables internal env not wired (set STARBOARD_INTERNAL_FLEET_*)",
)

requires_genie = pytest.mark.skipif(
    _missing(*GenieConfig.REQUIRED),
    reason="curated Genie internal env not wired (set STARBOARD_INTERNAL_GENIE_*)",
)
