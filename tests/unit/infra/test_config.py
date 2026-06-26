# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for application configuration."""

import pytest
from starboard_server.infra.core.config import EnvConfig


def test_envconfig_defaults():
    """Should have sensible defaults."""
    config = EnvConfig()
    assert config.environment == "dev"
    assert config.cache_ttl == 300
    assert config.postgres_min_pool_size == 5
    assert config.postgres_max_pool_size == 20


def test_envconfig_from_env(monkeypatch):
    """Should load configuration from environment variables."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("CACHE_TTL", "600")
    monkeypatch.setenv("OFFLINE_MODE", "true")  # Skip credential validation

    config = EnvConfig.from_env()
    assert config.environment == "production"
    assert config.database_url == "postgresql://localhost/test"
    assert config.redis_url == "redis://localhost:6379"
    assert config.cache_ttl == 600


def test_envconfig_validate_dev():
    """Dev environment with offline mode should not require credentials."""
    config = EnvConfig(environment="dev", offline_mode=True)
    config.validate_config()  # Should not raise


def test_envconfig_validate_production_missing_db():
    """Production environment should require DATABASE_URL for postgres backend."""
    config = EnvConfig(
        environment="production",
        database_backend="postgres",
        database_url=None,
        offline_mode=True,
    )
    with pytest.raises(ValueError, match="DATABASE_URL required"):
        config.validate_config()


def test_envconfig_validate_production_with_db():
    """Production with DATABASE_URL should validate successfully."""
    config = EnvConfig(
        environment="production",
        database_backend="postgres",
        database_url="postgresql://localhost/test",
        offline_mode=True,  # Skip credential validation in tests
    )
    config.validate_config()  # Should not raise


def test_envconfig_validate_pool_size():
    """Pool size validation should catch invalid configs."""
    config = EnvConfig(
        postgres_min_pool_size=20,
        postgres_max_pool_size=5,
        offline_mode=True,
    )
    with pytest.raises(ValueError, match="min_pool_size"):
        config.validate_config()


def test_envconfig_validate_negative_ttl():
    """Negative TTL should be rejected."""
    config = EnvConfig(cache_ttl=-1, offline_mode=True)
    with pytest.raises(ValueError, match="cache_ttl must be"):
        config.validate_config()
