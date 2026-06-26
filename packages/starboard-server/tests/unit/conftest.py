# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit test configuration and shared fixtures.

Ensures test isolation by resetting global singletons between tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_env_config_singleton() -> None:
    """Reset the global EnvConfig singleton before each unit test.

    Prevents test pollution when tests patch ``EnvConfig`` at the class level
    (e.g., ``patch("starboard_server.infra.core.config.EnvConfig")``), which
    would otherwise leave a Mock in the singleton cache and cause downstream
    tests to receive a Mock instead of a real ``EnvConfig`` instance.
    """
    import starboard_server.infra.core.config as config_module

    # Clear the singleton before the test
    config_module._env_config = None
    yield
    # Clear the singleton after the test to prevent pollution of later tests
    config_module._env_config = None
