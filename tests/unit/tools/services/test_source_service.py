# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SourceTools internal methods.

Tests for source code extraction and analysis functionality.
All async methods are properly tested with pytest-asyncio.

Note: These tests exercise the internal implementation methods of SourceTools
(formerly SourceService) which are now private methods prefixed with '_'.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from starboard_server.tools.adapters.source_tools import SourceTools


class MockDatabricksAPI:
    """Mock Databricks API for testing.
    Provides async mock methods matching the AsyncDatabricksClient interface.
    """

    def __init__(self):
        """Initialize with mock jobs and workspace services."""
        self.jobs = MagicMock()
        self.jobs.get_job = AsyncMock()
        self.workspace = MagicMock()
        self.workspace.get_notebook_content = AsyncMock()

        # Data stores for configuring test responses
        self._jobs_data: dict[int, dict[str, Any]] = {}
        self._notebooks_data: dict[str, str] = {}

    def set_job(self, job_id: int, job_data: dict[str, Any]) -> None:
        """Configure a job response."""
        self._jobs_data[job_id] = job_data
        self.jobs.get_job.side_effect = lambda jid: self._jobs_data.get(jid)

    def set_notebook(self, path: str, content: str) -> None:
        """Configure a notebook response."""
        self._notebooks_data[path] = content
        self.workspace.get_notebook_content.side_effect = lambda p: (
            self._notebooks_data.get(p)
        )


class TestSourceToolsInternal:
    """Tests for SourceTools internal methods."""

    @pytest.fixture
    def mock_api(self) -> MockDatabricksAPI:
        """Create mock Databricks API."""
        return MockDatabricksAPI()

    @pytest.fixture
    def tools(self, mock_api: MockDatabricksAPI) -> SourceTools:
        """Create SourceTools instance."""
        return SourceTools(api=mock_api)

    @pytest.mark.asyncio
    async def test_get_task_definitions_from_job(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test getting task definitions from a job."""
        mock_api.set_job(
            123,
            {
                "settings": {
                    "tasks": [
                        {
                            "task_key": "task1",
                            "notebook_task": {"notebook_path": "/path"},
                        },
                        {
                            "task_key": "task2",
                            "spark_python_task": {"python_file": "file.py"},
                        },
                    ]
                }
            },
        )

        tasks = await tools._get_task_definitions_from_job("123")

        assert len(tasks) == 2
        assert tasks[0]["task_key"] == "task1"
        assert tasks[1]["task_key"] == "task2"

    @pytest.mark.asyncio
    async def test_get_task_definitions_with_task_key_filter(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test getting specific task by task_key."""
        mock_api.set_job(
            123,
            {
                "settings": {
                    "tasks": [
                        {"task_key": "task1", "notebook_task": {}},
                        {"task_key": "task2", "spark_python_task": {}},
                    ]
                }
            },
        )

        tasks = await tools._get_task_definitions_from_job("123", task_key="task1")

        assert len(tasks) == 1
        assert tasks[0]["task_key"] == "task1"

    @pytest.mark.asyncio
    async def test_get_task_definitions_invalid_job_id(self, tools: SourceTools):
        """Test handling invalid job_id."""
        tasks = await tools._get_task_definitions_from_job("not-a-number")

        assert tasks == []

    @pytest.mark.asyncio
    async def test_get_task_definitions_job_not_found(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test handling non-existent job."""
        mock_api.jobs.get_job.return_value = None

        tasks = await tools._get_task_definitions_from_job("999")

        assert tasks == []

    @pytest.mark.asyncio
    async def test_extract_notebook_source(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test extracting notebook source code."""
        mock_api.set_notebook("/path/to/notebook", "# Notebook code here")

        task = {"notebook_task": {"notebook_path": "/path/to/notebook"}}

        source_info = await tools._extract_notebook_source(task)

        assert source_info is not None
        assert source_info["type"] == "notebook"
        assert source_info["path"] == "/path/to/notebook"
        assert "Notebook code" in source_info["source"]

    @pytest.mark.asyncio
    async def test_extract_notebook_source_missing_path(self, tools: SourceTools):
        """Test extracting notebook with missing path."""
        task = {"notebook_task": {}}

        source_info = await tools._extract_notebook_source(task)

        assert source_info is None

    @pytest.mark.asyncio
    async def test_extract_notebook_source_fetch_failed(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test extracting notebook when fetch fails."""
        # Notebook not in mock - will return None
        mock_api.workspace.get_notebook_content.return_value = None
        task = {"notebook_task": {"notebook_path": "/nonexistent"}}

        source_info = await tools._extract_notebook_source(task)

        assert source_info is None

    def test_extract_python_source(self, tools: SourceTools):
        """Test extracting Python file source (placeholder)."""
        task = {"spark_python_task": {"python_file": "/path/to/script.py"}}

        source_info = tools._extract_python_source(task)

        assert source_info is not None
        assert source_info["type"] == "python_file"
        assert source_info["path"] == "/path/to/script.py"
        assert "Source not available" in source_info["source"]

    def test_extract_python_source_missing_path(self, tools: SourceTools):
        """Test extracting Python with missing path."""
        task = {"spark_python_task": {}}

        source_info = tools._extract_python_source(task)

        assert source_info is None

    def test_extract_sql_source(self, tools: SourceTools):
        """Test extracting SQL source from task."""
        task = {"sql_task": {"query": {"query": "SELECT * FROM table"}}}

        source_info = tools._extract_sql_source(task)

        assert source_info is not None
        assert source_info["type"] == "sql"
        assert source_info["source"] == "SELECT * FROM table"

    def test_extract_sql_source_missing_query(self, tools: SourceTools):
        """Test extracting SQL with missing query."""
        task = {"sql_task": {"query": {}}}

        source_info = tools._extract_sql_source(task)

        assert source_info is None

    @pytest.mark.asyncio
    async def test_extract_task_source_notebook(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test extracting source from notebook task."""
        mock_api.set_notebook("/notebook", "# Code")

        task = {"task_key": "task1", "notebook_task": {"notebook_path": "/notebook"}}

        source_info = await tools._extract_task_source(task)

        assert source_info is not None
        assert source_info["type"] == "notebook"

    @pytest.mark.asyncio
    async def test_extract_task_source_python(self, tools: SourceTools):
        """Test extracting source from Python task."""
        task = {"task_key": "task1", "spark_python_task": {"python_file": "/file.py"}}

        source_info = await tools._extract_task_source(task)

        assert source_info is not None
        assert source_info["type"] == "python_file"

    @pytest.mark.asyncio
    async def test_extract_task_source_sql(self, tools: SourceTools):
        """Test extracting source from SQL task."""
        task = {"task_key": "task1", "sql_task": {"query": {"query": "SELECT 1"}}}

        source_info = await tools._extract_task_source(task)

        assert source_info is not None
        assert source_info["type"] == "sql"

    @pytest.mark.asyncio
    async def test_extract_task_source_unsupported_type(self, tools: SourceTools):
        """Test extracting source from unsupported task type."""
        task = {"task_key": "task1", "jar_task": {"jar": "app.jar"}}

        source_info = await tools._extract_task_source(task)

        assert source_info is None

    def test_tools_initialization(self, mock_api: MockDatabricksAPI):
        """Test tools initialization."""
        tools = SourceTools(api=mock_api)

        assert tools.databricks_api == mock_api
        assert tools.llm_client is None
        assert tools.events is not None  # Default EventEmitter created

    def test_tools_initialization_with_llm(self, mock_api: MockDatabricksAPI):
        """Test tools initialization with LLM client."""
        mock_llm = Mock()
        tools = SourceTools(api=mock_api, llm_client=mock_llm)

        assert tools.llm_client == mock_llm

    def test_tools_initialization_with_events(self, mock_api: MockDatabricksAPI):
        """Test tools initialization with event emitter."""
        mock_events = Mock()
        tools = SourceTools(api=mock_api, events=mock_events)

        assert tools.events == mock_events

    def test_emit_info_with_emitter(self, mock_api: MockDatabricksAPI):
        """Test emitting info event when emitter is available."""
        mock_events = Mock()
        tools = SourceTools(api=mock_api, events=mock_events)

        tools._emit_info("test_source", "test message")

        mock_events.emit_info.assert_called_once_with(
            source="test_source", message="test message"
        )

    def test_emit_info_without_emitter(self, tools: SourceTools):
        """Test emitting info event when default emitter available (should not error)."""
        # Should not raise error (default EventEmitter is always created)
        tools._emit_info("test_source", "test message")

    @pytest.mark.asyncio
    async def test_inspect_source_code(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test inspecting source code from job."""
        mock_api.set_job(
            123,
            {
                "settings": {
                    "tasks": [
                        {
                            "task_key": "notebook_task",
                            "notebook_task": {"notebook_path": "/notebook"},
                        }
                    ]
                }
            },
        )
        mock_api.set_notebook("/notebook", "# Notebook code")

        result = await tools._inspect_source_code("123")

        assert "task_sources" in result
        assert "has_source_code" in result
        assert result["has_source_code"] is True
        assert "notebook_task" in result["task_sources"]

    @pytest.mark.asyncio
    async def test_inspect_source_code_no_tasks(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test inspecting source code when no tasks found."""
        mock_api.set_job(123, {"settings": {"tasks": []}})

        result = await tools._inspect_source_code("123")

        assert result["has_source_code"] is False

    @pytest.mark.asyncio
    async def test_inspect_source_code_job_not_found(
        self, tools: SourceTools, mock_api: MockDatabricksAPI
    ):
        """Test inspecting source code for non-existent job."""
        mock_api.jobs.get_job.return_value = None

        result = await tools._inspect_source_code("999")

        assert result["has_source_code"] is False

    @pytest.mark.asyncio
    async def test_analyze_code_quality_without_llm(self, mock_api: MockDatabricksAPI):
        """Test code quality analysis without LLM client."""
        tools = SourceTools(api=mock_api)

        result = await tools._analyze_code_quality(source_code="SELECT * FROM table")

        assert "code_quality_issues" in result
        assert "code_quality_notes" in result
        # Should return empty results without LLM
        assert len(result["code_quality_issues"]) == 0

    @pytest.mark.asyncio
    async def test_analyze_code_quality_no_source(self, mock_api: MockDatabricksAPI):
        """Test code quality analysis with no source code."""
        mock_llm = Mock()
        tools = SourceTools(api=mock_api, llm_client=mock_llm)

        result = await tools._analyze_code_quality()

        assert result["code_quality_issues"] == []
        assert result["code_quality_notes"] == []
