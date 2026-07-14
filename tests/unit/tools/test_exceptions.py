# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for tool-specific exceptions."""

import pytest
from starboard.tools.exceptions import (
    AccessDeniedError,
    ClusterNotFoundError,
    DataUnavailableError,
    JobNotFoundError,
    SparkLogsUnavailableError,
    TableNotFoundError,
    ToolError,
    WarehouseNotFoundError,
)


class TestToolError:
    """Tests for base ToolError exception."""

    def test_basic_initialization(self):
        """Test basic ToolError initialization."""
        error = ToolError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.details == {}

    def test_initialization_with_details(self):
        """Test ToolError with details."""
        details = {"key": "value", "count": 42}
        error = ToolError("Error occurred", details=details)
        assert error.message == "Error occurred"
        assert error.details == {"key": "value", "count": 42}

    def test_to_dict(self):
        """Test conversion to dict for LLM responses."""
        error = ToolError("Error message", details={"context": "test"})
        result = error.to_dict()
        assert result["found"] is False
        assert result["error"] == "Error message"
        assert result["error_type"] == "tool_error"
        assert result["details"]["context"] == "test"

    def test_inheritance(self):
        """Test that ToolError inherits from Exception."""
        error = ToolError("test")
        assert isinstance(error, Exception)


class TestClusterNotFoundError:
    """Tests for ClusterNotFoundError."""

    def test_initialization(self):
        """Test ClusterNotFoundError initialization."""
        error = ClusterNotFoundError("cluster-123")
        assert error.cluster_id == "cluster-123"
        assert error.resource_type == "Cluster"
        assert error.resource_id == "cluster-123"
        assert "cluster-123" in str(error)
        assert "Cluster" in str(error)

    def test_to_dict(self):
        """Test conversion to dict."""
        error = ClusterNotFoundError("cluster-456")
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "cluster_not_found"
        assert result["cluster_id"] == "cluster-456"

    def test_inheritance(self):
        """Test inheritance hierarchy."""
        error = ClusterNotFoundError("test")
        assert isinstance(error, ToolError)


class TestWarehouseNotFoundError:
    """Tests for WarehouseNotFoundError."""

    def test_initialization(self):
        """Test WarehouseNotFoundError initialization."""
        error = WarehouseNotFoundError("warehouse-abc")
        assert error.warehouse_id == "warehouse-abc"
        assert error.resource_type == "Warehouse"
        assert error.resource_id == "warehouse-abc"
        assert "warehouse-abc" in str(error)

    def test_to_dict(self):
        """Test conversion to dict."""
        error = WarehouseNotFoundError("wh-789")
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "warehouse_not_found"
        assert result["warehouse_id"] == "wh-789"


class TestJobNotFoundError:
    """Tests for JobNotFoundError."""

    def test_initialization(self):
        """Test JobNotFoundError initialization."""
        error = JobNotFoundError("12345")
        assert error.job_id == "12345"
        assert error.resource_type == "Job"
        assert error.resource_id == "12345"

    def test_to_dict(self):
        """Test conversion to dict."""
        error = JobNotFoundError("job-999")
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "job_not_found"
        assert result["job_id"] == "job-999"


class TestTableNotFoundError:
    """Tests for TableNotFoundError."""

    def test_initialization(self):
        """Test TableNotFoundError initialization."""
        error = TableNotFoundError("catalog.schema.table")
        assert error.table_name == "catalog.schema.table"
        assert error.resource_type == "Table"
        assert error.resource_id == "catalog.schema.table"

    def test_to_dict(self):
        """Test conversion to dict."""
        error = TableNotFoundError("main.default.users")
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "table_not_found"
        assert result["table_name"] == "main.default.users"


class TestDataUnavailableError:
    """Tests for DataUnavailableError."""

    def test_initialization(self):
        """Test DataUnavailableError initialization."""
        error = DataUnavailableError("Data not ready", reason="still processing")
        assert error.message == "Data not ready"
        assert error.reason == "still processing"

    def test_to_dict(self):
        """Test conversion to dict."""
        error = DataUnavailableError("Metrics unavailable", reason="cluster terminated")
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "data_unavailable"
        assert result["reason"] == "cluster terminated"


class TestSparkLogsUnavailableError:
    """Tests for SparkLogsUnavailableError."""

    def test_initialization(self):
        """Test SparkLogsUnavailableError initialization."""
        error = SparkLogsUnavailableError(
            cluster_id="cluster-xyz",
            reason="Logging not configured",
        )
        assert error.cluster_id == "cluster-xyz"
        assert error.reason == "Logging not configured"
        assert "cluster-xyz" in str(error)
        assert "Logging not configured" in str(error)

    def test_to_dict(self):
        """Test conversion to dict."""
        error = SparkLogsUnavailableError(
            cluster_id="cl-001",
            reason="Logs expired",
        )
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "spark_logs_unavailable"
        assert result["cluster_id"] == "cl-001"
        assert result["reason"] == "Logs expired"

    def test_inheritance(self):
        """Test that SparkLogsUnavailableError inherits from DataUnavailableError."""
        error = SparkLogsUnavailableError("cl-1", "test")
        assert isinstance(error, DataUnavailableError)
        assert isinstance(error, ToolError)


class TestAccessDeniedError:
    """Tests for AccessDeniedError."""

    def test_initialization(self):
        """Test AccessDeniedError initialization."""
        error = AccessDeniedError(
            resource_type="Cluster",
            resource_id="cluster-private",
            required_permission="CAN_MANAGE",
        )
        assert error.resource_type == "Cluster"
        assert error.resource_id == "cluster-private"
        assert error.required_permission == "CAN_MANAGE"

    def test_to_dict(self):
        """Test conversion to dict."""
        error = AccessDeniedError(
            resource_type="Warehouse",
            resource_id="wh-secure",
            required_permission="CAN_USE",
        )
        result = error.to_dict()
        assert result["found"] is False
        assert result["error_type"] == "access_denied"
        assert result["resource_type"] == "Warehouse"
        assert result["resource_id"] == "wh-secure"
        assert result["required_permission"] == "CAN_USE"

    def test_default_permission(self):
        """Test AccessDeniedError with default permission."""
        error = AccessDeniedError(
            resource_type="Table",
            resource_id="catalog.schema.secret_table",
        )
        assert error.required_permission is None


class TestExceptionCatching:
    """Tests for exception handling patterns."""

    def test_catch_specific_not_found(self):
        """Test catching specific not found errors."""
        errors = [
            ClusterNotFoundError("c1"),
            WarehouseNotFoundError("w1"),
            JobNotFoundError("j1"),
            TableNotFoundError("t1"),
        ]

        for error in errors:
            # All should be catchable as ToolError
            try:
                raise error
            except ToolError as e:
                assert e.to_dict()["found"] is False

    def test_catch_data_unavailable_hierarchy(self):
        """Test catching DataUnavailableError catches SparkLogsUnavailableError."""
        error = SparkLogsUnavailableError("cl-1", "not configured")

        with pytest.raises(DataUnavailableError):
            raise error

        with pytest.raises(ToolError):
            raise error
