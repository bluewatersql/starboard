# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for :mod:`starboard_x.charts` — the SDK-free chart-spec builder.

The builder mirrors ``starboard.tools.services.direct_chart_builder``'s
``VisualizationOutput`` shape (decision D-2.2): a Vega-Lite-style chart *spec*
(no render deps — altair / vl-convert are banned). These tests validate the
spec against that schema and assert the SDK/altair-free guarantee.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from starboard_x.charts import (
    CHART_KINDS,
    build_chart_spec,
    build_cost_trend_spec,
    build_rightsizing_waterfall_spec,
    build_utilization_bands_spec,
)

_CORE_DIR = Path(__file__).parents[3]

# Vega-Lite-ish chart types the spec may declare (mirrors ChartType).
_ALLOWED_CHART_TYPES = {"bar", "line", "area", "scatter", "histogram", "table"}
_ALLOWED_ENCODING_TYPES = {"quantitative", "nominal", "ordinal", "temporal"}


def _assert_visualization_output(spec: dict) -> None:
    """Assert the spec is VisualizationOutput-shaped (D-2.2)."""
    assert set(spec) >= {
        "summary",
        "chart_recommendation",
        "chart_config",
        "data_reference",
        "has_visualization",
    }
    assert isinstance(spec["summary"], str) and spec["summary"]
    assert spec["has_visualization"] is True

    config = spec["chart_config"]
    assert config["chart_type"] in _ALLOWED_CHART_TYPES
    assert isinstance(config["title"], str) and config["title"]

    encodings = config["encodings"]
    assert encodings, "chart spec must declare at least one encoding"
    for channel, enc in encodings.items():
        assert channel in {"x", "y", "color", "size"}
        assert enc["field"]
        assert enc["type"] in _ALLOWED_ENCODING_TYPES


@pytest.mark.unit
class TestChartSpecShape:
    def test_utilization_bands(self) -> None:
        spec = build_utilization_bands_spec()
        _assert_visualization_output(spec)
        assert spec["chart_config"]["chart_type"] == "bar"

    def test_cost_trend_is_temporal_line(self) -> None:
        spec = build_cost_trend_spec()
        _assert_visualization_output(spec)
        assert spec["chart_config"]["chart_type"] == "line"
        assert spec["chart_config"]["encodings"]["x"]["type"] == "temporal"

    def test_rightsizing_waterfall(self) -> None:
        spec = build_rightsizing_waterfall_spec()
        _assert_visualization_output(spec)
        assert spec["chart_config"]["chart_type"] == "bar"

    def test_cost_trend_labels_list_price(self) -> None:
        # Governance: `$` on the public path == list-price DBU estimate.
        spec = build_cost_trend_spec()
        blob = json.dumps(spec).lower()
        assert "list-price" in blob or "list price" in blob


@pytest.mark.unit
class TestBuildChartSpecDispatch:
    def test_all_kinds_build(self) -> None:
        for kind in CHART_KINDS:
            spec = build_chart_spec(kind)
            _assert_visualization_output(spec)

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError):
            build_chart_spec("does-not-exist")


@pytest.mark.unit
class TestChartsCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "starboard_x.charts", *args],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )

    def test_help_smoke(self) -> None:
        proc = self._run("--help")
        assert proc.returncode == 0, proc.stderr

    def test_default_emits_spec_envelope(self) -> None:
        proc = self._run()
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert set(payload) >= {"ok", "domain", "command", "data", "error", "meta"}
        assert payload["ok"] is True
        assert payload["domain"] == "charts"

    def test_kind_selects_chart(self) -> None:
        proc = self._run("--kind", "cost-trend")
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)["data"]
        # --kind returns a single-entry mapping keyed by the kind name.
        spec = data["cost-trend"]
        assert spec["chart_config"]["chart_type"] == "line"

    def test_bad_kind_is_arg_error(self) -> None:
        proc = self._run("--kind", "nope")
        assert proc.returncode == 4, proc.stdout


@pytest.mark.unit
class TestSdkFree:
    def test_import_pulls_no_sdk_or_altair(self) -> None:
        body = (
            "import sys\n"
            "import starboard_x.charts  # noqa: F401\n"
            "banned = sorted(m for m in sys.modules if m == 'databricks' "
            "or m.startswith('databricks.') or m in {'altair', 'vl_convert'})\n"
            "assert not banned, banned\n"
            "print('OK')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", body],
            capture_output=True,
            text=True,
            cwd=str(_CORE_DIR),
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert "OK" in result.stdout
