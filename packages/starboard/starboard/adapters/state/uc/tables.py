# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog table definitions for native agent state (Phase 2 C2).

Registers the Delta ``TableDef``\\s that back the UC-native state/memory/user/
feedback stores. Modeled on :mod:`starboard.infra.storage.warehouse_tables`:
JSON blobs are stored as ``STRING`` (Delta has no native JSON type), tables are
partitioned by ``user_id`` where present, and ``delta.autoOptimize.optimizeWrite``
is enabled so the low-write governed state stays compact.

Per D-2.6 the memory tables are **recency-only** — ``memory_episodes`` carries no
embedding/vector column; semantic recall stays behind ``[vectorsearch]``.
"""

from __future__ import annotations

from starboard.infra.storage.table_registry import (
    ColumnDef,
    TableDef,
    TableRegistry,
)

# Table identifiers (registry keys) used by the UC state adapters.
CONVERSATIONS = "conversations"
USERS = "users"
USER_FEEDBACK = "user_feedback"
MEMORY_EPISODES = "memory_episodes"
MEMORY_FACTS = "memory_facts"
USER_PROFILES = "user_profiles"

_OPTIMIZE = {"delta.autoOptimize.optimizeWrite": "true"}


def register_state_tables(registry: TableRegistry) -> None:
    """Register all UC-native state tables into ``registry``.

    Args:
        registry: Table registry to populate.
    """
    # Conversation snapshots (periodic, low-write — D-2.6).
    registry.register(
        TableDef(
            table_id=CONVERSATIONS,
            table_name="conversations",
            columns=(
                ColumnDef("conversation_id", "STRING", nullable=False),
                ColumnDef("user_id", "STRING", nullable=False),
                ColumnDef("messages", "STRING", comment="JSON array of messages"),
                ColumnDef("metadata", "STRING", comment="JSON object"),
                ColumnDef("title", "STRING"),
                ColumnDef("tags", "STRING", comment="JSON array of tags"),
                ColumnDef("archived", "BOOLEAN"),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
                ColumnDef("updated_at", "TIMESTAMP", nullable=False),
            ),
            primary_key=("conversation_id",),
            partition_by=("user_id",),
            comment="Agent conversation snapshots",
            properties=dict(_OPTIMIZE),
        )
    )

    # Users (auth identities).
    registry.register(
        TableDef(
            table_id=USERS,
            table_name="users",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("external_id", "STRING", nullable=False),
                ColumnDef("provider", "STRING", nullable=False),
                ColumnDef("username", "STRING", nullable=False),
                ColumnDef("display_name", "STRING"),
                ColumnDef("status", "STRING", nullable=False),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
                ColumnDef("last_login", "TIMESTAMP"),
                ColumnDef("login_count", "BIGINT"),
                ColumnDef("metadata", "STRING", comment="JSON object"),
            ),
            primary_key=("id",),
            comment="Authenticated user identities",
            properties=dict(_OPTIMIZE),
        )
    )

    # User feedback on agent responses.
    registry.register(
        TableDef(
            table_id=USER_FEEDBACK,
            table_name="user_feedback",
            columns=(
                ColumnDef("feedback_id", "STRING", nullable=False),
                ColumnDef("conversation_id", "STRING", nullable=False),
                ColumnDef("message_id", "STRING", nullable=False),
                ColumnDef("user_id", "STRING", nullable=False),
                ColumnDef("agent_name", "STRING", nullable=False),
                ColumnDef("rating", "STRING", nullable=False),
                ColumnDef("categories", "STRING", comment="JSON array"),
                ColumnDef("comment", "STRING"),
                ColumnDef("context_snapshot", "STRING", comment="JSON object"),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
            ),
            primary_key=("feedback_id",),
            partition_by=("user_id",),
            comment="User feedback on agent responses",
            properties=dict(_OPTIMIZE),
        )
    )

    # Episodic memory (recency-only — NO embedding/vector column, D-2.6).
    registry.register(
        TableDef(
            table_id=MEMORY_EPISODES,
            table_name="memory_episodes",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("user_id", "STRING", nullable=False),
                ColumnDef("conversation_id", "STRING"),
                ColumnDef("summary", "STRING", nullable=False),
                ColumnDef("key_points", "STRING", comment="JSON array"),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
                ColumnDef("metadata", "STRING", comment="JSON object"),
            ),
            primary_key=("id",),
            partition_by=("user_id",),
            comment="Episodic memory (recency-only, no vectors)",
            properties=dict(_OPTIMIZE),
        )
    )

    # Semantic memory (extracted facts).
    registry.register(
        TableDef(
            table_id=MEMORY_FACTS,
            table_name="memory_facts",
            columns=(
                ColumnDef("id", "STRING", nullable=False),
                ColumnDef("user_id", "STRING", nullable=False),
                ColumnDef("statement", "STRING", nullable=False),
                ColumnDef("category", "STRING", nullable=False),
                ColumnDef("confidence", "DOUBLE"),
                ColumnDef("source", "STRING"),
                ColumnDef("verified", "BOOLEAN"),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
                ColumnDef("updated_at", "TIMESTAMP", nullable=False),
                ColumnDef("metadata", "STRING", comment="JSON object"),
            ),
            primary_key=("id",),
            partition_by=("user_id",),
            comment="Semantic memory facts",
            properties=dict(_OPTIMIZE),
        )
    )

    # User profiles (cross-session preferences).
    registry.register(
        TableDef(
            table_id=USER_PROFILES,
            table_name="user_profiles",
            columns=(
                ColumnDef("user_id", "STRING", nullable=False),
                ColumnDef("job_preferences", "STRING", comment="JSON object"),
                ColumnDef("technical_context", "STRING", comment="JSON object"),
                ColumnDef(
                    "communication_preferences", "STRING", comment="JSON object"
                ),
                ColumnDef("custom_fields", "STRING", comment="JSON object"),
                ColumnDef("created_at", "TIMESTAMP", nullable=False),
                ColumnDef("updated_at", "TIMESTAMP", nullable=False),
            ),
            primary_key=("user_id",),
            comment="Cross-session user profiles/preferences",
            properties=dict(_OPTIMIZE),
        )
    )


def build_state_registry() -> TableRegistry:
    """Build a fresh registry populated with the UC state tables."""
    registry = TableRegistry()
    register_state_tables(registry)
    return registry


# Pre-instantiated registry with all UC-native state tables.
UC_STATE_REGISTRY = build_state_registry()
