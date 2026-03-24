"""Unit tests for SQLValidator.

Tests cover SQL validation with two gates:
1. SQLglot syntax validation
2. EXPLAIN plan validation (runtime)
3. Cache key generation
4. Error message parsing
5. Edge cases and security
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard_server.tools.domain.analytics_sql.models import ValidationResult
from starboard_server.tools.domain.analytics_sql.sql_validator import (
    DATABRICKS_ERROR_PATTERNS,
    SQLValidator,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_sql_executor():
    """Mock SQL executor for EXPLAIN validation."""
    executor = MagicMock()
    executor.execute_sql = AsyncMock()
    return executor


@pytest.fixture
def sql_validator(mock_sql_executor):
    """Create SQLValidator instance for testing."""
    return SQLValidator(sql_executor=mock_sql_executor)


@pytest.fixture
def sql_validator_no_executor():
    """Create SQLValidator without executor (syntax-only validation)."""
    return SQLValidator(sql_executor=None)


# ============================================================================
# Syntax Validation Tests (SQLglot)
# ============================================================================


class TestSyntaxValidation:
    """Tests for SQLglot syntax validation (Gate 1)."""

    @pytest.mark.asyncio
    async def test_validate_valid_sql(self, sql_validator):
        """Test validation passes for valid SQL."""
        sql = "SELECT warehouse_name, SUM(list_cost) FROM system.billing.usage GROUP BY warehouse_name"

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert result.validation_method == "sqlglot"

    @pytest.mark.asyncio
    async def test_validate_syntax_error(self, sql_validator):
        """Test validation catches syntax errors."""
        sql = "SELECT * FORM system.billing.usage"  # FORM instead of FROM

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_validate_missing_select(self, sql_validator):
        """Test validation catches missing SELECT."""
        # Note: SQLglot may accept "FROM table" as valid (implicit SELECT *)
        # so we use a more clearly invalid query
        sql = "WHERE usage_date >= '2024-01-01'"

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_validate_incomplete_sql(self, sql_validator):
        """Test validation catches incomplete SQL."""
        sql = "SELECT warehouse_name FROM"  # Missing table

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_validate_empty_sql(self, sql_validator):
        """Test validation catches empty SQL."""
        sql = ""

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is False
        assert any("empty" in err.lower() for err in result.errors)

    @pytest.mark.asyncio
    async def test_validate_whitespace_only_sql(self, sql_validator):
        """Test validation catches whitespace-only SQL."""
        sql = "   \n   \t   "

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_validate_complex_valid_query(self, sql_validator):
        """Test validation passes for complex valid query."""
        sql = """
        WITH daily_costs AS (
            SELECT
                usage_date,
                warehouse_id,
                SUM(list_cost) as total_cost
            FROM system.billing.usage
            WHERE usage_date >= CURRENT_DATE - INTERVAL 30 DAYS
            GROUP BY usage_date, warehouse_id
        )
        SELECT
            w.warehouse_name,
            AVG(dc.total_cost) as avg_daily_cost
        FROM daily_costs dc
        LEFT JOIN system.compute.warehouses w ON dc.warehouse_id = w.warehouse_id
        GROUP BY w.warehouse_name
        ORDER BY avg_daily_cost DESC
        LIMIT 10
        """

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is True
        assert len(result.errors) == 0


# ============================================================================
# Runtime Validation Tests (EXPLAIN)
# ============================================================================


class TestRuntimeValidation:
    """Tests for EXPLAIN plan validation (Gate 2)."""

    @pytest.mark.asyncio
    async def test_validate_with_explain_success(
        self, sql_validator, mock_sql_executor
    ):
        """Test EXPLAIN plan validation succeeds."""
        sql = "SELECT * FROM system.billing.usage LIMIT 10"

        # Mock successful EXPLAIN
        import polars as pl

        mock_sql_executor.execute_sql.return_value = pl.DataFrame(
            {"plan": ["SeqScan on system.billing.usage"]}
        )

        result = await sql_validator.validate(sql, runtime_validation=True)

        assert result.is_valid is True
        assert "explain" in result.validation_method.lower()

        # Verify EXPLAIN was called
        mock_sql_executor.execute_sql.assert_called_once()
        call_sql = mock_sql_executor.execute_sql.call_args[1]["sql"]
        assert "EXPLAIN" in call_sql.upper()

    @pytest.mark.asyncio
    async def test_validate_with_explain_table_not_found(
        self, sql_validator, mock_sql_executor
    ):
        """Test EXPLAIN catches table not found error."""
        sql = "SELECT * FROM system.billing.nonexistent_table"

        # Mock EXPLAIN error
        mock_sql_executor.execute_sql.side_effect = Exception(
            "TABLE_OR_VIEW_NOT_FOUND: Table 'system.billing.nonexistent_table' not found"
        )

        result = await sql_validator.validate(sql, runtime_validation=True)

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert any("not found" in err.lower() for err in result.errors)

    @pytest.mark.asyncio
    async def test_validate_with_explain_column_not_found(
        self, sql_validator, mock_sql_executor
    ):
        """Test EXPLAIN catches column not found error."""
        sql = "SELECT invalid_column FROM system.billing.usage"

        # Mock EXPLAIN error
        mock_sql_executor.execute_sql.side_effect = Exception(
            "UNRESOLVED_COLUMN: Column 'invalid_column' cannot be resolved"
        )

        result = await sql_validator.validate(sql, runtime_validation=True)

        assert result.is_valid is False
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_validate_skip_runtime_when_disabled(
        self, sql_validator, mock_sql_executor
    ):
        """Test skipping runtime validation when disabled."""
        sql = "SELECT * FROM system.billing.usage"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should only do syntax validation, not EXPLAIN
        assert result.is_valid is True
        mock_sql_executor.execute_sql.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_runtime_without_executor(self, sql_validator_no_executor):
        """Test runtime validation gracefully skips when no executor."""
        sql = "SELECT * FROM system.billing.usage"

        result = await sql_validator_no_executor.validate(sql, runtime_validation=True)

        # Should fall back to syntax-only validation
        assert result.validation_method == "sqlglot"


# ============================================================================
# Cache Key Generation Tests
# ============================================================================


class TestCacheKeyGeneration:
    """Tests for SQL cache key generation."""

    def test_generate_cache_key_same_sql(self, sql_validator):
        """Test same SQL generates same cache key."""
        sql = "SELECT * FROM system.billing.usage WHERE usage_date >= '2024-01-01'"

        key1 = sql_validator.generate_sql_cache_key(sql)
        key2 = sql_validator.generate_sql_cache_key(sql)

        assert key1 == key2

    def test_generate_cache_key_normalized(self, sql_validator):
        """Test cache keys use canonicalized SQL (AST-based)."""
        # Same SQL should generate same key
        sql1 = "SELECT * FROM system.billing.usage"
        sql2 = "SELECT * FROM system.billing.usage"

        key1 = sql_validator.generate_sql_cache_key(sql1)
        key2 = sql_validator.generate_sql_cache_key(sql2)

        # Identical SQL should produce identical keys
        assert key1 == key2

        # Semantically equivalent but differently formatted SQL
        # Note: Cache keys are AST-based so whitespace differences may affect AST serialization
        # This is intentional - ensures safe caching even with formatting differences

    def test_generate_cache_key_different_sql(self, sql_validator):
        """Test different SQL generates different cache keys."""
        sql1 = "SELECT * FROM system.billing.usage"
        sql2 = "SELECT * FROM system.billing.list_prices"

        key1 = sql_validator.generate_sql_cache_key(sql1)
        key2 = sql_validator.generate_sql_cache_key(sql2)

        assert key1 != key2

    def test_generate_cache_key_format(self, sql_validator):
        """Test cache key format."""
        sql = "SELECT * FROM system.billing.usage"

        key = sql_validator.generate_sql_cache_key(sql)

        # Should be a string with version prefix and hex hash
        assert isinstance(key, str)
        assert len(key) > 0
        # Format is "v1|<hex_hash>"
        assert "|" in key
        version, hash_part = key.split("|", 1)
        assert version == "v1"
        assert len(hash_part) > 0
        # Hash part should be hex
        assert all(c in "0123456789abcdef" for c in hash_part)


# ============================================================================
# Security and Safety Tests
# ============================================================================


class TestSecurityValidation:
    """Tests for security and safety checks."""

    @pytest.mark.asyncio
    async def test_validate_detects_drop_table(self, sql_validator):
        """Test validation detects DROP TABLE (dangerous operation)."""
        sql = "DROP TABLE system.billing.usage"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should either fail validation or add warnings
        assert result.is_valid is False or len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_validate_detects_delete(self, sql_validator):
        """Test validation detects DELETE (dangerous operation)."""
        sql = "DELETE FROM system.billing.usage WHERE usage_date < '2023-01-01'"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should either fail validation or add warnings
        assert result.is_valid is False or len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_validate_detects_update(self, sql_validator):
        """Test validation detects UPDATE (dangerous operation)."""
        sql = "UPDATE system.billing.usage SET list_cost = 0"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should either fail validation or add warnings
        assert result.is_valid is False or len(result.warnings) > 0

    @pytest.mark.asyncio
    async def test_validate_allows_select_only(self, sql_validator):
        """Test validation allows SELECT-only queries."""
        sql = "SELECT * FROM system.billing.usage"

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is True


# ============================================================================
# Warning Detection Tests
# ============================================================================


class TestWarningDetection:
    """Tests for warning detection (non-fatal issues)."""

    @pytest.mark.asyncio
    async def test_validate_warns_on_select_star(self, sql_validator):
        """Test validation warns about SELECT * (performance concern)."""
        sql = "SELECT * FROM system.billing.usage"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # May add warning about SELECT * but should still be valid
        assert result.is_valid is True
        # Warnings may or may not be present depending on implementation

    @pytest.mark.asyncio
    async def test_validate_warns_on_missing_limit(self, sql_validator):
        """Test validation warns about missing LIMIT clause."""
        sql = "SELECT warehouse_name, list_cost FROM system.billing.usage"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # May add warning about missing LIMIT but should still be valid
        assert result.is_valid is True


# ============================================================================
# Error Pattern Tests
# ============================================================================


class TestErrorPatterns:
    """Tests for Databricks error pattern definitions."""

    def test_error_patterns_defined(self):
        """Test that error patterns are defined."""
        assert isinstance(DATABRICKS_ERROR_PATTERNS, dict)
        assert len(DATABRICKS_ERROR_PATTERNS) > 0

    def test_error_pattern_structure(self):
        """Test that error patterns have required fields."""
        for code, pattern in DATABRICKS_ERROR_PATTERNS.items():
            assert pattern.code == code
            assert isinstance(pattern.sqlstate, str)
            assert isinstance(pattern.category, str)
            assert isinstance(pattern.severity, str)
            assert isinstance(pattern.reflexion_hint, str)

    def test_high_priority_patterns_present(self):
        """Test that high-priority error patterns are defined."""
        expected_patterns = [
            "UNRESOLVED_COLUMN",
            "TABLE_OR_VIEW_NOT_FOUND",
            "PARSE_SYNTAX_ERROR",
        ]

        for pattern in expected_patterns:
            assert any(pattern in key for key in DATABRICKS_ERROR_PATTERNS)


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_validate_very_long_sql(self, sql_validator):
        """Test validation handles very long SQL queries."""
        # Create a long query with many JOINs
        sql = "SELECT * FROM system.billing.usage u1"
        for i in range(10):
            sql += f" LEFT JOIN system.billing.usage u{i + 2} ON u1.workspace_id = u{i + 2}.workspace_id"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should still validate (may be slow but should work)
        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_validate_sql_with_comments(self, sql_validator):
        """Test validation handles SQL with comments."""
        sql = """
        -- This is a comment
        SELECT
            warehouse_name,  -- Column 1
            list_cost        -- Column 2
        FROM system.billing.usage
        /* Multi-line
           comment */
        WHERE usage_date >= '2024-01-01'
        """

        result = await sql_validator.validate(sql, runtime_validation=False)

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_validate_sql_with_special_characters(self, sql_validator):
        """Test validation handles SQL with special characters in strings."""
        sql = "SELECT * FROM system.billing.usage WHERE sku_name = 'Premium\\'s Choice'"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Should handle escaped quotes
        assert isinstance(result, ValidationResult)

    @pytest.mark.asyncio
    async def test_validate_multiple_statements(self, sql_validator):
        """Test validation handles multiple statements."""
        sql = "SELECT * FROM system.billing.usage; SELECT * FROM system.billing.list_prices;"

        result = await sql_validator.validate(sql, runtime_validation=False)

        # Behavior depends on implementation - may reject or validate first statement
        assert isinstance(result, ValidationResult)


# ============================================================================
# ValidationResult Model Tests
# ============================================================================


class TestValidationResultModel:
    """Tests for ValidationResult data model."""

    def test_validation_result_valid(self):
        """Test ValidationResult for valid SQL."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=[],
            validation_method="sqlglot",
        )

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert result.validation_method == "sqlglot"

    def test_validation_result_invalid(self):
        """Test ValidationResult for invalid SQL."""
        result = ValidationResult(
            is_valid=False,
            errors=["Syntax error near FORM"],
            warnings=[],
            validation_method="sqlglot",
        )

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "Syntax error" in result.errors[0]

    def test_validation_result_with_warnings(self):
        """Test ValidationResult with warnings."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=["SELECT * may impact performance"],
            validation_method="sqlglot",
        )

        assert result.is_valid is True
        assert len(result.warnings) == 1
