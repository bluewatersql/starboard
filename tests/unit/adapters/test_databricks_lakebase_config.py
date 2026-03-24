"""Unit tests for Databricks Lakebase configuration."""

import os
from unittest.mock import patch

import pytest
from starboard_server.adapters.state.databricks.config import DatabricksLakebaseConfig


class TestDatabricksLakebaseConfig:
    """Unit tests for DatabricksLakebaseConfig."""

    def test_from_env_success(self):
        """Test loading configuration from environment variables."""
        with patch.dict(
            os.environ,
            {
                "LAKEBASE_INSTANCE_NAME": "test-instance",
                "LAKEBASE_DATABASE_NAME": "test_db",
                "DB_POOL_SIZE": "10",
                "DB_MAX_OVERFLOW": "20",
                "DB_POOL_TIMEOUT": "30",
                "DB_POOL_RECYCLE_INTERVAL": "7200",
                "DB_COMMAND_TIMEOUT": "60",
                "DATABRICKS_DATABASE_PORT": "5433",
            },
        ):
            config = DatabricksLakebaseConfig.from_env()

            assert config.instance_name == "test-instance"
            assert config.database_name == "test_db"
            assert config.pool_size == 10
            assert config.max_overflow == 20
            assert config.pool_timeout == 30
            assert config.pool_recycle_interval == 7200
            assert config.command_timeout == 60
            assert config.port == 5433

    def test_from_env_defaults(self):
        """Test default values when optional env vars not set."""
        with patch.dict(
            os.environ,
            {
                "LAKEBASE_INSTANCE_NAME": "test-instance",
                "LAKEBASE_DATABASE_NAME": "test_db",
            },
            clear=True,
        ):
            config = DatabricksLakebaseConfig.from_env()

            assert config.instance_name == "test-instance"
            assert config.database_name == "test_db"
            assert config.pool_size == 5
            assert config.max_overflow == 10
            assert config.pool_timeout == 10
            assert config.pool_recycle_interval == 3600
            assert config.command_timeout == 30
            assert config.port == 5432

    def test_from_env_missing_instance_name(self):
        """Test error when LAKEBASE_INSTANCE_NAME is missing."""
        with (
            patch.dict(
                os.environ,
                {"LAKEBASE_DATABASE_NAME": "test_db"},
                clear=True,
            ),
            pytest.raises(ValueError, match="LAKEBASE_INSTANCE_NAME"),
        ):
            DatabricksLakebaseConfig.from_env()

    def test_from_env_missing_database_name(self):
        """Test error when LAKEBASE_DATABASE_NAME is missing."""
        with (
            patch.dict(
                os.environ,
                {"LAKEBASE_INSTANCE_NAME": "test-instance"},
                clear=True,
            ),
            pytest.raises(ValueError, match="LAKEBASE_DATABASE_NAME"),
        ):
            DatabricksLakebaseConfig.from_env()

    def test_validate_success(self):
        """Test validation passes with valid config."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
        )

        # Should not raise
        config.validate()

    def test_validate_empty_instance_name(self):
        """Test validation fails with empty instance name."""
        config = DatabricksLakebaseConfig(
            instance_name="",
            database_name="test_db",
        )

        with pytest.raises(ValueError, match="instance_name cannot be empty"):
            config.validate()

    def test_validate_empty_database_name(self):
        """Test validation fails with empty database name."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="",
        )

        with pytest.raises(ValueError, match="database_name cannot be empty"):
            config.validate()

    def test_validate_invalid_pool_size(self):
        """Test validation fails with non-positive pool size."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            pool_size=0,
        )

        with pytest.raises(ValueError, match="pool_size must be positive"):
            config.validate()

    def test_validate_negative_max_overflow(self):
        """Test validation fails with negative max overflow."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            max_overflow=-1,
        )

        with pytest.raises(ValueError, match="max_overflow must be non-negative"):
            config.validate()

    def test_validate_invalid_pool_timeout(self):
        """Test validation fails with non-positive pool timeout."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            pool_timeout=0,
        )

        with pytest.raises(ValueError, match="pool_timeout must be positive"):
            config.validate()

    def test_validate_invalid_recycle_interval(self):
        """Test validation fails with non-positive recycle interval."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            pool_recycle_interval=0,
        )

        with pytest.raises(ValueError, match="pool_recycle_interval must be positive"):
            config.validate()

    def test_validate_invalid_command_timeout(self):
        """Test validation fails with non-positive command timeout."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            command_timeout=0,
        )

        with pytest.raises(ValueError, match="command_timeout must be positive"):
            config.validate()

    def test_validate_invalid_port_low(self):
        """Test validation fails with port too low."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            port=0,
        )

        with pytest.raises(ValueError, match="port must be between 1 and 65535"):
            config.validate()

    def test_validate_invalid_port_high(self):
        """Test validation fails with port too high."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
            port=70000,
        )

        with pytest.raises(ValueError, match="port must be between 1 and 65535"):
            config.validate()

    def test_frozen_dataclass(self):
        """Test that config is frozen (immutable)."""
        config = DatabricksLakebaseConfig(
            instance_name="test-instance",
            database_name="test_db",
        )

        with pytest.raises(AttributeError):
            config.instance_name = "new-instance"
