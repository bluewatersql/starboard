# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pytest configuration and shared fixtures."""

import warnings
from unittest.mock import AsyncMock, Mock

import pytest  # pyright: ignore[reportMissingImports]
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.observability.events import EventEmitter

# Filter warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")


@pytest.fixture
def mock_config():
    """Provide a mock configuration for testing."""
    return EnvConfig(
        databricks_host="https://test.databricks.com",
        databricks_token="test_token",
        databricks_warehouse_id="test_warehouse",
        default_catalog="test_catalog",
        default_schema="test_schema",
        llm_provider="openai",
        llm_api_key="test_api_key",
        llm_model="test-model",
        llm_base_url="",
        llm_temperature=0.4,
        llm_max_tokens=8192,
    )


# WorkflowState fixture removed - all tools now use V2 architecture


@pytest.fixture
def event_emitter():
    """Provide an EventEmitter for testing."""
    return EventEmitter()


@pytest.fixture
def mock_event_emitter():
    """Provide a mocked EventEmitter for testing."""
    mock = Mock(spec=EventEmitter)
    mock.emit_info = Mock()
    mock.emit_trace = Mock()
    return mock


@pytest.fixture
def execution_context():
    """Provide a sample execution context for testing."""
    return {
        "warehouse_id": "test_warehouse",
        "target": "SELECT * FROM test_table",
        "mode": "online",
        "history_window": "14d",
        "metrics_window": "24h",
    }


@pytest.fixture
def mock_llm_client():
    """Provide a mocked LLM client for testing."""
    mock = Mock()
    mock.json_response = AsyncMock(
        return_value={
            "goal": "Test optimization",
            "mode": "online",
            "intents": [{"intent": "analyze_query", "reason": "Test reason"}],
        }
    )
    mock.text_response = AsyncMock(return_value="Test response text")
    mock.embed = Mock(return_value=[[0.1, 0.2, 0.3]])
    return mock


@pytest.fixture
def mock_llm_code_analysis():
    """Provide a mocked LLM client for code analysis testing."""
    mock = Mock()
    mock.json_response = AsyncMock(
        return_value={
            "hotspots": [
                {
                    "artifact": "test_task",
                    "risk": "high",
                    "issue": "Test issue",
                    "evidence": "Test evidence",
                    "signal": ["test"],
                    "line_range": "1-10",
                    "fix": {
                        "strategy": "Test fix",
                        "snippet_before": "before",
                        "snippet_after": "after",
                    },
                }
            ],
            "notes": ["Test note"],
        }
    )
    return mock


@pytest.fixture
def sample_task_sources():
    """Provide sample task sources for testing."""
    return {
        "notebook_task": {
            "type": "notebook",
            "path": "/Workspace/notebooks/etl_pipeline",
            "source": "# ETL Code\nimport spark\ndf = spark.read.table('source')\ndf.collect()",
        },
        "sql_task": {
            "type": "sql",
            "source": "SELECT * FROM production.sales WHERE date = current_date()",
        },
        "python_task": {
            "type": "python_file",
            "path": "dbfs:/FileStore/scripts/process.py",
            "source": "# Python processing script\nprint('Processing data')",
        },
    }


@pytest.fixture
def mock_context_provider():
    """Provide a mocked context provider for testing."""
    mock = Mock()

    # Mock query context
    query_context = Mock()
    query_context.get_query_text = AsyncMock(return_value="SELECT * FROM test_table")
    query_context.get_query_profile = AsyncMock(
        return_value={"duration_ms": 1000, "rows_produced": 100}
    )
    query_context.get_query_history = AsyncMock(return_value=[])
    query_context.get_warehouse_config = AsyncMock(
        return_value={"name": "test_warehouse", "cluster_size": "Small"}
    )

    mock.query = Mock(return_value=query_context)

    # Mock job context
    job_context = Mock()
    job_context.get_job_config = AsyncMock(
        return_value={"job_id": 123, "name": "test_job"}
    )
    job_context.get_job_runs = AsyncMock(return_value=[])
    job_context.get_cluster_config = AsyncMock(
        return_value={"cluster_id": "test_cluster"}
    )

    mock.job = Mock(return_value=job_context)

    return mock


@pytest.fixture
def sample_query_profile():
    """Provide a sample query profile for testing."""
    return {
        "statement_id": "test_statement_id",
        "query_text": "SELECT * FROM test_table WHERE id > 100",
        "warehouse_id": "test_warehouse",
        "executed_by": "test_user",
        "duration_ms": 5000,
        "rows_produced": 1000,
        "data_read_bytes": 1048576,
        "status": "FINISHED",
        "executed_at": "2025-10-31T12:00:00Z",
    }


@pytest.fixture
def sample_job_config():
    """Provide a sample job configuration for testing."""
    return {
        "job_id": 12345,
        "name": "test_job",
        "creator_user_name": "test_user",
        "created_time": 1698753600000,
        "tasks": [
            {
                "task_key": "test_task",
                "notebook_task": {"notebook_path": "/test/notebook"},
                "new_cluster": {
                    "spark_version": "13.3.x",
                    "node_type_id": "i3.xlarge",
                    "num_workers": 2,
                },
            }
        ],
        "schedule": {"quartz_cron_expression": "0 0 * * * ?", "timezone_id": "UTC"},
    }


@pytest.fixture
def sample_table_metadata():
    """Provide sample table metadata for testing."""
    return {
        "catalog_name": "test_catalog",
        "schema_name": "test_schema",
        "name": "test_table",
        "table_type": "MANAGED",
        "data_source_format": "DELTA",
        "columns": [
            {"name": "id", "type_text": "BIGINT", "type_name": "LONG", "position": 0},
            {
                "name": "name",
                "type_text": "STRING",
                "type_name": "STRING",
                "position": 1,
            },
        ],
        "storage_location": "s3://bucket/path/to/table",
        "created_at": 1698753600000,
        "updated_at": 1698753600000,
    }


@pytest.fixture(autouse=True)
def reset_event_emitter():
    """Reset EventEmitter state between tests."""
    yield
    # Cleanup if needed
