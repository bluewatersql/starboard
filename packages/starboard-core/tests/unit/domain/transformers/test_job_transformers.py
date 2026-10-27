# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for transform_task_sources — resolved_files data-shape extension.

TDD: these tests were written before the resolved_files feature was implemented.
The existing backward-compat tests live in:
  packages/starboard/tests/unit/services/test_task_sources_transformer.py
"""

from starboard_core.domain.transformers.job_transformers import transform_task_sources


class TestTransformTaskSourcesResolvedFiles:
    """Tests for the new resolved_files data shape in transform_task_sources."""

    # ------------------------------------------------------------------
    # Backward compatibility — no resolved_files key
    # ------------------------------------------------------------------

    def test_no_resolved_files_key_backward_compat(self):
        """No resolved_files key → behave exactly as before (single entry)."""
        task_sources = {
            "notebook_task": {
                "type": "notebook",
                "path": "/Workspace/etl/main",
                "source": "# code here",
            }
        }
        result = transform_task_sources(task_sources)
        assert "notebook_task" in result
        assert result["notebook_task"]["task_type"] == "notebook"
        assert result["notebook_task"]["file_path"] == "/Workspace/etl/main"
        assert result["notebook_task"]["code"] == "# code here"
        # No per-file keys should exist
        assert not any("::" in k for k in result)

    def test_empty_resolved_files_backward_compat(self):
        """Empty resolved_files list → behave exactly as before."""
        task_sources = {
            "my_task": {
                "type": "notebook",
                "path": "/Workspace/etl/main",
                "source": "# code",
                "resolved_files": [],
            }
        }
        result = transform_task_sources(task_sources)
        assert "my_task" in result
        assert result["my_task"]["task_type"] == "notebook"
        # No per-file keys
        assert not any("::" in k for k in result)

    # ------------------------------------------------------------------
    # New shape — non-empty resolved_files
    # ------------------------------------------------------------------

    def test_resolved_files_emits_one_entry_per_file(self):
        """Non-empty resolved_files → one output entry per file."""
        task_sources = {
            "etl": {
                "type": "notebook",
                "path": "/Workspace/project/main",
                "source": "# entry code",
                "resolved_files": [
                    {
                        "path": "/Workspace/project/main",
                        "code": "# entry code",
                        "reason": "entry",
                        "depth": 0,
                    },
                    {
                        "path": "/Workspace/project/helpers",
                        "code": "# helper code",
                        "reason": "run",
                        "depth": 1,
                    },
                ],
            }
        }
        result = transform_task_sources(task_sources)

        # Should have two entries, not one
        assert len(result) == 2
        assert "etl::/Workspace/project/main" in result
        assert "etl::/Workspace/project/helpers" in result

    def test_resolved_files_entry_shape(self):
        """Each resolved-file entry has task_type, file_path, code, reason."""
        task_sources = {
            "task1": {
                "type": "notebook",
                "path": "/Workspace/main",
                "source": "# main",
                "resolved_files": [
                    {
                        "path": "/Workspace/main",
                        "code": "# main code",
                        "reason": "entry",
                        "depth": 0,
                    },
                    {
                        "path": "/Workspace/utils",
                        "code": "# utils code",
                        "reason": "run",
                        "depth": 1,
                    },
                ],
            }
        }
        result = transform_task_sources(task_sources)

        entry = result["task1::/Workspace/main"]
        assert entry["task_type"] == "notebook"
        assert entry["file_path"] == "/Workspace/main"
        assert entry["code"] == "# main code"
        assert entry["reason"] == "entry"

        helper = result["task1::/Workspace/utils"]
        assert helper["task_type"] == "notebook"
        assert helper["file_path"] == "/Workspace/utils"
        assert helper["code"] == "# utils code"
        assert helper["reason"] == "run"

    def test_resolved_files_none_fields_dropped(self):
        """None values in resolved file entries are dropped."""
        task_sources = {
            "t": {
                "type": "notebook",
                "path": "/nb",
                "source": "code",
                "resolved_files": [
                    {
                        "path": "/nb",
                        "code": "code",
                        "reason": "entry",
                        "depth": 0,
                    },
                ],
            }
        }
        result = transform_task_sources(task_sources)
        entry = result["t::/nb"]
        # depth is not part of output shape
        assert "depth" not in entry

    def test_resolved_files_three_files(self):
        """Three resolved_files → three output entries."""
        task_sources = {
            "pipeline": {
                "type": "notebook",
                "path": "/Workspace/pipeline/main",
                "source": "# main",
                "resolved_files": [
                    {"path": "/Workspace/pipeline/main", "code": "# main", "reason": "entry", "depth": 0},
                    {"path": "/Workspace/pipeline/ingest", "code": "# ingest", "reason": "run", "depth": 1},
                    {"path": "/Workspace/shared/utils", "code": "# utils", "reason": "run", "depth": 1},
                ],
            }
        }
        result = transform_task_sources(task_sources)
        assert len(result) == 3
        assert "pipeline::/Workspace/pipeline/main" in result
        assert "pipeline::/Workspace/pipeline/ingest" in result
        assert "pipeline::/Workspace/shared/utils" in result

    def test_mixed_tasks_resolved_and_plain(self):
        """Mix of tasks — one with resolved_files, one without."""
        task_sources = {
            "nb_task": {
                "type": "notebook",
                "path": "/Workspace/main",
                "source": "# main",
                "resolved_files": [
                    {"path": "/Workspace/main", "code": "# main", "reason": "entry", "depth": 0},
                    {"path": "/Workspace/helper", "code": "# helper", "reason": "run", "depth": 1},
                ],
            },
            "sql_task": {
                "type": "sql",
                "source": "SELECT 1",
            },
        }
        result = transform_task_sources(task_sources)
        # sql_task → plain entry (no resolved_files)
        assert "sql_task" in result
        # nb_task → two per-file entries
        assert "nb_task::/Workspace/main" in result
        assert "nb_task::/Workspace/helper" in result
        # Total: 3 entries
        assert len(result) == 3

    def test_resolved_files_parent_task_key_not_in_result(self):
        """When resolved_files is non-empty, the bare task_key must NOT appear."""
        task_sources = {
            "etl": {
                "type": "notebook",
                "path": "/Workspace/main",
                "source": "# main",
                "resolved_files": [
                    {"path": "/Workspace/main", "code": "# main", "reason": "entry", "depth": 0},
                ],
            }
        }
        result = transform_task_sources(task_sources)
        assert "etl" not in result
        assert "etl::/Workspace/main" in result
