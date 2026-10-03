# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for run_following — extract_run_targets and resolve_run_path.

TDD: these tests were written before the implementation.
"""

from starboard_core.domain.source.run_following import (
    extract_run_targets,
    resolve_run_path,
)


class TestExtractRunTargets:
    """Tests for extract_run_targets."""

    # ------------------------------------------------------------------
    # Bare %run
    # ------------------------------------------------------------------

    def test_bare_run_simple(self):
        source = "%run ./setup"
        assert extract_run_targets(source) == ["./setup"]

    def test_bare_run_absolute(self):
        source = "%run /Shared/utils/helpers"
        assert extract_run_targets(source) == ["/Shared/utils/helpers"]

    def test_bare_run_leading_whitespace(self):
        source = "   %run /Shared/common"
        assert extract_run_targets(source) == ["/Shared/common"]

    def test_bare_run_trailing_params_ignored(self):
        """Target is first token; trailing args are ignored."""
        source = "%run ./setup $env=prod $mode=test"
        assert extract_run_targets(source) == ["./setup"]

    # ------------------------------------------------------------------
    # Python magic prefix
    # ------------------------------------------------------------------

    def test_python_magic_prefix(self):
        source = "# MAGIC %run ./setup"
        assert extract_run_targets(source) == ["./setup"]

    def test_python_magic_prefix_with_leading_whitespace(self):
        source = "  # MAGIC %run /Workspace/shared"
        assert extract_run_targets(source) == ["/Workspace/shared"]

    def test_python_magic_with_trailing_params(self):
        source = "# MAGIC %run /Shared/lib $key=value"
        assert extract_run_targets(source) == ["/Shared/lib"]

    # ------------------------------------------------------------------
    # SQL magic prefix
    # ------------------------------------------------------------------

    def test_sql_magic_prefix(self):
        source = "-- MAGIC %run ./sql_utils"
        assert extract_run_targets(source) == ["./sql_utils"]

    def test_sql_magic_absolute(self):
        source = "-- MAGIC %run /Shared/sql/common"
        assert extract_run_targets(source) == ["/Shared/sql/common"]

    # ------------------------------------------------------------------
    # Scala magic prefix
    # ------------------------------------------------------------------

    def test_scala_magic_prefix(self):
        source = "// MAGIC %run ./scala_setup"
        assert extract_run_targets(source) == ["./scala_setup"]

    def test_scala_magic_absolute(self):
        source = "// MAGIC %run /Shared/scala/common"
        assert extract_run_targets(source) == ["/Shared/scala/common"]

    # ------------------------------------------------------------------
    # Quoted targets
    # ------------------------------------------------------------------

    def test_double_quoted_target(self):
        source = '%run "./setup notebook"'
        assert extract_run_targets(source) == ["./setup notebook"]

    def test_single_quoted_target(self):
        source = "%run './setup'"
        assert extract_run_targets(source) == ["./setup"]

    def test_magic_with_quoted_target(self):
        source = "# MAGIC %run './utils/common'"
        assert extract_run_targets(source) == ["./utils/common"]

    # ------------------------------------------------------------------
    # Multi-line source (document order)
    # ------------------------------------------------------------------

    def test_multiple_runs_document_order(self):
        source = "\n".join([
            "# some preamble",
            "%run /Shared/setup",
            "x = 1",
            "# MAGIC %run ./helpers",
            "-- MAGIC %run /Shared/sql_utils",
        ])
        assert extract_run_targets(source) == [
            "/Shared/setup",
            "./helpers",
            "/Shared/sql_utils",
        ]

    def test_no_dedup_in_extract(self):
        """extract_run_targets does NOT deduplicate — that is the caller's job."""
        source = "%run ./setup\n%run ./setup"
        assert extract_run_targets(source) == ["./setup", "./setup"]

    # ------------------------------------------------------------------
    # No match
    # ------------------------------------------------------------------

    def test_empty_source_returns_empty(self):
        assert extract_run_targets("") == []

    def test_no_run_magic_returns_empty(self):
        source = "import pyspark\ndf = spark.read.table('t')\ndf.show()"
        assert extract_run_targets(source) == []

    def test_run_in_string_literal_not_matched(self):
        """A %run inside a quoted string is not a run directive."""
        # Only matching at line start (with optional comment prefix)
        source = 'print("%run ./helper")'
        assert extract_run_targets(source) == []

    def test_comment_without_magic_not_matched(self):
        """A plain comment mentioning %run is not a run directive."""
        source = "# this is %run ./setup comment, not magic"
        # Does not have the MAGIC keyword, so should not match
        assert extract_run_targets(source) == []

    # ------------------------------------------------------------------
    # Real notebook export shapes
    # ------------------------------------------------------------------

    def test_databricks_export_python_cell(self):
        """Simulates a cell in a Python notebook exported with magic."""
        source = "\n".join([
            "# Databricks notebook source",
            "# COMMAND ----------",
            "# MAGIC %run ../common/setup",
            "# COMMAND ----------",
            "df = spark.range(10)",
        ])
        assert extract_run_targets(source) == ["../common/setup"]


class TestResolveRunPath:
    """Tests for resolve_run_path."""

    # ------------------------------------------------------------------
    # Absolute targets
    # ------------------------------------------------------------------

    def test_absolute_target_returned_as_is(self):
        result = resolve_run_path("/Workspace/project/main", "/Shared/utils")
        assert result == "/Shared/utils"

    def test_absolute_target_normalized(self):
        result = resolve_run_path("/Workspace/project/main", "/Shared/../utils")
        assert result == "/utils"

    def test_absolute_target_strips_quotes(self):
        result = resolve_run_path("/Workspace/project/main", '"/Shared/utils"')
        assert result == "/Shared/utils"

    # ------------------------------------------------------------------
    # Relative targets
    # ------------------------------------------------------------------

    def test_relative_dot_slash(self):
        result = resolve_run_path("/Workspace/project/main", "./helpers")
        assert result == "/Workspace/project/helpers"

    def test_relative_no_prefix(self):
        result = resolve_run_path("/Workspace/project/main", "helpers")
        assert result == "/Workspace/project/helpers"

    def test_relative_parent(self):
        result = resolve_run_path("/Workspace/project/notebooks/main", "../common/utils")
        assert result == "/Workspace/project/common/utils"

    def test_relative_parent_two_levels(self):
        result = resolve_run_path("/Workspace/a/b/c/main", "../../shared")
        assert result == "/Workspace/a/shared"

    def test_relative_strips_quotes(self):
        result = resolve_run_path("/Workspace/project/main", "'./helpers'")
        assert result == "/Workspace/project/helpers"

    # ------------------------------------------------------------------
    # Normpath idempotency
    # ------------------------------------------------------------------

    def test_double_slash_normalized(self):
        result = resolve_run_path("/Workspace/project//main", "./helpers")
        assert result == "/Workspace/project/helpers"

    def test_no_extension_added(self):
        """Workspace notebook paths have no file extension."""
        result = resolve_run_path("/Workspace/project/main", "./setup")
        assert not result.endswith(".py")
        assert not result.endswith(".ipynb")
        assert result == "/Workspace/project/setup"
