# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for warehouse chargeback calculation."""

from datetime import UTC, datetime
from typing import Any

import pytest
from starboard.tools.domain.warehouse.chargeback import (
    ChargebackCalculator,
    UserAllocation,
    WarehouseChargeback,
    aggregate_user_chargebacks,
)

# =============================================================================
# Test Fixtures
# =============================================================================


def _make_user_activity(
    user_name: str,
    total_queries: int = 100,
    total_runtime_sec: float = 1000.0,
    total_bytes_read: int = 1_000_000_000,
) -> dict[str, Any]:
    """Create test user activity data."""
    return {
        "user_name": user_name,
        "total_queries": total_queries,
        "total_runtime_sec": total_runtime_sec,
        "total_bytes_read": total_bytes_read,
    }


@pytest.fixture
def calculator() -> ChargebackCalculator:
    """Create test chargeback calculator."""
    return ChargebackCalculator(
        warehouse_id="wh-001",
        warehouse_name="Test Warehouse",
        total_cost_usd=1000.0,
        period_start=datetime(2025, 1, 1, tzinfo=UTC),
        period_end=datetime(2025, 2, 1, tzinfo=UTC),
        allocation_method="runtime",
    )


# =============================================================================
# ChargebackCalculator Tests
# =============================================================================


class TestChargebackCalculatorBasic:
    """Test basic chargeback calculations."""

    def test_calculate_single_user(self, calculator: ChargebackCalculator) -> None:
        """Single user gets 100% allocation."""
        activity = [_make_user_activity("alice@example.com", total_runtime_sec=1000)]

        result = calculator.calculate(activity)

        assert isinstance(result, WarehouseChargeback)
        assert len(result.allocations) == 1
        assert result.allocations[0].user_name == "alice@example.com"
        assert result.allocations[0].usage_share_pct == 100.0
        assert result.allocations[0].allocated_cost_usd == 1000.0

    def test_calculate_two_users_equal(self, calculator: ChargebackCalculator) -> None:
        """Two users with equal usage get 50% each."""
        activity = [
            _make_user_activity("alice@example.com", total_runtime_sec=500),
            _make_user_activity("bob@example.com", total_runtime_sec=500),
        ]

        result = calculator.calculate(activity)

        assert len(result.allocations) == 2
        for alloc in result.allocations:
            assert alloc.usage_share_pct == 50.0
            assert alloc.allocated_cost_usd == 500.0

    def test_calculate_proportional_allocation(
        self, calculator: ChargebackCalculator
    ) -> None:
        """Users get proportional allocation based on runtime."""
        activity = [
            _make_user_activity("alice@example.com", total_runtime_sec=750),
            _make_user_activity("bob@example.com", total_runtime_sec=250),
        ]

        result = calculator.calculate(activity)

        # Find alice and bob
        alice = next(
            a for a in result.allocations if a.user_name == "alice@example.com"
        )
        bob = next(a for a in result.allocations if a.user_name == "bob@example.com")

        assert alice.usage_share_pct == 75.0
        assert alice.allocated_cost_usd == 750.0
        assert bob.usage_share_pct == 25.0
        assert bob.allocated_cost_usd == 250.0

    def test_calculate_empty_activity(self, calculator: ChargebackCalculator) -> None:
        """Empty activity returns empty allocations."""
        result = calculator.calculate([])

        assert len(result.allocations) == 0
        assert result.total_cost_usd == 1000.0


class TestChargebackAllocationMethods:
    """Test different allocation methods."""

    def test_allocate_by_queries(self) -> None:
        """Allocate based on query count."""
        calculator = ChargebackCalculator(
            warehouse_id="wh-001",
            warehouse_name="Test",
            total_cost_usd=1000.0,
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            allocation_method="queries",
        )

        activity = [
            _make_user_activity(
                "alice@example.com", total_queries=80, total_runtime_sec=100
            ),
            _make_user_activity(
                "bob@example.com", total_queries=20, total_runtime_sec=900
            ),
        ]

        result = calculator.calculate(activity)

        alice = next(
            a for a in result.allocations if a.user_name == "alice@example.com"
        )
        bob = next(a for a in result.allocations if a.user_name == "bob@example.com")

        # Based on queries: alice=80, bob=20
        assert alice.usage_share_pct == 80.0
        assert bob.usage_share_pct == 20.0

    def test_allocate_by_bytes(self) -> None:
        """Allocate based on bytes read."""
        calculator = ChargebackCalculator(
            warehouse_id="wh-001",
            warehouse_name="Test",
            total_cost_usd=1000.0,
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            allocation_method="bytes",
        )

        activity = [
            _make_user_activity("alice@example.com", total_bytes_read=9_000_000_000),
            _make_user_activity("bob@example.com", total_bytes_read=1_000_000_000),
        ]

        result = calculator.calculate(activity)

        alice = next(
            a for a in result.allocations if a.user_name == "alice@example.com"
        )
        bob = next(a for a in result.allocations if a.user_name == "bob@example.com")

        # Based on bytes: alice=90%, bob=10%
        assert alice.usage_share_pct == 90.0
        assert bob.usage_share_pct == 10.0


class TestChargebackResultStructure:
    """Test the structure of chargeback results."""

    def test_result_has_all_fields(self, calculator: ChargebackCalculator) -> None:
        """Result includes all expected fields."""
        activity = [_make_user_activity("alice@example.com")]

        result = calculator.calculate(activity)

        assert result.warehouse_id == "wh-001"
        assert result.warehouse_name == "Test Warehouse"
        assert result.period_start == datetime(2025, 1, 1, tzinfo=UTC)
        assert result.period_end == datetime(2025, 2, 1, tzinfo=UTC)
        assert result.total_cost_usd == 1000.0
        assert result.allocation_method == "runtime"

    def test_allocation_has_all_fields(self, calculator: ChargebackCalculator) -> None:
        """User allocation includes all expected fields."""
        activity = [
            _make_user_activity(
                "alice@example.com",
                total_queries=100,
                total_runtime_sec=500,
                total_bytes_read=1_000_000_000,
            )
        ]

        result = calculator.calculate(activity)
        alloc = result.allocations[0]

        assert alloc.user_name == "alice@example.com"
        assert alloc.total_queries == 100
        assert alloc.total_runtime_sec == 500.0
        assert alloc.total_bytes_read == 1_000_000_000
        assert isinstance(alloc.usage_share_pct, float)
        assert isinstance(alloc.allocated_cost_usd, float)

    def test_allocations_sorted_by_cost(self, calculator: ChargebackCalculator) -> None:
        """Allocations are sorted by cost descending."""
        activity = [
            _make_user_activity("charlie@example.com", total_runtime_sec=100),
            _make_user_activity("alice@example.com", total_runtime_sec=600),
            _make_user_activity("bob@example.com", total_runtime_sec=300),
        ]

        result = calculator.calculate(activity)

        costs = [a.allocated_cost_usd for a in result.allocations]
        assert costs == sorted(costs, reverse=True)
        assert result.allocations[0].user_name == "alice@example.com"


# =============================================================================
# Aggregation Tests
# =============================================================================


class TestAggregateUserChargebacks:
    """Test aggregating chargebacks across warehouses."""

    def test_aggregate_single_warehouse(self) -> None:
        """Single warehouse returns same allocations."""
        cb = WarehouseChargeback(
            warehouse_id="wh-001",
            warehouse_name="Test",
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            total_cost_usd=1000.0,
            allocations=(
                UserAllocation(
                    user_name="alice@example.com",
                    total_queries=100,
                    total_runtime_sec=500,
                    total_bytes_read=1_000_000_000,
                    usage_share_pct=100.0,
                    allocated_cost_usd=1000.0,
                ),
            ),
            allocation_method="runtime",
        )

        result = aggregate_user_chargebacks([cb])

        assert len(result) == 1
        assert result[0].user_name == "alice@example.com"
        assert result[0].allocated_cost_usd == 1000.0

    def test_aggregate_multiple_warehouses(self) -> None:
        """Aggregate costs across multiple warehouses."""
        cb1 = WarehouseChargeback(
            warehouse_id="wh-001",
            warehouse_name="Warehouse 1",
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            total_cost_usd=1000.0,
            allocations=(
                UserAllocation(
                    "alice@example.com", 100, 500, 1_000_000_000, 100.0, 1000.0
                ),
            ),
            allocation_method="runtime",
        )
        cb2 = WarehouseChargeback(
            warehouse_id="wh-002",
            warehouse_name="Warehouse 2",
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            total_cost_usd=500.0,
            allocations=(
                UserAllocation("alice@example.com", 50, 250, 500_000_000, 50.0, 250.0),
                UserAllocation("bob@example.com", 50, 250, 500_000_000, 50.0, 250.0),
            ),
            allocation_method="runtime",
        )

        result = aggregate_user_chargebacks([cb1, cb2])

        # Alice: $1000 + $250 = $1250
        # Bob: $250
        alice = next(a for a in result if a.user_name == "alice@example.com")
        bob = next(a for a in result if a.user_name == "bob@example.com")

        assert alice.allocated_cost_usd == 1250.0
        assert bob.allocated_cost_usd == 250.0
        assert alice.total_queries == 150
        assert bob.total_queries == 50

    def test_aggregate_empty_list(self) -> None:
        """Empty chargeback list returns empty aggregation."""
        result = aggregate_user_chargebacks([])
        assert len(result) == 0

    def test_aggregate_sorted_by_cost(self) -> None:
        """Aggregated results are sorted by cost."""
        cb = WarehouseChargeback(
            warehouse_id="wh-001",
            warehouse_name="Test",
            period_start=datetime(2025, 1, 1, tzinfo=UTC),
            period_end=datetime(2025, 2, 1, tzinfo=UTC),
            total_cost_usd=1000.0,
            allocations=(
                UserAllocation(
                    "charlie@example.com", 10, 100, 100_000_000, 10.0, 100.0
                ),
                UserAllocation("alice@example.com", 60, 600, 600_000_000, 60.0, 600.0),
                UserAllocation("bob@example.com", 30, 300, 300_000_000, 30.0, 300.0),
            ),
            allocation_method="runtime",
        )

        result = aggregate_user_chargebacks([cb])

        costs = [a.allocated_cost_usd for a in result]
        assert costs == sorted(costs, reverse=True)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_runtime_users(self, calculator: ChargebackCalculator) -> None:
        """Handle users with zero runtime."""
        activity = [
            _make_user_activity("alice@example.com", total_runtime_sec=0),
            _make_user_activity("bob@example.com", total_runtime_sec=1000),
        ]

        result = calculator.calculate(activity)

        alice = next(
            a for a in result.allocations if a.user_name == "alice@example.com"
        )
        bob = next(a for a in result.allocations if a.user_name == "bob@example.com")

        assert alice.usage_share_pct == 0.0
        assert alice.allocated_cost_usd == 0.0
        assert bob.usage_share_pct == 100.0

    def test_all_zero_runtime(self, calculator: ChargebackCalculator) -> None:
        """Handle case where all users have zero runtime."""
        activity = [
            _make_user_activity("alice@example.com", total_runtime_sec=0),
            _make_user_activity("bob@example.com", total_runtime_sec=0),
        ]

        result = calculator.calculate(activity)

        for alloc in result.allocations:
            assert alloc.usage_share_pct == 0.0
            assert alloc.allocated_cost_usd == 0.0

    def test_rounding(self, calculator: ChargebackCalculator) -> None:
        """Costs are rounded to 2 decimal places."""
        activity = [
            _make_user_activity("alice@example.com", total_runtime_sec=333.333),
            _make_user_activity("bob@example.com", total_runtime_sec=666.667),
        ]

        result = calculator.calculate(activity)

        # Values should be rounded
        for alloc in result.allocations:
            cost_str = str(alloc.allocated_cost_usd)
            if "." in cost_str:
                decimals = len(cost_str.split(".")[1])
                assert decimals <= 2

    def test_missing_fields_use_defaults(
        self, calculator: ChargebackCalculator
    ) -> None:
        """Missing fields in activity data use defaults."""
        activity = [{"user_name": "alice@example.com"}]  # Missing metrics

        result = calculator.calculate(activity)

        alloc = result.allocations[0]
        assert alloc.total_queries == 0
        assert alloc.total_runtime_sec == 0.0
        assert alloc.total_bytes_read == 0
