# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit test configuration and shared fixtures.

Ensures test isolation by resetting global singletons between tests.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def reset_env_config_singleton() -> None:
    """Reset the global EnvConfig singleton before each unit test.

    Prevents test pollution when tests patch ``EnvConfig`` at the class level
    (e.g., ``patch("starboard.infra.core.config.EnvConfig")``), which
    would otherwise leave a Mock in the singleton cache and cause downstream
    tests to receive a Mock instead of a real ``EnvConfig`` instance.
    """
    import starboard.infra.core.config as config_module

    # Clear the singleton before the test
    config_module._env_config = None
    yield
    # Clear the singleton after the test to prevent pollution of later tests
    config_module._env_config = None


@pytest.fixture(autouse=True)
def restore_logging_config() -> Iterator[None]:
    """Restore structlog and the root / ``starboard`` stdlib loggers after each test.

    ``setup_cli_logging`` (and ``starboard review``'s logging setup) bind structlog's
    ``PrintLoggerFactory`` and a root ``StreamHandler`` to the current
    ``sys.stderr``. Under ``capsys`` that stream is closed at teardown, so a later
    test that logs through those loggers fails with "I/O operation on closed file".
    """
    import logging

    import structlog

    saved = structlog.get_config()
    loggers = [logging.getLogger(), logging.getLogger("starboard")]
    state = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in loggers]
    yield
    structlog.configure(**saved)
    for lg, handlers, level, propagate in state:
        lg.handlers[:] = handlers
        lg.setLevel(level)
        lg.propagate = propagate
