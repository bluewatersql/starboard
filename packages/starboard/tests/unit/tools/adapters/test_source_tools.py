# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for source v2 adapter.

Test coverage for SourceTools v2 interface:
- Clean async signatures
- Dict returns
- Integration with service layer
- Error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]
from starboard.adapters.llm.base import BaseLLMClient
from starboard.tools.adapters.source_tools import SourceTools


def create_mock_async_client():
    """Create a mock AsyncDatabricksClient with async methods."""
    mock = MagicMock()

    # Mock jobs service with async get_job
    mock.jobs = MagicMock()
    mock.jobs.get_job = AsyncMock()

    # Mock workspace service with async methods
    mock.workspace = MagicMock()
    mock.workspace.get_notebook_content = AsyncMock()
    mock.workspace.export_workspace_file = AsyncMock()
    mock.workspace.read_dbfs_file = AsyncMock()
    # list_workspace: default returns empty list (no imports resolved)
    mock.workspace.list_workspace = AsyncMock(return_value=[])

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


class TestExtractPythonSource:
    """Unit tests for _extract_python_source — Phase 1 source resolver."""

    @pytest.fixture
    def mock_api(self):
        """Create mock with export_workspace_file and read_dbfs_file stubs."""
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        """Create SourceTools backed by the mock API."""
        return SourceTools(api=mock_api)

    @pytest.mark.asyncio
    async def test_workspace_path_calls_export_and_returns_source(
        self, source_tools, mock_api
    ):
        """spark_python_task with /Workspace/... path returns source + walk metadata."""
        from starboard.tools.adapters.source_tools import (
            _MAX_BYTES,
            _MAX_DEPTH,
            _MAX_FILES,
        )

        mock_api.workspace.export_workspace_file.return_value = "print('hello')"
        task = {"spark_python_task": {"python_file": "/Workspace/Shared/etl.py"}}

        result = await source_tools._extract_python_source(task)

        # Core fields unchanged
        assert result is not None
        assert result["type"] == "python_file"
        assert result["path"] == "/Workspace/Shared/etl.py"
        assert result["source"] == "print('hello')"
        # Phase-3: walk metadata added
        assert "resolved_files" in result
        assert "resolution" in result
        assert result["resolved_files"][0] == {
            "path": "/Workspace/Shared/etl.py",
            "code": "print('hello')",
            "reason": "entry",
            "depth": 0,
        }
        res = result["resolution"]
        assert res["roots"] == ["/Workspace/Shared"]
        assert res["truncated"] is False
        assert res["limits"] == {
            "max_depth": _MAX_DEPTH,
            "max_files": _MAX_FILES,
            "max_bytes": _MAX_BYTES,
        }
        assert res["dropped"] == []
        mock_api.workspace.export_workspace_file.assert_called_once_with(
            "/Workspace/Shared/etl.py"
        )
        mock_api.workspace.read_dbfs_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_dbfs_path_calls_read_dbfs_and_returns_source(
        self, source_tools, mock_api
    ):
        """spark_python_task with dbfs:/... path fetches via read_dbfs_file."""
        mock_api.workspace.read_dbfs_file.return_value = "import pyspark"
        task = {"spark_python_task": {"python_file": "dbfs:/scripts/job.py"}}

        result = await source_tools._extract_python_source(task)

        assert result == {
            "type": "python_file",
            "path": "dbfs:/scripts/job.py",
            "source": "import pyspark",
        }
        mock_api.workspace.read_dbfs_file.assert_called_once_with("dbfs:/scripts/job.py")
        mock_api.workspace.export_workspace_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_s3_path_degrades_to_placeholder_without_fetch(
        self, source_tools, mock_api
    ):
        """spark_python_task with s3://... degrades to placeholder and calls NO fetch methods."""
        task = {"spark_python_task": {"python_file": "s3://my-bucket/scripts/job.py"}}

        result = await source_tools._extract_python_source(task)

        assert result is not None
        assert result["type"] == "python_file"
        assert result["path"] == "s3://my-bucket/scripts/job.py"
        assert "# Python file: s3://my-bucket/scripts/job.py" in result["source"]
        assert "# Source not available" in result["source"]
        mock_api.workspace.export_workspace_file.assert_not_called()
        mock_api.workspace.read_dbfs_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_returns_none_degrades_to_placeholder(
        self, source_tools, mock_api
    ):
        """When export_workspace_file returns None, result degrades to placeholder without crash."""
        mock_api.workspace.export_workspace_file.return_value = None
        task = {"spark_python_task": {"python_file": "/Workspace/Shared/missing.py"}}

        result = await source_tools._extract_python_source(task)

        assert result is not None
        assert result["type"] == "python_file"
        assert result["path"] == "/Workspace/Shared/missing.py"
        assert "# Python file: /Workspace/Shared/missing.py" in result["source"]
        assert "# Source not available" in result["source"]


# =============================================================================
# Part C — %run following BFS tests (TDD, written before implementation)
# =============================================================================


class TestExtractNotebookSourceRunFollowing:
    """Tests for the BFS %run-following logic in _extract_notebook_source.

    Uses a mock workspace client whose get_notebook_content returns source
    by path via side_effect mapping.
    """

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    def _make_side_effect(self, path_to_source: dict):
        """Return an async side_effect that maps path -> source (None if missing)."""
        async def _get(path):
            return path_to_source.get(path)
        return _get

    def _notebook_task(self, path: str) -> dict:
        return {"task_key": "task1", "notebook_task": {"notebook_path": path}}

    # ------------------------------------------------------------------
    # Zero %run → 1 resolved_file
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_zero_run_one_resolved_file(self, source_tools, mock_api):
        """A notebook with no %run → resolved_files has exactly 1 entry."""
        mock_api.workspace.get_notebook_content.return_value = "# just code\ndf = spark.range(1)"

        task = self._notebook_task("/Workspace/project/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        assert result["type"] == "notebook"
        assert result["path"] == "/Workspace/project/main"
        assert result["source"] == "# just code\ndf = spark.range(1)"
        assert len(result["resolved_files"]) == 1
        assert result["resolved_files"][0]["path"] == "/Workspace/project/main"
        assert result["resolved_files"][0]["reason"] == "entry"
        assert result["resolved_files"][0]["depth"] == 0
        assert result["resolution"]["truncated"] is False

    # ------------------------------------------------------------------
    # Entry + two %runs → 3 resolved_files
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_two_runs_three_resolved_files(self, source_tools, mock_api):
        """Entry + two distinct %runs → 3 entries, all fetched."""
        entry_src = "%run ./ingest\n%run ./transform\ndf.write.saveAsTable('out')"
        path_map = {
            "/Workspace/p/main": entry_src,
            "/Workspace/p/ingest": "# ingest code",
            "/Workspace/p/transform": "# transform code",
        }
        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        assert len(result["resolved_files"]) == 3
        paths = [f["path"] for f in result["resolved_files"]]
        assert "/Workspace/p/main" in paths
        assert "/Workspace/p/ingest" in paths
        assert "/Workspace/p/transform" in paths
        # Entry must be first
        assert result["resolved_files"][0]["path"] == "/Workspace/p/main"
        assert result["resolved_files"][0]["reason"] == "entry"
        assert result["resolution"]["truncated"] is False

    # ------------------------------------------------------------------
    # Cycle: A runs B, B runs A → each visited once
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_cycle_terminates(self, source_tools, mock_api):
        """Cycle A→B→A terminates; each notebook appears once."""
        path_map = {
            "/Workspace/p/a": "%run ./b\n# A code",
            "/Workspace/p/b": "%run ./a\n# B code",
        }
        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/a")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert paths.count("/Workspace/p/a") == 1
        assert paths.count("/Workspace/p/b") == 1
        assert len(result["resolved_files"]) == 2

    # ------------------------------------------------------------------
    # Missing %run target skipped gracefully
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_missing_run_target_skipped(self, source_tools, mock_api):
        """A %run whose target returns None is skipped; walk continues."""
        entry_src = "%run ./missing\n%run ./present\n# main"
        path_map = {
            "/Workspace/p/main": entry_src,
            "/Workspace/p/present": "# present code",
            # /Workspace/p/missing is absent → returns None
        }
        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert "/Workspace/p/main" in paths
        assert "/Workspace/p/present" in paths
        assert "/Workspace/p/missing" not in paths
        # Walk was not aborted
        assert len(result["resolved_files"]) == 2

    # ------------------------------------------------------------------
    # max_files bound → truncated=True
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_max_files_truncated(self, source_tools, mock_api):
        """When max_files is hit, truncated=True and no further files added."""
        from starboard.tools.adapters.source_tools import _MAX_FILES

        # Build more %runs than max_files so we hit the bound
        runs_count = _MAX_FILES  # entry + runs_count children would exceed limit
        entry_runs = "\n".join(f"%run ./nb{i}" for i in range(runs_count))
        path_map: dict = {"/Workspace/p/entry": entry_runs}
        for i in range(runs_count):
            path_map[f"/Workspace/p/nb{i}"] = f"# nb{i}"

        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/entry")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        assert result["resolution"]["truncated"] is True
        assert len(result["resolved_files"]) <= _MAX_FILES

    # ------------------------------------------------------------------
    # max_depth bound → truncated=True
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_max_depth_truncated(self, source_tools, mock_api):
        """A chain longer than max_depth → truncated=True."""
        from starboard.tools.adapters.source_tools import _MAX_DEPTH

        # Build a linear chain of max_depth + 2 notebooks
        depth = _MAX_DEPTH + 2
        path_map = {}
        for i in range(depth):
            src = f"%run ./nb{i + 1}" if i < depth - 1 else "# leaf"
            path_map[f"/Workspace/p/nb{i}"] = src

        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/nb0")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        assert result["resolution"]["truncated"] is True
        depths = [f["depth"] for f in result["resolved_files"]]
        assert max(depths) <= _MAX_DEPTH

    # ------------------------------------------------------------------
    # Resolution metadata shape
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_resolution_metadata_shape(self, source_tools, mock_api):
        """resolution dict has roots, truncated, limits."""
        from starboard.tools.adapters.source_tools import (
            _MAX_BYTES,
            _MAX_DEPTH,
            _MAX_FILES,
        )

        mock_api.workspace.get_notebook_content.return_value = "# no runs"

        task = self._notebook_task("/Workspace/project/sub/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        res = result["resolution"]
        assert res["roots"] == ["/Workspace/project/sub"]
        assert res["truncated"] is False
        assert res["limits"] == {
            "max_depth": _MAX_DEPTH,
            "max_files": _MAX_FILES,
            "max_bytes": _MAX_BYTES,
        }

    # ------------------------------------------------------------------
    # Entry fetch failure → None (backward compat)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_entry_fetch_failure_returns_none(self, source_tools, mock_api):
        """If the entry notebook can't be fetched, return None as before."""
        mock_api.workspace.get_notebook_content.return_value = None

        task = self._notebook_task("/Workspace/project/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is None

    # ------------------------------------------------------------------
    # Backward compat: source field equals entry code
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_source_field_is_entry_code(self, source_tools, mock_api):
        """The top-level 'source' key retains only the entry notebook's code."""
        entry_src = "%run ./helper\n# entry"
        path_map = {
            "/Workspace/p/main": entry_src,
            "/Workspace/p/helper": "# helper",
        }
        mock_api.workspace.get_notebook_content.side_effect = self._make_side_effect(path_map)

        task = self._notebook_task("/Workspace/p/main")
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        assert result["source"] == entry_src


# =============================================================================
# Phase 3 — import following in _walk_source_graph
# =============================================================================


class TestResolutionRoots:
    """Tests for SourceTools._resolution_roots (static method)."""

    def test_non_repo_path_returns_dirname_only(self):
        roots = SourceTools._resolution_roots("/Workspace/project/src/etl.py")
        assert roots == ["/Workspace/project/src"]

    def test_repos_path_returns_dirname_and_repo_root(self):
        roots = SourceTools._resolution_roots(
            "/Repos/user@company.com/project/src/utils.py"
        )
        assert roots[0] == "/Repos/user@company.com/project/src"
        assert roots[1] == "/Repos/user@company.com/project"

    def test_workspace_repos_path_returns_dirname_and_repo_root(self):
        roots = SourceTools._resolution_roots(
            "/Workspace/Repos/user/project/src/utils.py"
        )
        assert roots[0] == "/Workspace/Repos/user/project/src"
        assert roots[1] == "/Workspace/Repos/user/project"

    def test_file_directly_in_repo_root_no_duplicate(self):
        """When dirname == repo_root, only one entry is returned."""
        roots = SourceTools._resolution_roots("/Repos/user/project/utils.py")
        assert roots == ["/Repos/user/project"]

    def test_repos_path_too_shallow_no_repo_root(self):
        """Less than 3 parts after /Repos/ → no repo root added."""
        roots = SourceTools._resolution_roots("/Repos/user/file.py")
        assert roots == ["/Repos/user"]

    def test_dirname_always_first(self):
        roots = SourceTools._resolution_roots(
            "/Workspace/Repos/user/project/pkg/module.py"
        )
        assert roots[0] == "/Workspace/Repos/user/project/pkg"

    # ------------------------------------------------------------------
    # Phase 5: bundle root detection
    # ------------------------------------------------------------------

    def test_bundle_path_yields_bundle_root(self):
        """A path under .bundle/.../files/... includes the …/files dir as root."""
        roots = SourceTools._resolution_roots(
            "/Workspace/Users/u/.bundle/proj/dev/files/pkg/mod.py"
        )
        assert "/Workspace/Users/u/.bundle/proj/dev/files" in roots

    def test_bundle_path_dirname_is_first(self):
        """dirname always precedes the bundle root."""
        roots = SourceTools._resolution_roots(
            "/Workspace/Users/u/.bundle/proj/dev/files/pkg/mod.py"
        )
        assert roots[0] == "/Workspace/Users/u/.bundle/proj/dev/files/pkg"
        assert roots[1] == "/Workspace/Users/u/.bundle/proj/dev/files"

    def test_no_bundle_segment_no_bundle_root(self):
        """A path with no .bundle segment gets no bundle root."""
        roots = SourceTools._resolution_roots("/Workspace/Users/u/files/pkg/mod.py")
        # The 'files' segment is not preceded by .bundle — no bundle root added
        assert roots == ["/Workspace/Users/u/files/pkg"]

    def test_bundle_path_deep_resolves_to_files_dir(self):
        """A deeply nested bundle file still resolves root to the …/files dir."""
        roots = SourceTools._resolution_roots(
            "/Workspace/Users/u/.bundle/proj/dev/files/a/b/c.py"
        )
        assert "/Workspace/Users/u/.bundle/proj/dev/files" in roots
        # Should NOT include a deeper sub-path as the bundle root
        assert "/Workspace/Users/u/.bundle/proj/dev/files/a" not in roots

    def test_repos_path_unaffected_by_bundle_detection(self):
        """A normal Repos path yields no bundle root."""
        roots = SourceTools._resolution_roots(
            "/Workspace/Repos/user/project/src/utils.py"
        )
        assert all(".bundle" not in r for r in roots)
        assert len(roots) == 2  # dirname + repo root only


class TestWalkSourceGraph:
    """Tests for _walk_source_graph import-following logic."""

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    def _make_list_side_effect(self, dir_map: dict):
        """Return async side_effect mapping dir_path → list of file dicts."""

        async def _list(path):
            return dir_map.get(path, [])

        return _list

    def _make_export_side_effect(self, path_map: dict):
        """Return async side_effect mapping file path → source string."""

        async def _export(path):
            return path_map.get(path)

        return _export

    # ------------------------------------------------------------------
    # Notebook: first-party repo import resolved
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_notebook_import_repo_module_resolved(
        self, source_tools, mock_api
    ):
        """Entry notebook imports a first-party Repos module → added with reason='import'."""
        notebook_path = "/Workspace/Repos/user/project/notebooks/main"
        notebook_src = "import utils\n# notebook code"

        mock_api.workspace.get_notebook_content.return_value = notebook_src

        # utils.py lives at repo root, not in notebooks/
        dir_map = {
            "/Workspace/Repos/user/project/notebooks": [],  # no utils.py here
            "/Workspace/Repos/user/project": [
                {"path": "/Workspace/Repos/user/project/utils.py", "object_type": "FILE"}
            ],
        }
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            dir_map
        )
        mock_api.workspace.export_workspace_file.return_value = "def helper(): pass"

        task = {"notebook_task": {"notebook_path": notebook_path}}
        result = await source_tools._extract_notebook_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert notebook_path in paths
        assert "/Workspace/Repos/user/project/utils.py" in paths

        import_entry = next(
            f for f in result["resolved_files"] if f["path"].endswith("utils.py")
        )
        assert import_entry["reason"] == "import"
        assert import_entry["code"] == "def helper(): pass"

    # ------------------------------------------------------------------
    # spark_python: sibling import resolved
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_python_file_sibling_import_resolved(
        self, source_tools, mock_api
    ):
        """spark_python file importing a sibling .py module resolves it."""
        python_file = "/Workspace/project/jobs/etl.py"
        python_src = "from . import helpers\n# etl code"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(
                {
                    python_file: python_src,
                    "/Workspace/project/jobs/helpers.py": "def help(): pass",
                }
            )
        )
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            {
                "/Workspace/project/jobs": [
                    {
                        "path": "/Workspace/project/jobs/helpers.py",
                        "object_type": "FILE",
                    }
                ]
            }
        )

        task = {"spark_python_task": {"python_file": python_file}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        assert "resolved_files" in result
        paths = [f["path"] for f in result["resolved_files"]]
        assert python_file in paths
        assert "/Workspace/project/jobs/helpers.py" in paths
        helper_entry = next(
            f for f in result["resolved_files"] if "helpers" in f["path"]
        )
        assert helper_entry["reason"] == "import"

    # ------------------------------------------------------------------
    # Third-party import → dropped, not fetched
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_third_party_import_dropped_not_fetched(
        self, source_tools, mock_api
    ):
        """import pandas with no matching workspace file → dropped, export not called."""
        python_file = "/Workspace/project/etl.py"
        python_src = "import pandas\ndf = None"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect({python_file: python_src})
        )
        # No pandas.py anywhere → all dirs return []

        task = {"spark_python_task": {"python_file": python_file}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        dropped = result["resolution"]["dropped"]
        assert any(d["module"] == "pandas" for d in dropped)
        # export_workspace_file called only for the entry file itself
        assert mock_api.workspace.export_workspace_file.call_count == 1

    # ------------------------------------------------------------------
    # Relative import resolves against file's package
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_relative_import_resolves_against_package(
        self, source_tools, mock_api
    ):
        """from .utils import parse resolves to siblings directory."""
        python_file = "/Workspace/project/pkg/processor.py"
        python_src = "from .utils import parse\n# code"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(
                {
                    python_file: python_src,
                    "/Workspace/project/pkg/utils.py": "def parse(x): return x",
                }
            )
        )
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            {
                "/Workspace/project/pkg": [
                    {
                        "path": "/Workspace/project/pkg/utils.py",
                        "object_type": "FILE",
                    }
                ]
            }
        )

        task = {"spark_python_task": {"python_file": python_file}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert "/Workspace/project/pkg/utils.py" in paths

    # ------------------------------------------------------------------
    # Import cycle terminates
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_import_cycle_terminates(self, source_tools, mock_api):
        """Mutual imports between a.py and b.py each appear exactly once."""
        a_path = "/Workspace/project/a.py"
        b_path = "/Workspace/project/b.py"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(
                {
                    a_path: "from . import b\n# A",
                    b_path: "from . import a\n# B",
                }
            )
        )
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            {
                "/Workspace/project": [
                    {"path": a_path, "object_type": "FILE"},
                    {"path": b_path, "object_type": "FILE"},
                ]
            }
        )

        task = {"spark_python_task": {"python_file": a_path}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert paths.count(a_path) == 1
        assert paths.count(b_path) == 1
        assert len(result["resolved_files"]) == 2

    # ------------------------------------------------------------------
    # _MAX_FILES bound → truncated=True
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_max_files_truncated_by_imports(self, source_tools, mock_api):
        """When _MAX_FILES is hit via import resolution, truncated=True."""
        from starboard.tools.adapters.source_tools import _MAX_FILES

        entry_path = "/Workspace/project/main.py"
        # Entry imports _MAX_FILES sibling modules
        imports = "\n".join(f"from . import mod{i}" for i in range(_MAX_FILES))
        path_map = {entry_path: imports}
        dir_entries = []
        for i in range(_MAX_FILES):
            p = f"/Workspace/project/mod{i}.py"
            path_map[p] = f"# mod{i}"
            dir_entries.append({"path": p, "object_type": "FILE"})

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(path_map)
        )
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            {"/Workspace/project": dir_entries}
        )

        task = {"spark_python_task": {"python_file": entry_path}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        assert result["resolution"]["truncated"] is True
        assert len(result["resolved_files"]) <= _MAX_FILES

    # ------------------------------------------------------------------
    # Submodule file preferred over package (candidate ordering)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_submodule_file_preferred_over_package(
        self, source_tools, mock_api
    ):
        """from pkg import mod picks pkg/mod.py before pkg.py (first candidate wins)."""
        python_file = "/Workspace/project/main.py"
        python_src = "from pkg import mod\n# code"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(
                {
                    python_file: python_src,
                    "/Workspace/project/pkg/mod.py": "# submodule",
                    "/Workspace/project/pkg.py": "# package",
                }
            )
        )
        # pkg/mod.py exists (submodule) AND pkg.py exists (package)
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            {
                "/Workspace/project/pkg": [
                    {"path": "/Workspace/project/pkg/mod.py", "object_type": "FILE"}
                ],
                "/Workspace/project": [
                    {"path": "/Workspace/project/pkg.py", "object_type": "FILE"}
                ],
            }
        )

        task = {"spark_python_task": {"python_file": python_file}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        # Submodule file picked, not package
        assert "/Workspace/project/pkg/mod.py" in paths
        assert "/Workspace/project/pkg.py" not in paths

    # ------------------------------------------------------------------
    # DBFS path keeps Phase-1 behaviour (no walk)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dbfs_path_no_walk(self, source_tools, mock_api):
        """DBFS spark_python files skip the walk (no resolved_files/resolution)."""
        mock_api.workspace.read_dbfs_file.return_value = "import pyspark"
        task = {"spark_python_task": {"python_file": "dbfs:/scripts/job.py"}}

        result = await source_tools._extract_python_source(task)

        assert result is not None
        assert result["source"] == "import pyspark"
        assert "resolved_files" not in result
        assert "resolution" not in result
        mock_api.workspace.list_workspace.assert_not_called()

    # ------------------------------------------------------------------
    # Dropped deduplication: same module imported twice → one dropped entry
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dropped_deduplicated(self, source_tools, mock_api):
        """The same unresolvable import produces only one dropped entry."""
        python_file = "/Workspace/project/main.py"
        python_src = "import pandas\nimport pandas\n# duplicate"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect({python_file: python_src})
        )

        task = {"spark_python_task": {"python_file": python_file}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        pandas_drops = [
            d for d in result["resolution"]["dropped"] if d["module"] == "pandas"
        ]
        assert len(pandas_drops) == 1


# =============================================================================
# Phase 4 — git_source support
# =============================================================================


class TestExtractGitSource:
    """Tests for git_source task resolution (Phase 4)."""

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    # ------------------------------------------------------------------
    # git_url parsing helper: _derive_repo_name
    # ------------------------------------------------------------------

    def test_derive_repo_name_https_with_git_suffix(self):
        """https://.../org/repo.git → repo."""
        assert SourceTools._derive_repo_name("https://github.com/org/repo.git") == "repo"

    def test_derive_repo_name_ssh_url(self):
        """git@github.com:org/repo.git → repo."""
        assert SourceTools._derive_repo_name("git@github.com:org/repo.git") == "repo"

    def test_derive_repo_name_no_git_suffix(self):
        """https://.../org/repo (no .git) → repo."""
        assert SourceTools._derive_repo_name("https://github.com/org/repo") == "repo"

    # ------------------------------------------------------------------
    # GIT notebook task: checkout found under /Workspace/Repos
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_git_notebook_checkout_resolved(self, source_tools, mock_api):
        """GIT notebook task whose repo is checked out under /Workspace/Repos/alice/repo."""
        git_source = {
            "git_url": "https://github.com/org/repo.git",
            "git_branch": "main",
        }
        task = {
            "notebook_task": {
                "notebook_path": "notebooks/etl",
                "source": "GIT",
            }
        }

        async def _list(path):
            if path == "/Workspace/Repos":
                return [
                    {"path": "/Workspace/Repos/alice", "object_type": "DIRECTORY"}
                ]
            if path == "/Workspace/Repos/alice/repo/notebooks":
                return [
                    {
                        "path": "/Workspace/Repos/alice/repo/notebooks/etl",
                        "object_type": "NOTEBOOK",
                    }
                ]
            return []

        mock_api.workspace.list_workspace.side_effect = _list
        mock_api.workspace.get_notebook_content.return_value = "# etl code"

        result = await source_tools._extract_git_source(task, git_source)

        assert result is not None
        assert result["type"] == "notebook"
        assert result["path"] == "/Workspace/Repos/alice/repo/notebooks/etl"
        assert result["source"] == "# etl code"
        assert result["resolved_files"][0]["reason"] == "entry"
        assert "caveats" in result["resolution"]
        assert any("main" in c for c in result["resolution"]["caveats"])

    # ------------------------------------------------------------------
    # GIT spark_python task: checkout found under /Repos, follows import
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_git_python_task_resolves_with_import_walk(
        self, source_tools, mock_api
    ):
        """GIT spark_python task resolves src/main.py under /Repos/bob/repo and follows import."""
        git_source = {
            "git_url": "git@github.com:org/repo.git",
            "git_tag": "v1.0",
        }
        task = {
            "spark_python_task": {
                "python_file": "src/main.py",
                "source": "GIT",
            }
        }

        entry_src = "from . import helpers\n# main"
        helper_src = "def help(): pass"

        async def _list(path):
            if path == "/Workspace/Repos":
                return []
            if path == "/Repos":
                return [{"path": "/Repos/bob", "object_type": "DIRECTORY"}]
            if path == "/Repos/bob/repo/src":
                return [
                    {"path": "/Repos/bob/repo/src/main.py", "object_type": "FILE"},
                    {"path": "/Repos/bob/repo/src/helpers.py", "object_type": "FILE"},
                ]
            return []

        async def _export(path):
            if path == "/Repos/bob/repo/src/main.py":
                return entry_src
            if path == "/Repos/bob/repo/src/helpers.py":
                return helper_src
            return None

        mock_api.workspace.list_workspace.side_effect = _list
        mock_api.workspace.export_workspace_file.side_effect = _export

        result = await source_tools._extract_git_source(task, git_source)

        assert result is not None
        assert result["type"] == "python_file"
        assert result["path"] == "/Repos/bob/repo/src/main.py"
        paths = [f["path"] for f in result["resolved_files"]]
        assert "/Repos/bob/repo/src/main.py" in paths
        assert "/Repos/bob/repo/src/helpers.py" in paths
        helper_entry = next(
            f for f in result["resolved_files"] if "helpers" in f["path"]
        )
        assert helper_entry["reason"] == "import"
        assert "caveats" in result["resolution"]
        assert any("v1.0" in c for c in result["resolution"]["caveats"])

    # ------------------------------------------------------------------
    # No checkout anywhere → graceful degradation
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_git_no_checkout_degrades_gracefully(self, source_tools, mock_api):
        """No checkout found anywhere → degradation dict with git_source_no_checkout reason."""
        git_source = {
            "git_url": "https://github.com/org/repo.git",
            "git_branch": "main",
        }
        task = {
            "notebook_task": {
                "notebook_path": "notebooks/etl",
                "source": "GIT",
            }
        }

        # All list_workspace calls return empty → no checkout found
        mock_api.workspace.list_workspace.return_value = []

        result = await source_tools._extract_git_source(task, git_source)

        assert result is not None
        assert result["type"] == "notebook"
        assert result["path"] == "notebooks/etl"
        assert "git_source" in result["source"]
        assert "No workspace checkout found" in result["source"]
        dropped = result["resolution"]["dropped"]
        assert any(d["reason"] == "git_source_no_checkout" for d in dropped)
        # Must not crash; get_notebook_content never called
        mock_api.workspace.get_notebook_content.assert_not_called()

    # ------------------------------------------------------------------
    # Non-GIT notebook task: source absent → normal workspace path (regression)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_git_notebook_uses_normal_path(self, source_tools, mock_api):
        """Notebook task without source==GIT routes to normal workspace fetch."""
        task = {
            "task_key": "t1",
            "notebook_task": {
                "notebook_path": "/Workspace/project/main",
                # no 'source' field
            },
        }
        git_source = {
            "git_url": "https://github.com/org/repo.git",
            "git_branch": "main",
        }

        mock_api.workspace.get_notebook_content.return_value = "# normal code"

        result = await source_tools._extract_task_source(task, git_source=git_source)

        assert result is not None
        assert result["type"] == "notebook"
        assert result["path"] == "/Workspace/project/main"
        assert result["source"] == "# normal code"
        mock_api.workspace.get_notebook_content.assert_called_with(
            "/Workspace/project/main"
        )


# =============================================================================
# Phase 5 — DAB bundle awareness
# =============================================================================


class TestBundleWalkSourceGraph:
    """Walker resolves sibling imports via the bundle …/files root (Phase 5)."""

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    def _make_list_side_effect(self, dir_map: dict):
        async def _list(path):
            return dir_map.get(path, [])

        return _list

    def _make_export_side_effect(self, path_map: dict):
        async def _export(path):
            return path_map.get(path)

        return _export

    @pytest.mark.asyncio
    async def test_bundle_entry_resolves_sibling_package_via_files_root(
        self, source_tools, mock_api
    ):
        """Bundle entry at …/files/jobs/main.py imports shared.utils → resolved via bundle root."""
        bundle_root = "/Workspace/Users/u/.bundle/proj/dev/files"
        entry_path = f"{bundle_root}/jobs/main.py"
        shared_utils_path = f"{bundle_root}/shared/utils.py"
        entry_src = "import shared.utils\n# bundle job"

        mock_api.workspace.export_workspace_file.side_effect = (
            self._make_export_side_effect(
                {
                    entry_path: entry_src,
                    shared_utils_path: "def helper(): pass",
                }
            )
        )

        # bundle root dir contains shared/; shared/ contains utils.py
        dir_map = {
            f"{bundle_root}/jobs": [],  # no shared.py here
            bundle_root: [
                {"path": f"{bundle_root}/shared", "object_type": "DIRECTORY"}
            ],
            f"{bundle_root}/shared": [
                {"path": shared_utils_path, "object_type": "FILE"}
            ],
        }
        mock_api.workspace.list_workspace.side_effect = self._make_list_side_effect(
            dir_map
        )

        task = {"spark_python_task": {"python_file": entry_path}}
        result = await source_tools._extract_python_source(task)

        assert result is not None
        paths = [f["path"] for f in result["resolved_files"]]
        assert entry_path in paths
        assert shared_utils_path in paths

        import_entry = next(
            f for f in result["resolved_files"] if "utils.py" in f["path"]
        )
        assert import_entry["reason"] == "import"
        assert bundle_root in result["resolution"]["roots"]


class TestBundleDeploymentProvenance:
    """_inspect_source_code attaches bundle provenance to resolution.caveats (Phase 5)."""

    _BUNDLE_NOTE = (
        "bundle-deployed job (deployment.kind=BUNDLE); "
        "resolution roots include the bundle sync tree"
    )

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    def _job_config(self, deployment: dict | None, tasks: list) -> dict:
        settings: dict = {"tasks": tasks}
        if deployment is not None:
            settings["deployment"] = deployment
        return {"settings": settings}

    @pytest.mark.asyncio
    async def test_bundle_job_adds_provenance_note(self, source_tools, mock_api):
        """A BUNDLE-deployed job produces resolution.caveats with the bundle note."""
        bundle_root = "/Workspace/Users/u/.bundle/proj/dev/files"
        entry_path = f"{bundle_root}/jobs/main.py"

        mock_api.jobs.get_job.return_value = self._job_config(
            deployment={"kind": "BUNDLE"},
            tasks=[{"task_key": "run_main", "spark_python_task": {"python_file": entry_path}}],
        )
        mock_api.workspace.export_workspace_file.return_value = "# bundle job"

        result = await source_tools._inspect_source_code("42")

        assert result["has_source_code"] is True
        task_src = result["task_sources"]["run_main"]
        assert "resolution" in task_src, "Expected resolution dict on workspace task"
        caveats = task_src["resolution"].get("caveats", [])
        assert any(self._BUNDLE_NOTE in c for c in caveats)

    @pytest.mark.asyncio
    async def test_non_bundle_job_has_no_bundle_provenance(self, source_tools, mock_api):
        """A non-bundle job does NOT get the bundle provenance note."""
        entry_path = "/Workspace/project/jobs/main.py"

        mock_api.jobs.get_job.return_value = self._job_config(
            deployment=None,
            tasks=[{"task_key": "run_main", "spark_python_task": {"python_file": entry_path}}],
        )
        mock_api.workspace.export_workspace_file.return_value = "# normal job"

        result = await source_tools._inspect_source_code("43")

        task_src = result["task_sources"]["run_main"]
        caveats = task_src.get("resolution", {}).get("caveats", [])
        assert not any(self._BUNDLE_NOTE in c for c in caveats)

    @pytest.mark.asyncio
    async def test_bundle_note_not_duplicated(self, source_tools, mock_api):
        """Calling _inspect_source_code on a bundle job twice doesn't duplicate the note."""
        bundle_root = "/Workspace/Users/u/.bundle/proj/dev/files"
        entry_path = f"{bundle_root}/jobs/main.py"

        mock_api.jobs.get_job.return_value = self._job_config(
            deployment={"kind": "BUNDLE"},
            tasks=[{"task_key": "run_main", "spark_python_task": {"python_file": entry_path}}],
        )
        mock_api.workspace.export_workspace_file.return_value = "# bundle job"

        result = await source_tools._inspect_source_code("44")
        task_src = result["task_sources"]["run_main"]
        caveats = task_src["resolution"].get("caveats", [])
        bundle_notes = [c for c in caveats if self._BUNDLE_NOTE in c]
        assert len(bundle_notes) == 1  # exactly once


# =============================================================================
# Phase 6 — rank_and_trim + runtime_context wiring (TDD, written before impl)
# =============================================================================


class TestAnalyzeCodeQualityRankingAndContext:
    """Tests for Phase 6: budget ranking and runtime_context wiring."""

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def mock_llm(self):
        mock = MagicMock(spec=BaseLLMClient)
        mock.json_response = AsyncMock(return_value={"hotspots": [], "notes": []})
        return mock

    @pytest.fixture
    def source_tools(self, mock_api, mock_llm):
        return SourceTools(api=mock_api, llm_client=mock_llm)

    # ------------------------------------------------------------------
    # Trim-to-budget
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_many_large_artifacts_trimmed_to_budget_with_note(
        self, source_tools, mock_llm
    ):
        """When total artifact bytes exceed _MAX_ANALYSIS_BYTES, excess is trimmed
        and a note is appended to the result."""
        from starboard.tools.adapters.source_tools import _MAX_ANALYSIS_BYTES

        # Build a task_sources dict whose combined byte-size exceeds the budget.
        # Each artifact: 1 KiB of code.
        # We need ceil(_MAX_ANALYSIS_BYTES / 1024) + 1 to guarantee overflow.
        chunk = "x" * 1024
        n_artifacts = (_MAX_ANALYSIS_BYTES // 1024) + 2
        task_sources = {
            f"task{i}": {"type": "notebook", "source": chunk, "path": f"/nb/task{i}"}
            for i in range(n_artifacts)
        }

        result = await source_tools._analyze_code_quality(
            task_sources=task_sources,
        )

        notes = result.get("code_quality_notes", [])
        trim_notes = [n for n in notes if "Trimmed" in n]
        assert trim_notes, (
            f"Expected a Trimmed note when budget exceeded; got notes={notes}"
        )

    @pytest.mark.asyncio
    async def test_hot_paths_keeps_hot_module_trims_others(
        self, source_tools, mock_llm
    ):
        """hot_paths keeps the specified module and trims low-priority artifacts."""
        from starboard.tools.adapters.source_tools import _MAX_ANALYSIS_BYTES

        chunk = "y" * 1024
        n_fillers = (_MAX_ANALYSIS_BYTES // 1024) + 2
        hot_path = "/notebooks/critical.py"

        task_sources = {
            f"filler_{i}": {
                "type": "python_file",
                "source": chunk,
                "path": f"/notebooks/filler_{i}.py",
                "resolved_files": [
                    {
                        "path": f"/notebooks/filler_{i}.py",
                        "code": chunk,
                        "reason": "import",
                        "depth": 1,
                    }
                ],
            }
            for i in range(n_fillers)
        }
        # Hot task uses resolved_files so transform_task_sources produces the right shape.
        task_sources["hot_task"] = {
            "type": "python_file",
            "source": "print('hot')",
            "path": hot_path,
            "resolved_files": [
                {
                    "path": hot_path,
                    "code": "print('hot')",
                    "reason": "import",
                    "depth": 1,
                }
            ],
        }

        result = await source_tools._analyze_code_quality(
            task_sources=task_sources,
            hot_paths=[hot_path],
        )

        notes = result.get("code_quality_notes", [])
        # There should be a trim note (some fillers were dropped)
        trim_notes = [n for n in notes if "Trimmed" in n]
        assert trim_notes, "Expected Trimmed note when budget exceeded with hot_paths"
        # hot_task key should NOT appear in any drop note
        for note in trim_notes:
            assert "hot_task" not in note, (
                f"hot_task should not have been trimmed; trim note: {note}"
            )

    @pytest.mark.asyncio
    async def test_entry_artifact_never_trimmed(self, source_tools, mock_llm):
        """An artifact with reason='entry' is always kept even if it alone exceeds budget."""
        from starboard.tools.adapters.source_tools import _MAX_ANALYSIS_BYTES

        entry_code = "e" * (_MAX_ANALYSIS_BYTES + 100)
        task_sources = {
            "entry_task": {
                "type": "python_file",
                "source": entry_code,
                "path": "/entry.py",
                "resolved_files": [
                    {
                        "path": "/entry.py",
                        "code": entry_code,
                        "reason": "entry",
                        "depth": 0,
                    }
                ],
            }
        }

        # Should not raise; entry is kept regardless of size.
        result = await source_tools._analyze_code_quality(task_sources=task_sources)
        # Analysis ran (LLM was invoked — no hard error)
        assert "code_quality_issues" in result

    @pytest.mark.asyncio
    async def test_adhoc_source_never_trimmed(self, source_tools, mock_llm):
        """Adhoc source_code is pinned and never trimmed by budget enforcement."""
        from starboard.tools.adapters.source_tools import _MAX_ANALYSIS_BYTES

        adhoc_code = "a" * (_MAX_ANALYSIS_BYTES + 100)
        result = await source_tools._analyze_code_quality(source_code=adhoc_code)
        assert "code_quality_issues" in result
        notes = result.get("code_quality_notes", [])
        # No trim note for adhoc itself
        for note in notes:
            assert "adhoc" not in note.lower() or "Trimmed" not in note, (
                f"adhoc should not appear in a Trimmed note: {note}"
            )

    # ------------------------------------------------------------------
    # Default call unchanged
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_default_call_no_new_args_unchanged(self, source_tools, mock_llm):
        """Calling _analyze_code_quality with no new args behaves identically to before."""
        mock_llm.json_response = AsyncMock(
            return_value={"hotspots": [{"artifact": "adhoc", "line_range": "1",
                                        "issue": "x", "signal": [], "evidence": "e",
                                        "risk": "low", "fix": {"strategy": "s",
                                                                "snippet_before": "a",
                                                                "snippet_after": "b"}}],
                          "notes": ["ok"]}
        )
        result = await source_tools._analyze_code_quality(source_code="SELECT 1")
        assert "code_quality_issues" in result
        assert len(result["code_quality_issues"]) == 1
        assert result["code_quality_notes"] == ["ok"]

    # ------------------------------------------------------------------
    # runtime_context wiring
    # ------------------------------------------------------------------

    def test_build_analysis_messages_with_runtime_context(self, source_tools):
        """_build_analysis_messages includes runtime_context in user message."""
        rt = "avg_duration=120s p95=200s"
        artifacts = {"adhoc": {"code": "SELECT 1", "task_type": "adhoc"}}
        messages = source_tools._build_analysis_messages(artifacts, runtime_context=rt)
        user_msg = messages[1]["content"]
        assert rt in user_msg

    def test_build_analysis_messages_no_runtime_context_empty_block(
        self, source_tools
    ):
        """When runtime_context is None, the RUNTIME CONTEXT block is empty (as before)."""
        artifacts = {"adhoc": {"code": "SELECT 1", "task_type": "adhoc"}}
        messages = source_tools._build_analysis_messages(artifacts, runtime_context=None)
        user_msg = messages[1]["content"]
        assert "RUNTIME CONTEXT (if available):" in user_msg
        # Block should be present but contain no actual context data
        rt_index = user_msg.index("RUNTIME CONTEXT (if available):")
        after_header = user_msg[rt_index + len("RUNTIME CONTEXT (if available):"):]
        # Next non-whitespace section should be the Focus line, not user data
        stripped = after_header.lstrip("\n ")
        assert stripped.startswith("Focus on:") or stripped.startswith("\n") or stripped == ""

    @pytest.mark.asyncio
    async def test_runtime_context_threaded_to_llm_call(self, source_tools, mock_llm):
        """runtime_context passed to _analyze_code_quality reaches the LLM message."""
        captured: list[list[dict]] = []

        async def capture_call(**kwargs):
            captured.append(kwargs.get("messages", []))
            return {"hotspots": [], "notes": []}

        mock_llm.json_response = AsyncMock(side_effect=capture_call)

        rt = "task_duration=45s rows_written=1000000"
        await source_tools._analyze_code_quality(
            source_code="df.collect()",
            runtime_context=rt,
        )

        assert captured, "LLM should have been called"
        user_content = captured[0][1]["content"]
        assert rt in user_content, (
            f"runtime_context not found in LLM message; content snippet: {user_content[:300]}"
        )

    @pytest.mark.asyncio
    async def test_public_analyze_code_quality_passes_runtime_context(
        self, source_tools, mock_llm
    ):
        """The public analyze_code_quality method accepts and forwards runtime_context."""
        captured: list[list[dict]] = []

        async def capture_call(**kwargs):
            captured.append(kwargs.get("messages", []))
            return {"hotspots": [], "notes": []}

        mock_llm.json_response = AsyncMock(side_effect=capture_call)

        rt = "cluster_size=8 spill_bytes=0"
        await source_tools.analyze_code_quality(
            source_code="spark.read.parquet('/data')",
            runtime_context=rt,
        )

        assert captured
        user_content = captured[0][1]["content"]
        assert rt in user_content


class TestJobFetchErrorHandling:
    """get_job raising a raw Databricks SDK error degrades gracefully.

    Regression for issue #18 Isaac Review finding: _inspect_source_code and
    _get_task_definitions_from_job must not let a NotFound/DatabricksError
    (bad/deleted job, permission denied) propagate out of the analysis path.
    """

    @pytest.fixture
    def mock_api(self):
        return create_mock_async_client()

    @pytest.fixture
    def source_tools(self, mock_api):
        return SourceTools(api=mock_api)

    @pytest.mark.asyncio
    async def test_get_source_code_degrades_on_sdk_notfound(
        self, source_tools, mock_api
    ):
        """A NotFound from get_job yields an empty source result, not an exception."""
        from databricks.sdk.errors import NotFound

        mock_api.jobs.get_job.side_effect = NotFound("job 123 not found")

        result = await source_tools.get_source_code("123")

        assert result["has_source_code"] is False
        assert result["task_sources"] == {}

    @pytest.mark.asyncio
    async def test_get_task_definitions_degrades_on_sdk_error(
        self, source_tools, mock_api
    ):
        """A DatabricksError from get_job yields no task definitions, not an exception."""
        from databricks.sdk.errors import DatabricksError

        mock_api.jobs.get_job.side_effect = DatabricksError("permission denied")

        result = await source_tools.get_task_definitions("123")

        assert result["tasks"] == []
        assert result["task_count"] == 0
