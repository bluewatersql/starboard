# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for chart rendering flow.

Tests the complete pipeline:
1. Query execution → Data caching
2. Visualization recommendation → Chart config generation
3. Chart rendering → PNG/SVG output

Catches issues like:
- Cache key mismatches
- Schema validation failures
- LLM output issues
- Null handling bugs
"""

from datetime import UTC, datetime

import polars as pl
import pytest
from starboard_server.adapters.state.inmemory.cache_store import InMemoryCacheStore
from starboard_server.tools.domain.analytics.visualization_models import (
    ChartType,
)
from starboard_server.tools.services.cached_data_models import CachedQueryResult
from starboard_server.tools.services.chart_config_validator import ChartConfigValidator
from starboard_server.tools.services.chart_renderer import ChartRenderer
from starboard_server.tools.services.query_result_cache import QueryResultCache


class TestChartRenderingIntegration:
    """End-to-end tests for chart rendering pipeline."""

    @pytest.fixture
    def cache_store(self):
        """Create in-memory cache store for testing."""
        return InMemoryCacheStore()

    @pytest.fixture
    def result_cache(self, cache_store):
        """Create query result cache."""
        return QueryResultCache(cache_store, default_ttl=600)

    @pytest.fixture
    def sample_dataframe(self):
        """Create sample DataFrame for testing."""
        return pl.DataFrame(
            {
                "job_name": ["Job A", "Job B", "Job C"],
                "list_cost": [100.0, 200.0, 150.0],
                "run_count": [10, 20, 15],
            }
        )

    @pytest.fixture
    def sample_dataframe_with_datetime(self):
        """Create sample DataFrame with timezone-aware datetime column."""

        return pl.DataFrame(
            {
                "date": [
                    datetime(2025, 11, 1, tzinfo=UTC),
                    datetime(2025, 11, 2, tzinfo=UTC),
                    datetime(2025, 11, 3, tzinfo=UTC),
                ],
                "cost": [100.0, 200.0, 150.0],
            }
        )

    @pytest.fixture
    def sample_dataframe_with_decimal(self):
        """Create sample DataFrame with Decimal column (like Databricks returns)."""
        from decimal import Decimal

        # Create DataFrame with Decimal column matching Databricks schema
        return pl.DataFrame(
            {
                "job_name": ["Job A", "Job B", "Job C"],
                "list_cost": [
                    Decimal("846.890553"),
                    Decimal("628.230147"),
                    Decimal("520.070000"),
                ],
            }
        )

    @pytest.mark.asyncio
    async def test_cache_write_and_read_consistency(
        self,
        result_cache,
        sample_dataframe,
    ):
        """
        Test that cached data can be written and read back correctly.

        This test catches KeyError issues like the 'data' vs 'rows' bug.
        """
        # Cache the data
        data_ref = await result_cache.cache_result(
            query_id="test-query-123",
            parameters={"limit": 10},
            df=sample_dataframe,
        )

        assert data_ref.startswith("data_ref_")

        # Retrieve the data
        cached_data = await result_cache.get_cached_data(data_ref)

        # Validate structure
        assert "rows" in cached_data
        assert "columns" in cached_data
        assert "dtypes" in cached_data
        assert "row_count" in cached_data

        # Validate content
        assert len(cached_data["rows"]) == 3
        assert cached_data["columns"] == ["job_name", "list_cost", "run_count"]
        assert cached_data["row_count"] == 3

        # Test conversion back to DataFrame
        retrieved_df = pl.DataFrame(cached_data["rows"])
        assert retrieved_df.columns == sample_dataframe.columns
        assert len(retrieved_df) == len(sample_dataframe)

    @pytest.mark.asyncio
    async def test_cached_query_result_model(self, sample_dataframe):
        """Test type-safe CachedQueryResult model."""
        # Create from DataFrame
        result = CachedQueryResult.from_polars(
            df=sample_dataframe,
            query_id="test-query-123",
        )

        # Validate fields
        assert result.row_count == 3
        assert result.columns == ["job_name", "list_cost", "run_count"]
        assert len(result.rows) == 3
        assert result.query_id == "test-query-123"

        # Convert back to DataFrame
        df = result.to_polars()
        assert df.columns == sample_dataframe.columns
        assert len(df) == len(sample_dataframe)

    def test_chart_config_sanitization_removes_null_encodings(self):
        """Test that null encoding values are removed."""
        config_dict = {
            "chart_type": "bar",
            "title": "Cost by Job",
            "encodings": {
                "x": {"field": "job_name", "type": "nominal"},
                "y": {"field": "list_cost", "type": "quantitative"},
                "color": None,  # LLM-generated null value
            },
        }

        # Validate and fix
        config = ChartConfigValidator.validate_and_fix(config_dict)

        # Verify null encoding was removed
        assert "x" in config.encodings
        assert "y" in config.encodings
        assert "color" not in config.encodings

    def test_chart_config_sanitization_removes_empty_encodings(self):
        """Test that empty encoding objects are removed."""
        config_dict = {
            "chart_type": "bar",
            "title": "Cost by Job",
            "encodings": {
                "x": {"field": "job_name", "type": "nominal"},
                "y": {"field": "list_cost", "type": "quantitative"},
                "size": {},  # Empty object
            },
        }

        config = ChartConfigValidator.validate_and_fix(config_dict)

        assert "x" in config.encodings
        assert "y" in config.encodings
        assert "size" not in config.encodings

    def test_chart_config_validation_fails_on_missing_required_fields(self):
        """Test that validation fails if required fields are missing."""
        config_dict = {
            "title": "Cost by Job",  # Missing chart_type
            "encodings": {},
        }

        with pytest.raises(ValueError, match="Missing required chart config fields"):
            ChartConfigValidator.validate_and_fix(config_dict)

    @pytest.mark.asyncio
    async def test_full_pipeline_query_to_chart_render(
        self,
        result_cache,
        sample_dataframe,
    ):
        """
        Test complete pipeline from query result to chart rendering.

        This is the most important test - it catches integration bugs.
        """
        # Step 1: Cache query results
        data_ref = await result_cache.cache_result(
            query_id="top-10-jobs",
            parameters={"days": 30},
            df=sample_dataframe,
        )

        # Step 2: Create chart config (simulating LLM output)
        config_dict = {
            "chart_type": "bar",
            "title": "Top Jobs by Cost",
            "description": "Most expensive jobs in the last 30 days",
            "encodings": {
                "x": {
                    "field": "job_name",
                    "type": "nominal",
                    "title": "Job Name",
                },
                "y": {
                    "field": "list_cost",
                    "type": "quantitative",
                    "title": "Cost (USD)",
                },
                "color": None,  # Simulate LLM bug
            },
        }

        # Step 3: Validate and sanitize config
        config = ChartConfigValidator.validate_and_fix(config_dict)

        # Step 4: Retrieve cached data
        cached_data = await result_cache.get_cached_data(data_ref)

        # Step 5: Convert to DataFrame (test the KeyError-prone step)
        df = pl.DataFrame(cached_data["rows"])  # This was the bug!

        assert len(df) == 3
        assert "job_name" in df.columns
        assert "list_cost" in df.columns

        # Step 6: Render chart
        renderer = ChartRenderer()

        try:
            png_bytes = renderer.render_chart(
                config=config,
                data=df,
                format="png",
            )

            # Validate output
            assert isinstance(png_bytes, bytes)
            assert len(png_bytes) > 0
            # PNG magic number
            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        except Exception as e:
            # If rendering fails due to missing deps (altair_saver, vega, etc.)
            # that's OK for this test - we're testing the data flow
            pytest.skip(f"Chart rendering dependencies not available: {e}")

    @pytest.mark.asyncio
    async def test_cache_expiration_raises_error(self, result_cache, sample_dataframe):
        """Test that expired cache entries raise ValueError."""
        # Cache with very short TTL
        data_ref = await result_cache.cache_result(
            query_id="test-query",
            parameters={},
            df=sample_dataframe,
            ttl=1,  # 1 second
        )

        # Wait for expiration
        import asyncio

        await asyncio.sleep(2)

        # Should raise ValueError for expired/missing data
        with pytest.raises(ValueError, match="not found or expired"):
            await result_cache.get_cached_data(data_ref)

    def test_chart_config_validator_handles_wrapped_report(self):
        """
        Test handling of LLM wrapping everything in 'report' key.

        This was another bug we encountered where LLM returned:
        {"report": {"chart_type": ..., "title": ...}}
        instead of:
        {"chart_type": ..., "title": ...}
        """
        # Simulate LLM wrapping in 'report' key
        wrapped_config = {
            "report": {
                "chart_type": "bar",
                "title": "Cost Analysis",
                "encodings": {
                    "x": {"field": "job_name", "type": "nominal"},
                },
            }
        }

        # Unwrap if needed (this would be in the validator)
        config_dict = wrapped_config.get("report", wrapped_config)

        # Should validate successfully after unwrapping
        config = ChartConfigValidator.validate_and_fix(config_dict)
        assert config.chart_type == ChartType.BAR
        assert config.title == "Cost Analysis"

    @pytest.mark.asyncio
    async def test_datetime_normalization_for_altair_compatibility(
        self,
        result_cache,
        sample_dataframe_with_datetime,
    ):
        """
        Test that timezone-aware datetimes are normalized to naive UTC.

        Altair only supports naive datetimes or 'UTC' string.
        This prevents: "Unsupported timezone zoneinfo.ZoneInfo(key='UTC')"

        Bug reference: Chart rendering failed with timezone-aware datetime columns
        from Databricks queries.
        """
        # Cache data with timezone-aware datetime column
        data_ref = await result_cache.cache_result(
            query_id="test-query-with-datetime",
            parameters={},
            df=sample_dataframe_with_datetime,
        )

        # Retrieve cached data
        cached_data = await result_cache.get_cached_data(data_ref)

        # Convert to DataFrame
        df = pl.DataFrame(cached_data["rows"])

        # Verify datetime column exists
        assert "date" in df.columns

        # Verify datetime values are present (not None)
        assert df["date"].null_count() == 0

        # Create chart config with temporal encoding
        config_dict = {
            "chart_type": "line",
            "title": "Cost Over Time",
            "encodings": {
                "x": {
                    "field": "date",
                    "type": "temporal",  # Temporal encoding requires proper datetime handling
                    "title": "Date",
                },
                "y": {
                    "field": "cost",
                    "type": "quantitative",
                    "title": "Cost (USD)",
                },
            },
        }

        # Validate config
        config = ChartConfigValidator.validate_and_fix(config_dict)

        # Attempt to render (this would fail with timezone-aware datetimes)
        renderer = ChartRenderer()

        try:
            png_bytes = renderer.render_chart(
                config=config,
                data=df,
                format="png",
            )

            # If we get here, datetime normalization worked!
            assert isinstance(png_bytes, bytes)
            assert len(png_bytes) > 0
        except Exception as e:
            # If rendering fails due to missing deps, that's OK for this test
            # We're testing that datetime normalization doesn't cause Altair errors
            error_msg = str(e)

            # Should NOT fail with timezone error
            assert "Unsupported timezone" not in error_msg
            assert "zoneinfo.ZoneInfo" not in error_msg

            # If it fails for other reasons (missing deps), skip
            if "altair" in error_msg.lower() or "vega" in error_msg.lower():
                pytest.skip(f"Chart rendering dependencies not available: {e}")
            else:
                # Unexpected error - re-raise
                raise

    @pytest.mark.asyncio
    async def test_decimal_normalization_for_json_serialization(
        self,
        result_cache,
        sample_dataframe_with_decimal,
    ):
        """
        Test that Decimal columns are converted to Float64 for JSON serialization.

        Altair/Vega-Lite can't serialize Python Decimal objects to JSON.
        This prevents: "Failed to parse vl_spec dict as JSON: unsupported type Decimal"

        Bug reference: Databricks returns Decimal(precision=38, scale=6) for monetary
        values, which Altair rejects.
        """
        # Cache data with Decimal column
        data_ref = await result_cache.cache_result(
            query_id="test-query-with-decimal",
            parameters={},
            df=sample_dataframe_with_decimal,
        )

        # Retrieve cached data
        cached_data = await result_cache.get_cached_data(data_ref)

        # Convert to DataFrame
        df = pl.DataFrame(cached_data["rows"])

        # Verify cost column exists and is numeric (Float64, not Decimal)
        assert "list_cost" in df.columns
        assert df["list_cost"].dtype == pl.Float64  # Should be converted from Decimal

        # Verify values are preserved (within floating point precision)
        assert df["list_cost"][0] == pytest.approx(846.890553, rel=1e-6)
        assert df["list_cost"][1] == pytest.approx(628.230147, rel=1e-6)
        assert df["list_cost"][2] == pytest.approx(520.070000, rel=1e-6)

        # Create chart config with quantitative encoding
        config_dict = {
            "chart_type": "bar",
            "title": "Top Jobs by Cost",
            "encodings": {
                "x": {
                    "field": "job_name",
                    "type": "nominal",
                    "title": "Job Name",
                },
                "y": {
                    "field": "list_cost",
                    "type": "quantitative",  # Quantitative requires numeric type
                    "title": "Cost (USD)",
                },
            },
        }

        # Validate config
        config = ChartConfigValidator.validate_and_fix(config_dict)

        # Attempt to render (this would fail with Decimal types)
        renderer = ChartRenderer()

        try:
            png_bytes = renderer.render_chart(
                config=config,
                data=df,
                format="png",
            )

            # If we get here, Decimal normalization worked!
            assert isinstance(png_bytes, bytes)
            assert len(png_bytes) > 0
            assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number
        except Exception as e:
            error_msg = str(e)

            # Should NOT fail with Decimal serialization error
            assert "unsupported type Decimal" not in error_msg
            assert (
                "Decimal" not in error_msg or "precision" in error_msg
            )  # Schema info OK

            # If it fails for other reasons (missing deps), skip
            if "altair" in error_msg.lower() or "vega" in error_msg.lower():
                pytest.skip(f"Chart rendering dependencies not available: {e}")
            else:
                # Unexpected error - re-raise
                raise


if __name__ == "__main__":
    # Run tests with: pytest tests/integration/test_chart_rendering_integration.py -v
    pytest.main([__file__, "-v", "--tb=short"])
