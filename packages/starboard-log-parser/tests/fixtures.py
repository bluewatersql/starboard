# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pytest configuration and shared fixtures for log parser tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_event_log_path(tmp_path):
    """Create a sample event log file for testing."""
    log_file = tmp_path / "eventlog.json"
    log_file.write_text('{"Event":"SparkListenerLogStart","Spark Version":"3.5.0"}\n')
    return str(log_file)
