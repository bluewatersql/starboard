# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for service catalog loader.

Tests loading and parsing service catalog from YAML configuration.
Part of Router Integration for Phase 9.
"""

from pathlib import Path

import pytest

# These imports will fail initially - that's expected in TDD
from starboard_server.config.catalog_loader import (
    CatalogLoadError,
    load_service_catalog,
)
from starboard_server.domain.models.service_catalog import (
    ServiceStatus,
    ServiceType,
)


class TestCatalogLoader:
    """Test service catalog YAML loader."""

    def test_load_catalog_from_yaml(self, tmp_path):
        """Test loading catalog from valid YAML file."""
        # Create temporary YAML file
        yaml_content = """
version: "1.0.0"
last_updated: "2025-11-25"

agents:
  - service_id: "test_agent"
    service_type: "agent"
    name: "Test Agent"
    domain: "test"
    description: "Test agent for unit tests"
    version: "1.0.0"
    status: "active"
    capabilities:
      - capability_id: "test_capability"
        name: "Test Capability"
        description: "Test capability description"
    examples:
      - example_id: "ex1"
        user_query: "Test query"
        expected_capability: "test_capability"
"""
        yaml_file = tmp_path / "test_catalog.yaml"
        yaml_file.write_text(yaml_content)

        # Load catalog
        entries = load_service_catalog(str(yaml_file))

        # Assert
        assert len(entries) == 1
        assert entries[0].service_id == "test_agent"
        assert entries[0].service_type == ServiceType.AGENT
        assert entries[0].name == "Test Agent"
        assert entries[0].domain == "test"
        assert entries[0].version == "1.0.0"
        assert entries[0].status == ServiceStatus.ACTIVE
        assert len(entries[0].capabilities) == 1
        assert entries[0].capabilities[0].capability_id == "test_capability"
        assert len(entries[0].examples) == 1

    def test_load_catalog_multiple_agents(self, tmp_path):
        """Test loading catalog with multiple agents."""
        yaml_content = """
agents:
  - service_id: "agent1"
    service_type: "agent"
    name: "Agent 1"
    domain: "domain1"
    description: "First agent"
    version: "1.0.0"
    status: "active"
    capabilities: []
    examples: []

  - service_id: "agent2"
    service_type: "agent"
    name: "Agent 2"
    domain: "domain2"
    description: "Second agent"
    version: "1.0.0"
    status: "active"
    capabilities: []
    examples: []
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        entries = load_service_catalog(str(yaml_file))

        assert len(entries) == 2
        assert entries[0].service_id == "agent1"
        assert entries[1].service_id == "agent2"

    def test_load_catalog_missing_file(self):
        """Test loading from non-existent file raises error."""
        with pytest.raises(CatalogLoadError, match="Catalog file not found"):
            load_service_catalog("/nonexistent/path/catalog.yaml")

    def test_load_catalog_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: content: [")

        with pytest.raises(CatalogLoadError, match="Failed to parse YAML"):
            load_service_catalog(str(yaml_file))

    def test_load_catalog_missing_agents_key(self, tmp_path):
        """Test loading YAML without 'agents' key."""
        yaml_content = """
version: "1.0.0"
# Missing agents key
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        entries = load_service_catalog(str(yaml_file))

        assert entries == []  # Should return empty list, not error

    def test_load_catalog_validates_entries(self, tmp_path):
        """Test that invalid entries raise validation errors."""
        yaml_content = """
agents:
  - service_id: ""  # Invalid: empty service_id
    service_type: "agent"
    name: "Test"
    domain: "test"
    description: "Test"
    version: "1.0.0"
    status: "active"
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        with pytest.raises(CatalogLoadError, match="Failed to validate"):
            load_service_catalog(str(yaml_file))

    def test_load_catalog_with_path_object(self, tmp_path):
        """Test loading with Path object instead of string."""
        yaml_content = """
agents:
  - service_id: "test_agent"
    service_type: "agent"
    name: "Test"
    domain: "test"
    description: "Test"
    version: "1.0.0"
    status: "active"
    capabilities: []
    examples: []
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        # Pass Path object
        entries = load_service_catalog(yaml_file)

        assert len(entries) == 1
        assert entries[0].service_id == "test_agent"

    def test_load_catalog_empty_capabilities(self, tmp_path):
        """Test loading agent with no capabilities."""
        yaml_content = """
agents:
  - service_id: "minimal_agent"
    service_type: "agent"
    name: "Minimal Agent"
    domain: "test"
    description: "Agent with no capabilities"
    version: "1.0.0"
    status: "active"
    capabilities: []
    examples: []
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        entries = load_service_catalog(str(yaml_file))

        assert len(entries) == 1
        assert len(entries[0].capabilities) == 0
        assert len(entries[0].examples) == 0

    def test_load_actual_service_catalog(self):
        """Test loading the actual service_catalog.yaml file."""
        # This tests the real config file
        catalog_path = (
            Path(__file__).parent.parent.parent.parent
            / "starboard_server"
            / "config"
            / "service_catalog.yaml"
        )

        if not catalog_path.exists():
            pytest.skip(f"Catalog file not found at {catalog_path}")

        entries = load_service_catalog(catalog_path)

        # Verify we loaded all 7 domain agents
        # (query, job, uc, compute, diagnostic, analytics, warehouse)
        assert len(entries) >= 7

        # Check for expected agents
        service_ids = {entry.service_id for entry in entries}
        assert "query_optimizer" in service_ids
        assert "job_analyzer" in service_ids
        assert "uc_manager" in service_ids  # Renamed from table_manager
        assert "cluster_manager" in service_ids  # Renamed from compute_manager
        assert "diagnostic_agent" in service_ids
        assert "analytics_agent" in service_ids  # Added in v1.1.0
        assert "warehouse_agent" in service_ids  # Added in v1.2.0

    def test_load_catalog_preserves_metadata(self, tmp_path):
        """Test that all agent metadata is preserved."""
        yaml_content = """
agents:
  - service_id: "full_agent"
    service_type: "agent"
    name: "Full Agent"
    domain: "test"
    description: "Agent with all fields"
    version: "1.2.3"
    status: "beta"
    capabilities:
      - capability_id: "cap1"
        name: "Capability 1"
        description: "First capability"
      - capability_id: "cap2"
        name: "Capability 2"
        description: "Second capability"
    examples:
      - example_id: "ex1"
        user_query: "Example query 1"
        expected_capability: "cap1"
      - example_id: "ex2"
        user_query: "Example query 2"
        expected_capability: "cap2"
"""
        yaml_file = tmp_path / "catalog.yaml"
        yaml_file.write_text(yaml_content)

        entries = load_service_catalog(str(yaml_file))

        agent = entries[0]
        assert agent.service_id == "full_agent"
        assert agent.version == "1.2.3"
        assert agent.status == ServiceStatus.BETA
        assert len(agent.capabilities) == 2
        assert len(agent.examples) == 2
        assert agent.capabilities[0].capability_id == "cap1"
        assert agent.examples[0].example_id == "ex1"
