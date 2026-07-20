# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for query domain transformers."""

from starboard.tools.domain.query.transformers import (
    _coerce_number,
    transform_query_metrics,
    transform_resolve_query_result,
)


class TestCoerceNumber:
    """Tests for the _coerce_number helper."""

    def test_passes_through_int_and_float(self):
        assert _coerce_number(42) == 42
        assert _coerce_number(3.5) == 3.5

    def test_parses_numeric_strings(self):
        # Databricks REST APIs serialize int64 fields as JSON strings.
        assert _coerce_number("1048576") == 1048576
        assert _coerce_number("10.5") == 10.5
        assert _coerce_number("  0  ") == 0

    def test_returns_none_for_non_numeric(self):
        assert _coerce_number("n/a") is None
        assert _coerce_number("") is None
        assert _coerce_number(None) is None

    def test_ignores_bool(self):
        # bool is an int subclass but is not a meaningful metric value.
        assert _coerce_number(True) is None


class TestTransformQueryMetrics:
    """Tests for transform_query_metrics."""

    def test_string_valued_metrics_do_not_raise(self):
        """Regression: query-history API returns int64 metrics as strings.

        Previously this raised ``TypeError: '>' not supported between
        instances of 'str' and 'int'`` when the query agent resolved a query
        by statement id.
        """
        metrics = {
            "total_time_ms": "5000",
            "task_total_time_ms": "4000",
            "photon_total_time_ms": "3800",
            "read_bytes": "1048576",
            "pruned_bytes": "524288",
            "spill_to_disk_bytes": "0",
        }

        result = transform_query_metrics(metrics)

        assert result is not None
        assert result["read_bytes"] == 1048576
        assert result["photon_coverage_pct"] == 95.0
        assert result["pruning_efficiency_pct"] == 33.3

    def test_disk_spill_flag_from_string_value(self):
        result = transform_query_metrics({"spill_to_disk_bytes": "128"})
        assert result is not None
        assert result["flags"]["has_disk_spill"] is True

    def test_non_numeric_values_are_skipped(self):
        result = transform_query_metrics(
            {"read_bytes": 2048, "pruned_bytes": "", "spill_to_disk_bytes": "n/a"}
        )
        assert result == {"read_bytes": 2048}

    def test_returns_none_for_empty_metrics(self):
        assert transform_query_metrics(None) is None
        assert transform_query_metrics({}) is None


class TestTransformResolveQueryResult:
    """Tests for the resolve_query enrichment path."""

    def test_string_metrics_flow_through_resolve(self):
        raw = {
            "source": "query_history",
            "statement_id": "01f1838a-fade-1138-818d-52d0a75530d6",
            "sql_text": "SELECT 1",
            "plan_text": None,
            "metrics": {"read_bytes": "1048576", "spill_to_disk_bytes": "0"},
        }

        enhanced = transform_resolve_query_result(raw)

        assert enhanced["metrics_summary"]["read_bytes"] == 1048576
