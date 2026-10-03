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
    REQUIRED_FIELDS,
    build_chart_spec,
    build_cost_trend_spec,
    build_dbu_trend_spec,
    build_finding_count_over_time_spec,
    build_rightsizing_waterfall_spec,
    build_spend_over_time_spec,
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


@pytest.mark.parametrize("kind", ["spend-by-product", "spend-concentration", "recoverable-dbu"])
@pytest.mark.unit
def test_new_dbu_kinds_registered_and_build(kind):
    assert kind in CHART_KINDS
    spec = build_chart_spec(kind)
    assert spec["has_visualization"] is True
    cfg = spec["chart_config"]
    assert cfg["title"] and cfg["encodings"]


@pytest.mark.unit
def test_spend_concentration_is_horizontal_without_legend():
    """Long driver names read on the y-axis; no color channel duplicating them."""
    enc = build_chart_spec("spend-concentration")["chart_config"]["encodings"]
    assert enc["y"]["field"] == "driver" and enc["y"].get("sort") == "-x"
    assert enc["x"]["field"] == "share_pct"
    assert "color" not in enc


@pytest.mark.unit
def test_recoverable_dbu_has_descending_x_sort():
    """recoverable-dbu: x encoding (the measure) carries sort='-y' for vertical bar."""
    spec = build_chart_spec("recoverable-dbu")
    x_enc = spec["chart_config"]["encodings"]["x"]
    assert x_enc.get("sort") == "-y", (
        f"recoverable-dbu: x encoding missing descending sort; got sort={x_enc.get('sort')!r}"
    )


@pytest.mark.unit
def test_spend_by_product_is_horizontal_with_friendly_labels():
    """spend-by-product: horizontal layout (y=product, x=dbus), no color, labelExpr."""
    enc = build_chart_spec("spend-by-product")["chart_config"]["encodings"]
    # Horizontal: product on y-axis sorted descending by x value.
    assert enc["y"]["field"] == "billing_origin_product"
    assert enc["y"].get("sort") == "-x"
    # Friendly label expression must be present on the y axis.
    axis = enc["y"].get("axis", {})
    assert "labelExpr" in axis, "spend-by-product y-axis must carry a labelExpr for friendly names"
    # Spot-check a few known enum mappings.
    label_expr = axis["labelExpr"]
    assert "JOBS" in label_expr and "Jobs" in label_expr
    assert "PREDICTIVE_OPTIMIZATION" in label_expr and "Predictive optimization" in label_expr
    assert "DLT" in label_expr and "Lakeflow" in label_expr
    # Measure on x-axis.
    assert enc["x"]["field"] == "total_dbus"
    # No color channel — would duplicate the axis labels.
    assert "color" not in enc


@pytest.mark.parametrize("kind", ["spend-by-product", "spend-concentration", "recoverable-dbu"])
@pytest.mark.unit
def test_new_kinds_are_dbu_not_usd(kind):
    # DBU-first: no field/encoding may be a *_usd column on these kinds.
    import json
    blob = json.dumps(build_chart_spec(kind)).lower()
    assert "_usd" not in blob, f"{kind} leaks a USD field; kinds are DBU-first"
    assert "dbu" in blob


@pytest.mark.unit
def test_cost_by_product_spec_is_dollar_denominated():
    from starboard_x.charts import CHART_KINDS, build_chart_spec
    assert "cost-by-product" in CHART_KINDS
    spec = build_chart_spec("cost-by-product")
    cfg = spec["chart_config"]
    assert cfg["encodings"]["y"]["field"] == "list_cost_usd"
    assert cfg["encodings"]["x"].get("sort") == "-y"
    assert "$" in cfg["title"] and "list-price" in cfg["title"].lower()
    # DBU spend chart stays DBU-denominated and carries no bare "$" in its title
    dbu = build_chart_spec("spend-by-product")["chart_config"]
    assert "DBU" in dbu["title"] and "$" not in dbu["title"]


@pytest.mark.parametrize("kind", ["spend-over-time", "finding-count-over-time"])
@pytest.mark.unit
def test_trend_kinds_registered_and_build(kind):
    """Cross-run trend kinds are registered and produce a valid temporal line spec."""
    assert kind in CHART_KINDS
    spec = build_chart_spec(kind)
    _assert_visualization_output(spec)
    cfg = spec["chart_config"]
    assert cfg["chart_type"] == "line"
    # Trend charts plot metrics against the run date on the x-axis.
    assert cfg["encodings"]["x"]["type"] == "temporal"
    assert cfg["encodings"]["x"]["field"] == "run_date"


@pytest.mark.unit
def test_spend_over_time_is_dbu_and_list_price():
    """Spend trend is DBU-denominated, list-price-labelled, and account-scoped."""
    spec = build_spend_over_time_spec()
    cfg = spec["chart_config"]
    assert cfg["encodings"]["y"]["field"] == "total_dbu_estimate"
    blob = json.dumps(spec).lower()
    # Governance: DBU-first (no USD leak) and `$`/DBU == list-price estimate.
    assert "_usd" not in blob, "spend-over-time leaks a USD field; it is DBU-first"
    assert "dbu" in blob
    assert "list-price" in blob or "list price" in blob
    # Account-scoped caveat must ride along (system.billing.usage is account-scoped).
    assert "account-scoped" in blob


@pytest.mark.unit
def test_finding_count_over_time_series_by_severity():
    """Finding-count trend carries a severity color series and a count measure."""
    spec = build_finding_count_over_time_spec()
    encs = spec["chart_config"]["encodings"]
    assert encs["color"]["field"] == "severity"
    assert encs["color"]["type"] == "nominal"
    assert encs["y"]["field"] == "count"
    assert encs["y"]["type"] == "quantitative"


@pytest.mark.unit
def test_dbu_trend_kind_registered_and_builds() -> None:
    """dbu-trend is registered, builds a temporal line spec, and is DBU-first."""
    assert "dbu-trend" in CHART_KINDS
    spec = build_dbu_trend_spec()
    _assert_visualization_output(spec)
    cfg = spec["chart_config"]
    assert cfg["chart_type"] == "line"
    assert cfg["encodings"]["x"]["field"] == "usage_date"
    assert cfg["encodings"]["x"]["type"] == "temporal"
    assert cfg["encodings"]["y"]["field"] == "total_dbus"
    assert cfg["encodings"]["y"]["type"] == "quantitative"
    blob = json.dumps(spec).lower()
    # DBU-first: no USD fields
    assert "_usd" not in blob, "dbu-trend must not contain a USD field"
    assert "dbu" in blob
    # Governance: must be labelled as a list-price estimate
    assert "list-price" in blob or "list price" in blob


@pytest.mark.unit
def test_dbu_trend_dispatch_via_build_chart_spec() -> None:
    """build_chart_spec('dbu-trend') routes to the correct builder."""
    spec = build_chart_spec("dbu-trend")
    assert spec["chart_config"]["encodings"]["x"]["field"] == "usage_date"
    assert spec["chart_config"]["encodings"]["y"]["field"] == "total_dbus"


@pytest.mark.unit
def test_dbu_trend_has_interpolate_options() -> None:
    """dbu-trend carries the same linear+point options as cost-trend."""
    spec = build_dbu_trend_spec()
    opts = spec["chart_config"]["options"]
    assert opts is not None
    assert opts.get("interpolate") == "linear"
    assert opts.get("point") is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "builder",
    [
        build_cost_trend_spec,
        build_dbu_trend_spec,
        build_spend_over_time_spec,
        build_finding_count_over_time_spec,
    ],
)
def test_line_charts_use_linear_interpolation(builder) -> None:
    """E5: line charts join points with straight segments, never a smoothed curve.

    A monotone/basis curve invents values between daily points and can hide a
    one-day step, so every line chart uses ``linear``.
    """
    opts = builder()["chart_config"]["options"]
    assert opts["interpolate"] == "linear"


@pytest.mark.unit
def test_required_fields_registry_covers_all_kinds() -> None:
    """REQUIRED_FIELDS must have an entry for every registered chart kind."""
    for kind in CHART_KINDS:
        assert kind in REQUIRED_FIELDS, (
            f"REQUIRED_FIELDS is missing an entry for chart kind '{kind}'"
        )
        fields = REQUIRED_FIELDS[kind]
        assert len(fields) >= 1, f"'{kind}' must declare at least one required field"
        for field in fields:
            assert isinstance(field, str) and field, (
                f"REQUIRED_FIELDS['{kind}'] contains an empty or non-string entry"
            )


@pytest.mark.unit
def test_required_fields_for_known_kinds() -> None:
    """Spot-check required fields for the most commonly used kinds."""
    assert "billing_origin_product" in REQUIRED_FIELDS["spend-by-product"]
    assert "total_dbus" in REQUIRED_FIELDS["spend-by-product"]
    assert "usage_date" in REQUIRED_FIELDS["cost-trend"]
    assert "list_cost_usd" in REQUIRED_FIELDS["cost-trend"]
    assert "usage_date" in REQUIRED_FIELDS["dbu-trend"]
    assert "total_dbus" in REQUIRED_FIELDS["dbu-trend"]


@pytest.mark.unit
def test_unknown_kind_error_names_valid_kinds() -> None:
    """ValueError for an unknown kind must name valid kind strings."""
    with pytest.raises(ValueError, match="spend-by-product"):
        build_chart_spec("not-a-kind")
    with pytest.raises(ValueError, match="dbu-trend"):
        build_chart_spec("not-a-kind")


@pytest.mark.unit
def test_help_text_lists_required_fields() -> None:
    """--help output must contain required column names for key kinds."""
    proc = subprocess.run(
        [sys.executable, "-m", "starboard_x.charts", "--help"],
        capture_output=True,
        text=True,
        cwd=str(_CORE_DIR),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    # Epilog must show the required-fields table for at least two key kinds.
    assert "usage_date" in output, "--help must list 'usage_date' as a required field"
    assert "total_dbus" in output, "--help must list 'total_dbus' as a required field"
    assert "list_cost_usd" in output, "--help must list 'list_cost_usd' as a required field"
    assert "dbu-trend" in output, "--help must mention the dbu-trend kind"


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
