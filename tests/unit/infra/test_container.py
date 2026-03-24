"""Tests for dependency injection container."""

import pytest
from starboard_server.infra.core.config import EnvConfig
from starboard_server.infra.core.container import Container


@pytest.fixture
def dev_config():
    """Create dev configuration."""
    return EnvConfig(environment="dev", offline_mode=True)


@pytest.fixture
def prod_config():
    """Create production configuration."""
    return EnvConfig(
        environment="production",
        database_backend="postgres",
        database_url="postgresql://localhost/test",
        offline_mode=True,
    )


@pytest.mark.asyncio
async def test_container_initialize_dev(dev_config):
    """Should initialize container with in-memory providers for dev."""
    container = Container(dev_config)
    await container.initialize()

    # Should have repositories
    conv_repo = container.conversation_repo
    assert conv_repo is not None

    mem_repo = container.memory_repo
    assert mem_repo is not None

    cache_mgr = container.cache_manager
    assert cache_mgr is not None

    await container.shutdown()


@pytest.mark.asyncio
async def test_container_not_initialized():
    """Should raise error when accessing repos before initialization."""
    container = Container(EnvConfig(offline_mode=True))

    with pytest.raises(RuntimeError, match="not initialized"):
        _ = container.conversation_repo


@pytest.mark.asyncio
async def test_container_config_access(dev_config):
    """Should provide access to configuration."""
    container = Container(dev_config)
    assert container.config == dev_config


@pytest.mark.asyncio
async def test_container_store_access(dev_config):
    """Should provide access to stores."""
    container = Container(dev_config)
    await container.initialize()

    # Should have stores
    state_store = container.state_store
    assert state_store is not None

    memory_store = container.memory_store
    assert memory_store is not None

    cache_store = container.cache_store
    assert cache_store is not None

    await container.shutdown()


@pytest.mark.asyncio
async def test_container_shutdown_without_init():
    """Should handle shutdown gracefully even without initialization."""
    container = Container(EnvConfig(offline_mode=True))
    await container.shutdown()  # Should not raise
