# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for service catalog domain models.

Tests ServiceCatalogEntry, ServiceCapability, and ServiceExample models.
Following TDD: write tests first, then implement.

Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

import pytest

# These imports will fail initially - that's expected in TDD
from starboard.domain.models.service_catalog import (
    ServiceCapability,
    ServiceCatalogEntry,
    ServiceExample,
    ServiceStatus,
    ServiceType,
)


class TestServiceCapability:
    """Test ServiceCapability data model."""

    def test_create_service_capability(self):
        """Test creating a service capability with valid data."""
        capability = ServiceCapability(
            capability_id="identify_slow_queries",
            name="Identify Slow Queries",
            description="Finds queries that take longer than threshold",
        )

        assert capability.capability_id == "identify_slow_queries"
        assert capability.name == "Identify Slow Queries"
        assert capability.description == "Finds queries that take longer than threshold"

    def test_service_capability_immutable(self):
        """Test that ServiceCapability is immutable (frozen dataclass)."""
        capability = ServiceCapability(
            capability_id="test_cap",
            name="Test",
            description="Test capability",
        )

        with pytest.raises(AttributeError):
            capability.name = "Modified"  # type: ignore

    def test_service_capability_required_fields(self):
        """Test that all required fields must be provided."""
        with pytest.raises(TypeError):
            ServiceCapability()  # type: ignore

    def test_service_capability_string_representation(self):
        """Test string representation includes key fields."""
        capability = ServiceCapability(
            capability_id="test_cap",
            name="Test Capability",
            description="Description",
        )

        str_repr = str(capability)
        assert "test_cap" in str_repr
        assert "Test Capability" in str_repr


class TestServiceExample:
    """Test ServiceExample data model."""

    def test_create_service_example(self):
        """Test creating a service example with valid data."""
        example = ServiceExample(
            example_id="ex1",
            user_query="Why is my query slow?",
            expected_capability="identify_slow_queries",
        )

        assert example.example_id == "ex1"
        assert example.user_query == "Why is my query slow?"
        assert example.expected_capability == "identify_slow_queries"

    def test_service_example_immutable(self):
        """Test that ServiceExample is immutable."""
        example = ServiceExample(
            example_id="ex1",
            user_query="Test query",
            expected_capability="test_cap",
        )

        with pytest.raises(AttributeError):
            example.user_query = "Modified"  # type: ignore


class TestServiceType:
    """Test ServiceType enum."""

    def test_service_type_values(self):
        """Test that ServiceType has expected values."""
        assert ServiceType.AGENT.value == "agent"
        assert ServiceType.TOOL.value == "tool"
        assert ServiceType.CAPABILITY.value == "capability"

    def test_service_type_from_string(self):
        """Test creating ServiceType from string."""
        assert ServiceType("agent") == ServiceType.AGENT
        assert ServiceType("tool") == ServiceType.TOOL
        assert ServiceType("capability") == ServiceType.CAPABILITY

    def test_service_type_invalid_value(self):
        """Test that invalid service type raises error."""
        with pytest.raises(ValueError):
            ServiceType("invalid")


class TestServiceStatus:
    """Test ServiceStatus enum."""

    def test_service_status_values(self):
        """Test that ServiceStatus has expected values."""
        assert ServiceStatus.ACTIVE.value == "active"
        assert ServiceStatus.BETA.value == "beta"
        assert ServiceStatus.DEPRECATED.value == "deprecated"

    def test_service_status_from_string(self):
        """Test creating ServiceStatus from string."""
        assert ServiceStatus("active") == ServiceStatus.ACTIVE
        assert ServiceStatus("beta") == ServiceStatus.BETA
        assert ServiceStatus("deprecated") == ServiceStatus.DEPRECATED

    def test_service_status_invalid_value(self):
        """Test that invalid status raises error."""
        with pytest.raises(ValueError):
            ServiceStatus("invalid")


class TestServiceCatalogEntry:
    """Test ServiceCatalogEntry data model."""

    def test_create_minimal_catalog_entry(self):
        """Test creating a catalog entry with minimal required fields."""
        entry = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Analyzes Spark performance bottlenecks",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        assert entry.service_id == "perf_analyzer"
        assert entry.service_type == ServiceType.AGENT
        assert entry.name == "Performance Analyzer"
        assert entry.domain == "performance"
        assert entry.description == "Analyzes Spark performance bottlenecks"
        assert entry.capabilities == ()
        assert entry.version == "1.0.0"
        assert entry.status == ServiceStatus.ACTIVE
        assert entry.input_schema is None
        assert entry.examples == ()

    def test_create_full_catalog_entry(self):
        """Test creating a catalog entry with all fields."""
        capabilities = (
            ServiceCapability(
                capability_id="identify_slow_queries",
                name="Identify Slow Queries",
                description="Finds slow queries",
            ),
            ServiceCapability(
                capability_id="analyze_spark_ui",
                name="Analyze Spark UI",
                description="Analyzes Spark UI metrics",
            ),
        )

        examples = (
            ServiceExample(
                example_id="ex1",
                user_query="Why is my query slow?",
                expected_capability="identify_slow_queries",
            ),
        )

        input_schema = {
            "type": "object",
            "properties": {
                "query_id": {"type": "string"},
            },
        }

        entry = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Analyzes Spark performance bottlenecks",
            capabilities=capabilities,
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
            input_schema=input_schema,
            examples=examples,
        )

        assert len(entry.capabilities) == 2
        assert entry.capabilities[0].capability_id == "identify_slow_queries"
        assert len(entry.examples) == 1
        assert entry.input_schema == input_schema

    def test_catalog_entry_immutable(self):
        """Test that ServiceCatalogEntry is immutable."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service",
            domain="test",
            description="Test description",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        with pytest.raises(AttributeError):
            entry.name = "Modified"  # type: ignore

    def test_catalog_entry_validation_empty_service_id(self):
        """Test that empty service_id is rejected."""
        with pytest.raises(ValueError, match="service_id cannot be empty"):
            ServiceCatalogEntry(
                service_id="",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )

    def test_catalog_entry_validation_empty_name(self):
        """Test that empty name is rejected."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )

    def test_catalog_entry_validation_empty_domain(self):
        """Test that empty domain is rejected."""
        with pytest.raises(ValueError, match="domain cannot be empty"):
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )

    def test_catalog_entry_validation_invalid_version(self):
        """Test that invalid semantic version is rejected."""
        with pytest.raises(ValueError, match="version must follow semantic versioning"):
            ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version="invalid",
                status=ServiceStatus.ACTIVE,
            )

    def test_catalog_entry_valid_versions(self):
        """Test that valid semantic versions are accepted."""
        valid_versions = ["1.0.0", "2.1.3", "0.1.0", "10.20.30"]

        for version in valid_versions:
            entry = ServiceCatalogEntry(
                service_id="test_service",
                service_type=ServiceType.AGENT,
                name="Test",
                domain="test",
                description="Test",
                capabilities=(),
                version=version,
                status=ServiceStatus.ACTIVE,
            )
            assert entry.version == version

    def test_catalog_entry_to_dict(self):
        """Test serialization to dictionary."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service",
            domain="test",
            description="Test description",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        result = entry.to_dict()

        assert isinstance(result, dict)
        assert result["service_id"] == "test_service"
        assert result["service_type"] == "agent"
        assert result["name"] == "Test Service"
        assert result["domain"] == "test"
        assert result["version"] == "1.0.0"
        assert result["status"] == "active"
        assert result["capabilities"] == []
        assert result["examples"] == []

    def test_catalog_entry_to_dict_with_nested_objects(self):
        """Test serialization with nested capabilities and examples."""
        capability = ServiceCapability(
            capability_id="test_cap",
            name="Test Capability",
            description="Test",
        )

        example = ServiceExample(
            example_id="ex1",
            user_query="Test query",
            expected_capability="test_cap",
        )

        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(capability,),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
            examples=(example,),
        )

        result = entry.to_dict()

        assert len(result["capabilities"]) == 1
        assert result["capabilities"][0]["capability_id"] == "test_cap"
        assert len(result["examples"]) == 1
        assert result["examples"][0]["example_id"] == "ex1"

    def test_catalog_entry_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "service_id": "test_service",
            "service_type": "agent",
            "name": "Test Service",
            "domain": "test",
            "description": "Test description",
            "capabilities": [],
            "version": "1.0.0",
            "status": "active",
            "input_schema": None,
            "examples": [],
        }

        entry = ServiceCatalogEntry.from_dict(data)

        assert entry.service_id == "test_service"
        assert entry.service_type == ServiceType.AGENT
        assert entry.name == "Test Service"
        assert entry.status == ServiceStatus.ACTIVE

    def test_catalog_entry_from_dict_with_nested_objects(self):
        """Test deserialization with nested objects."""
        data = {
            "service_id": "test_service",
            "service_type": "agent",
            "name": "Test",
            "domain": "test",
            "description": "Test",
            "capabilities": [
                {
                    "capability_id": "cap1",
                    "name": "Capability 1",
                    "description": "Test capability",
                }
            ],
            "version": "1.0.0",
            "status": "active",
            "examples": [
                {
                    "example_id": "ex1",
                    "user_query": "Test query",
                    "expected_capability": "cap1",
                }
            ],
        }

        entry = ServiceCatalogEntry.from_dict(data)

        assert len(entry.capabilities) == 1
        assert entry.capabilities[0].capability_id == "cap1"
        assert len(entry.examples) == 1
        assert entry.examples[0].example_id == "ex1"

    def test_catalog_entry_equality(self):
        """Test equality comparison of catalog entries."""
        entry1 = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        entry2 = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        entry3 = ServiceCatalogEntry(
            service_id="different_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        assert entry1 == entry2
        assert entry1 != entry3

    def test_catalog_entry_hash(self):
        """Test that catalog entries are hashable."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        # Should be hashable for use in sets/dicts
        entry_set = {entry}
        assert entry in entry_set
