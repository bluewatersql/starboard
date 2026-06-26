# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for InMemorySLOConfigStore."""

from __future__ import annotations

import pytest
from starboard_core.domain.models.warehouse import (
    DEFAULT_BATCH_SLOS,
    DEFAULT_INTERACTIVE_SLOS,
    SLOTarget,
)
from starboard_server.tools.adapters.slo_config_store import InMemorySLOConfigStore


class TestInMemorySLOConfigStore:
    """Tests for InMemorySLOConfigStore."""

    @pytest.fixture
    def store(self) -> InMemorySLOConfigStore:
        """Create a fresh store for each test."""
        return InMemorySLOConfigStore()

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(
        self, store: InMemorySLOConfigStore
    ) -> None:
        """Test getting a nonexistent config returns None."""
        result = await store.get_slo_config("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_and_get_config(self, store: InMemorySLOConfigStore) -> None:
        """Test saving and retrieving a config."""
        config = store.create_default_config("warehouse-123", "interactive")
        await store.save_slo_config(config)

        result = await store.get_slo_config("warehouse-123")
        assert result is not None
        assert result.warehouse_id == "warehouse-123"
        assert len(result.targets) == len(DEFAULT_INTERACTIVE_SLOS)

    @pytest.mark.asyncio
    async def test_delete_config(self, store: InMemorySLOConfigStore) -> None:
        """Test deleting a config."""
        config = store.create_default_config("warehouse-123", "interactive")
        await store.save_slo_config(config)

        # Verify it exists
        assert await store.get_slo_config("warehouse-123") is not None

        # Delete it
        deleted = await store.delete_slo_config("warehouse-123")
        assert deleted is True

        # Verify it's gone
        assert await store.get_slo_config("warehouse-123") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(
        self, store: InMemorySLOConfigStore
    ) -> None:
        """Test deleting nonexistent config returns False."""
        deleted = await store.delete_slo_config("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_configs_empty(self, store: InMemorySLOConfigStore) -> None:
        """Test listing configs when empty."""
        configs = await store.list_configs()
        assert configs == []

    @pytest.mark.asyncio
    async def test_list_configs_with_data(self, store: InMemorySLOConfigStore) -> None:
        """Test listing configs with data."""
        config1 = store.create_default_config("warehouse-1", "interactive")
        config2 = store.create_default_config("warehouse-2", "batch")
        await store.save_slo_config(config1)
        await store.save_slo_config(config2)

        configs = await store.list_configs()
        assert len(configs) == 2
        ids = {c.warehouse_id for c in configs}
        assert ids == {"warehouse-1", "warehouse-2"}

    def test_create_default_interactive(self, store: InMemorySLOConfigStore) -> None:
        """Test creating default interactive config."""
        config = store.create_default_config("warehouse-123", "interactive")

        assert config.warehouse_id == "warehouse-123"
        assert config.targets == DEFAULT_INTERACTIVE_SLOS
        assert "interactive" in (config.notes or "")

    def test_create_default_batch(self, store: InMemorySLOConfigStore) -> None:
        """Test creating default batch config."""
        config = store.create_default_config("warehouse-123", "batch")

        assert config.warehouse_id == "warehouse-123"
        assert config.targets == DEFAULT_BATCH_SLOS
        assert "batch" in (config.notes or "")

    def test_create_default_with_created_by(
        self, store: InMemorySLOConfigStore
    ) -> None:
        """Test creating config with created_by."""
        config = store.create_default_config(
            "warehouse-123",
            "interactive",
            created_by="test-user",
        )
        assert config.created_by == "test-user"

    def test_create_custom_config(self, store: InMemorySLOConfigStore) -> None:
        """Test creating custom config."""
        custom_targets = (
            SLOTarget(
                slo_type="p95_latency",
                target_value=10.0,
                unit="seconds",
            ),
        )

        config = store.create_custom_config(
            "warehouse-123",
            targets=custom_targets,
            notes="Custom config",
        )

        assert config.warehouse_id == "warehouse-123"
        assert config.targets == custom_targets
        assert config.notes == "Custom config"

    @pytest.mark.asyncio
    async def test_get_or_create_default_creates(
        self, store: InMemorySLOConfigStore
    ) -> None:
        """Test get_or_create_default creates new config."""
        config = await store.get_or_create_default("warehouse-123", "interactive")

        assert config.warehouse_id == "warehouse-123"
        assert config.targets == DEFAULT_INTERACTIVE_SLOS

        # Verify it was saved
        stored = await store.get_slo_config("warehouse-123")
        assert stored is not None
        assert stored.warehouse_id == "warehouse-123"

    @pytest.mark.asyncio
    async def test_get_or_create_default_returns_existing(
        self, store: InMemorySLOConfigStore
    ) -> None:
        """Test get_or_create_default returns existing config."""
        # Create and save a batch config
        original = store.create_default_config("warehouse-123", "batch")
        await store.save_slo_config(original)

        # get_or_create should return existing, not create new
        config = await store.get_or_create_default("warehouse-123", "interactive")

        # Should be the batch config, not interactive
        assert config.targets == DEFAULT_BATCH_SLOS

    @pytest.mark.asyncio
    async def test_overwrite_config(self, store: InMemorySLOConfigStore) -> None:
        """Test saving overwrites existing config."""
        config1 = store.create_default_config("warehouse-123", "interactive")
        await store.save_slo_config(config1)

        config2 = store.create_default_config("warehouse-123", "batch")
        await store.save_slo_config(config2)

        result = await store.get_slo_config("warehouse-123")
        assert result is not None
        assert result.targets == DEFAULT_BATCH_SLOS
