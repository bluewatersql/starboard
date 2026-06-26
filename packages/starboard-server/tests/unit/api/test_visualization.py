# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for visualization API endpoints.

Tests the /api/visualization routes for chart rendering and recommendations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartConfig,
    ChartType,
    Encoding,
    EncodingType,
)


@pytest.fixture
def mock_container():
    """Mock Container for dependency injection."""
    container = MagicMock()
    container.cache_store = MagicMock()
    return container


@pytest.fixture
def mock_query_result_cache():
    """Mock QueryResultCache."""
    cache = MagicMock()
    cache.get_cached_data = AsyncMock()
    return cache


@pytest.fixture
def sample_chart_config():
    """Sample chart configuration."""
    return ChartConfig(
        chart_type=ChartType.BAR,
        title="Test Chart",
        encodings={
            "x": Encoding(field="category", type=EncodingType.NOMINAL),
            "y": Encoding(field="value", type=EncodingType.QUANTITATIVE),
        },
        options={},
    )


@pytest.fixture
def sample_cached_data():
    """Sample cached query result data."""
    return {
        "rows": [
            {"category": "A", "value": 10},
            {"category": "B", "value": 20},
            {"category": "C", "value": 15},
        ],
        "row_count": 3,
        "columns": ["category", "value"],
    }


class TestRenderChartEndpoint:
    """Test POST /api/visualization/render endpoint."""

    @pytest.mark.asyncio
    async def test_render_png_chart_success(
        self, mock_container, sample_chart_config, sample_cached_data
    ):
        """Test successful PNG chart rendering."""
        from starboard_server.api.models.visualization import RenderChartRequest
        from starboard_server.api.visualization import render_chart

        # Create request
        request = RenderChartRequest(
            chart_config=sample_chart_config,
            data_reference="test_ref_123",
            format="png",
        )

        # Mock cache to return data
        with patch("starboard_server.api.visualization.QueryResultCache") as MockCache:
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.get_cached_data = AsyncMock(
                return_value=sample_cached_data
            )

            # Call endpoint
            response = await render_chart(request, mock_container)

            # Verify response
            assert response.media_type == "image/png"
            assert isinstance(response.body, bytes)
            # PNG signature check
            assert response.body[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_render_svg_chart_success(
        self, mock_container, sample_chart_config, sample_cached_data
    ):
        """Test successful SVG chart rendering."""
        from starboard_server.api.models.visualization import RenderChartRequest
        from starboard_server.api.visualization import render_chart

        request = RenderChartRequest(
            chart_config=sample_chart_config,
            data_reference="test_ref_123",
            format="svg",
        )

        with patch("starboard_server.api.visualization.QueryResultCache") as MockCache:
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.get_cached_data = AsyncMock(
                return_value=sample_cached_data
            )

            response = await render_chart(request, mock_container)

            assert response.media_type == "image/svg+xml"
            assert isinstance(response.body, (str, bytes))
            # SVG content check
            body_str = (
                response.body
                if isinstance(response.body, str)
                else response.body.decode()
            )
            assert "<svg" in body_str

    @pytest.mark.asyncio
    async def test_render_chart_data_not_found(
        self, mock_container, sample_chart_config
    ):
        """Test rendering when data reference not found in cache."""
        from fastapi import HTTPException
        from starboard_server.api.models.visualization import RenderChartRequest
        from starboard_server.api.visualization import render_chart

        request = RenderChartRequest(
            chart_config=sample_chart_config,
            data_reference="nonexistent_ref",
            format="png",
        )

        with patch("starboard_server.api.visualization.QueryResultCache") as MockCache:
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.get_cached_data = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await render_chart(request, mock_container)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "not found in cache" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_render_chart_rendering_failure(
        self, mock_container, sample_chart_config, sample_cached_data
    ):
        """Test handling of chart rendering failures."""
        from fastapi import HTTPException
        from starboard_server.api.models.visualization import RenderChartRequest
        from starboard_server.api.visualization import render_chart

        request = RenderChartRequest(
            chart_config=sample_chart_config,
            data_reference="test_ref_123",
            format="png",
        )

        with patch("starboard_server.api.visualization.QueryResultCache") as MockCache:
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.get_cached_data = AsyncMock(
                return_value=sample_cached_data
            )

            # Mock ChartRenderer to raise an error
            with patch(
                "starboard_server.api.visualization.ChartRenderer"
            ) as MockRenderer:
                mock_renderer = MockRenderer.return_value
                mock_renderer.render_chart.side_effect = RuntimeError(
                    "Chart rendering failed"
                )

                with pytest.raises(HTTPException) as exc_info:
                    await render_chart(request, mock_container)

                assert (
                    exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                assert "Chart rendering failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_render_chart_with_empty_data(
        self, mock_container, sample_chart_config
    ):
        """Test rendering with empty dataset."""
        from starboard_server.api.models.visualization import RenderChartRequest
        from starboard_server.api.visualization import render_chart

        request = RenderChartRequest(
            chart_config=sample_chart_config,
            data_reference="empty_ref",
            format="png",
        )

        empty_data = {"rows": [], "row_count": 0, "columns": ["category", "value"]}

        with patch("starboard_server.api.visualization.QueryResultCache") as MockCache:
            mock_cache_instance = MockCache.return_value
            mock_cache_instance.get_cached_data = AsyncMock(return_value=empty_data)

            # Should still render (empty chart)
            response = await render_chart(request, mock_container)

            assert response.media_type == "image/png"
            assert isinstance(response.body, bytes)
