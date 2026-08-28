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
    "build_utilization_bands_spec",
    "build_cost_trend_spec",
    "build_rightsizing_waterfall_spec",
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
    RIGHTSIZING_WATERFALL = "rightsizing-waterfall"


CHART_KINDS: tuple[str, ...] = tuple(k.value for k in ChartKind)


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
        options={"interpolate": "monotone", "point": True},
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


_BUILDERS = {
    ChartKind.UTILIZATION_BANDS: build_utilization_bands_spec,
    ChartKind.COST_TREND: build_cost_trend_spec,
    ChartKind.RIGHTSIZING_WATERFALL: build_rightsizing_waterfall_spec,
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
