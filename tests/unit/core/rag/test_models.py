# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for RAG data models.

Tests all Pydantic models and dataclasses for correct validation,
serialization, and business logic.
"""

import pytest
from pydantic import ValidationError
from starboard_core.rag.models import (
    AggregationRecord,
    AnalysisResult,
    ColumnMetadata,
    FacetRow,
    JoinRecord,
    PredicateRecord,
    RelationshipCondition,
    RelationshipMetadata,
    TableMetadata,
)


class TestJoinRecord:
    """Test JoinRecord model."""

    def test_valid_join_record(self):
        """Should create valid join record."""
        record = JoinRecord(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_type="INNER",
            join_pairs=(("sku_name", "sku_name"),),
            join_condition="usage.sku_name = list_prices.sku_name",
        )

        assert record.from_table == "system.billing.usage"
        assert record.to_table == "system.billing.list_prices"
        assert record.join_type == "INNER"
        assert len(record.join_pairs) == 1
        assert record.join_pairs[0] == ("sku_name", "sku_name")

    def test_frozen_join_record(self):
        """Should be immutable (frozen)."""
        record = JoinRecord(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_type="INNER",
            join_pairs=(("sku_name", "sku_name"),),
            join_condition="usage.sku_name = list_prices.sku_name",
        )

        with pytest.raises((ValidationError, AttributeError)):
            record.join_type = "LEFT"  # type: ignore


class TestPredicateRecord:
    """Test PredicateRecord model."""

    def test_valid_predicate_record(self):
        """Should create valid predicate record."""
        record = PredicateRecord(
            scope="WHERE",
            op="=",
            lhs="billing_origin_product",
            rhs_kind="literal",
            rhs="<string>",
            negated=False,
            values=("JOBS", "WAREHOUSES", "CLUSTERS"),
        )

        assert record.scope == "WHERE"
        assert record.op == "="
        assert record.lhs == "billing_origin_product"
        assert "JOBS" in record.values

    def test_predicate_defaults(self):
        """Should use defaults for optional fields."""
        record = PredicateRecord(
            scope="WHERE",
            op="=",
            lhs="warehouse_id",
            rhs_kind="literal",
            rhs="abc123",
        )

        assert record.negated is False
        assert record.values == ()


class TestAggregationRecord:
    """Test AggregationRecord model."""

    def test_valid_aggregation_record(self):
        """Should create valid aggregation record."""
        record = AggregationRecord(
            agg="SUM",
            arg_kind="column",
            arg="usage_quantity",
            alias="total_usage",
            distinct=False,
        )

        assert record.agg == "SUM"
        assert record.arg == "usage_quantity"
        assert record.alias == "total_usage"

    def test_aggregation_defaults(self):
        """Should use defaults for optional fields."""
        record = AggregationRecord(
            agg="COUNT",
            arg_kind="star",
            arg="*",
        )

        assert record.alias is None
        assert record.distinct is False


class TestAnalysisResult:
    """Test AnalysisResult model."""

    def test_valid_analysis_result(self):
        """Should create valid analysis result."""
        result = AnalysisResult(
            success_count=100,
            failed_count=5,
            join_summary=[
                {
                    "from_table": "system.billing.usage",
                    "to_table": "system.billing.list_prices",
                    "frequency": 50,
                }
            ],
        )

        assert result.success_count == 100
        assert result.failed_count == 5
        assert len(result.join_summary) == 1

    def test_analysis_with_raw_records(self):
        """Should store raw records."""
        join = JoinRecord(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_type="INNER",
            join_pairs=(("sku_name", "sku_name"),),
            join_condition="usage.sku_name = list_prices.sku_name",
        )

        result = AnalysisResult(
            success_count=100,
            failed_count=5,
            join_summary=[],
            raw_joins=[join],
        )

        assert result.raw_joins is not None
        assert len(result.raw_joins) == 1
        assert result.raw_joins[0].from_table == "system.billing.usage"


class TestRelationshipCondition:
    """Test RelationshipCondition model."""

    def test_valid_relationship_condition(self):
        """Should create valid relationship condition."""
        condition = RelationshipCondition(
            condition="usage_date BETWEEN pricing_start_time AND pricing_end_time",
            frequency="very_common",
        )

        assert "usage_date" in condition.condition
        assert condition.frequency == "very_common"


class TestRelationshipMetadata:
    """Test RelationshipMetadata model."""

    def test_valid_relationship_metadata(self):
        """Should create valid relationship metadata."""
        condition = RelationshipCondition(
            condition="usage_date BETWEEN pricing_start_time AND pricing_end_time",
            frequency="very_common",
        )

        relationship = RelationshipMetadata(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_types=["INNER", "LEFT"],
            core_columns="sku_name = sku_name",
            extended_conditions=[condition],
        )

        assert relationship.from_table == "system.billing.usage"
        assert relationship.to_table == "system.billing.list_prices"
        assert "INNER" in relationship.join_types
        assert len(relationship.extended_conditions) == 1

    def test_relationship_full_name(self):
        """Should generate full relationship name."""
        relationship = RelationshipMetadata(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_types=["INNER"],
            core_columns="sku_name = sku_name",
            extended_conditions=[],
        )

        assert (
            relationship.full_name
            == "system.billing.usage -> system.billing.list_prices"
        )


class TestColumnMetadata:
    """Test ColumnMetadata model."""

    def test_valid_column_metadata(self):
        """Should create valid column metadata."""
        column = ColumnMetadata(
            table_name="system.billing.usage",
            column_name="usage_quantity",
            data_type="DECIMAL(38,10)",
            is_nullable=False,
            comment="Amount of resource consumed",
            common_aggregations=["SUM", "AVG"],
            example_filters=[],
            business_meaning="Quantity of resource consumed in the billing period",
            cardinality_estimate="high",
        )

        assert column.column_name == "usage_quantity"
        assert column.data_type == "DECIMAL(38,10)"
        assert column.is_nullable is False
        assert "SUM" in column.common_aggregations
        assert column.cardinality_estimate == "high"

    def test_column_defaults(self):
        """Should use defaults for optional fields."""
        column = ColumnMetadata(
            table_name="system.billing.usage",
            column_name="usage_quantity",
            data_type="DECIMAL(38,10)",
        )

        assert column.is_nullable is True
        assert column.comment is None
        assert column.common_aggregations == []
        assert column.example_filters == []
        assert column.business_meaning is None
        assert column.cardinality_estimate is None


class TestTableMetadata:
    """Test TableMetadata model."""

    def test_valid_table_metadata(self):
        """Should create valid table metadata."""
        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            comment="Tracks Databricks resource consumption",
        )

        assert table.table_catalog == "system"
        assert table.table_schema == "billing"
        assert table.table_name == "usage"
        assert table.table_type == "TABLE"

    def test_table_full_name(self):
        """Should generate fully qualified table name."""
        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
        )

        assert table.full_name == "system.billing.usage"

    def test_table_with_columns(self):
        """Should store columns."""
        column = ColumnMetadata(
            table_name="system.billing.usage",
            column_name="usage_quantity",
            data_type="DECIMAL(38,10)",
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            columns=[column],
        )

        assert len(table.columns) == 1
        assert table.columns[0].column_name == "usage_quantity"

    def test_table_with_relationships(self):
        """Should store relationships."""
        relationship = RelationshipMetadata(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_types=["INNER"],
            core_columns="sku_name = sku_name",
            extended_conditions=[],
        )

        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            relationships=[relationship],
        )

        assert len(table.relationships) == 1
        assert table.relationships[0].to_table == "system.billing.list_prices"

    def test_table_with_enrichment(self):
        """Should store LLM-enriched fields."""
        table = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            business_context="Tracks Databricks resource consumption for billing purposes",
            grain="One row per SKU per hour per workspace",
            common_use_cases=[
                "Calculate total spend by SKU",
                "Analyze usage trends by workspace",
            ],
        )

        assert table.business_context is not None
        assert "billing" in table.business_context.lower()
        assert table.grain == "One row per SKU per hour per workspace"
        assert len(table.common_use_cases) == 2


class TestFacetRow:
    """Test FacetRow dataclass."""

    def test_valid_facet_row(self):
        """Should create valid facet row."""
        facet = FacetRow(
            facet_key="system.compute.warehouses.warehouse_size",
            facet_value="X_LARGE",
            facet_norm="x large",
            domain="compute_warehouses",
            parent_id="nuance::codebook_warehouse_size",
            base_id="nuance::codebook_warehouse_size::facet::X_LARGE",
            source_record_id="nuance::codebook_warehouse_size@@domain=compute_warehouses",
            doc_set_version=20251223,
            is_active=True,
            hint="Use for capacity-based filtering",
        )

        assert facet.facet_key == "system.compute.warehouses.warehouse_size"
        assert facet.facet_value == "X_LARGE"
        assert facet.facet_norm == "x large"
        assert facet.domain == "compute_warehouses"
        assert facet.is_active is True

    def test_frozen_facet_row(self):
        """Should be immutable (frozen)."""
        facet = FacetRow(
            facet_key="system.compute.warehouses.warehouse_size",
            facet_value="X_LARGE",
            facet_norm="x large",
            domain="compute_warehouses",
            parent_id="nuance::codebook_warehouse_size",
            base_id="nuance::codebook_warehouse_size::facet::X_LARGE",
            source_record_id="nuance::codebook_warehouse_size@@domain=compute_warehouses",
            doc_set_version=20251223,
            is_active=True,
            hint="",
        )

        with pytest.raises(AttributeError):
            facet.facet_value = "LARGE"  # type: ignore


class TestModelSerialization:
    """Test Pydantic model serialization and deserialization."""

    def test_table_metadata_round_trip(self):
        """Should serialize and deserialize TableMetadata."""
        original = TableMetadata(
            table_catalog="system",
            table_schema="billing",
            table_name="usage",
            table_type="TABLE",
            common_join_columns=["sku_name", "usage_date"],
        )

        # Serialize
        serialized = original.model_dump()
        assert serialized["table_catalog"] == "system"
        assert "sku_name" in serialized["common_join_columns"]

        # Deserialize
        deserialized = TableMetadata.model_validate(serialized)
        assert deserialized.table_catalog == original.table_catalog
        assert deserialized.common_join_columns == original.common_join_columns

    def test_analysis_result_round_trip(self):
        """Should serialize and deserialize AnalysisResult with nested models."""
        join = JoinRecord(
            from_table="system.billing.usage",
            to_table="system.billing.list_prices",
            join_type="INNER",
            join_pairs=(("sku_name", "sku_name"),),
            join_condition="usage.sku_name = list_prices.sku_name",
        )

        original = AnalysisResult(
            success_count=100,
            failed_count=5,
            join_summary=[{"from_table": "system.billing.usage"}],
            raw_joins=[join],
        )

        # Serialize
        serialized = original.model_dump()
        assert serialized["success_count"] == 100
        assert len(serialized["raw_joins"]) == 1

        # Deserialize
        deserialized = AnalysisResult.model_validate(serialized)
        assert deserialized.success_count == original.success_count
        assert len(deserialized.raw_joins or []) == 1
