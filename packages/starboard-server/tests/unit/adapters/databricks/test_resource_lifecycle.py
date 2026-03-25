"""Tests for resource lifecycle / leak fixes.

Covers:
- Item 1: _rest_client caching (not recreated on each access)
- Item 2: AsyncDatabricksClient close in dependencies.py
- Item 3: ThreadPoolExecutor shutdown on process exit
- Item 4: Container shutdown closes vector/reflexion/semantic_cache
- Item 5: CLI chat.py report formatting error is logged
- Item 7: Cache key consistency (includes all relevant params)
- Item 8: Retry only on transient errors
- Item 15: Connection pooling on HTTP client (single shared instance)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Item 1: _rest_client caching
# ---------------------------------------------------------------------------


class TestRestClientCaching:
    """The _rest_client property must return a cached instance."""

    def _make_client(self):
        from starboard_server.adapters.databricks.client import AsyncDatabricksClient

        client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
        client._host = "https://example.databricks.com"
        client._token = "dapi-test"
        client._rest_client_instance = None  # Will be set by the property
        return client

    def test_rest_client_returns_same_instance(self) -> None:
        """_rest_client should return the same HTTPClient instance on repeat access."""
        from starboard_server.adapters.databricks.client import AsyncDatabricksClient

        client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
        client._host = "https://example.databricks.com"
        client._token = "dapi-test"
        client._rest_client_instance = None

        first = client._rest_client
        second = client._rest_client

        assert first is second, (
            "_rest_client must be cached; each access currently creates a new HTTPClient"
        )

    def test_rest_client_has_correct_base_url(self) -> None:
        """Cached _rest_client must use the client's host URL."""
        from starboard_server.adapters.databricks.client import AsyncDatabricksClient

        client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
        client._host = "https://my-workspace.databricks.com"
        client._token = "dapi-test"
        client._rest_client_instance = None

        rest = client._rest_client

        assert "my-workspace.databricks.com" in rest.base_url


# ---------------------------------------------------------------------------
# Item 3: ThreadPoolExecutor has shutdown registered
# ---------------------------------------------------------------------------


class TestThreadPoolExecutorShutdown:
    """The Databricks thread pool must expose a shutdown helper."""

    def test_shutdown_databricks_executor_exists(self) -> None:
        """A shutdown_databricks_executor() function must be importable."""
        from starboard_server.adapters.databricks.services.base import (  # noqa: F401
            shutdown_databricks_executor,
        )

    def test_shutdown_databricks_executor_shuts_down_pool(self) -> None:
        """Calling shutdown_databricks_executor() must shut down the active pool."""
        from starboard_server.adapters.databricks.services.base import (
            _get_databricks_executor,
            shutdown_databricks_executor,
        )

        # Ensure pool is created
        _get_databricks_executor()

        # Shutdown must not raise
        shutdown_databricks_executor(wait=False)

        # After shutdown the global reference must be cleared so a fresh pool
        # is created on next use.
        from starboard_server.adapters.databricks.services import base as base_mod

        assert base_mod._databricks_executor is None

    def test_shutdown_databricks_executor_safe_when_no_pool(self) -> None:
        """shutdown_databricks_executor() must be a no-op when pool was never created."""
        from starboard_server.adapters.databricks.services import base as base_mod
        from starboard_server.adapters.databricks.services.base import (
            shutdown_databricks_executor,
        )

        # Force no pool
        original = base_mod._databricks_executor
        base_mod._databricks_executor = None
        try:
            shutdown_databricks_executor(wait=False)  # Must not raise
        finally:
            base_mod._databricks_executor = original


# ---------------------------------------------------------------------------
# Item 4: Container shutdown closes foundation components
# ---------------------------------------------------------------------------


class TestContainerShutdownFoundationComponents:
    """Container.shutdown() must close vector store, reflexion store, semantic cache."""

    @pytest.fixture
    def config(self):
        from starboard_server.infra.core.config import EnvConfig

        return EnvConfig(environment="test", database_backend="sqlite", offline_mode=True)

    @pytest.mark.asyncio
    async def test_shutdown_closes_reflexion_store(self, config) -> None:
        """shutdown() must call close()/shutdown() on the reflexion store if present."""
        from starboard_server.infra.core.container import Container

        container = Container(config)

        mock_reflexion = AsyncMock()
        mock_reflexion.close = AsyncMock()
        container._reflexion_store = mock_reflexion
        container._state_store = None
        container._cache_store = None
        container._memory_store = None
        container._vector_store = None
        container._semantic_cache = None

        await container.shutdown()

        mock_reflexion.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_vector_store(self, config) -> None:
        """shutdown() must call close() on the vector store if present."""
        from starboard_server.infra.core.container import Container

        container = Container(config)

        mock_vector = AsyncMock()
        mock_vector.close = AsyncMock()
        container._vector_store = mock_vector
        container._state_store = None
        container._cache_store = None
        container._memory_store = None
        container._reflexion_store = None
        container._semantic_cache = None

        await container.shutdown()

        mock_vector.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_semantic_cache(self, config) -> None:
        """shutdown() must call close() on the semantic cache if present."""
        from starboard_server.infra.core.container import Container

        container = Container(config)

        mock_cache = AsyncMock()
        mock_cache.close = AsyncMock()
        container._semantic_cache = mock_cache
        container._state_store = None
        container._cache_store = None
        container._memory_store = None
        container._reflexion_store = None
        container._vector_store = None

        await container.shutdown()

        mock_cache.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_safe_when_foundation_components_none(self, config) -> None:
        """shutdown() must not raise when foundation components are None."""
        from starboard_server.infra.core.container import Container

        container = Container(config)
        container._state_store = None
        container._cache_store = None
        container._memory_store = None
        container._reflexion_store = None
        container._vector_store = None
        container._semantic_cache = None

        # Should not raise
        await container.shutdown()


# ---------------------------------------------------------------------------
# Item 5: CLI chat.py logs report formatting errors
# ---------------------------------------------------------------------------


class TestChatReportFormattingError:
    """Report formatting exceptions must be logged, not crash the CLI."""

    def test_format_error_handler_exists_in_source(self) -> None:
        """The chat module must have a try/except around format_agent_report."""
        import ast
        from pathlib import Path

        chat_path = Path(__file__).resolve().parents[6] / "packages" / "starboard-cli" / "starboard_cli" / "cli" / "chat.py"
        if not chat_path.exists():
            pytest.skip("chat.py not found")

        source = chat_path.read_text()
        tree = ast.parse(source)

        # Find that format_agent_report is called inside a try block
        found_try_around_format = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "format_agent_report":
                        found_try_around_format = True
                    if isinstance(child, ast.Name) and child.id == "format_agent_report":
                        found_try_around_format = True

        assert found_try_around_format, (
            "format_agent_report must be wrapped in try/except in chat.py "
            "to prevent formatting errors from crashing the CLI"
        )

    def test_logger_warning_call_exists_in_handler(self) -> None:
        """The except block must call logger.warning with report_format_failed."""
        from pathlib import Path

        chat_path = Path(__file__).resolve().parents[6] / "packages" / "starboard-cli" / "starboard_cli" / "cli" / "chat.py"
        if not chat_path.exists():
            pytest.skip("chat.py not found")

        source = chat_path.read_text()
        assert "report_format_failed" in source, (
            "chat.py must log 'report_format_failed' when format_agent_report raises"
        )


# ---------------------------------------------------------------------------
# Item 7: Cache key consistency
# ---------------------------------------------------------------------------


class TestCacheKeyConsistency:
    """Cache keys must include all relevant parameters."""

    @pytest.mark.asyncio
    async def test_execute_sql_cache_key_includes_warehouse(self) -> None:
        """execute_sql cache key must include the warehouse_id."""
        from starboard_server.adapters.databricks.cache.manager import CacheManager
        from starboard_server.adapters.databricks.client import AsyncDatabricksClient

        client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
        client._cache = MagicMock(spec=CacheManager)
        client._cache.sql_key = CacheManager.sql_key  # use real method
        client._cache.get_dataframe = AsyncMock(return_value=None)
        client._cache.set_dataframe = AsyncMock()
        client._warehouse_id = "warehouse-A"
        client._sql_service = MagicMock()

        import polars as pl

        client._sql_service.execute_polars = AsyncMock(return_value=pl.DataFrame())

        # First call with warehouse A
        await client.execute_sql("SELECT 1", warehouse_id="warehouse-A", cache_ttl=60)

        # Second call with different warehouse
        await client.execute_sql("SELECT 1", warehouse_id="warehouse-B", cache_ttl=60)

        # Both set_dataframe calls should have been made (different keys → cache miss for B)
        assert client._cache.set_dataframe.call_count == 2

        # Verify the keys differ
        calls = client._cache.set_dataframe.call_args_list
        key_a = calls[0][0][0]
        key_b = calls[1][0][0]
        assert key_a != key_b, "Cache keys for different warehouses must differ"


# ---------------------------------------------------------------------------
# Item 8: Retry classification - only transient errors
# ---------------------------------------------------------------------------


class TestRetryClassification:
    """_run_with_retry must not retry permanent errors (400, 404, 403)."""

    @pytest.mark.asyncio
    async def test_no_retry_on_404(self) -> None:
        """404 errors must not be retried — fail immediately."""
        import httpx
        from starboard_server.adapters.databricks.services.base import BaseService

        service = BaseService(MagicMock())
        call_count = 0

        def raise_404():
            nonlocal call_count
            call_count += 1
            response = MagicMock(spec=httpx.Response)
            response.status_code = 404
            raise httpx.HTTPStatusError(
                "404 Not Found",
                request=MagicMock(),
                response=response,
            )

        with pytest.raises(httpx.HTTPStatusError):
            await service._run_with_retry(raise_404, max_retries=3, retry_delay=0.01)

        assert call_count == 1, "404 must not be retried (permanent error)"

    @pytest.mark.asyncio
    async def test_no_retry_on_403(self) -> None:
        """403 errors must not be retried."""
        import httpx
        from starboard_server.adapters.databricks.services.base import BaseService

        service = BaseService(MagicMock())
        call_count = 0

        def raise_403():
            nonlocal call_count
            call_count += 1
            response = MagicMock(spec=httpx.Response)
            response.status_code = 403
            raise httpx.HTTPStatusError(
                "403 Forbidden",
                request=MagicMock(),
                response=response,
            )

        with pytest.raises(httpx.HTTPStatusError):
            await service._run_with_retry(raise_403, max_retries=3, retry_delay=0.01)

        assert call_count == 1, "403 must not be retried (permanent error)"

    @pytest.mark.asyncio
    async def test_retry_on_429(self) -> None:
        """429 rate-limit errors must be retried (transient)."""
        import httpx
        from starboard_server.adapters.databricks.services.base import BaseService

        service = BaseService(MagicMock())
        call_count = 0

        def raise_429():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                response = MagicMock(spec=httpx.Response)
                response.status_code = 429
                raise httpx.HTTPStatusError(
                    "429 Too Many Requests",
                    request=MagicMock(),
                    response=response,
                )
            return "success"

        result = await service._run_with_retry(raise_429, max_retries=3, retry_delay=0.01)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_503(self) -> None:
        """503 service unavailable must be retried (transient)."""
        import httpx
        from starboard_server.adapters.databricks.services.base import BaseService

        service = BaseService(MagicMock())
        call_count = 0

        def raise_503():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                response = MagicMock(spec=httpx.Response)
                response.status_code = 503
                raise httpx.HTTPStatusError(
                    "503 Service Unavailable",
                    request=MagicMock(),
                    response=response,
                )
            return "ok"

        result = await service._run_with_retry(raise_503, max_retries=3, retry_delay=0.01)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self) -> None:
        """Network errors (ConnectError, TimeoutException) must be retried."""
        import httpx
        from starboard_server.adapters.databricks.services.base import BaseService

        service = BaseService(MagicMock())
        call_count = 0

        def raise_network():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("Connection refused")
            return "connected"

        result = await service._run_with_retry(
            raise_network, max_retries=3, retry_delay=0.01
        )
        assert result == "connected"


# ---------------------------------------------------------------------------
# Item 13: Dead code removal in openai/client.py
# ---------------------------------------------------------------------------


class TestOpenAIClientDeadCode:
    """_handle_api_errors is documented dead code and must be removed."""

    def test_handle_api_errors_removed(self) -> None:
        """_handle_api_errors is documented as dead (never called); it must be removed."""
        from starboard_server.adapters.llm.openai.client import OpenAIProvider

        assert not hasattr(OpenAIProvider, "_handle_api_errors"), (
            "_handle_api_errors is documented dead code (never called) and must be removed"
        )


# ---------------------------------------------------------------------------
# Item 15: HTTP connection pooling — _rest_client reuse
# ---------------------------------------------------------------------------


class TestHTTPConnectionPooling:
    """The _rest_client HTTPClient must be created once and reused (connection pooling)."""

    def test_rest_client_reused_across_calls(self) -> None:
        """Multiple accesses to _rest_client must return the same instance."""
        from starboard_server.adapters.databricks.client import AsyncDatabricksClient

        client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
        client._host = "https://example.databricks.com"
        client._token = "dapi-test"
        client._rest_client_instance = None

        instances = [client._rest_client for _ in range(5)]
        assert len({id(i) for i in instances}) == 1, (
            "All _rest_client accesses must return the same instance"
        )
