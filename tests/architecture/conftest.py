"""Shared fixtures for architecture fitness tests."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the absolute path to the repository root."""
    return Path("/Users/c.price/Work/github/job-agent")
