"""Tests for source v2 adapter.

Test coverage for SourceTools v2 interface:
- Clean async signatures
- Dict returns
- Integration with service layer
- Error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]
from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.tools.adapters.source_tools import SourceTools


def create_mock_async_client():
    """Create a mock AsyncDatabricksClient with async methods."""
    mock = MagicMock()

    # Mock jobs service with async get_job
    mock.jobs = MagicMock()
    mock.jobs.get_job = AsyncMock()

    # Mock workspace service with async get_notebook_content
    mock.workspace = MagicMock()
    mock.workspace.get_notebook_content = AsyncMock()

    return mock


class TestSourceToolsV2:
    """Test SourceTools v2 adapter."""

    @pytest.fixture
    def mock_api(self):
        """Create mock Async Databricks client."""
        return create_mock_async_client()

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM client."""
        mock = MagicMock(spec=BaseLLMClient)
        return mock

    @pytest.fixture
    def source_tools(self, mock_api, mock_llm):
        """Create SourceTools instance."""
        return SourceTools(api=mock_api, llm_client=mock_llm)

    @pytest.mark.asyncio
    async def test_get_source_code_returns_json(self, source_tools):
        """Test get_source_code returns valid dict."""
        with patch.object(
            source_tools,
            "_inspect_source_code",
            new_callable=AsyncMock,
            return_value={
                "task_sources": {
                    "task1": {
                        "type": "notebook",
                        "path": "/path",
                        "source": "code",
                    }
                },
                "has_source_code": True,
            },
        ):
            result = await source_tools.get_source_code("12345")

            assert isinstance(result, dict)
            assert "task_sources" in result
            assert "has_source_code" in result

    @pytest.mark.asyncio
    async def test_analyze_code_quality_returns_json(self, source_tools):
        """Test analyze_code_quality returns valid dict."""
        with patch.object(
            source_tools,
            "_analyze_code_quality",
            new_callable=AsyncMock,
            return_value={
                "code_quality_issues": [{"severity": "high", "issue": "Full scan"}],
                "code_quality_notes": ["Analysis complete"],
            },
        ):
            result = await source_tools.analyze_code_quality(source_code="SELECT *")

            assert isinstance(result, dict)
            # SourceTools returns 'issues' and 'notes', not 'code_quality_issues'
            assert "issues" in result
            assert "notes" in result
            assert "issue_count" in result
            assert result["issue_count"] == 1

    @pytest.mark.asyncio
    async def test_get_source_code_with_task_key_filter(self, source_tools):
        """Test get_source_code with task_key filter."""
        mock_result = {
            "task_sources": {"filtered_task": {}},
            "has_source_code": True,
        }
        with patch.object(
            source_tools,
            "_inspect_source_code",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_inspect:
            result = await source_tools.get_source_code(
                "12345", task_key="filtered_task"
            )

            # Check that the method was called with correct positional args
            mock_inspect.assert_called_once()
            call_args = mock_inspect.call_args
            assert call_args[0][0] == "12345"  # job_id
            assert call_args[0][1] == "filtered_task"  # task_key
            assert "task_sources" in result

    @pytest.mark.asyncio
    async def test_analyze_handles_no_source(self, source_tools):
        """Test analyze_code_quality handles empty source gracefully."""
        with patch.object(
            source_tools,
            "_analyze_code_quality",
            new_callable=AsyncMock,
            return_value={
                "code_quality_issues": [],
                "code_quality_notes": [],
            },
        ):
            result = await source_tools.analyze_code_quality()

            assert isinstance(result, dict)
            # SourceTools returns 'issues', not 'code_quality_issues'
            assert "issues" in result
            assert result["issues"] == []
            assert "issue_count" in result
            assert result["issue_count"] == 0

    @pytest.mark.asyncio
    async def test_get_source_code_handles_api_errors(self, source_tools):
        """Test get_source_code handles API errors."""
        with (
            patch.object(
                source_tools,
                "_inspect_source_code",
                new_callable=AsyncMock,
                side_effect=Exception("API error"),
            ),
            pytest.raises(Exception, match="API error"),
        ):
            await source_tools.get_source_code("12345")

    @pytest.mark.asyncio
    async def test_analyze_handles_llm_errors(self, source_tools):
        """Test analyze_code_quality handles LLM errors gracefully."""
        with patch.object(
            source_tools,
            "_analyze_code_quality",
            new_callable=AsyncMock,
            return_value={
                "code_quality_issues": [],
                "code_quality_notes": ["Analysis failed due to LLM error"],
            },
        ):
            result = await source_tools.analyze_code_quality(source_code="SELECT 1")

            assert isinstance(result, dict)
            # SourceTools returns 'notes', not 'code_quality_notes'
            assert "notes" in result
            # Should return gracefully with error note
            assert any("failed" in note.lower() for note in result["notes"])


class TestSourceToolsIntegration:
    """Integration tests for SourceTools with mock service."""

    @pytest.fixture
    def mock_api(self):
        """Create mock Async Databricks client with return values."""
        mock = create_mock_async_client()
        mock.jobs.get_job.return_value = {
            "settings": {
                "tasks": [
                    {
                        "task_key": "task1",
                        "notebook_task": {"notebook_path": "/path"},
                    }
                ]
            }
        }
        mock.workspace.get_notebook_content.return_value = "# Code"
        return mock

    @pytest.fixture
    def source_tools(self, mock_api):
        """Create SourceTools without LLM."""
        return SourceTools(api=mock_api)

    @pytest.mark.asyncio
    async def test_full_inspection_flow(self, source_tools):
        """Test complete source inspection flow."""
        result = await source_tools.get_source_code("12345")

        assert isinstance(result, dict)
        assert "task_sources" in result
        assert "has_source_code" in result
