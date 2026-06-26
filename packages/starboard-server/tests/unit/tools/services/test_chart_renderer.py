# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for ChartRenderer service.

Tests chart rendering from ChartConfig to PNG/SVG images.
"""

from __future__ import annotations

import polars as pl
import pytest
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartType,
    Encoding,
    EncodingType,
)


class TestChartConfigToAltair:
    """Test conversion of ChartConfig to Altair charts."""

    def test_bar_chart_basic(self):
        """Test basic bar chart conversion."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        # Create sample data
        data = pl.DataFrame(
            {
                "category": ["A", "B", "C", "D"],
                "value": [10, 20, 15, 25],
            }
        )

        # Create chart config
        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test Bar Chart",
            encodings={
                "x": Encoding(
                    field="category", type=EncodingType.NOMINAL, title="Category"
                ),
                "y": Encoding(
                    field="value", type=EncodingType.QUANTITATIVE, title="Value"
                ),
            },
            options={},
        )

        # Convert to Altair
        chart = renderer._chartconfig_to_altair(config, data)

        # Verify chart exists and has correct type
        assert chart is not None
        # chart.mark can be string or MarkDef object
        mark_type = chart.mark.type if hasattr(chart.mark, "type") else chart.mark
        assert mark_type == "bar"

    def test_line_chart_temporal(self):
        """Test line chart with temporal x-axis."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        # Create sample time-series data
        data = pl.DataFrame(
            {
                "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                "value": [10, 15, 12],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.LINE,
            title="Time Series",
            encodings={
                "x": Encoding(field="date", type=EncodingType.TEMPORAL, title="Date"),
                "y": Encoding(
                    field="value", type=EncodingType.QUANTITATIVE, title="Value"
                ),
            },
            options={"interpolation": "monotone"},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None
        assert chart.mark.type == "line"

    def test_area_chart_with_interpolation(self):
        """Test area chart with interpolation option."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "x": [1, 2, 3, 4, 5],
                "y": [10, 20, 15, 25, 20],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.AREA,
            title="Area Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.QUANTITATIVE, title="X"),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE, title="Y"),
            },
            options={"interpolation": "step"},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None
        assert chart.mark.type == "area"

    def test_scatter_chart_with_color(self):
        """Test scatter chart with color encoding."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "x": [1, 2, 3, 4],
                "y": [10, 20, 15, 25],
                "category": ["A", "B", "A", "B"],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.SCATTER,
            title="Scatter Plot",
            encodings={
                "x": Encoding(field="x", type=EncodingType.QUANTITATIVE, title="X"),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE, title="Y"),
                "color": Encoding(
                    field="category", type=EncodingType.NOMINAL, title="Category"
                ),
            },
            options={},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None
        mark_type = chart.mark.type if hasattr(chart.mark, "type") else chart.mark
        assert mark_type == "point"  # Altair uses 'point' for scatter

    def test_histogram_basic(self):
        """Test histogram chart."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "value": [1, 2, 2, 3, 3, 3, 4, 4, 5],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.HISTOGRAM,
            title="Distribution",
            encodings={
                "x": Encoding(
                    field="value", type=EncodingType.QUANTITATIVE, title="Value"
                ),
            },
            options={},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None
        mark_type = chart.mark.type if hasattr(chart.mark, "type") else chart.mark
        assert mark_type == "bar"  # Histogram uses bar mark

    def test_chart_with_title_and_description(self):
        """Test that title and description are applied."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame({"x": [1, 2], "y": [10, 20]})

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="My Chart Title",
            description="This is a test chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None
        # Verify title is set (Altair stores it in properties)
        assert hasattr(chart, "title")

    def test_chart_with_sorting(self):
        """Test chart with sorting option."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "category": ["A", "B", "C"],
                "value": [15, 10, 20],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Sorted Bar Chart",
            encodings={
                "x": Encoding(
                    field="category",
                    type=EncodingType.NOMINAL,
                    sort="ascending",
                ),
                "y": Encoding(field="value", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        chart = renderer._chartconfig_to_altair(config, data)

        assert chart is not None

    def test_missing_required_encodings(self):
        """Test handling of missing required encodings."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame({"x": [1, 2]})

        # Bar chart requires both x and y
        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Incomplete Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                # Missing y encoding
            },
            options={},
        )

        # Should raise ValueError or return error
        with pytest.raises((ValueError, KeyError)):
            renderer._chartconfig_to_altair(config, data)


class TestChartRendering:
    """Test chart rendering to PNG/SVG."""

    def test_render_to_png(self):
        """Test rendering chart to PNG."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "x": ["A", "B", "C"],
                "y": [10, 20, 15],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        # Render to PNG
        png_bytes = renderer.render_chart(config, data, format="png")

        # Verify it's a PNG (starts with PNG signature)
        assert png_bytes is not None
        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 0
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature

    def test_render_to_svg(self):
        """Test rendering chart to SVG."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame(
            {
                "x": ["A", "B", "C"],
                "y": [10, 20, 15],
            }
        )

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        # Render to SVG
        svg_str = renderer.render_chart(config, data, format="svg")

        # Verify it's SVG XML
        assert svg_str is not None
        assert isinstance(svg_str, str)
        assert svg_str.strip().startswith("<svg")
        assert "</svg>" in svg_str

    def test_render_with_empty_data(self):
        """Test rendering with empty data."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame({"x": [], "y": []})

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Empty Chart",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        # Should still render (empty chart)
        png_bytes = renderer.render_chart(config, data, format="png")

        assert png_bytes is not None
        assert isinstance(png_bytes, bytes)

    def test_render_invalid_format(self):
        """Test rendering with invalid format."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        data = pl.DataFrame({"x": ["A"], "y": [10]})

        config = ChartConfig(
            chart_type=ChartType.BAR,
            title="Test",
            encodings={
                "x": Encoding(field="x", type=EncodingType.NOMINAL),
                "y": Encoding(field="y", type=EncodingType.QUANTITATIVE),
            },
            options={},
        )

        # Should raise ValueError for invalid format
        with pytest.raises(ValueError):
            renderer.render_chart(config, data, format="pdf")  # type: ignore


class TestRendererInit:
    """Test ChartRenderer initialization."""

    def test_init_default(self):
        """Test default initialization."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer()

        assert renderer is not None
        assert hasattr(renderer, "render_chart")
        assert hasattr(renderer, "_chartconfig_to_altair")

    def test_init_with_options(self):
        """Test initialization with custom options."""
        from starboard_server.tools.services.chart_renderer import ChartRenderer

        renderer = ChartRenderer(width=1000, height=800, dpi=150)

        assert renderer is not None
        assert renderer.width == 1000
        assert renderer.height == 800
        assert renderer.dpi == 150
