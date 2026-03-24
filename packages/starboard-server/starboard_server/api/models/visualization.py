"""
Visualization API models.

Pydantic models for visualization API requests and responses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from starboard_server.tools.domain.analytics.visualization_models import ChartConfig


class RenderChartRequest(BaseModel):
    """
    Request to render a chart.

    Attributes:
        chart_config: Complete chart configuration
        data_reference: Reference to cached query result data
        format: Output format ("png" or "svg")
    """

    chart_config: ChartConfig = Field(..., description="Chart configuration")
    data_reference: str = Field(..., description="Data reference key for cached result")
    format: Literal["png", "svg"] = Field(default="png", description="Output format")
