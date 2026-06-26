# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for SQLite state management."""

from datetime import UTC, datetime

import pytest
from starboard_core.models.conversation import Conversation, Message
from starboard_core.models.memory import Episode, Fact, SemanticQuery
from starboard_server.adapters.state.sqlite import SQLiteMemoryStore, SQLiteStateStore
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.core.state_factory import (
    create_memory_store,
    create_state_store,
)


@pytest.mark.integration
class TestSQLiteIntegration:
    """Integration tests for SQLite backend."""

    async def test_state_store_full_workflow(self, tmp_path):
        """Test complete workflow with SQLite state store."""
        db_path = str(tmp_path / "integration_state.db")
        store = SQLiteStateStore(db_path)
        await store.connect()

        try:
            # Create conversation
            conv = Conversation(
                id="conv_integration",
                user_id="user_test",
                messages=[
                    Message(
                        role="user",
                        content="How can I optimize my query?",
                        timestamp=datetime.now(UTC),
                    )
                ],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title="Query Optimization",
                tags=["performance"],
                archived=False,
            )

            # Save conversation
            await store.save_conversation(conv)

            # Retrieve and verify
            retrieved = await store.get_conversation("conv_integration")
            assert retrieved is not None
            assert retrieved.id == conv.id

            # Add more messages
            conv.messages.append(
                Message(
                    role="assistant",
                    content="I can help you optimize your query...",
                    timestamp=datetime.now(UTC),
                )
            )
            await store.save_conversation(conv)

            # List conversations
            convs = await store.list_conversations("user_test")
            assert len(convs) == 1

            # Update metadata
            await store.update_metadata(
                "conv_integration", {"tags": ["performance", "completed"]}
            )

            # Archive conversation
            conv.archived = True
            await store.save_conversation(conv)

            # Verify not in active list
            active_convs = await store.list_conversations("user_test")
            assert len(active_convs) == 0

        finally:
            await store.close()

    async def test_memory_store_full_workflow(self, tmp_path):
        """Test complete workflow with SQLite memory store."""
        db_path = str(tmp_path / "integration_memory.db")
        store = SQLiteMemoryStore(db_path)
        await store.connect()

        try:
            user_id = "user_test"

            # Store multiple episodes
            for i in range(5):
                episode = Episode(
                    id=f"ep_{i}",
                    user_id=user_id,
                    conversation_id=f"conv_{i}",
                    summary=f"Optimized query {i}",
                    key_points=[f"Added index {i}", f"Improved performance {i}%"],
                    embedding=[0.1 * i] * 1536,
                    created_at=datetime.now(UTC),
                    metadata={"iteration": i},
                )
                await store.store_episode(episode)

            # Retrieve recent episodes
            recent = await store.get_recent_episodes(user_id, limit=3)
            assert len(recent) == 3

            # Store facts
            categories = ["preference", "skill", "experience"]
            for i, category in enumerate(categories):
                fact = Fact(
                    id=f"fact_{i}",
                    user_id=user_id,
                    statement=f"User has {category}",
                    category=category,
                    confidence=0.8 + (i * 0.05),
                    source=f"conversation:conv_{i}",
                    verified=False,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    metadata={"source_type": "conversation"},
                )
                await store.store_fact(fact)

            # Query facts by category
            query = SemanticQuery(
                text="skill facts",
                categories=["skill"],
                min_confidence=0.7,
                include_unverified=True,
                limit=10,
            )
            facts = await store.query_facts(user_id, query)
            assert len(facts) == 1
            assert facts[0].category == "skill"

            # Update fact
            await store.update_fact("fact_0", {"verified": True, "confidence": 1.0})

            # Query verified facts only
            verified_query = SemanticQuery(
                text="verified facts",
                categories=None,
                min_confidence=0.7,
                include_unverified=False,
                limit=10,
            )
            verified_facts = await store.query_facts(user_id, verified_query)
            assert len(verified_facts) == 1
            assert verified_facts[0].verified is True

            # Manage user profile
            await store.update_profile(user_id, {"role": "data_engineer"})
            profile = await store.get_profile(user_id)
            assert profile.user_id == user_id

        finally:
            await store.close()

    async def test_cross_store_consistency(self, tmp_path):
        """Test consistency across state and memory stores."""
        state_path = str(tmp_path / "state.db")
        memory_path = str(tmp_path / "memory.db")

        state_store = SQLiteStateStore(state_path)
        memory_store = SQLiteMemoryStore(memory_path)

        await state_store.connect()
        await memory_store.connect()

        try:
            user_id = "user_test"
            conv_id = "conv_123"

            # Create conversation in state store
            conv = Conversation(
                id=conv_id,
                user_id=user_id,
                messages=[
                    Message(
                        role="user",
                        content="Optimize query",
                        timestamp=datetime.now(UTC),
                    ),
                    Message(
                        role="assistant",
                        content="Here's how...",
                        timestamp=datetime.now(UTC),
                    ),
                ],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title="Query Optimization",
                tags=[],
                archived=False,
            )
            await state_store.save_conversation(conv)

            # Create episode summary in memory store
            episode = Episode(
                id="ep_123",
                user_id=user_id,
                conversation_id=conv_id,
                summary="User learned to optimize queries with indexes",
                key_points=["Added index", "50% faster"],
                embedding=None,
                created_at=datetime.now(UTC),
                metadata={"conversation_title": conv.title},
            )
            await memory_store.store_episode(episode)

            # Verify both stores
            retrieved_conv = await state_store.get_conversation(conv_id)
            assert retrieved_conv is not None

            episodes = await memory_store.get_recent_episodes(user_id)
            assert len(episodes) == 1
            assert episodes[0].conversation_id == conv_id

        finally:
            await state_store.close()
            await memory_store.close()

    async def test_factory_creates_sqlite_stores(self):
        """Test that factory creates SQLite stores correctly."""
        # Test environment
        config = EnvConfig(
            environment="test",
            database_backend="sqlite",
            offline_mode=True,  # Skip validation for required API keys in tests
        )

        state_store = create_state_store(config)
        memory_store = create_memory_store(config)

        assert isinstance(state_store, SQLiteStateStore)
        assert isinstance(memory_store, SQLiteMemoryStore)

        # Both should use :memory: for test environment
        assert state_store.db_path == ":memory:"
        assert memory_store.db_path == ":memory:"

        # Connect and verify they work
        await state_store.connect()
        await memory_store.connect()

        try:
            # Quick smoke test
            conv = Conversation(
                id="test_conv",
                user_id="test_user",
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title="Test",
                tags=[],
                archived=False,
            )
            await state_store.save_conversation(conv)

            retrieved = await state_store.get_conversation("test_conv")
            assert retrieved is not None

        finally:
            await state_store.close()
            await memory_store.close()

    async def test_concurrent_access(self, tmp_path):
        """Test concurrent access to SQLite stores."""
        import asyncio

        db_path = str(tmp_path / "concurrent.db")
        store = SQLiteStateStore(db_path)
        await store.connect()

        try:

            async def create_conversation(i: int):
                conv = Conversation(
                    id=f"conv_{i}",
                    user_id="user_test",
                    messages=[],
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                    title=f"Conversation {i}",
                    tags=[],
                    archived=False,
                )
                await store.save_conversation(conv)

            # Create 20 conversations concurrently
            await asyncio.gather(*[create_conversation(i) for i in range(20)])

            # Verify all were created
            convs = await store.list_conversations("user_test", limit=50)
            assert len(convs) == 20

        finally:
            await store.close()

    async def test_large_data_volume(self, tmp_path):
        """Test handling large data volumes."""
        db_path = str(tmp_path / "large.db")
        store = SQLiteStateStore(db_path)
        await store.connect()

        try:
            # Create conversation with 1000 messages
            messages = [
                Message(
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"Message {i}" * 10,  # Make messages longer
                    timestamp=datetime.now(UTC),
                )
                for i in range(1000)
            ]

            conv = Conversation(
                id="large_conv",
                user_id="user_test",
                messages=messages,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title="Large Conversation",
                tags=[],
                archived=False,
            )

            await store.save_conversation(conv)

            # Retrieve and verify
            retrieved = await store.get_conversation("large_conv")
            assert retrieved is not None
            assert len(retrieved.messages) == 1000

        finally:
            await store.close()

    async def test_error_handling(self):
        """Test error handling in SQLite stores."""
        store = SQLiteStateStore(":memory:")
        await store.connect()

        try:
            # Test update non-existent conversation
            with pytest.raises(ValueError, match="not found"):
                await store.update_metadata("nonexistent", {"title": "New"})

            # Test get non-existent conversation (should return None, not error)
            result = await store.get_conversation("nonexistent")
            assert result is None

        finally:
            await store.close()

    async def test_database_file_creation(self, tmp_path):
        """Test that database files are created correctly."""
        db_path = str(tmp_path / "subdir" / "test.db")

        # Store should create parent directory
        store = SQLiteStateStore(db_path)
        await store.connect()

        try:
            # Verify file exists
            import os

            assert os.path.exists(db_path)

            # Verify it's a valid SQLite database
            conv = Conversation(
                id="test",
                user_id="user",
                messages=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                title="Test",
                tags=[],
                archived=False,
            )
            await store.save_conversation(conv)

        finally:
            await store.close()
