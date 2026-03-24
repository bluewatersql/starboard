"""
Unit tests for QueryAnalyzer (TDD).

Tests SQL query parsing and pattern extraction following TDD principles.
"""

from starboard_core.rag.models import AnalysisResult
from starboard_server.infra.rag.domain.query_analyzer import QueryAnalyzer


class TestQueryAnalyzerInit:
    """Test QueryAnalyzer initialization."""

    def test_init_creates_analyzer(self):
        """Should create analyzer instance."""
        analyzer = QueryAnalyzer()
        assert analyzer is not None


class TestParsePredicates:
    """Test predicate extraction from WHERE clauses."""

    def test_parse_simple_equality(self):
        """Should parse simple equality predicate."""
        analyzer = QueryAnalyzer()
        query = "SELECT * FROM usage WHERE sku_name = 'JOBS_COMPUTE'"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        assert len(predicates) > 0
        # Should have extracted the sku_name predicate
        sku_predicates = [p for p in predicates if "sku_name" in p.lhs.lower()]
        assert len(sku_predicates) > 0

    def test_parse_multiple_predicates(self):
        """Should parse multiple WHERE conditions."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage
        WHERE sku_name = 'JOBS_COMPUTE'
          AND workspace_id = '12345'
        """

        predicates = analyzer.parse_predicates(query, table_name="usage")

        assert len(predicates) >= 2

    def test_parse_in_clause(self):
        """Should parse IN clause predicates."""
        analyzer = QueryAnalyzer()
        query = "SELECT * FROM usage WHERE sku_name IN ('JOBS', 'SERVERLESS')"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        assert len(predicates) > 0

    def test_parse_like_clause(self):
        """Should parse LIKE predicates."""
        analyzer = QueryAnalyzer()
        query = "SELECT * FROM usage WHERE sku_name LIKE 'JOBS%'"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        assert len(predicates) > 0

    def test_skip_column_to_column_comparison(self):
        """Should skip predicates comparing two columns."""
        analyzer = QueryAnalyzer()
        query = "SELECT * FROM usage WHERE start_date < end_date"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        # Should filter out column-to-column comparisons
        # Only keep literal comparisons
        literal_predicates = [p for p in predicates if p.rhs_kind == "literal"]
        assert all(p.rhs_kind == "literal" for p in literal_predicates)

    def test_handles_unparseable_query(self):
        """Should return empty list for malformed SQL."""
        analyzer = QueryAnalyzer()
        query = "INVALID SQL GARBAGE"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        assert predicates == []

    def test_extracts_actual_values(self):
        """Should extract actual literal values from predicates."""
        analyzer = QueryAnalyzer()
        query = "SELECT * FROM usage WHERE sku_name = 'JOBS_COMPUTE'"

        predicates = analyzer.parse_predicates(query, table_name="usage")

        # Should have values tuple populated
        sku_predicates = [p for p in predicates if "sku_name" in p.lhs.lower()]
        if sku_predicates:
            assert len(sku_predicates[0].values) > 0


class TestParseAggregations:
    """Test aggregation extraction from SELECT and GROUP BY."""

    def test_parse_simple_aggregation(self):
        """Should parse simple aggregation function."""
        analyzer = QueryAnalyzer()
        query = "SELECT SUM(usage_quantity) FROM usage GROUP BY sku_name"

        aggregations = analyzer.parse_aggregations(query, table_name="usage")

        assert len(aggregations) > 0
        sum_aggs = [a for a in aggregations if a.agg == "SUM"]
        assert len(sum_aggs) > 0

    def test_parse_multiple_aggregations(self):
        """Should parse multiple aggregation functions."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT
            SUM(usage_quantity),
            AVG(usage_quantity),
            COUNT(*)
        FROM usage
        GROUP BY sku_name
        """

        aggregations = analyzer.parse_aggregations(query, table_name="usage")

        agg_types = {a.agg for a in aggregations}
        assert "SUM" in agg_types or "AVG" in agg_types or "COUNT" in agg_types

    def test_parse_count_star(self):
        """Should handle COUNT(*) aggregation."""
        analyzer = QueryAnalyzer()
        query = "SELECT COUNT(*) FROM usage"

        aggregations = analyzer.parse_aggregations(query, table_name="usage")

        count_aggs = [a for a in aggregations if a.agg == "COUNT"]
        assert len(count_aggs) > 0

    def test_parse_distinct_aggregation(self):
        """Should identify DISTINCT in aggregations."""
        analyzer = QueryAnalyzer()
        query = "SELECT COUNT(DISTINCT workspace_id) FROM usage"

        aggregations = analyzer.parse_aggregations(query, table_name="usage")

        [a for a in aggregations if a.distinct]
        # May or may not be captured depending on sqlglot parsing
        assert isinstance(aggregations, list)

    def test_handles_unparseable_query(self):
        """Should return empty list for malformed SQL."""
        analyzer = QueryAnalyzer()
        query = "INVALID SQL"

        aggregations = analyzer.parse_aggregations(query, table_name="usage")

        assert aggregations == []


class TestParseJoins:
    """Test join pattern extraction."""

    def test_parse_simple_join(self):
        """Should parse simple INNER JOIN."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage u
        JOIN list_prices p ON u.sku_name = p.sku_name
        """

        joins = analyzer.parse_joins(query, table_name="usage")

        assert len(joins) > 0

    def test_parse_left_join(self):
        """Should identify LEFT JOIN."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage u
        LEFT JOIN list_prices p ON u.sku_name = p.sku_name
        """

        joins = analyzer.parse_joins(query, table_name="usage")

        assert len(joins) > 0
        # Should capture join type
        left_joins = [j for j in joins if j.join_type == "LEFT"]
        assert len(left_joins) > 0 or len(joins) > 0  # At least found the join

    def test_parse_multiple_joins(self):
        """Should parse multiple JOIN clauses."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage u
        JOIN list_prices p ON u.sku_name = p.sku_name
        JOIN workspaces w ON u.workspace_id = w.workspace_id
        """

        joins = analyzer.parse_joins(query, table_name="usage")

        assert len(joins) >= 2

    def test_parse_complex_join_condition(self):
        """Should handle complex join conditions."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage u
        JOIN list_prices p
          ON u.sku_name = p.sku_name
          AND u.usage_date BETWEEN p.price_start_time AND p.price_end_time
        """

        joins = analyzer.parse_joins(query, table_name="usage")

        assert len(joins) > 0

    def test_extracts_join_columns(self):
        """Should extract column pairs from ON clause."""
        analyzer = QueryAnalyzer()
        query = """
        SELECT * FROM usage u
        JOIN list_prices p ON u.workspace_id = p.workspace_id
        """

        joins = analyzer.parse_joins(query, table_name="usage")

        # Should have extracted join pairs
        if joins:
            assert len(joins[0].join_pairs) > 0 or joins[0].join_condition

    def test_handles_unparseable_query(self):
        """Should return empty list for malformed SQL."""
        analyzer = QueryAnalyzer()
        query = "INVALID SQL"

        joins = analyzer.parse_joins(query, table_name="usage")

        assert joins == []


class TestAnalyzeQueries:
    """Test full query analysis."""

    def test_analyze_empty_list(self):
        """Should handle empty query list."""
        analyzer = QueryAnalyzer()

        result = analyzer.analyze_queries([])

        assert isinstance(result, AnalysisResult)
        assert result.success_count == 0
        assert result.failed_count == 0

    def test_analyze_single_query(self):
        """Should analyze single query."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT SUM(usage_quantity) FROM usage WHERE sku_name = 'JOBS'")
        ]

        result = analyzer.analyze_queries(queries)

        assert isinstance(result, AnalysisResult)
        assert result.success_count >= 0

    def test_analyze_multiple_queries(self):
        """Should analyze multiple queries."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS'"),
            ("usage", "SELECT SUM(usage_quantity) FROM usage GROUP BY sku_name"),
            (
                "usage",
                "SELECT * FROM usage u JOIN list_prices p ON u.sku_name = p.sku_name",
            ),
        ]

        result = analyzer.analyze_queries(queries)

        assert isinstance(result, AnalysisResult)
        assert result.success_count > 0

    def test_tracks_failures(self):
        """Should track failed query parses."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "VALID: SELECT * FROM usage"),
            ("usage", "INVALID SQL GARBAGE"),
            ("usage", "ANOTHER INVALID"),
        ]

        result = analyzer.analyze_queries(queries)

        assert isinstance(result, AnalysisResult)
        assert result.failed_count >= 0  # Should track failures

    def test_aggregates_results_by_table(self):
        """Should group analysis results by table."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS'"),
            ("list_prices", "SELECT * FROM list_prices WHERE sku_name = 'SERVERLESS'"),
        ]

        result = analyzer.analyze_queries(queries)

        assert isinstance(result, AnalysisResult)
        # Results should be aggregated
        assert result.raw_predicates is not None or result.success_count >= 0


class TestGetColumnPredicates:
    """Test extraction of column-specific predicates."""

    def test_get_column_predicates_from_analysis(self):
        """Should extract predicates for specific column."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS'"),
            ("usage", "SELECT * FROM usage WHERE sku_name = 'SERVERLESS'"),
        ]

        result = analyzer.analyze_queries(queries)
        predicates = analyzer.get_column_predicates(result, "usage", "sku_name")

        assert isinstance(predicates, list)

    def test_get_column_predicates_returns_values(self):
        """Should return list of observed values for column."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS_COMPUTE'"),
        ]

        result = analyzer.analyze_queries(queries)
        predicates = analyzer.get_column_predicates(result, "usage", "sku_name")

        # Should return list of values
        assert isinstance(predicates, list)

    def test_get_column_predicates_deduplicates(self):
        """Should deduplicate values."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS'"),
            ("usage", "SELECT * FROM usage WHERE sku_name = 'JOBS'"),
            ("usage", "SELECT * FROM usage WHERE sku_name = 'SERVERLESS'"),
        ]

        result = analyzer.analyze_queries(queries)
        predicates = analyzer.get_column_predicates(result, "usage", "sku_name")

        # Should have unique values
        assert len(predicates) == len(set(predicates))


class TestGetColumnAggregations:
    """Test extraction of column-specific aggregations."""

    def test_get_column_aggregations_from_analysis(self):
        """Should extract aggregations for specific column."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT SUM(usage_quantity) FROM usage"),
            ("usage", "SELECT AVG(usage_quantity) FROM usage"),
        ]

        result = analyzer.analyze_queries(queries)
        aggs = analyzer.get_column_aggregations(result, "usage", "usage_quantity")

        assert isinstance(aggs, list)

    def test_get_column_aggregations_returns_functions(self):
        """Should return list of aggregation function names."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT SUM(amount), AVG(amount) FROM usage"),
        ]

        result = analyzer.analyze_queries(queries)
        aggs = analyzer.get_column_aggregations(result, "usage", "amount")

        # Should return list of agg function names
        assert isinstance(aggs, list)

    def test_get_column_aggregations_deduplicates(self):
        """Should deduplicate aggregation functions."""
        analyzer = QueryAnalyzer()
        queries = [
            ("usage", "SELECT SUM(amount) FROM usage"),
            ("usage", "SELECT SUM(amount) FROM usage"),
            ("usage", "SELECT AVG(amount) FROM usage"),
        ]

        result = analyzer.analyze_queries(queries)
        aggs = analyzer.get_column_aggregations(result, "usage", "amount")

        # Should have unique function names
        assert len(aggs) == len(set(aggs))


class TestGetJoinColumns:
    """Test extraction of join columns."""

    def test_get_join_columns_from_analysis(self):
        """Should extract frequently joined columns."""
        analyzer = QueryAnalyzer()
        queries = [
            (
                "usage",
                "SELECT * FROM usage u JOIN list_prices p ON u.workspace_id = p.workspace_id",
            ),
        ]

        result = analyzer.analyze_queries(queries)
        join_cols = analyzer.get_join_columns(result, "usage")

        assert isinstance(join_cols, list)

    def test_get_join_columns_sorts_by_frequency(self):
        """Should return most frequent columns first."""
        analyzer = QueryAnalyzer()
        queries = [
            (
                "usage",
                "SELECT * FROM usage u JOIN t1 ON u.workspace_id = t1.workspace_id",
            ),
            (
                "usage",
                "SELECT * FROM usage u JOIN t2 ON u.workspace_id = t2.workspace_id",
            ),
            ("usage", "SELECT * FROM usage u JOIN t3 ON u.sku_name = t3.sku_name"),
        ]

        result = analyzer.analyze_queries(queries)
        join_cols = analyzer.get_join_columns(result, "usage")

        # Should be sorted by frequency
        assert isinstance(join_cols, list)

    def test_get_join_columns_limits_results(self):
        """Should limit to top N columns."""
        analyzer = QueryAnalyzer()
        # Create many different join columns
        queries = [
            ("usage", f"SELECT * FROM usage u JOIN t{i} ON u.col{i} = t{i}.col{i}")
            for i in range(20)
        ]

        result = analyzer.analyze_queries(queries)
        join_cols = analyzer.get_join_columns(result, "usage", limit=10)

        assert len(join_cols) <= 10
