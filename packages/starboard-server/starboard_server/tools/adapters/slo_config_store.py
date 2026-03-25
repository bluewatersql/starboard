"""In-memory SLO configuration store.

Provides ephemeral storage for SLO configurations with sensible defaults.
Configuration is not persisted across restarts - this is acceptable
until usage data justifies implementing persistent storage.

Future implementations:
- UCTableSLOConfigStore: Persist to Unity Catalog Delta tables
- RedisSLOConfigStore: Persist to Redis for distributed access
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from starboard_core.domain.models.warehouse import (
    DEFAULT_BATCH_SLOS,
    DEFAULT_INTERACTIVE_SLOS,
    SLOConfig,
    SLOTarget,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class InMemorySLOConfigStore:
    """In-memory SLO configuration storage.

    Provides ephemeral storage for warehouse SLO configurations.
    Supports default profiles (interactive, batch) and custom configurations.

    Thread-safe for concurrent access within a single process.

    Example:
        >>> store = InMemorySLOConfigStore()
        >>> config = await store.get_slo_config("warehouse-123")
        >>> if config is None:
        ...     config = store.create_default_config("warehouse-123", "interactive")
        ...     await store.save_slo_config(config)
    """

    def __init__(self) -> None:
        """Initialize in-memory store."""
        self._configs: dict[str, SLOConfig] = {}
        logger.debug("slo_config_store_initialized", extra={"type": "in_memory"})

    async def get_slo_config(self, warehouse_id: str) -> SLOConfig | None:
        """Get SLO configuration for a warehouse.

        Args:
            warehouse_id: Warehouse identifier.

        Returns:
            SLOConfig if found, None otherwise.
        """
        config = self._configs.get(warehouse_id)
        if config:
            logger.debug(
                "slo_config_found",
                extra={
                    "warehouse_id": warehouse_id,
                    "target_count": len(config.targets),
                },
            )
        return config

    async def save_slo_config(self, config: SLOConfig) -> None:
        """Save SLO configuration for a warehouse.

        Args:
            config: SLO configuration to save.
        """
        self._configs[config.warehouse_id] = config
        logger.debug(
            "slo_config_saved",
            extra={
                "warehouse_id": config.warehouse_id,
                "target_count": len(config.targets),
            },
        )

    async def delete_slo_config(self, warehouse_id: str) -> bool:
        """Delete SLO configuration for a warehouse.

        Args:
            warehouse_id: Warehouse identifier.

        Returns:
            True if config was deleted, False if not found.
        """
        if warehouse_id in self._configs:
            del self._configs[warehouse_id]
            logger.debug(
                "slo_config_deleted",
                extra={"warehouse_id": warehouse_id},
            )
            return True
        return False

    async def list_configs(self) -> list[SLOConfig]:
        """List all stored SLO configurations.

        Returns:
            List of all stored configurations.
        """
        return list(self._configs.values())

    def create_default_config(
        self,
        warehouse_id: str,
        profile: Literal["interactive", "batch"] = "interactive",
        created_by: str | None = None,
    ) -> SLOConfig:
        """Create a default SLO configuration for a warehouse.

        Args:
            warehouse_id: Warehouse identifier.
            profile: SLO profile type (interactive or batch).
            created_by: Optional user who created the config.

        Returns:
            New SLOConfig with default targets for the profile.
        """
        now = datetime.now(UTC)
        targets = (
            DEFAULT_INTERACTIVE_SLOS if profile == "interactive" else DEFAULT_BATCH_SLOS
        )

        return SLOConfig(
            warehouse_id=warehouse_id,
            targets=targets,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            notes=f"Default {profile} SLO profile",
        )

    def create_custom_config(
        self,
        warehouse_id: str,
        targets: tuple[SLOTarget, ...],
        created_by: str | None = None,
        notes: str | None = None,
    ) -> SLOConfig:
        """Create a custom SLO configuration.

        Args:
            warehouse_id: Warehouse identifier.
            targets: Custom SLO targets.
            created_by: Optional user who created the config.
            notes: Optional notes about the configuration.

        Returns:
            New SLOConfig with custom targets.
        """
        now = datetime.now(UTC)

        return SLOConfig(
            warehouse_id=warehouse_id,
            targets=targets,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            notes=notes,
        )

    async def get_or_create_default(
        self,
        warehouse_id: str,
        profile: Literal["interactive", "batch"] = "interactive",
    ) -> SLOConfig:
        """Get existing config or create and store a default.

        Convenience method that ensures a config always exists.

        Args:
            warehouse_id: Warehouse identifier.
            profile: Default profile if creating new config.

        Returns:
            Existing or newly created SLOConfig.
        """
        config = await self.get_slo_config(warehouse_id)
        if config is None:
            config = self.create_default_config(warehouse_id, profile)
            await self.save_slo_config(config)
        return config

    async def close(self) -> None:
        """Release resources (no-op for this store)."""

    async def connect(self) -> None:
        """Initialize connection (no-op for this store)."""

    async def delete(self, _key: str) -> bool:
        """Generic key-value delete (Protocol compliance)."""
        return False

    async def get(self, _key: str) -> object | None:
        """Generic key-value get (Protocol compliance)."""
        return None

    async def set(self, _key: str, _value: object) -> None:
        """Generic key-value set (Protocol compliance)."""
