# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the internal-deployment config loaders (Phase-3 O1).

Each ``*Config.from_env`` returns a populated config only when all required env
vars are present; a partial/absent env yields ``None`` (the adapter then falls
back to an unwired backend). Reading never raises.
"""

from __future__ import annotations

import pytest
from starboard_internal._config import (
    DbrDoctorConfig,
    FleetSqlConfig,
    GenieConfig,
    LogsSummariserConfig,
    MissingInternalConfigError,
    missing_config_message,
)


@pytest.mark.unit
class TestLogsSummariserConfig:
    def test_absent_env_is_none(self) -> None:
        assert LogsSummariserConfig.from_env({}) is None

    def test_partial_env_is_none(self) -> None:
        assert (
            LogsSummariserConfig.from_env(
                {"STARBOARD_INTERNAL_LOGS_SUMMARISER_URL": "https://x"}
            )
            is None
        )

    def test_full_env_populates_and_normalizes(self) -> None:
        cfg = LogsSummariserConfig.from_env(
            {
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL": "https://logs/",
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN": "tok",
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_KUBE_CONTEXT": "prod-aws-us-west-2",
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_TIMEOUT": "12.5",
            }
        )
        assert cfg is not None
        assert cfg.url == "https://logs"  # trailing slash stripped
        assert cfg.token == "tok"
        assert cfg.kube_context == "prod-aws-us-west-2"
        assert cfg.timeout == 12.5

    def test_bad_timeout_falls_back_to_default(self) -> None:
        cfg = LogsSummariserConfig.from_env(
            {
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL": "https://logs",
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN": "tok",
                "STARBOARD_INTERNAL_LOGS_SUMMARISER_TIMEOUT": "not-a-number",
            }
        )
        assert cfg is not None and cfg.timeout == 30.0


@pytest.mark.unit
class TestDbrDoctorConfig:
    def test_absent_env_is_none(self) -> None:
        assert DbrDoctorConfig.from_env({}) is None

    def test_full_env_populates(self) -> None:
        cfg = DbrDoctorConfig.from_env(
            {
                "STARBOARD_INTERNAL_DBR_DOCTOR_URL": "https://doctor/",
                "STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN": "tok",
            }
        )
        assert cfg is not None and cfg.url == "https://doctor" and cfg.token == "tok"


@pytest.mark.unit
class TestFleetSqlConfig:
    def test_absent_env_is_none(self) -> None:
        assert FleetSqlConfig.from_env({}) is None

    def test_warehouse_only_is_enough(self) -> None:
        cfg = FleetSqlConfig.from_env(
            {"STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "wh-1"}
        )
        assert cfg is not None
        assert cfg.warehouse_id == "wh-1"
        # Host/token fall through to the SDK default credential chain.
        assert cfg.host is None and cfg.token is None

    def test_optional_overrides(self) -> None:
        cfg = FleetSqlConfig.from_env(
            {
                "STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "wh-1",
                "STARBOARD_INTERNAL_FLEET_HOST": "https://dbc",
                "STARBOARD_INTERNAL_FLEET_TOKEN": "pat",
                "STARBOARD_INTERNAL_FLEET_CATALOG": "main",
            }
        )
        assert cfg is not None
        assert cfg.host == "https://dbc" and cfg.token == "pat"
        assert cfg.catalog == "main"


@pytest.mark.unit
class TestGenieConfig:
    def test_absent_env_is_none(self) -> None:
        assert GenieConfig.from_env({}) is None

    def test_invalid_json_is_none(self) -> None:
        assert (
            GenieConfig.from_env({"STARBOARD_INTERNAL_GENIE_SPACES": "not json"})
            is None
        )

    def test_empty_mapping_is_none(self) -> None:
        assert GenieConfig.from_env({"STARBOARD_INTERNAL_GENIE_SPACES": "{}"}) is None

    def test_valid_spaces_mapping(self) -> None:
        cfg = GenieConfig.from_env(
            {
                "STARBOARD_INTERNAL_GENIE_SPACES": '{"global_genie": "01ef", "hls_genie": "02ab"}',
                "STARBOARD_INTERNAL_GENIE_HOST": "https://dbc",
            }
        )
        assert cfg is not None
        assert cfg.spaces == {"global_genie": "01ef", "hls_genie": "02ab"}
        assert cfg.host == "https://dbc"


@pytest.mark.unit
class TestMissingConfigMessage:
    def test_message_is_actionable(self) -> None:
        msg = missing_config_message(
            "LogsSummariserAdapter",
            "logs-summariser",
            LogsSummariserConfig.REQUIRED,
            "LogTriageBackend",
        )
        assert "LogsSummariserAdapter" in msg
        assert "logs-summariser" in msg
        assert "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL" in msg
        assert "LogTriageBackend" in msg

    def test_error_is_a_runtimeerror(self) -> None:
        assert issubclass(MissingInternalConfigError, RuntimeError)
