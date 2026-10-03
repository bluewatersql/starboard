# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard_x.charts`` — SDK-free chart-spec builder (Phase-2 X2).

Emits a Vega-Lite-style **chart spec** (declarative JSON), never a rendered
image (decision D-2.2): no render dependencies (``altair`` / ``vl-convert`` were
removed in Wave-3 cleanup and must not be reintroduced). The output mirrors the
``VisualizationOutput`` shape produced by
:mod:`starboard.tools.services.direct_chart_builder` so a downstream consumer can
treat both identically:

    {
      "summary": str,
      "chart_recommendation": {"chart_type", "reasoning", "confidence"} | None,
      "chart_config": {"chart_type", "title", "description", "encodings", "options"},
      "data_reference": str,
      "has_visualization": bool,
    }

Kernel purity (import-linter contract 3, "pure analyzers are SDK-free"): this
module is stdlib-only — it imports **no** ``databricks-sdk`` / ``openai`` /
``fastapi`` / ``mcp`` / ``altair`` and never reaches into the heavy ``starboard``
server package.

The three builders cover the common right-sizing analytic outputs:
``utilization-bands`` (distribution of nodes across utilization bands),
``cost-trend`` (daily list-price cost over time), and ``rightsizing-waterfall``
(current → target cost bridge).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

__all__ = [
    "ChartType",
    "EncodingType",
    "ChartKind",
    "CHART_KINDS",
    "REQUIRED_FIELDS",
    "build_utilization_bands_spec",
    "build_cost_trend_spec",
    "build_dbu_trend_spec",
    "build_rightsizing_waterfall_spec",
    "build_spend_by_product_spec",
    "build_spend_concentration_spec",
    "build_recoverable_dbu_spec",
    "build_cost_by_product_spec",
    "build_spend_over_time_spec",
    "build_finding_count_over_time_spec",
    "build_chart_spec",
]


class ChartType(StrEnum):
    """Vega-Lite mark types (mirrors ``visualization_models.ChartType``)."""

    BAR = "bar"
    LINE = "line"
    AREA = "area"
    SCATTER = "scatter"
    HISTOGRAM = "histogram"
    TABLE = "table"


class EncodingType(StrEnum):
    """Vega-Lite encoding types (mirrors ``visualization_models.EncodingType``)."""

    QUANTITATIVE = "quantitative"
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    TEMPORAL = "temporal"


class ChartKind(StrEnum):
    """The analytic chart kinds this builder ships."""

    UTILIZATION_BANDS = "utilization-bands"
    COST_TREND = "cost-trend"
    DBU_TREND = "dbu-trend"
    RIGHTSIZING_WATERFALL = "rightsizing-waterfall"
    SPEND_BY_PRODUCT = "spend-by-product"
    SPEND_CONCENTRATION = "spend-concentration"
    RECOVERABLE_DBU = "recoverable-dbu"
    COST_BY_PRODUCT = "cost-by-product"
    SPEND_OVER_TIME = "spend-over-time"
    FINDING_COUNT_OVER_TIME = "finding-count-over-time"


CHART_KINDS: tuple[str, ...] = tuple(k.value for k in ChartKind)

# Required input columns for each chart kind — consumed by the CLI help text
# and by consumers who need to know which columns must be present in the data
# before passing it to the chart spec renderer.
#
# Since ChartKind is a StrEnum, these keys compare equal to their plain string
# equivalents (e.g. REQUIRED_FIELDS["cost-trend"] works too).
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    ChartKind.UTILIZATION_BANDS: ("utilization_band", "node_count", "resource"),
    ChartKind.COST_TREND: ("usage_date", "list_cost_usd"),
    ChartKind.DBU_TREND: ("usage_date", "total_dbus"),
    ChartKind.RIGHTSIZING_WATERFALL: ("stage", "list_cost_usd"),
    ChartKind.SPEND_BY_PRODUCT: ("billing_origin_product", "total_dbus"),
    ChartKind.SPEND_CONCENTRATION: ("driver", "share_pct"),
    ChartKind.RECOVERABLE_DBU: ("opportunity", "recoverable_dbus", "confidence_tier"),
    ChartKind.COST_BY_PRODUCT: ("billing_origin_product", "list_cost_usd"),
    ChartKind.SPEND_OVER_TIME: ("run_date", "total_dbu_estimate"),
    ChartKind.FINDING_COUNT_OVER_TIME: ("run_date", "count", "severity"),
}


def _encoding(field: str, enc_type: EncodingType, title: str, **extra: Any) -> dict[str, Any]:
    """Build one Vega-Lite encoding channel."""
    enc: dict[str, Any] = {"field": field, "type": str(enc_type.value), "title": title}
    enc.update(extra)
    return enc


def _visualization_output(
    *,
    summary: str,
    chart_type: ChartType,
    title: str,
    encodings: dict[str, dict[str, Any]],
    reasoning: str,
    data_reference: str,
    description: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the ``VisualizationOutput``-shaped chart spec (D-2.2)."""
    return {
        "summary": summary,
        "chart_recommendation": {
            "chart_type": str(chart_type.value),
            "reasoning": reasoning,
            "confidence": 1.0,
        },
        "chart_config": {
            "chart_type": str(chart_type.value),
            "title": title,
            "description": description,
            "encodings": encodings,
            "options": options,
        },
        "data_reference": data_reference,
        "has_visualization": True,
    }


def build_utilization_bands_spec(
    data_reference: str = "utilization_bands",
) -> dict[str, Any]:
    """Distribution of nodes across CPU/memory utilization bands (bar chart)."""
    return _visualization_output(
        summary=(
            "Distribution of cluster nodes across utilization bands "
            "(idle / low / healthy / high / saturated)."
        ),
        chart_type=ChartType.BAR,
        title="Node Utilization Bands",
        description="How many nodes fall into each p95 utilization band.",
        encodings={
            "x": _encoding(
                "utilization_band", EncodingType.ORDINAL, "Utilization Band"
            ),
            "y": _encoding("node_count", EncodingType.QUANTITATIVE, "Node Count"),
            "color": _encoding(
                "resource", EncodingType.NOMINAL, "Resource"
            ),
        },
        reasoning=(
            "Bar chart compares node counts across ordered utilization bands to "
            "surface over- and under-provisioned tails."
        ),
        data_reference=data_reference,
    )


def build_cost_trend_spec(data_reference: str = "cost_trend") -> dict[str, Any]:
    """Daily list-price DBU cost over time (temporal line chart)."""
    return _visualization_output(
        summary=(
            "Daily compute cost over time (list-price DBU estimate, $). "
            "List price only; actual cost may differ under contracted rates."
        ),
        chart_type=ChartType.LINE,
        title="Daily Cost Trend (list-price $, DBU estimate)",
        description="List-price DBU cost per day; use to spot cost regressions.",
        encodings={
            "x": _encoding("usage_date", EncodingType.TEMPORAL, "Date"),
            "y": _encoding(
                "list_cost_usd",
                EncodingType.QUANTITATIVE,
                "List-price cost ($/day)",
            ),
        },
        reasoning=(
            "Line chart selected for temporal cost data to show list-price DBU "
            "spend trends over time."
        ),
        data_reference=data_reference,
        options={"interpolate": "linear", "point": True},
    )


def build_dbu_trend_spec(data_reference: str = "dbu_trend") -> dict[str, Any]:
    """Daily list-price DBU consumption over time (temporal line chart).

    DBU-denominated counterpart to :func:`build_cost_trend_spec`.  Use this
    kind when the engagement path is DBU-first (list-price DBU estimates) and a
    dollar axis is not appropriate.

    Required input columns: ``usage_date``, ``total_dbus``.
    """
    return _visualization_output(
        summary=(
            "Daily DBU consumption over time (list-price DBU estimate). "
            "DBU is a usage unit, not a dollar amount. "
            "List price only; actual cost may differ under contracted rates."
        ),
        chart_type=ChartType.LINE,
        title="Daily DBU Trend (list-price est.)",
        description="List-price DBU per day; use to spot DBU consumption regressions.",
        encodings={
            "x": _encoding("usage_date", EncodingType.TEMPORAL, "Date"),
            "y": _encoding(
                "total_dbus",
                EncodingType.QUANTITATIVE,
                "Total DBU (list-price est.)",
            ),
        },
        reasoning=(
            "Line chart selected for temporal DBU data to show list-price DBU "
            "consumption trends over time (DBU-first, no dollar axis)."
        ),
        data_reference=data_reference,
        options={"interpolate": "linear", "point": True},
    )


def build_rightsizing_waterfall_spec(
    data_reference: str = "rightsizing_waterfall",
) -> dict[str, Any]:
    """Current → target list-price cost bridge for a right-sizing recommendation."""
    return _visualization_output(
        summary=(
            "Right-sizing cost bridge: current list-price spend, projected "
            "reduction, and target spend (list-price DBU estimate, $)."
        ),
        chart_type=ChartType.BAR,
        title="Right-sizing Waterfall (list-price $, DBU estimate)",
        description=(
            "Waterfall from current to target list-price cost after applying the "
            "recommended right-sizing action."
        ),
        encodings={
            "x": _encoding("stage", EncodingType.ORDINAL, "Stage"),
            "y": _encoding(
                "list_cost_usd",
                EncodingType.QUANTITATIVE,
                "List-price cost ($)",
            ),
            "color": _encoding("stage", EncodingType.NOMINAL, "Stage"),
        },
        reasoning=(
            "Bar/waterfall chart bridges current to target list-price cost so the "
            "projected savings from a right-sizing action are legible."
        ),
        data_reference=data_reference,
        options={"mark": "waterfall"},
    )


# Vega expression that maps billing_origin_product enum values to customer-
# friendly labels.  Unknown values fall back to datum.value (the raw enum
# string) so future products are still legible without a code change.
_PRODUCT_LABEL_EXPR: str = (
    "datum.value == 'JOBS' ? 'Jobs'"
    " : datum.value == 'DLT' ? 'Lakeflow Declarative Pipelines'"
    " : datum.value == 'SQL' ? 'Databricks SQL'"
    " : datum.value == 'ALL_PURPOSE' ? 'All-purpose compute'"
    " : datum.value == 'INTERACTIVE' ? 'Interactive'"
    " : datum.value == 'PREDICTIVE_OPTIMIZATION' ? 'Predictive optimization'"
    " : datum.value == 'LAKEBASE' ? 'Lakebase'"
    " : datum.value == 'DATABASE' ? 'Lakebase'"
    " : datum.value == 'MODEL_SERVING' ? 'Model serving'"
    " : datum.value == 'VECTOR_SEARCH' ? 'Vector search'"
    " : datum.value == 'APPS' ? 'Apps'"
    " : datum.value"
)


def build_spend_by_product_spec(data_reference: str = "spend_by_product") -> dict[str, Any]:
    """30-day DBU by billing_origin_product (horizontal bar; list-price DBU estimate).

    Horizontal layout mirrors :func:`build_spend_concentration_spec`: product
    names read naturally on the y-axis instead of being truncated as rotated
    x-axis labels.  A Vega-Lite ``labelExpr`` on the y-axis maps raw enum
    values (``PREDICTIVE_OPTIMIZATION``, ``DLT``, …) to customer-friendly
    strings; unknown future enums fall back to the raw value.  The color
    channel is omitted — a per-product legend only duplicated the axis labels.
    """
    return _visualization_output(
        summary="30-day spend by product (list-price DBU estimate). DBU is a usage unit, not a dollar amount.",
        chart_type=ChartType.BAR,
        title="Spend by Product (30-day DBU, list-price est.)",
        description="Total DBU per billing_origin_product over the window.",
        encodings={
            "y": _encoding(
                "billing_origin_product",
                EncodingType.NOMINAL,
                "Product",
                sort="-x",
                axis={"labelExpr": _PRODUCT_LABEL_EXPR},
            ),
            "x": _encoding("total_dbus", EncodingType.QUANTITATIVE, "Total DBU (30d)"),
        },
        reasoning=(
            "Horizontal bar chart ranks products by DBU descending so the dominant "
            "spend leads; product names on the y-axis are fully readable without rotation."
        ),
        data_reference=data_reference,
    )


def build_spend_concentration_spec(data_reference: str = "spend_concentration") -> dict[str, Any]:
    """Share of total DBU held by the top drivers (bar; list-price DBU estimate)."""
    return _visualization_output(
        summary="Concentration of DBU across the top cost drivers (list-price DBU estimate).",
        chart_type=ChartType.BAR,
        title="Spend Concentration (share of 30-day DBU)",
        description="Each driver's share of total DBU, largest first.",
        # Horizontal bars: driver names are long (job/pipeline names), so they
        # read on the y-axis instead of being truncated as rotated x labels. No
        # color channel — a per-driver legend only duplicated (and truncated) the
        # axis labels.
        encodings={
            "y": _encoding("driver", EncodingType.NOMINAL, "Cost driver", sort="-x"),
            "x": _encoding("share_pct", EncodingType.QUANTITATIVE, "Share of DBU (%)"),
        },
        reasoning="Horizontal bar chart of DBU share descending surfaces how few drivers carry most of the spend.",
        data_reference=data_reference,
    )


def build_recoverable_dbu_spec(data_reference: str = "recoverable_dbu") -> dict[str, Any]:
    """Recoverable DBU per opportunity (bar; bounded list-price DBU estimate)."""
    return _visualization_output(
        summary="Bounded recoverable DBU per opportunity (list-price DBU estimate); not a per-day projection.",
        chart_type=ChartType.BAR,
        title="Recoverable DBU by Opportunity (30-day, bounded est.)",
        description="Expected recoverable DBU per verified opportunity.",
        encodings={
            "x": _encoding("opportunity", EncodingType.NOMINAL, "Opportunity", sort="-y"),
            "y": _encoding("recoverable_dbus", EncodingType.QUANTITATIVE, "Recoverable DBU (30d)"),
            "color": _encoding("confidence_tier", EncodingType.NOMINAL, "Tier"),
        },
        reasoning="Bar chart ranks opportunities by bounded recoverable DBU descending so the plan leads with the biggest confident win.",
        data_reference=data_reference,
    )


def build_cost_by_product_spec(data_reference: str = "cost_by_product") -> dict[str, Any]:
    """30-day list-price cost ($) by billing_origin_product (bar; DBU-derived estimate)."""
    return _visualization_output(
        summary=(
            "30-day compute cost by product (list-price $, DBU estimate). "
            "List price only; actual cost may differ under contracted rates."
        ),
        chart_type=ChartType.BAR,
        title="Cost by Product (30-day list-price $, DBU estimate)",
        description="List-price dollar cost per billing_origin_product over the window.",
        encodings={
            "x": _encoding("billing_origin_product", EncodingType.NOMINAL, "Product", sort="-y"),
            "y": _encoding("list_cost_usd", EncodingType.QUANTITATIVE, "List-price cost ($, 30d)"),
            "color": _encoding("billing_origin_product", EncodingType.NOMINAL, "Product"),
        },
        reasoning=(
            "Bar chart ranks products by list-price dollar cost descending so a cost "
            "deck leads with the dominant $ driver (complements the DBU spend-by-product view)."
        ),
        data_reference=data_reference,
    )


def build_spend_over_time_spec(data_reference: str = "spend_over_time") -> dict[str, Any]:
    """Total list-price DBU per review run over time (temporal line; trend chart).

    The cross-run trend view for recurring reviews: one point per dated run,
    read from an accumulated ``trend/history.json``. DBU-denominated and
    account-scoped (``system.billing.usage`` is account-scoped) — labelled as
    such so the trend is not misread as workspace-attributable spend.
    """
    return _visualization_output(
        summary=(
            "Total workload spend per run over time (list-price DBU estimate, "
            "account-scoped). DBU is a usage unit, not a dollar amount."
        ),
        chart_type=ChartType.LINE,
        title="Spend Over Time (per-run DBU, list-price est., account-scoped)",
        description=(
            "Total list-price DBU estimate per review run; use to see whether "
            "spend is trending down across runs."
        ),
        encodings={
            "x": _encoding("run_date", EncodingType.TEMPORAL, "Run date"),
            "y": _encoding(
                "total_dbu_estimate",
                EncodingType.QUANTITATIVE,
                "Total DBU (list-price est.)",
            ),
        },
        reasoning=(
            "Line chart over the run date shows the list-price DBU trend across "
            "recurring reviews so 'are we improving?' is legible at a glance."
        ),
        data_reference=data_reference,
        options={"interpolate": "linear", "point": True},
    )


def build_finding_count_over_time_spec(
    data_reference: str = "finding_count_over_time",
) -> dict[str, Any]:
    """Finding counts by severity per review run over time (temporal multi-line).

    Expects long-form rows — one per (run, severity) — so each severity renders
    as its own line: ``[{"run_date", "severity", "count"}, ...]``. The severity
    color series carries the critical/high/medium trend across runs.
    """
    return _visualization_output(
        summary=(
            "Finding counts by severity per run over time — the "
            "'are we improving?' view across recurring reviews."
        ),
        chart_type=ChartType.LINE,
        title="Finding Count Over Time (by severity)",
        description="Critical / high / medium finding counts per review run.",
        encodings={
            "x": _encoding("run_date", EncodingType.TEMPORAL, "Run date"),
            "y": _encoding("count", EncodingType.QUANTITATIVE, "Finding count"),
            "color": _encoding("severity", EncodingType.NOMINAL, "Severity"),
        },
        reasoning=(
            "Multi-series line (one line per severity) over the run date shows "
            "whether high-severity findings are trending down across runs."
        ),
        data_reference=data_reference,
        options={"interpolate": "linear", "point": True},
    )


_BUILDERS = {
    ChartKind.UTILIZATION_BANDS: build_utilization_bands_spec,
    ChartKind.COST_TREND: build_cost_trend_spec,
    ChartKind.DBU_TREND: build_dbu_trend_spec,
    ChartKind.RIGHTSIZING_WATERFALL: build_rightsizing_waterfall_spec,
    ChartKind.SPEND_BY_PRODUCT: build_spend_by_product_spec,
    ChartKind.SPEND_CONCENTRATION: build_spend_concentration_spec,
    ChartKind.RECOVERABLE_DBU: build_recoverable_dbu_spec,
    ChartKind.COST_BY_PRODUCT: build_cost_by_product_spec,
    ChartKind.SPEND_OVER_TIME: build_spend_over_time_spec,
    ChartKind.FINDING_COUNT_OVER_TIME: build_finding_count_over_time_spec,
}


def build_chart_spec(
    kind: str | ChartKind, data_reference: str | None = None
) -> dict[str, Any]:
    """Build a chart spec by kind name.

    Args:
        kind: One of :data:`CHART_KINDS` (or a :class:`ChartKind`).
        data_reference: Optional cache key override for the spec.

    Raises:
        ValueError: if ``kind`` is not a known chart kind.
    """
    try:
        chart_kind = ChartKind(kind)
    except ValueError as exc:
        raise ValueError(
            f"unknown chart kind '{kind}'; expected one of {', '.join(CHART_KINDS)}"
        ) from exc
    builder = _BUILDERS[chart_kind]
    if data_reference is not None:
        return builder(data_reference=data_reference)
    return builder()
