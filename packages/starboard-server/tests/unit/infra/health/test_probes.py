# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for health check dependency probes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.infra.health.probes import (
    DatabaseProbe,
    DatabricksProbe,
    HealthCheckRunner,
    LLMProviderProbe,
    ProbeResult,
    RedisProbe,
    check_with_timeout,
)


class TestProbeResult:
    """Tests for ProbeResult dataclass."""

    def test_healthy_probe_result(self):
        result = ProbeResult(name="database", healthy=True, latency_ms=5.2)
        assert result.name == "database"
        assert result.healthy is True
        assert result.latency_ms == 5.2
        assert result.error is None

    def test_unhealthy_probe_result(self):
        result = ProbeResult(
            name="cache", healthy=False, latency_ms=100.0, error="connection refused"
        )
        assert result.healthy is False
        assert result.error == "connection refused"


class TestDatabaseProbe:
    """Tests for DatabaseProbe."""

    @pytest.mark.asyncio
    async def test_healthy_database(self):
        mock_conn = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.acquire.return_value = mock_conn

        probe = DatabaseProbe(mock_pool)
        result = await probe.check()

        assert result.name == "database"
        assert result.healthy is True
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_unhealthy_database(self):
        mock_pool = AsyncMock()
        mock_pool.acquire.side_effect = ConnectionError("refused")

        probe = DatabaseProbe(mock_pool)
        result = await probe.check()

        assert result.name == "database"
        assert result.healthy is False
        assert "refused" in result.error

    def test_probe_name(self):
        probe = DatabaseProbe(MagicMock())
        assert probe.name == "database"


class TestRedisProbe:
    """Tests for RedisProbe."""

    @pytest.mark.asyncio
    async def test_healthy_redis(self):
        mock_client = AsyncMock()
        mock_client.ping.return_value = True

        probe = RedisProbe(mock_client)
        result = await probe.check()

        assert result.name == "cache"
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_redis(self):
        mock_client = AsyncMock()
        mock_client.ping.side_effect = ConnectionError("redis down")

        probe = RedisProbe(mock_client)
        result = await probe.check()

        assert result.name == "cache"
        assert result.healthy is False

    def test_probe_name(self):
        probe = RedisProbe(MagicMock())
        assert probe.name == "cache"


class TestDatabricksProbe:
    """Tests for DatabricksProbe."""

    @pytest.mark.asyncio
    async def test_healthy_databricks(self):
        mock_client = AsyncMock()
        mock_client.get_current_user.return_value = {"user": "test"}

        probe = DatabricksProbe(mock_client)
        result = await probe.check()

        assert result.name == "compute"
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_databricks(self):
        mock_client = AsyncMock()
        mock_client.get_current_user.side_effect = Exception("auth failed")

        probe = DatabricksProbe(mock_client)
        result = await probe.check()

        assert result.name == "compute"
        assert result.healthy is False

    def test_probe_name(self):
        probe = DatabricksProbe(MagicMock())
        assert probe.name == "compute"


class TestLLMProviderProbe:
    """Tests for LLMProviderProbe."""

    @pytest.mark.asyncio
    async def test_healthy_llm(self):
        mock_client = AsyncMock()
        mock_client.models = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=[{"id": "gpt-4"}])

        probe = LLMProviderProbe(mock_client)
        result = await probe.check()

        assert result.name == "ai"
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_llm(self):
        mock_client = AsyncMock()
        mock_client.models = AsyncMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("provider error"))

        probe = LLMProviderProbe(mock_client)
        result = await probe.check()

        assert result.name == "ai"
        assert result.healthy is False

    def test_probe_name(self):
        mock_client = MagicMock()
        probe = LLMProviderProbe(mock_client)
        assert probe.name == "ai"


class TestCheckWithTimeout:
    """Tests for check_with_timeout helper."""

    @pytest.mark.asyncio
    async def test_probe_within_timeout(self):
        mock_probe = AsyncMock()
        mock_probe.name = "test"
        mock_probe.check.return_value = ProbeResult(
            name="test", healthy=True, latency_ms=1.0
        )

        result = await check_with_timeout(mock_probe, timeout_seconds=5.0)
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_probe_exceeds_timeout(self):
        async def slow_check():
            await asyncio.sleep(10)
            return ProbeResult(name="test", healthy=True, latency_ms=1.0)

        mock_probe = AsyncMock()
        mock_probe.name = "slow"
        mock_probe.check = slow_check

        result = await check_with_timeout(mock_probe, timeout_seconds=0.1)
        assert result.healthy is False
        assert result.error == "timeout"
        assert result.name == "slow"


class TestHealthCheckRunner:
    """Tests for HealthCheckRunner."""

    @pytest.mark.asyncio
    async def test_all_healthy(self):
        probes = []
        for name in ["database", "cache"]:
            p = AsyncMock()
            p.name = name
            p.check.return_value = ProbeResult(name=name, healthy=True, latency_ms=1.0)
            probes.append(p)

        runner = HealthCheckRunner(probes, timeout_seconds=5.0)
        result = await runner.run()

        assert result["status"] == "ready"
        assert len(result["checks"]) == 2
        assert all(c["healthy"] for c in result["checks"].values())

    @pytest.mark.asyncio
    async def test_one_unhealthy(self):
        healthy_probe = AsyncMock()
        healthy_probe.name = "database"
        healthy_probe.check.return_value = ProbeResult(
            name="database", healthy=True, latency_ms=1.0
        )

        unhealthy_probe = AsyncMock()
        unhealthy_probe.name = "cache"
        unhealthy_probe.check.return_value = ProbeResult(
            name="cache", healthy=False, latency_ms=50.0, error="down"
        )

        runner = HealthCheckRunner(
            [healthy_probe, unhealthy_probe], timeout_seconds=5.0
        )
        result = await runner.run()

        assert result["status"] == "degraded"
        assert result["checks"]["database"]["healthy"] is True
        assert result["checks"]["cache"]["healthy"] is False

    @pytest.mark.asyncio
    async def test_no_probes(self):
        runner = HealthCheckRunner([], timeout_seconds=5.0)
        result = await runner.run()
        assert result["status"] == "ready"

    @pytest.mark.asyncio
    async def test_no_internal_details_exposed(self):
        """Health response must not expose internal service names."""
        probe = AsyncMock()
        probe.name = "database"
        probe.check.return_value = ProbeResult(
            name="database", healthy=True, latency_ms=1.0
        )

        runner = HealthCheckRunner([probe], timeout_seconds=5.0)
        result = await runner.run()

        result_str = str(result).lower()
        for forbidden in [
            "postgres",
            "redis",
            "openai",
            "databricks",
            "sqlite",
            "asyncpg",
        ]:
            assert forbidden not in result_str, (
                f"Internal detail '{forbidden}' exposed in health response"
            )

    @pytest.mark.asyncio
    async def test_latency_included(self):
        probe = AsyncMock()
        probe.name = "database"
        probe.check.return_value = ProbeResult(
            name="database", healthy=True, latency_ms=5.2
        )

        runner = HealthCheckRunner([probe], timeout_seconds=5.0)
        result = await runner.run()

        assert result["checks"]["database"]["latency_ms"] == 5.2
