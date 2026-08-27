# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the UC-native state table registry (Phase 2 C2)."""

from __future__ import annotations

from starboard.adapters.state.uc.tables import (
    MEMORY_EPISODES,
    UC_STATE_REGISTRY,
    build_state_registry,
)

EXPECTED_TABLES = {
    "conversations",
    "users",
    "user_feedback",
    "memory_episodes",
    "memory_facts",
    "user_profiles",
}


def test_registers_expected_state_tables() -> None:
    registry = build_state_registry()
    assert set(registry.list_all()) >= EXPECTED_TABLES


def test_memory_episodes_has_no_vector_column() -> None:
    # D-2.6: recency-only, NO embedding/vector column.
    table = UC_STATE_REGISTRY.get(MEMORY_EPISODES)
    assert table is not None
    col_names = {c.name for c in table.columns}
    assert "embedding" not in col_names
    assert "vector" not in col_names


def test_tables_partition_and_optimize() -> None:
    conv = UC_STATE_REGISTRY.get("conversations")
    assert conv is not None
    assert conv.partition_by == ("user_id",)
    assert conv.properties.get("delta.autoOptimize.optimizeWrite") == "true"


def test_ddl_generates_for_all_tables() -> None:
    for table in UC_STATE_REGISTRY.list_all().values():
        ddl = table.to_create_ddl("starboard", "agent_state")
        assert ddl.startswith("CREATE TABLE IF NOT EXISTS")
        assert "starboard.agent_state." in ddl
