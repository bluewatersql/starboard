"""
Data API REST endpoint.

Provides HTTP endpoint for retrieving cached query results:
- GET /api/data/{data_reference} - Get cached data for table view
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field

from fastapi import Request

from starboard_server.api.dependencies import ContainerDep
from starboard_server.api.models import ErrorResponse
from starboard_server.infra.middleware.rate_limit import check_rate_limit
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.query_result_cache import QueryResultCache

logger = get_logger(__name__)

router = APIRouter(prefix="/api/data", tags=["data"])


# =============================================================================
# Response Models
# =============================================================================


class CachedDataResponse(BaseModel):
    """Response model for cached query data.

    Matches the structure stored in QueryResultCache.

    Attributes:
        rows: List of data rows as dictionaries
        columns: Column names in order
        dtypes: Optional mapping of column names to data types
        row_count: Total number of rows
    """

    version: int = Field(1, description="Version of the data format")
    orientation: Literal["columns", "records"] = Field(
        "records", description="Orientation of the data"
    )
    data_schema: dict[str, Any] = Field(
        ..., description="Schema of the data", alias="schema"
    )
    data: list[dict[str, Any]] = Field(..., description="Data rows")
    row_count: int = Field(..., description="Total row count")


# =============================================================================
# Data Endpoint
# =============================================================================


@router.get(
    "/{data_reference}",
    response_model=CachedDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Cached Data",
    description="Retrieve cached query results by data reference",
    responses={
        200: {"description": "Cached data retrieved successfully"},
        404: {
            "description": "Data reference not found or expired",
            "model": ErrorResponse,
        },
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
async def get_cached_data(
    request: Request,
    data_reference: str = Path(
        ...,
        description="Unique data reference from query execution",
        examples=["data_ref_abc123def456"],
    ),
    container: ContainerDep = ...,  # type: ignore[assignment]
) -> CachedDataResponse:
    """
    Retrieve cached query results.

    This endpoint provides cached query results for the frontend table view.
    Data is cached with a TTL (default 10 minutes) and will return 404 if
    the data has expired.

    Args:
        data_reference: Unique cache key from query execution
        container: Dependency injection container

    Returns:
        CachedDataResponse with rows, columns, dtypes, and row_count

    Raises:
        HTTPException(404): Data reference not found or expired
        HTTPException(500): Unexpected error

    Example:
        >>> # Frontend call
        >>> response = await fetch('/api/data/data_ref_abc123')
        >>> data = await response.json()
        >>> console.log(data.rows, data.columns, data.row_count)
    """
    logger.debug(
        "get_cached_data_request",
        data_reference=data_reference,
    )

    # Enforce rate limiting on this endpoint
    check_rate_limit(request, "60/minute")

    try:
        # QueryResultCache wraps the store with NamespacedCache(namespace="data")
        # so keys are stored as "data:{data_reference}" - we must use the same wrapper to retrieve
        result_cache = QueryResultCache(cache_store=container.cache_store)

        # Retrieve cached data via QueryResultCache (handles namespace prefix)
        try:
            cached_data = await result_cache.get_cached_data(data_reference)
        except ValueError:
            cached_data = None

        if cached_data is None:
            logger.warning(
                "data_reference_not_found",
                data_reference=data_reference,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Data reference '{data_reference}' not found. "
                    "The cached data may have expired (default TTL: 60 minutes)."
                ),
            )

        if not isinstance(cached_data, dict):
            logger.error(
                "invalid_cached_data_type",
                data_reference=data_reference,
                data_type=type(cached_data).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid cached data format",
            )

        logger.debug(
            "get_cached_data_success",
            data_reference=data_reference,
            row_count=cached_data.get("row_count"),
        )

        return CachedDataResponse(
            version=cached_data.get("version", 1),
            orientation=cached_data.get("orientation", "records"),
            schema=cached_data.get("schema", {}),
            data=cached_data.get("data", []),
            row_count=cached_data.get("row_count", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "get_cached_data_error",
            data_reference=data_reference,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
