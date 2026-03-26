"""
Chart Renderer Service.

Converts ChartConfig objects to rendered chart images (PNG/SVG) using Altair
and vl-convert-python.

Design:
    - ChartConfig → Altair Chart → Vega-Lite JSON → PNG/SVG
    - Server-side rendering for static images
    - Supports all chart types: bar, line, area, scatter, histogram
    - Configurable dimensions and DPI

Example:
    >>> renderer = ChartRenderer()
    >>> data = pl.DataFrame({"x": ["A", "B"], "y": [10, 20]})
    >>> config = ChartConfig(...)
    >>> png_bytes = renderer.render_chart(config, data, format="png")
"""

from __future__ import annotations

from typing import Any, Literal

import altair as alt
import polars as pl
import vl_convert as vlc

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartType,
    EncodingType,
)
from starboard_server.tools.domain.utils import polars_df_to_dict

logger = get_logger(__name__)


class ChartRenderer:
    """
    Renders ChartConfig objects to PNG/SVG images.

    This service converts validated ChartConfig objects (from VisualizationService)
    into rendered chart images ready for frontend display. It uses Altair for
    declarative chart generation and vl-convert-python for image conversion.

    Attributes:
        width: Default chart width in pixels
        height: Default chart height in pixels
        dpi: DPI for PNG rendering (higher = better quality, larger file)

    Example:
        >>> renderer = ChartRenderer(width=800, height=600)
        >>> data = pl.DataFrame({"category": ["A", "B"], "value": [10, 20]})
        >>> config = ChartConfig(
        ...     chart_type=ChartType.BAR,
        ...     encodings={"x": ..., "y": ...}
        ... )
        >>> png_bytes = renderer.render_chart(config, data, format="png")
    """

    def __init__(
        self,
        width: int = 800,
        height: int = 300,
        dpi: int = 96,
    ) -> None:
        """
        Initialize the chart renderer.

        Args:
            width: Default chart width in pixels (default: 800)
            height: Default chart height in pixels (default: 300, compact for chat)
            dpi: DPI for PNG rendering (default: 96)
        """
        self.width = width
        self.height = height
        self.dpi = dpi

    def render_chart(
        self,
        config: ChartConfig,
        data: pl.DataFrame,
        format: Literal["png", "svg"] = "png",
    ) -> bytes | str:
        """
        Render a chart to PNG or SVG.

        Converts a ChartConfig and data to a rendered image using Altair and
        vl-convert-python. The process:
        1. Convert ChartConfig to Altair chart
        2. Add data to the chart
        3. Generate Vega-Lite JSON specification
        4. Convert to PNG or SVG using vl-convert

        Args:
            config: Chart configuration (from VisualizationService)
            data: Polars DataFrame with the data to visualize
            format: Output format ("png" or "svg")

        Returns:
            PNG bytes if format="png", SVG string if format="svg"

        Raises:
            ValueError: If format is not "png" or "svg"
            ValueError: If chart config is invalid
            RuntimeError: If rendering fails

        Example:
            >>> renderer = ChartRenderer()
            >>> data = pl.DataFrame({"x": ["A", "B"], "y": [10, 20]})
            >>> config = ChartConfig(chart_type=ChartType.BAR, ...)
            >>> png = renderer.render_chart(config, data, format="png")
        """
        if format not in ("png", "svg"):
            raise ValueError(f"Unsupported format: {format}. Must be 'png' or 'svg'.")

        # Validate encoding field names match data columns
        data_columns = set(data.columns)
        missing_fields = []
        for channel, encoding in config.encodings.items():
            if encoding.field not in data_columns:
                missing_fields.append(f"{channel}: '{encoding.field}'")

        if missing_fields:
            logger.warning(
                "chart_encoding_field_mismatch",
                missing_fields=missing_fields,
                available_columns=list(data_columns),
                config_encodings={k: v.field for k, v in config.encodings.items()},
            )
            # Attempt to auto-correct common mismatches (case-insensitive match)
            data_columns_lower = {col.lower(): col for col in data_columns}
            corrected_encodings = {}
            for channel, encoding in config.encodings.items():
                if encoding.field not in data_columns:
                    # Try case-insensitive match
                    lower_field = encoding.field.lower()
                    if lower_field in data_columns_lower:
                        corrected_field = data_columns_lower[lower_field]
                        logger.debug(
                            "chart_encoding_field_corrected",
                            channel=channel,
                            original_field=encoding.field,
                            corrected_field=corrected_field,
                        )
                        # Create corrected encoding
                        from starboard_server.tools.domain.analytics.visualization_models import (
                            Encoding,
                        )

                        corrected_encodings[channel] = Encoding(
                            field=corrected_field,
                            type=encoding.type,
                            title=encoding.title,
                            sort=encoding.sort,
                        )
                    else:
                        corrected_encodings[channel] = encoding
                else:
                    corrected_encodings[channel] = encoding

            # Update config with corrected encodings
            config = ChartConfig(
                chart_type=config.chart_type,
                title=config.title,
                description=config.description,
                encodings=corrected_encodings,
                options=config.options,
            )

        # Get chart type as string (handle both enum and string)
        chart_type_str = (
            config.chart_type.value
            if isinstance(config.chart_type, ChartType)
            else config.chart_type
        )

        logger.debug(
            "chart_render_started",
            chart_type=chart_type_str,
            format=format,
            row_count=len(data),
            columns=list(data.columns),
            dtypes={col: str(data[col].dtype) for col in data.columns},
            encoding_fields={ch: enc.field for ch, enc in config.encodings.items()},
        )

        try:
            # Convert ChartConfig to Altair chart
            chart = self._chartconfig_to_altair(config, data)

            # Get Vega-Lite JSON spec
            vega_lite_spec = chart.to_dict()

            # Debug log the Vega-Lite spec and sample data values
            vl_data = vega_lite_spec.get("data", {})
            vl_values = vl_data.get("values", [])
            encoding_spec = vega_lite_spec.get("encoding", {})

            # Log sample data values for encoding fields
            sample_values = {}
            for channel in ["x", "y", "color"]:
                if channel in config.encodings:
                    field = config.encodings[channel].field
                    if vl_values:
                        sample_values[f"{channel}_{field}"] = [
                            row.get(field) for row in vl_values[:3]
                        ]

            logger.debug(
                "chart_vegalite_spec_debug",
                data_values_count=len(vl_values),
                sample_data_values=sample_values,
                encoding_spec_x=encoding_spec.get("x"),
                encoding_spec_y=encoding_spec.get("y"),
                encoding_spec_color=encoding_spec.get("color"),
                mark_type=vega_lite_spec.get("mark"),
            )

            # Convert to PNG or SVG using vl-convert
            if format == "png":
                png_bytes = vlc.vegalite_to_png(
                    vl_spec=vega_lite_spec,
                    scale=self.dpi / 96,  # Scale factor based on DPI
                )
                logger.debug(
                    "chart_rendered",
                    chart_type=chart_type_str,
                    format="png",
                    size_bytes=len(png_bytes),
                )
                return png_bytes
            else:  # svg
                svg_str = vlc.vegalite_to_svg(vl_spec=vega_lite_spec)
                logger.debug(
                    "chart_rendered",
                    chart_type=chart_type_str,
                    format="svg",
                    size_bytes=len(svg_str),
                )
                return svg_str

        except (ValueError, TypeError, KeyError) as e:
            logger.error(
                "chart_render_failed",
                chart_type=chart_type_str,
                error=str(e),
            )
            raise RuntimeError(f"Failed to render chart: {e}") from e

    def _chartconfig_to_altair(
        self, config: ChartConfig, data: pl.DataFrame
    ) -> alt.Chart:
        """
        Convert ChartConfig to Altair chart.

        Maps our ChartConfig abstraction to Altair's declarative chart API.
        Handles all chart types, encodings, and options.

        Args:
            config: Chart configuration
            data: Data to visualize

        Returns:
            Altair Chart object

        Raises:
            ValueError: If required encodings are missing
            ValueError: If chart type is unsupported
        """
        # Convert Polars DataFrame to format Altair can use
        # Use the standardized serialization utility to handle Date, Datetime, and other types

        # Convert to dict format with proper temporal serialization
        data_payload = polars_df_to_dict(
            data,
            orientation="records",  # Altair expects array of row objects
        )
        data_dict = data_payload["data"]

        # Create base chart with data
        base_chart = alt.Chart(alt.Data(values=data_dict))  # type: ignore[no-untyped-call]

        # Set dimensions
        base_chart = (
            base_chart.properties(
                width=self.width,
                height=self.height,
                title=config.title or "",
            )
            .configure_axis(
                labelLimit=200,  # Allow longer labels without truncation
            )
            .configure_view(
                strokeWidth=0  # Remove border around chart
            )
        )

        # Build encodings
        encodings = self._build_encodings(config)

        # Apply mark based on chart type
        if config.chart_type == ChartType.BAR:
            chart = base_chart.mark_bar().encode(**encodings)
        elif config.chart_type == ChartType.LINE:
            # Apply interpolation option if specified
            interpolation = (config.options or {}).get("interpolation", "linear")
            # Use layer to combine line + points for better visibility
            line = base_chart.mark_line(interpolate=interpolation, point=True).encode(
                **encodings
            )
            chart = line
        elif config.chart_type == ChartType.AREA:
            interpolation = (config.options or {}).get("interpolation", "linear")
            chart = base_chart.mark_area(interpolate=interpolation).encode(**encodings)
        elif config.chart_type == ChartType.SCATTER:
            chart = base_chart.mark_point().encode(**encodings)
        elif config.chart_type == ChartType.HISTOGRAM:
            # Histogram uses bar mark with automatic binning
            chart = base_chart.mark_bar().encode(**encodings)
        else:
            raise ValueError(f"Unsupported chart type: {config.chart_type}")

        return chart  # type: ignore[no-any-return]

    def _build_encodings(self, config: ChartConfig) -> dict[str, Any]:
        """
        Build Altair encodings from ChartConfig encodings.

        Converts our encoding specification to Altair's encoding format.

        Args:
            config: Chart configuration with encodings

        Returns:
            Dictionary of Altair encodings

        Raises:
            ValueError: If required encodings are missing
        """
        encodings = {}

        for channel, encoding in config.encodings.items():
            # Map encoding type to Altair shorthand
            altair_type = self._map_encoding_type(encoding.type)

            # Build field specification with type shorthand (e.g., "field:Q" or "sum(field):Q")
            if encoding.aggregate:
                # Use Altair aggregate syntax: "sum(field):Q"
                field_spec = (
                    f"{encoding.aggregate}({encoding.field}):{altair_type[0].upper()}"
                )
            else:
                # No aggregation: "field:Q"
                field_spec = f"{encoding.field}:{altair_type[0].upper()}"

            # Build encoding kwargs
            encoding_kwargs: dict[str, Any] = {}

            if encoding.title:
                encoding_kwargs["title"] = encoding.title

            if encoding.sort:
                # Map sort string to Altair sort specification
                if encoding.sort in ("ascending", "descending"):
                    encoding_kwargs["sort"] = encoding.sort
                else:
                    # Could be a field name for sorting
                    encoding_kwargs["sort"] = encoding.sort

            # Create Altair encoding using channel-specific constructors
            if channel == "x":
                # For temporal x-axis, add label rotation and formatting to prevent overlap
                if encoding.type == EncodingType.TEMPORAL:
                    encoding_kwargs["axis"] = alt.Axis(
                        labelAngle=-45,  # Rotate labels for better readability
                        format="%b %d",  # Format as "Dec 30" (month abbrev + day)
                        labelOverlap=False,  # Don't allow overlapping labels
                    )
                encodings["x"] = alt.X(field_spec, **encoding_kwargs)
            elif channel == "y":
                encodings["y"] = alt.Y(field_spec, **encoding_kwargs)  # type: ignore[assignment]
            elif channel == "color":
                encodings["color"] = alt.Color(field_spec, **encoding_kwargs)  # type: ignore[assignment]
            elif channel == "size":
                encodings["size"] = alt.Size(field_spec, **encoding_kwargs)  # type: ignore[assignment]
            elif channel == "shape":
                encodings["shape"] = alt.Shape(field_spec, **encoding_kwargs)  # type: ignore[assignment]
            else:
                # Generic channel
                encodings[channel] = alt.value(field_spec)  # type: ignore[assignment]

        # Validate required encodings for certain chart types
        # Handle both enum and string chart types
        chart_type_check = (
            config.chart_type
            if isinstance(config.chart_type, ChartType)
            else ChartType(config.chart_type)
        )
        if chart_type_check in (
            ChartType.BAR,
            ChartType.LINE,
            ChartType.AREA,
            ChartType.SCATTER,
        ) and ("x" not in encodings or "y" not in encodings):
            chart_type_str = (
                config.chart_type.value
                if isinstance(config.chart_type, ChartType)
                else config.chart_type
            )
            raise ValueError(f"{chart_type_str} chart requires both x and y encodings")

        if chart_type_check == ChartType.HISTOGRAM:
            if "x" not in encodings:
                raise ValueError("Histogram requires x encoding")
            # Add automatic y encoding for count
            encodings["y"] = alt.Y("count()", title="Count")  # type: ignore[assignment]

        return encodings

    def _map_encoding_type(self, encoding_type: EncodingType) -> str:
        """
        Map our EncodingType to Altair's type strings.

        Args:
            encoding_type: Our encoding type enum

        Returns:
            Altair type string ("quantitative", "nominal", "ordinal", "temporal")
        """
        mapping = {
            EncodingType.QUANTITATIVE: "quantitative",
            EncodingType.NOMINAL: "nominal",
            EncodingType.ORDINAL: "ordinal",
            EncodingType.TEMPORAL: "temporal",
        }
        return mapping[encoding_type]
