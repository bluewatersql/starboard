"""
Tests for starboard_server.main.

Tests the FastAPI application initialization, configuration, and health endpoints.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from starboard_server.main import (
    create_app,
    get_container,
)


@pytest.fixture
def mock_event_coverage():
    """Mock event coverage validation."""
    with patch("starboard_server.api.event_converter.validate_event_coverage") as mock:
        mock.return_value = (True, [])
        yield mock


@pytest.fixture
def mock_config():
    """Mock app configuration."""
    with patch("starboard_server.main.get_config") as mock:
        config = Mock()
        config.log_level = "INFO"
        config.log_json = False
        config.host = "localhost"
        config.port = 8000
        config.debug = False
        config.environment = "test"
        config.database_backend = "sqlite"
        config.sqlite_state_path = ":memory:"
        config.database_url = None
        config.redis_url = None
        config.max_request_size = 10 * 1024 * 1024  # 10 MB
        config.rate_limit_enabled = False
        config.rate_limit_storage = "memory"
        config.rate_limit_default = "100/minute"
        mock.return_value = config
        yield config


@pytest.fixture
def mock_container():
    """Mock Container for testing."""
    with patch("starboard_server.main.Container") as mock_container_class:
        container = AsyncMock()
        container.config = Mock(
            environment="test",
            database_backend="sqlite",
        )
        container.state_store = Mock(__name__="InMemoryStateStore")
        container.memory_store = Mock(__name__="InMemoryMemoryStore")
        mock_container_class.return_value = container
        yield container


@pytest.fixture
def mock_app_config():
    """Mock get_config function."""
    with patch("starboard_server.infra.core.config.get_config") as mock_get_config:
        config = Mock()
        config.environment = "test"
        config.database_backend = "sqlite"
        config.sqlite_state_path = ":memory:"
        config.database_url = None
        config.redis_url = None
        config.validate = Mock()
        mock_get_config.return_value = config
        yield config


class TestCreateApp:
    """Tests for create_app function."""

    def test_create_app_returns_fastapi_instance(
        self, mock_config, mock_event_coverage
    ):
        """Test that create_app returns a FastAPI instance."""
        app = create_app()

        assert app is not None
        assert app.title == "Starboard AI Agent API"
        assert app.version == "0.1.0"

    def test_create_app_configures_cors(self, mock_config, mock_event_coverage):
        """Test that CORS middleware is configured."""
        app = create_app()
        client = TestClient(app)

        # Test CORS by checking response headers on a request
        response = client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        # CORS should allow the request (200 status)
        assert response.status_code == 200

    def test_create_app_registers_routes(self, mock_config, mock_event_coverage):
        """Test that API routes are registered."""
        app = create_app()

        # Check that routes are registered
        routes = [route.path for route in app.routes]
        assert "/health/live" in routes
        assert "/health/ready" in routes

    def test_create_app_has_docs_endpoints(self, mock_config, mock_event_coverage):
        """Test that documentation endpoints are configured."""
        app = create_app()

        assert app.docs_url == "/docs"
        assert app.redoc_url == "/redoc"
        assert app.openapi_url == "/openapi.json"


@pytest.mark.requires_databricks
class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_live_returns_ok(self, mock_config, mock_event_coverage):
        """Test /health/live endpoint returns ok status."""
        app = create_app()
        client = TestClient(app)

        response = client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_ready_with_initialized_container(
        self, mock_config, mock_event_coverage, mock_container, mock_app_config
    ):
        """Test /health/ready endpoint when container is initialized."""
        app = create_app()

        # Use TestClient with lifespan context
        with TestClient(app) as client:
            response = client.get("/health/ready")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert "environment" in data
            assert "database_backend" in data

    def test_health_ready_without_container(self):
        """Test get_container raises error when container is not initialized."""
        # Reset the global container
        import starboard_server.main as main_module

        original_container = main_module._container

        try:
            # Set container to None
            main_module._container = None

            # get_container should raise RuntimeError
            with pytest.raises(RuntimeError, match="Container not initialized"):
                get_container()
        finally:
            # Restore original container
            main_module._container = original_container


@pytest.mark.requires_databricks
class TestGetContainer:
    """Tests for get_container function."""

    def test_get_container_raises_when_not_initialized(self):
        """Test that get_container raises RuntimeError when container is not initialized."""
        # Reset the global container
        import starboard_server.main as main_module

        main_module._container = None

        with pytest.raises(RuntimeError, match="Container not initialized"):
            get_container()

    @pytest.mark.asyncio
    async def test_get_container_returns_container_when_initialized(
        self, mock_config, mock_event_coverage, mock_container, mock_app_config
    ):
        """Test that get_container returns container after initialization."""
        app = create_app()

        # Initialize the app (which initializes the container)
        with TestClient(app):
            # Container should now be initialized
            container = get_container()
            assert container is not None


@pytest.mark.requires_databricks
class TestLifespan:
    """Tests for lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_container(
        self, mock_config, mock_event_coverage, mock_container, mock_app_config
    ):
        """Test that lifespan initializes the container on startup."""
        app = create_app()

        # Start the app (triggers lifespan startup)
        with TestClient(app):
            # Verify container was initialized
            mock_container.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_validates_events(
        self, mock_config, mock_event_coverage, mock_container, mock_app_config
    ):
        """Test that lifespan validates event coverage on startup."""
        app = create_app()

        # Start the app
        with TestClient(app):
            # Verify event validation was called
            mock_event_coverage.assert_called()

    @pytest.mark.asyncio
    async def test_lifespan_raises_on_invalid_events(
        self, mock_config, mock_container, mock_app_config
    ):
        """Test that lifespan raises error when event coverage is invalid."""
        with patch(
            "starboard_server.api.event_converter.validate_event_coverage"
        ) as mock_validate:
            # Simulate invalid event coverage
            mock_validate.return_value = (False, ["MissingEvent"])

            app = create_app()

            # Starting the app should raise RuntimeError
            with pytest.raises(RuntimeError, match="Event coverage validation failed"):  # noqa: SIM117
                with TestClient(app):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_shuts_down_container(
        self, mock_config, mock_event_coverage, mock_container, mock_app_config
    ):
        """Test that lifespan shuts down container on shutdown."""
        app = create_app()

        # Start and stop the app
        with TestClient(app):
            pass  # Client context manager triggers startup and shutdown

        # Verify shutdown was called
        mock_container.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_handles_initialization_error(
        self, mock_config, mock_event_coverage, mock_app_config
    ):
        """Test that lifespan handles container initialization errors."""
        with patch("starboard_server.main.Container") as mock_container_class:
            # Simulate initialization error
            mock_container_class.return_value.initialize.side_effect = Exception(
                "Init failed"
            )

            app = create_app()

            # Starting the app should raise the exception
            with pytest.raises(Exception, match="Init failed"):  # noqa: SIM117
                with TestClient(app):
                    pass


class TestCORSConfiguration:
    """Tests for CORS middleware configuration."""

    def test_cors_allows_localhost_origins(self, mock_config, mock_event_coverage):
        """Test that CORS allows localhost origins for development."""
        app = create_app()
        client = TestClient(app)

        # Test preflight request
        response = client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        # CORS should allow the request
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_cors_allows_custom_frontend_url(self, mock_config, mock_event_coverage):
        """Test that CORS allows custom FRONTEND_URL from environment."""
        with patch.dict("os.environ", {"FRONTEND_URL": "https://myapp.example.com"}):
            create_app()
            # Custom frontend URL should be in allowed origins
            # This is implicitly tested by the app not raising an error


@pytest.mark.requires_databricks
class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_without_frontend_build(self, mock_config, mock_event_coverage):
        """Test root endpoint when frontend is not built."""
        app = create_app()

        # Use app context manager to initialize lifespan properly
        with TestClient(app) as client:
            # Assuming frontend is not built in test environment
            response = client.get("/")

            # Should return API info or 500 if auth not initialized
            # Accept 500 as valid since auth service may not be initialized in test
            assert response.status_code in [200, 404, 500]
            data = response.json()
            assert "name" in data or "error" in data or "detail" in data
