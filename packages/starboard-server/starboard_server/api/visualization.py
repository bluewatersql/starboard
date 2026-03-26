"""
Visualization API REST endpoints.

Provides HTTP endpoints for chart rendering and visualization recommendations:
- POST /api/visualization/render - Render a chart from ChartConfig + data reference
- POST /api/visualization/recommend - Get LLM visualization recommendation
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from starboard_server.api.dependencies import ContainerDep
from starboard_server.api.models import (
    ErrorResponse,
    RenderChartRequest,
)
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.utils import payload_to_polars_df
from starboard_server.tools.services.chart_renderer import ChartRenderer
from starboard_server.tools.services.query_result_cache import QueryResultCache

logger = get_logger(__name__)

router = APIRouter(prefix="/api/visualization", tags=["visualization"])


# =============================================================================
# Chart Rendering Endpoint
# =============================================================================


@router.post(
    "/render",
    status_code=status.HTTP_200_OK,
    summary="Render Chart",
    description="Render a chart from ChartConfig and cached data",
    responses={
        200: {"description": "Chart rendered successfully (PNG or SVG)"},
        404: {
            "description": "Data reference not found",
            "model": ErrorResponse,
        },
        422: {"description": "Validation error", "model": ErrorResponse},
        500: {"description": "Rendering failed", "model": ErrorResponse},
    },
)
async def render_chart(
    request: RenderChartRequest,
    container: ContainerDep,
) -> Response:
    """
    Render a chart to PNG or SVG.

    This endpoint:
    1. Retrieves cached query result data using data_reference
    2. Renders chart using ChartRenderer
    3. Returns image bytes (PNG) or SVG string

    Args:
        request: Chart rendering request with config, data ref, and format
        container: Dependency injection container

    Returns:
        Response with image data (PNG binary or SVG text)

    Raises:
        HTTPException(404): Data reference not found in cache
        HTTPException(500): Chart rendering failed
    """
    logger.debug(
        "render_chart_request",
        data_reference=request.data_reference,
        chart_type=request.chart_config.chart_type,
        format=request.format,
        chart_title=request.chart_config.title,
        encoding_channels=(
            list(request.chart_config.encodings.keys())
            if request.chart_config.encodings
            else []
        ),
    )

    try:
        cache_store = container.cache_store
        result_cache = QueryResultCache(cache_store=cache_store)

        try:
            cached_data_dict = await result_cache.get_cached_data(
                request.data_reference
            )
        except ValueError:
            logger.warning(
                "data_reference_not_found",
                data_reference=request.data_reference,
                cache_store_id=id(cache_store),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Data reference '{request.data_reference}' not found in cache",
            ) from None

        # Handle None return from cache (cache miss without ValueError)
        if cached_data_dict is None:
            logger.warning(
                "data_reference_not_found",
                data_reference=request.data_reference,
                cache_store_id=id(cache_store),
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Data reference '{request.data_reference}' not found in cache",
            )

        try:
            cached_df = payload_to_polars_df(cached_data_dict)

            logger.debug(
                "cached_data_loaded",
                data_reference=request.data_reference,
                row_count=cached_df.height,
                columns=cached_df.columns,
            )
        except Exception as df_err:  # noqa: BLE001 - API error boundary
            logger.error(
                "cached_data_conversion_failed",
                data_reference=request.data_reference,
                error=str(df_err),
                cached_data_keys=(
                    list(cached_data_dict.keys())
                    if isinstance(cached_data_dict, dict)
                    else "not_a_dict"
                ),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load cached data: {str(df_err)}",
            ) from df_err

        # Initialize chart renderer
        renderer = ChartRenderer()

        # Render chart
        try:
            rendered = renderer.render_chart(
                config=request.chart_config,
                data=cached_df,
                format=request.format,
            )
        except Exception as e:  # noqa: BLE001 - API error boundary
            logger.error(
                "chart_rendering_failed",
                data_reference=request.data_reference,
                error=str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Chart rendering failed: {str(e)}",
            ) from e

        media_type = "image/png" if request.format == "png" else "image/svg+xml"
        logger.debug(
            "chart_rendered",
            data_reference=request.data_reference,
            format=request.format,
            size_bytes=len(rendered),
        )
        return Response(content=rendered, media_type=media_type)

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - API error boundary
        logger.error("render_chart_unexpected_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        ) from e
