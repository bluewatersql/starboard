"""Tests for custom exception hierarchy.

Tests cover:
- Base exception functionality
- Exception inheritance hierarchy
- String representation with details
- Domain-specific exception types
- Context and detail preservation
- Error message formatting

Examples:
    >>> raise ResourceNotFoundError("table", "my_table", {"catalog": "main"})
    >>> raise APIRateLimitError(retry_after=60)
"""

import pytest
from starboard_server.infra.reliability.exceptions import (
    APIRateLimitError,
    ApprovalRequiredError,
    ConfigurationError,
    DatabricksAPIError,
    DataProcessingError,
    InvalidDataFormatError,
    InvalidResourceStateError,
    InvalidSQLError,
    MissingDataError,
    MissingParameterError,
    ResourceNotFoundError,
    SparkLogPathNotFoundError,
    StarboardAgentError,
    TaskExecutionError,
    UnsafeSQLError,
    ValidationError,
    WorkflowError,
)


class TestStarboardAgentErrorBase:
    """Tests for base exception functionality."""

    def test_base_exception_with_message(self):
        """Test base exception creation with message."""
        error = StarboardAgentError("Test error message")

        assert str(error) == "Test error message"
        assert error.message == "Test error message"
        assert error.details == {}

    def test_base_exception_with_details(self):
        """Test base exception with additional details."""
        details = {"key1": "value1", "key2": 42}
        error = StarboardAgentError("Error occurred", details=details)

        assert error.message == "Error occurred"
        assert error.details == details
        assert "key1=value1" in str(error)
        assert "key2=42" in str(error)

    def test_base_exception_string_representation_with_details(self):
        """Test string representation includes details."""
        error = StarboardAgentError(
            "Error", details={"user_id": "123", "action": "delete"}
        )

        result = str(error)

        assert "Error" in result
        assert "user_id=123" in result
        assert "action=delete" in result

    def test_base_exception_empty_details_omitted(self):
        """Test that empty details don't appear in string."""
        error = StarboardAgentError("Simple error")

        assert str(error) == "Simple error"
        assert "(" not in str(error)


class TestDatabricksAPIErrors:
    """Tests for Databricks API specific exceptions."""

    def test_resource_not_found_error(self):
        """Test ResourceNotFoundError creation."""
        error = ResourceNotFoundError("table", "my_catalog.my_schema.my_table")

        assert error.resource_type == "table"
        assert error.resource_id == "my_catalog.my_schema.my_table"
        assert "table not found" in str(error).lower()
        assert "my_catalog.my_schema.my_table" in str(error)

    def test_resource_not_found_with_details(self):
        """Test ResourceNotFoundError with additional details."""
        details = {"catalog": "main", "schema": "default"}
        error = ResourceNotFoundError("warehouse", "warehouse_123", details=details)

        assert error.resource_type == "warehouse"
        assert error.resource_id == "warehouse_123"
        assert error.details == details
        assert "warehouse" in str(error).lower()

    def test_invalid_resource_state_error(self):
        """Test InvalidResourceStateError creation."""
        error = InvalidResourceStateError(
            "cluster", "cluster_abc", "TERMINATED", "RUNNING"
        )

        assert error.resource_type == "cluster"
        assert error.resource_id == "cluster_abc"
        assert error.current_state == "TERMINATED"
        assert error.expected_state == "RUNNING"
        assert "TERMINATED" in str(error)
        assert "RUNNING" in str(error)

    def test_api_rate_limit_error_without_retry(self):
        """Test APIRateLimitError without retry_after."""
        error = APIRateLimitError()

        assert error.retry_after is None
        assert "rate limit exceeded" in str(error).lower()

    def test_api_rate_limit_error_with_retry(self):
        """Test APIRateLimitError with retry_after."""
        error = APIRateLimitError(retry_after=120)

        assert error.retry_after == 120
        assert "120" in str(error)
        assert "retry after" in str(error).lower()

    def test_api_errors_inherit_from_databricks_error(self):
        """Test that API errors inherit from DatabricksAPIError."""
        assert issubclass(ResourceNotFoundError, DatabricksAPIError)
        assert issubclass(InvalidResourceStateError, DatabricksAPIError)
        assert issubclass(APIRateLimitError, DatabricksAPIError)

    def test_databricks_error_inherits_from_base(self):
        """Test that DatabricksAPIError inherits from base."""
        assert issubclass(DatabricksAPIError, StarboardAgentError)


class TestValidationErrors:
    """Tests for validation exception types."""

    def test_invalid_sql_error(self):
        """Test InvalidSQLError creation."""
        sql = "SELECT * FROM table WHERE id = ?"
        error = InvalidSQLError(sql, "Missing parameter placeholder")

        assert error.sql == sql
        assert error.reason == "Missing parameter placeholder"
        assert "Invalid SQL" in str(error)
        assert "Missing parameter" in str(error)

    def test_unsafe_sql_error(self):
        """Test UnsafeSQLError creation."""
        sql = "DROP TABLE users;"
        forbidden = ["DROP", "DELETE"]
        error = UnsafeSQLError(sql, forbidden)

        assert error.sql == sql
        assert error.forbidden_operations == forbidden
        assert "Unsafe SQL" in str(error)
        assert "DROP" in str(error)
        assert "DELETE" in str(error)

    def test_unsafe_sql_error_multiple_operations(self):
        """Test UnsafeSQLError with multiple forbidden operations."""
        error = UnsafeSQLError("TRUNCATE users; DROP DATABASE;", ["TRUNCATE", "DROP"])

        result = str(error)

        assert "TRUNCATE" in result
        assert "DROP" in result

    def test_missing_parameter_error(self):
        """Test MissingParameterError creation."""
        error = MissingParameterError("api_key", "authentication")

        assert error.parameter_name == "api_key"
        assert error.context == "authentication"
        assert "api_key" in str(error)
        assert "authentication" in str(error)
        assert "required parameter" in str(error).lower()

    def test_validation_errors_inherit_correctly(self):
        """Test validation error inheritance."""
        assert issubclass(InvalidSQLError, ValidationError)
        assert issubclass(UnsafeSQLError, ValidationError)
        assert issubclass(MissingParameterError, ValidationError)
        assert issubclass(ValidationError, StarboardAgentError)


class TestDataProcessingErrors:
    """Tests for data processing exception types."""

    def test_spark_log_path_not_found_error(self):
        """Test SparkLogPathNotFoundError creation."""
        error = SparkLogPathNotFoundError("/dbfs/spark-logs/app_123", "cluster_456")

        assert error.log_path == "/dbfs/spark-logs/app_123"
        assert error.cluster_id == "cluster_456"
        assert "log path does not exist" in str(error).lower()
        assert "/dbfs/spark-logs/app_123" in str(error)
        assert "cluster_456" in str(error)

    def test_spark_log_error_without_cluster_id(self):
        """Test SparkLogPathNotFoundError without cluster_id."""
        error = SparkLogPathNotFoundError("/path/to/logs")

        assert error.log_path == "/path/to/logs"
        assert error.cluster_id is None
        assert "/path/to/logs" in str(error)

    def test_missing_data_error(self):
        """Test MissingDataError creation."""
        error = MissingDataError("query_result", "warehouse_response")

        assert error.data_key == "query_result"
        assert error.source == "warehouse_response"
        assert "query_result" in str(error)
        assert "warehouse_response" in str(error)
        assert "not found" in str(error).lower()

    def test_invalid_data_format_error(self):
        """Test InvalidDataFormatError creation."""
        error = InvalidDataFormatError("timestamp", "ISO8601", "Unix epoch")

        assert error.data_key == "timestamp"
        assert error.expected_type == "ISO8601"
        assert error.actual_type == "Unix epoch"
        assert "Invalid data format" in str(error)
        assert "timestamp" in str(error)
        assert "ISO8601" in str(error)
        assert "Unix epoch" in str(error)

    def test_data_processing_errors_inherit_correctly(self):
        """Test data processing error inheritance."""
        assert issubclass(SparkLogPathNotFoundError, DataProcessingError)
        assert issubclass(MissingDataError, DataProcessingError)
        assert issubclass(InvalidDataFormatError, DataProcessingError)
        assert issubclass(DataProcessingError, StarboardAgentError)


class TestWorkflowErrors:
    """Tests for workflow execution exception types."""

    def test_task_execution_error(self):
        """Test TaskExecutionError creation."""
        error = TaskExecutionError("data_processing", "Timeout exceeded")

        assert error.task_name == "data_processing"
        assert error.reason == "Timeout exceeded"
        assert error.original_error is None
        assert "data_processing" in str(error)
        assert "Timeout exceeded" in str(error)

    def test_task_execution_error_with_original_error(self):
        """Test TaskExecutionError with original exception."""
        original = ValueError("Connection failed")
        error = TaskExecutionError("api_call", "Network error", original_error=original)

        assert error.task_name == "api_call"
        assert error.reason == "Network error"
        assert error.original_error == original

    def test_approval_required_error(self):
        """Test ApprovalRequiredError creation."""
        error = ApprovalRequiredError("delete_table", "Destructive operation")

        assert error.operation == "delete_table"
        assert error.reason == "Destructive operation"
        assert error.required_token == "approval_token"
        assert "delete_table" in str(error)
        assert "approval" in str(error).lower()

    def test_approval_required_custom_token(self):
        """Test ApprovalRequiredError with custom token."""
        error = ApprovalRequiredError(
            "modify_production",
            "Production environment",
            required_token="prod_access_token",
        )

        assert error.required_token == "prod_access_token"

    def test_workflow_errors_inherit_correctly(self):
        """Test workflow error inheritance."""
        assert issubclass(TaskExecutionError, WorkflowError)
        assert issubclass(ApprovalRequiredError, WorkflowError)
        assert issubclass(WorkflowError, StarboardAgentError)


class TestConfigurationErrors:
    """Tests for configuration exception types."""

    def test_configuration_error(self):
        """Test ConfigurationError creation."""
        error = ConfigurationError("database.connection_string", "Invalid format")

        assert error.config_key == "database.connection_string"
        assert error.reason == "Invalid format"
        assert "database.connection_string" in str(error)
        assert "Invalid format" in str(error)
        assert "Configuration error" in str(error)

    def test_configuration_error_with_details(self):
        """Test ConfigurationError with additional details."""
        details = {"expected_format": "postgres://", "actual_format": "mysql://"}
        error = ConfigurationError("db_url", "Wrong database type", details=details)

        assert error.details == details
        assert "expected_format" in str(error)


class TestExceptionInheritance:
    """Tests for exception hierarchy correctness."""

    def test_all_exceptions_inherit_from_base(self):
        """Test that all custom exceptions inherit from StarboardAgentError."""
        exception_classes = [
            DatabricksAPIError,
            ResourceNotFoundError,
            InvalidResourceStateError,
            APIRateLimitError,
            ValidationError,
            InvalidSQLError,
            UnsafeSQLError,
            MissingParameterError,
            DataProcessingError,
            SparkLogPathNotFoundError,
            MissingDataError,
            InvalidDataFormatError,
            WorkflowError,
            TaskExecutionError,
            ApprovalRequiredError,
            ConfigurationError,
        ]

        for exc_class in exception_classes:
            assert issubclass(exc_class, StarboardAgentError)

    def test_intermediate_exceptions_are_abstract(self):
        """Test that intermediate exception classes can be raised."""
        # These should be usable as exceptions themselves
        assert issubclass(DatabricksAPIError, Exception)
        assert issubclass(ValidationError, Exception)
        assert issubclass(DataProcessingError, Exception)
        assert issubclass(WorkflowError, Exception)


class TestExceptionUsage:
    """Tests for practical exception usage patterns."""

    def test_raising_and_catching_specific_exception(self):
        """Test raising and catching specific exception types."""
        with pytest.raises(ResourceNotFoundError) as exc_info:
            raise ResourceNotFoundError("table", "my_table")

        assert exc_info.value.resource_type == "table"

    def test_catching_by_category(self):
        """Test that exceptions can be caught by category."""
        with pytest.raises(DatabricksAPIError):
            raise ResourceNotFoundError("table", "my_table")

        with pytest.raises(ValidationError):
            raise InvalidSQLError("SELECT *", "Incomplete")

    def test_catching_base_exception(self):
        """Test that all exceptions can be caught as StarboardAgentError."""
        with pytest.raises(StarboardAgentError):
            raise ResourceNotFoundError("table", "my_table")

    def test_exception_details_accessible_after_catch(self):
        """Test that exception details are accessible after catching."""
        try:
            raise InvalidSQLError("SELECT *", "Missing FROM", {"line": 1})
        except InvalidSQLError as e:
            assert e.sql == "SELECT *"
            assert e.reason == "Missing FROM"
            assert e.details["line"] == 1
