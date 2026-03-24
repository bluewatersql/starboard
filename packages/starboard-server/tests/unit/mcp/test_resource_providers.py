# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCP resource providers."""

import pytest
from starboard_server.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry
from starboard_server.mcp.config import MCPServerConfig, WorkspaceProfile
from starboard_server.mcp.exceptions import ExecutionError
from starboard_server.mcp.resource_providers import StarboardResourceProvider


def _make_config(**overrides: object) -> MCPServerConfig:
    defaults: dict = {
        "default_workspace_id": "prod",
        "workspaces": {
            "prod": WorkspaceProfile(
                host="https://prod.databricks.com", token_env="PROD_TOKEN"
            ),
            "dev": WorkspaceProfile(
                host="https://dev.databricks.com", token_env="DEV_TOKEN"
            ),
        },
    }
    defaults.update(overrides)
    return MCPServerConfig(**defaults)


def _make_provider(**config_overrides: object) -> StarboardResourceProvider:
    config = _make_config(**config_overrides)
    cb = MCPCircuitBreakerRegistry()
    # Prime a circuit breaker
    cb.get("prod")
    return StarboardResourceProvider(config=config, circuit_breakers=cb)


class TestListResources:
    """Tests for list_resources."""

    def test_returns_all_5(self) -> None:
        provider = _make_provider()
        resources = provider.list_resources()
        assert len(resources) == 5
        uris = {r["uri"] for r in resources}
        assert "starboard://workspace/info" in uris
        assert "starboard://agents/catalog" in uris
        assert "starboard://tools/catalog" in uris
        assert "starboard://tools/dependencies" in uris
        assert "starboard://health" in uris


class TestWorkspaceInfo:
    """Tests for workspace/info resource."""

    def test_no_secrets(self) -> None:
        provider = _make_provider()
        info = provider.read_resource("starboard://workspace/info")
        # Must NOT contain token_env
        info_str = str(info)
        assert "token_env" not in info_str
        assert "PROD_TOKEN" not in info_str

    def test_has_workspace_hosts(self) -> None:
        provider = _make_provider()
        info = provider.read_resource("starboard://workspace/info")
        assert info["default_workspace_id"] == "prod"
        assert "prod" in info["workspaces"]
        assert info["workspaces"]["prod"]["host"] == "https://prod.databricks.com"

    def test_safe_mode_reflected(self) -> None:
        provider = _make_provider(safe_mode=True)
        info = provider.read_resource("starboard://workspace/info")
        assert info["safe_mode"] is True


class TestAgentsCatalog:
    """Tests for agents/catalog resource."""

    def test_has_all_domains(self) -> None:
        provider = _make_provider()
        catalog = provider.read_resource("starboard://agents/catalog")
        domains = {a["domain"] for a in catalog["agents"]}
        for expected in ("query", "job", "uc", "cluster", "warehouse", "diagnostic"):
            assert expected in domains


class TestToolsCatalog:
    """Tests for tools/catalog resource."""

    def test_matches_registry_count(self) -> None:
        from starboard_server.agents.tools.registry import ALL_TOOL_METADATA

        provider = _make_provider()
        catalog = provider.read_resource("starboard://tools/catalog")
        assert catalog["total_count"] == len(ALL_TOOL_METADATA)
        assert len(catalog["tools"]) == catalog["total_count"]


class TestToolsDependencies:
    """Tests for tools/dependencies resource."""

    def test_has_dependencies(self) -> None:
        provider = _make_provider()
        deps = provider.read_resource("starboard://tools/dependencies")
        assert "dependencies" in deps
        assert "analyze_query_plan" in deps["dependencies"]
        assert "resolve_query" in deps["dependencies"]["analyze_query_plan"]


class TestHealth:
    """Tests for health resource."""

    def test_includes_circuit_breaker_states(self) -> None:
        provider = _make_provider()
        health = provider.read_resource("starboard://health")
        assert "circuit_breakers" in health
        assert "prod" in health["circuit_breakers"]

    def test_includes_status(self) -> None:
        provider = _make_provider()
        health = provider.read_resource("starboard://health")
        assert health["status"] == "healthy"

    def test_includes_uptime(self) -> None:
        provider = _make_provider()
        health = provider.read_resource("starboard://health")
        assert "uptime_seconds" in health
        assert health["uptime_seconds"] >= 0


class TestUnknownURI:
    """Tests for unknown resource URIs."""

    def test_raises_execution_error(self) -> None:
        provider = _make_provider()
        with pytest.raises(ExecutionError) as exc_info:
            provider.read_resource("starboard://nonexistent")
        assert exc_info.value.code == "EXEC_UNKNOWN_RESOURCE"
