# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for warehouse domain input models."""

from __future__ import annotations

import pytest
from starboard_core.domain.models.warehouse.inputs import (
    PortfolioChargebackInput,
    WarehouseChargebackInput,
    WarehouseFingerprintInput,
    WarehouseHealthInput,
    WarehousePortfolioInput,
    WarehouseSLOConfigInput,
    WarehouseTopologyInput,
    WarehouseUserActivityInput,
)


class TestWarehousePortfolioInput:
    """Tests for WarehousePortfolioInput."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        input_model = WarehousePortfolioInput()
        assert input_model.window_days == 7
        assert input_model.include_inactive is False

    def test_custom_values(self) -> None:
        """Test custom values are accepted."""
        input_model = WarehousePortfolioInput(window_days=30, include_inactive=True)
        assert input_model.window_days == 30
        assert input_model.include_inactive is True


class TestWarehouseFingerprintInput:
    """Tests for WarehouseFingerprintInput."""

    def test_valid_input(self) -> None:
        """Test valid input is accepted."""
        input_model = WarehouseFingerprintInput(warehouse_id="abc123")
        assert input_model.warehouse_id == "abc123"
        assert input_model.window_days == 7

    def test_empty_warehouse_id_raises(self) -> None:
        """Test empty warehouse_id raises ValueError."""
        with pytest.raises(ValueError, match="warehouse_id must not be empty"):
            WarehouseFingerprintInput(warehouse_id="")

    def test_whitespace_warehouse_id_raises(self) -> None:
        """Test whitespace warehouse_id raises ValueError."""
        with pytest.raises(ValueError, match="warehouse_id must not be empty"):
            WarehouseFingerprintInput(warehouse_id="   ")


class TestWarehouseHealthInput:
    """Tests for WarehouseHealthInput."""

    def test_valid_input(self) -> None:
        """Test valid input is accepted."""
        input_model = WarehouseHealthInput(warehouse_id="abc123", window_days=30)
        assert input_model.warehouse_id == "abc123"
        assert input_model.window_days == 30

    def test_empty_warehouse_id_raises(self) -> None:
        """Test empty warehouse_id raises ValueError."""
        with pytest.raises(ValueError, match="warehouse_id must not be empty"):
            WarehouseHealthInput(warehouse_id="")


class TestWarehouseSLOConfigInput:
    """Tests for WarehouseSLOConfigInput."""

    def test_default_profile(self) -> None:
        """Test default profile is interactive."""
        input_model = WarehouseSLOConfigInput(warehouse_id="abc123")
        assert input_model.profile == "interactive"

    def test_custom_profile_requires_values(self) -> None:
        """Test custom profile requires latency and availability."""
        with pytest.raises(ValueError, match="p95_latency_ms required"):
            WarehouseSLOConfigInput(warehouse_id="abc123", profile="custom")

    def test_custom_profile_with_latency_only(self) -> None:
        """Test custom profile requires both values."""
        with pytest.raises(ValueError, match="availability_pct required"):
            WarehouseSLOConfigInput(
                warehouse_id="abc123",
                profile="custom",
                p95_latency_ms=1000,
            )

    def test_custom_profile_valid(self) -> None:
        """Test valid custom profile."""
        input_model = WarehouseSLOConfigInput(
            warehouse_id="abc123",
            profile="custom",
            p95_latency_ms=1000,
            availability_pct=99.9,
        )
        assert input_model.profile == "custom"
        assert input_model.p95_latency_ms == 1000
        assert input_model.availability_pct == 99.9


class TestWarehouseUserActivityInput:
    """Tests for WarehouseUserActivityInput."""

    def test_valid_input(self) -> None:
        """Test valid input is accepted."""
        input_model = WarehouseUserActivityInput(warehouse_id="abc123")
        assert input_model.warehouse_id == "abc123"

    def test_empty_warehouse_id_raises(self) -> None:
        """Test empty warehouse_id raises ValueError."""
        with pytest.raises(ValueError, match="warehouse_id must not be empty"):
            WarehouseUserActivityInput(warehouse_id="")


class TestWarehouseChargebackInput:
    """Tests for WarehouseChargebackInput."""

    def test_valid_input(self) -> None:
        """Test valid input is accepted."""
        input_model = WarehouseChargebackInput(
            warehouse_id="abc123",
            cost_per_dbu=0.25,
        )
        assert input_model.warehouse_id == "abc123"
        assert input_model.cost_per_dbu == 0.25

    def test_zero_cost_raises(self) -> None:
        """Test zero cost raises ValueError."""
        with pytest.raises(ValueError, match="cost_per_dbu must be positive"):
            WarehouseChargebackInput(warehouse_id="abc123", cost_per_dbu=0)

    def test_negative_cost_raises(self) -> None:
        """Test negative cost raises ValueError."""
        with pytest.raises(ValueError, match="cost_per_dbu must be positive"):
            WarehouseChargebackInput(warehouse_id="abc123", cost_per_dbu=-0.1)


class TestPortfolioChargebackInput:
    """Tests for PortfolioChargebackInput."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        input_model = PortfolioChargebackInput()
        assert input_model.window_days == 7
        assert input_model.cost_per_dbu == 0.22
        assert input_model.allocation_method == "runtime"

    def test_zero_cost_raises(self) -> None:
        """Test zero cost raises ValueError."""
        with pytest.raises(ValueError, match="cost_per_dbu must be positive"):
            PortfolioChargebackInput(cost_per_dbu=0)


class TestWarehouseTopologyInput:
    """Tests for WarehouseTopologyInput."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        input_model = WarehouseTopologyInput()
        assert input_model.similarity_threshold == 0.7
        assert input_model.min_cluster_size == 2

    def test_threshold_too_low_raises(self) -> None:
        """Test threshold below 0 raises ValueError."""
        with pytest.raises(ValueError, match="similarity_threshold must be between"):
            WarehouseTopologyInput(similarity_threshold=-0.1)

    def test_threshold_too_high_raises(self) -> None:
        """Test threshold above 1 raises ValueError."""
        with pytest.raises(ValueError, match="similarity_threshold must be between"):
            WarehouseTopologyInput(similarity_threshold=1.5)

    def test_cluster_size_too_small_raises(self) -> None:
        """Test cluster size below 2 raises ValueError."""
        with pytest.raises(ValueError, match="min_cluster_size must be at least 2"):
            WarehouseTopologyInput(min_cluster_size=1)
