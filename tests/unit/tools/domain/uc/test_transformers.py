# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for UC transformers including query classification."""

from __future__ import annotations

import pytest
from starboard_core.domain.transformers import (
    LineageGraphTransformer,
    QueryFingerprint,
    QueryOperation,
    TableFingerprintTransformer,
    classify_query,
)


class TestClassifyQuery:
    """Tests for classify_query function."""

    # -------------------------------------------------------------------------
    # Standard SQL operations (parsed by sqlglot)
    # -------------------------------------------------------------------------

    def test_simple_select(self) -> None:
        """Test simple SELECT query classification."""
        result = classify_query("SELECT * FROM users")
        assert result.operation == QueryOperation.SELECT
        assert result.is_read is True
        assert result.is_write is False
        assert result.parse_confidence == "parsed"

    def test_select_with_join(self) -> None:
        """Test SELECT with JOIN extracts join info."""
        sql = """
        SELECT u.name, o.total
        FROM users u
        INNER JOIN orders o ON u.id = o.user_id
        LEFT JOIN products p ON o.product_id = p.id
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.is_read is True
        assert result.join_count == 2
        # sqlglot normalizes join types - just verify we detect joins
        assert len(result.join_types) == 2

    def test_select_with_aggregation(self) -> None:
        """Test SELECT with aggregation extracts agg info."""
        sql = """
        SELECT user_id, COUNT(*), SUM(amount), AVG(price)
        FROM orders
        GROUP BY user_id
        HAVING COUNT(*) > 5
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.has_aggregation is True
        assert result.group_by_columns == 1
        # HAVING COUNT(*) is also counted as an aggregate function
        assert len(result.agg_functions) >= 3
        assert "Count" in result.agg_functions
        assert "Sum" in result.agg_functions
        assert "Avg" in result.agg_functions

    def test_select_with_window_function(self) -> None:
        """Test SELECT with window function."""
        sql = """
        SELECT user_id, amount,
               ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at) as rn
        FROM orders
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.window_count == 1

    def test_select_with_cte(self) -> None:
        """Test SELECT with CTE."""
        sql = """
        WITH active_users AS (
            SELECT id FROM users WHERE status = 'active'
        )
        SELECT * FROM orders o
        JOIN active_users au ON o.user_id = au.id
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.cte_count == 1

    def test_select_with_subquery(self) -> None:
        """Test SELECT with subquery."""
        sql = """
        SELECT * FROM orders
        WHERE user_id IN (SELECT id FROM users WHERE status = 'active')
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.subquery_count == 1

    def test_select_with_where_and_limit(self) -> None:
        """Test SELECT with WHERE and LIMIT."""
        sql = "SELECT * FROM users WHERE status = 'active' LIMIT 100"
        result = classify_query(sql)
        assert result.operation == QueryOperation.SELECT
        assert result.has_where is True
        assert result.has_limit is True

    def test_simple_insert(self) -> None:
        """Test simple INSERT query classification."""
        result = classify_query("INSERT INTO users (name) VALUES ('Alice')")
        assert result.operation == QueryOperation.INSERT
        assert result.is_read is False
        assert result.is_write is True
        assert result.parse_confidence == "parsed"

    def test_insert_select(self) -> None:
        """Test INSERT ... SELECT reads source."""
        sql = "INSERT INTO users_backup SELECT * FROM users"
        result = classify_query(sql)
        assert result.operation == QueryOperation.INSERT
        assert result.is_read is True  # Reads from source
        assert result.is_write is True

    def test_update(self) -> None:
        """Test UPDATE query classification."""
        result = classify_query("UPDATE users SET status = 'inactive' WHERE id = 1")
        assert result.operation == QueryOperation.UPDATE
        assert result.is_read is True  # Reads WHERE clause
        assert result.is_write is True

    def test_delete(self) -> None:
        """Test DELETE query classification."""
        result = classify_query("DELETE FROM users WHERE status = 'deleted'")
        assert result.operation == QueryOperation.DELETE
        assert result.is_read is True  # Reads WHERE clause
        assert result.is_write is True

    def test_merge(self) -> None:
        """Test MERGE query classification."""
        sql = """
        MERGE INTO target t
        USING source s ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET t.value = s.value
        WHEN NOT MATCHED THEN INSERT (id, value) VALUES (s.id, s.value)
        """
        result = classify_query(sql)
        assert result.operation == QueryOperation.MERGE
        assert result.is_read is True
        assert result.is_write is True

    def test_create_table(self) -> None:
        """Test CREATE TABLE classification."""
        result = classify_query("CREATE TABLE users (id INT, name STRING)")
        assert result.operation == QueryOperation.CREATE
        assert result.is_write is True

    def test_drop_table(self) -> None:
        """Test DROP TABLE classification."""
        result = classify_query("DROP TABLE IF EXISTS users")
        assert result.operation == QueryOperation.DROP
        assert result.is_write is True

    # -------------------------------------------------------------------------
    # Databricks-specific operations (pattern matching)
    # -------------------------------------------------------------------------

    def test_optimize(self) -> None:
        """Test OPTIMIZE (Databricks-specific) classification."""
        result = classify_query("OPTIMIZE catalog.schema.table ZORDER BY (col1, col2)")
        assert result.operation == QueryOperation.OPTIMIZE
        assert result.is_write is True
        assert result.is_maintenance is True
        assert result.parse_confidence == "pattern"

    def test_vacuum(self) -> None:
        """Test VACUUM (Databricks-specific) classification."""
        result = classify_query("VACUUM catalog.schema.table RETAIN 168 HOURS")
        assert result.operation == QueryOperation.VACUUM
        assert result.is_write is True
        assert result.is_maintenance is True
        assert result.parse_confidence == "pattern"

    def test_analyze_table(self) -> None:
        """Test ANALYZE TABLE (Databricks-specific) classification."""
        result = classify_query("ANALYZE TABLE catalog.schema.table COMPUTE STATISTICS")
        assert result.operation == QueryOperation.ANALYZE
        assert result.is_read is True
        assert result.is_maintenance is True
        assert result.parse_confidence == "pattern"

    def test_describe_history(self) -> None:
        """Test DESCRIBE HISTORY classification."""
        result = classify_query("DESCRIBE HISTORY catalog.schema.table")
        assert result.operation == QueryOperation.SELECT
        assert result.is_read is True
        assert result.parse_confidence == "pattern"

    def test_show_tables(self) -> None:
        """Test SHOW TABLES classification."""
        result = classify_query("SHOW TABLES IN catalog.schema")
        assert result.operation == QueryOperation.SELECT
        assert result.is_read is True
        assert result.parse_confidence == "pattern"

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    def test_empty_query(self) -> None:
        """Test empty query returns UNKNOWN."""
        result = classify_query("")
        assert result.operation == QueryOperation.UNKNOWN
        assert result.is_read is False
        assert result.is_write is False

    def test_none_query(self) -> None:
        """Test None query returns UNKNOWN."""
        result = classify_query(None)  # type: ignore[arg-type]
        assert result.operation == QueryOperation.UNKNOWN

    def test_whitespace_query(self) -> None:
        """Test whitespace-only query returns UNKNOWN."""
        result = classify_query("   \n\t  ")
        assert result.operation == QueryOperation.UNKNOWN

    def test_complex_query_extracts_tables(self) -> None:
        """Test table extraction from complex query."""
        sql = """
        SELECT *
        FROM catalog.schema.users u
        JOIN catalog.schema.orders o ON u.id = o.user_id
        """
        result = classify_query(sql)
        assert len(result.tables_referenced) >= 1

    def test_fast_mode_skips_parsing(self) -> None:
        """Test full_analysis=False uses heuristics."""
        result = classify_query("SELECT * FROM users", full_analysis=False)
        assert result.operation == QueryOperation.SELECT
        assert result.is_read is True
        # In fast mode, we don't get detailed metrics
        assert result.parse_confidence == "heuristic"


class TestTableFingerprintTransformer:
    """Tests for TableFingerprintTransformer."""

    def test_empty_input(self) -> None:
        """Test empty input returns empty fingerprint."""
        transformer = TableFingerprintTransformer()
        result = transformer.transform([])
        assert result["read_profile"]["query_count"] == 0
        assert result["write_profile"]["operation_count"] == 0
        assert result["access_pattern"] == "unknown"

    def test_read_only_workload(self) -> None:
        """Test read-only workload classification."""
        transformer = TableFingerprintTransformer()
        query_rows = [
            {
                "query_text": "SELECT * FROM users",
                "bytes_scanned": 1000,
                "user_id": "user1",
            },
            {
                "query_text": "SELECT id FROM users WHERE active = true",
                "bytes_scanned": 500,
                "user_id": "user2",
            },
            {
                "query_text": "SELECT COUNT(*) FROM users GROUP BY status",
                "bytes_scanned": 2000,
                "user_id": "user1",
            },
        ]
        result = transformer.transform(query_rows)
        assert result["read_profile"]["query_count"] == 3
        assert result["read_profile"]["total_bytes"] == 3500
        assert result["read_profile"]["distinct_users"] == 2
        assert result["write_profile"]["operation_count"] == 0
        assert result["access_pattern"] == "high_read_low_write"

    def test_write_heavy_workload(self) -> None:
        """Test write-heavy workload classification."""
        transformer = TableFingerprintTransformer()
        # Use INSERT only (not UPDATE/DELETE/MERGE which also count as reads)
        # to get a pure high_write_low_read pattern
        query_rows = [
            {
                "query_text": "INSERT INTO users (id, name) VALUES (1, 'Alice')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (2, 'Bob')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (3, 'Carol')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (4, 'Dave')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (5, 'Eve')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (6, 'Frank')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (7, 'Grace')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (8, 'Henry')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (9, 'Ivy')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (10, 'Jack')",
                "user_id": "etl",
            },
            {
                "query_text": "INSERT INTO users (id, name) VALUES (11, 'Kate')",
                "user_id": "etl",
            },
        ]
        result = transformer.transform(query_rows)
        assert result["write_profile"]["operation_count"] >= 10
        assert result["access_pattern"] == "high_write_low_read"
        # Check by_operation counts
        by_op = result["write_profile"]["by_operation"]
        assert by_op.get("insert", 0) >= 10

    def test_mixed_workload(self) -> None:
        """Test balanced read/write workload."""
        transformer = TableFingerprintTransformer()
        # Use complete SQL and enough queries to avoid "inactive" classification
        query_rows = [
            {"query_text": "SELECT * FROM users", "user_id": "analyst"},
            {"query_text": "SELECT * FROM orders", "user_id": "analyst"},
            {"query_text": "SELECT id FROM products", "user_id": "analyst"},
            {"query_text": "SELECT name FROM customers", "user_id": "analyst"},
            {"query_text": "SELECT * FROM inventory", "user_id": "analyst"},
            {"query_text": "SELECT * FROM transactions", "user_id": "analyst"},
            {"query_text": "INSERT INTO logs (msg) VALUES ('test')", "user_id": "app"},
            {
                "query_text": "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = 1",
                "user_id": "app",
            },
            {
                "query_text": "INSERT INTO audit (action) VALUES ('login')",
                "user_id": "app",
            },
            {
                "query_text": "DELETE FROM sessions WHERE expired = true",
                "user_id": "app",
            },
        ]
        result = transformer.transform(query_rows)
        assert result["access_pattern"] == "balanced"

    def test_maintenance_operations(self) -> None:
        """Test maintenance operations are tracked."""
        transformer = TableFingerprintTransformer()
        query_rows = [
            {
                "query_text": "OPTIMIZE catalog.schema.table ZORDER BY (col)",
                "user_id": "admin",
            },
            {"query_text": "VACUUM catalog.schema.table", "user_id": "admin"},
            {
                "query_text": "ANALYZE TABLE catalog.schema.table COMPUTE STATISTICS",
                "user_id": "admin",
            },
            {"query_text": "SELECT * FROM users", "user_id": "analyst"},
        ]
        result = transformer.transform(query_rows)
        assert result["maintenance_profile"]["operation_count"] == 3
        assert result["maintenance_profile"]["optimize_count"] == 1
        assert result["maintenance_profile"]["vacuum_count"] == 1
        assert result["maintenance_profile"]["analyze_count"] == 1

    def test_complexity_profile(self) -> None:
        """Test complexity metrics are computed."""
        transformer = TableFingerprintTransformer(full_analysis=True)
        query_rows = [
            {
                "query_text": """
                SELECT u.name, COUNT(o.id), SUM(o.amount)
                FROM users u
                JOIN orders o ON u.id = o.user_id
                GROUP BY u.name
                """,
                "user_id": "analyst",
            },
            {
                "query_text": """
                WITH active AS (SELECT * FROM users WHERE status = 'active')
                SELECT * FROM active
                """,
                "user_id": "analyst",
            },
        ]
        result = transformer.transform(query_rows)
        assert "complexity_profile" in result
        cp = result["complexity_profile"]
        assert cp["parse_success_rate"] > 0
        assert cp["join_stats"]["queries_with_joins"] >= 1
        assert cp["queries_with_ctes"] >= 1
        assert cp["queries_with_aggregation"] >= 1

    def test_sampling_large_input(self) -> None:
        """Test large input is sampled."""
        transformer = TableFingerprintTransformer(sample_size=10)
        query_rows = [
            {"query_text": f"SELECT {i} FROM users", "user_id": "user"}
            for i in range(100)
        ]
        result = transformer.transform(query_rows)
        assert result["sample_info"]["total_queries"] == 100
        assert result["sample_info"]["analyzed_queries"] == 10
        assert result["sample_info"]["sampled"] is True

    def test_no_sampling_small_input(self) -> None:
        """Test small input is not sampled."""
        transformer = TableFingerprintTransformer(sample_size=100)
        query_rows = [
            {"query_text": "SELECT * FROM users", "user_id": "user"} for _ in range(10)
        ]
        result = transformer.transform(query_rows)
        assert result["sample_info"]["total_queries"] == 10
        assert result["sample_info"]["analyzed_queries"] == 10
        assert result["sample_info"]["sampled"] is False

    def test_handles_none_query_text(self) -> None:
        """Test None query_text is handled gracefully."""
        transformer = TableFingerprintTransformer()
        query_rows = [
            {"query_text": None, "user_id": "user"},
            {"query_text": "SELECT * FROM users", "user_id": "user"},
        ]
        result = transformer.transform(query_rows)
        # Should not crash
        assert result["read_profile"]["query_count"] == 1


class TestQueryFingerprint:
    """Tests for QueryFingerprint dataclass."""

    def test_immutable(self) -> None:
        """Test QueryFingerprint is immutable."""
        fp = QueryFingerprint(
            operation=QueryOperation.SELECT,
            is_read=True,
            is_write=False,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            fp.operation = QueryOperation.INSERT  # type: ignore[misc]

    def test_default_values(self) -> None:
        """Test QueryFingerprint default values."""
        fp = QueryFingerprint(
            operation=QueryOperation.SELECT,
            is_read=True,
            is_write=False,
        )
        assert fp.join_count == 0
        assert fp.join_types == ()
        assert fp.subquery_count == 0
        assert fp.cte_count == 0
        assert fp.has_aggregation is False
        assert fp.agg_functions == ()
        assert fp.group_by_columns == 0
        assert fp.window_count == 0
        assert fp.has_where is False
        assert fp.has_limit is False
        assert fp.tables_referenced == ()
        assert fp.parse_confidence == "heuristic"


class TestLineageGraphTransformer:
    """Tests for LineageGraphTransformer."""

    def test_empty_lineage(self) -> None:
        """Test empty lineage response."""
        transformer = LineageGraphTransformer()
        result = transformer.transform({})
        assert result["upstream_count"] == 0
        assert result["downstream_count"] == 0
        assert result["upstream_summary"] == []
        assert result["downstream_summary"] == []
        assert result["truncated"] is False

    def test_real_api_response(self) -> None:
        """Test with realistic API response structure."""
        raw_lineage = {
            "upstreams": [
                {
                    "tableInfo": {
                        "name": "usage",
                        "catalog_name": "system",
                        "schema_name": "billing",
                        "table_type": "TABLE",
                        "lineage_timestamp": "2025-12-01 09:11:40.0",
                    },
                    "jobInfos": [
                        {
                            "workspace_id": 123,
                            "job_id": 456,
                            "lineage_timestamp": "2025-12-01",
                        },
                        {
                            "workspace_id": 123,
                            "job_id": 789,
                            "lineage_timestamp": "2025-11-10",
                        },
                    ],
                    "notebookInfos": [
                        {
                            "workspace_id": 123,
                            "notebook_id": 111,
                            "lineage_timestamp": "2025-12-01",
                        },
                    ],
                },
                {
                    "tableInfo": {
                        "name": "list_prices",
                        "catalog_name": "system",
                        "schema_name": "billing",
                        "table_type": "TABLE",
                        "lineage_timestamp": "2025-12-01 09:11:40.0",
                    },
                    "jobInfos": [
                        {
                            "workspace_id": 123,
                            "job_id": 456,
                            "lineage_timestamp": "2025-12-01",
                        },
                    ],
                    "notebookInfos": [],
                },
            ],
            "downstreams": [
                {
                    "tableInfo": {
                        "name": "cost_report",
                        "catalog_name": "analytics",
                        "schema_name": "finance",
                        "table_type": "VIEW",
                        "lineage_timestamp": "2025-12-01 10:00:00.0",
                    },
                    "jobInfos": [],
                    "notebookInfos": [
                        {
                            "workspace_id": 123,
                            "notebook_id": 222,
                            "lineage_timestamp": "2025-12-01",
                        },
                    ],
                },
            ],
        }
        transformer = LineageGraphTransformer()
        result = transformer.transform(raw_lineage)

        assert result["upstream_count"] == 2
        assert result["downstream_count"] == 1
        assert len(result["upstream_summary"]) == 2
        assert len(result["downstream_summary"]) == 1

        # Check first upstream
        upstream_0 = result["upstream_summary"][0]
        assert upstream_0["table"] == "system.billing.usage"
        assert upstream_0["table_type"] == "TABLE"
        assert upstream_0["job_count"] == 2
        assert upstream_0["notebook_count"] == 1
        assert upstream_0["job_ids"] == [456, 789]
        assert upstream_0["notebook_ids"] == [111]
        assert upstream_0["last_updated"] == "2025-12-01 09:11:40.0"

        # Check downstream
        downstream_0 = result["downstream_summary"][0]
        assert downstream_0["table"] == "analytics.finance.cost_report"
        assert downstream_0["table_type"] == "VIEW"
        assert downstream_0["job_count"] == 0
        assert downstream_0["notebook_count"] == 1

    def test_truncation(self) -> None:
        """Test truncation when items exceed max_items."""
        raw_lineage = {
            "upstreams": [
                {
                    "tableInfo": {
                        "name": f"table_{i}",
                        "catalog_name": "c",
                        "schema_name": "s",
                    },
                    "jobInfos": [],
                    "notebookInfos": [],
                }
                for i in range(15)
            ],
            "downstreams": [],
        }
        transformer = LineageGraphTransformer(max_items=5)
        result = transformer.transform(raw_lineage)

        assert result["upstream_count"] == 15
        assert len(result["upstream_summary"]) == 5  # Truncated to max_items
        assert result["truncated"] is True

    def test_job_ids_limited(self) -> None:
        """Test that job_ids are limited to first 5."""
        raw_lineage = {
            "upstreams": [
                {
                    "tableInfo": {
                        "name": "table",
                        "catalog_name": "c",
                        "schema_name": "s",
                    },
                    "jobInfos": [{"job_id": i} for i in range(10)],
                    "notebookInfos": [],
                }
            ],
            "downstreams": [],
        }
        transformer = LineageGraphTransformer()
        result = transformer.transform(raw_lineage)

        upstream_0 = result["upstream_summary"][0]
        assert len(upstream_0["job_ids"]) == 5  # Limited to first 5
        assert upstream_0["job_count"] == 10  # But count is accurate
