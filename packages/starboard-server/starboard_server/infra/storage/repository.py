# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Typed repository pattern for UC storage.

This module provides the UCRepository class that wraps UCStorageAdapter
with strongly-typed model conversions.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, TypeVar

from starboard_server.infra.storage.uc_adapter import UCStorageAdapter

T = TypeVar("T")


class UCRepository[T]:
    """Typed repository for a specific model.

    Provides strongly-typed CRUD operations backed by UC storage.
    Supports both dataclass and Pydantic models.

    Example:
        ```python
        @dataclass
        class WarehouseSLOConfig:
            warehouse_id: str
            p95_target: float
            error_rate_threshold: float

        repo = UCRepository(
            storage=adapter,
            table_id="warehouse_slo",
            model_class=WarehouseSLOConfig,
        )

        # Get by primary key
        slo = await repo.get(warehouse_id="wh-123")

        # List with filters
        slos = await repo.list(filters={"p95_target": 15.0})

        # Save (upsert)
        await repo.save(WarehouseSLOConfig("wh-123", 15.0, 0.01))

        # Delete
        await repo.delete(warehouse_id="wh-123")
        ```
    """

    def __init__(
        self,
        storage: UCStorageAdapter,
        table_id: str,
        model_class: type[T],
    ) -> None:
        """Initialize the repository.

        Args:
            storage: UC storage adapter instance.
            table_id: Registered table identifier.
            model_class: Model class for type conversion.
        """
        self.storage = storage
        self.table_id = table_id
        self.model_class = model_class

    async def get(self, **pk_values: Any) -> T | None:
        """Get a model by primary key.

        Args:
            **pk_values: Primary key column values.

        Returns:
            Model instance if found, None otherwise.

        Example:
            ```python
            slo = await repo.get(warehouse_id="wh-123")
            ```
        """
        row = await self.storage.read_one(self.table_id, pk_values)
        if row is None:
            return None
        return self._row_to_model(row)

    async def list(
        self,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[T]:
        """List models with optional filtering.

        Args:
            filters: Column filters for WHERE clause.
            order_by: ORDER BY clause.
            limit: Maximum number of results.

        Returns:
            List of model instances.

        Example:
            ```python
            active_slos = await repo.list(
                filters={"is_active": True},
                order_by="warehouse_id",
                limit=100,
            )
            ```
        """
        rows = await self.storage.read(
            self.table_id,
            filters=filters,
            order_by=order_by,
            limit=limit,
        )
        return [self._row_to_model(row) for row in rows]

    async def save(self, model: T) -> None:
        """Save (upsert) a model.

        Performs an upsert operation - inserts if new, updates if exists.

        Args:
            model: Model instance to save.

        Example:
            ```python
            slo = WarehouseSLOConfig("wh-123", 15.0, 0.01)
            await repo.save(slo)
            ```
        """
        row = self._model_to_row(model)
        await self.storage.upsert(self.table_id, row)

    async def delete(self, **pk_values: Any) -> None:
        """Delete a model by primary key.

        Args:
            **pk_values: Primary key column values.

        Example:
            ```python
            await repo.delete(warehouse_id="wh-123")
            ```
        """
        await self.storage.delete(self.table_id, pk_values)

    def _row_to_model(self, row: dict[str, Any]) -> T:
        """Convert row dict to model instance.

        Supports dataclasses and Pydantic models.

        Args:
            row: Row dictionary from storage.

        Returns:
            Model instance.
        """
        # Handle Pydantic models
        if hasattr(self.model_class, "model_validate"):
            # Pydantic V2 model
            model_validate = self.model_class.model_validate  # type: ignore[attr-defined]
            return model_validate(row)  # type: ignore[no-any-return]

        # Handle dataclasses and regular classes
        return self.model_class(**row)

    def _model_to_row(self, model: T) -> dict[str, Any]:
        """Convert model to row dict.

        Supports dataclasses and Pydantic models.

        Args:
            model: Model instance.

        Returns:
            Row dictionary for storage.
        """
        # Handle dataclasses
        if hasattr(model, "__dataclass_fields__"):
            # Runtime check confirmed this is a dataclass
            return asdict(model)  # type: ignore[call-overload]

        # Handle Pydantic models
        if hasattr(model, "model_dump"):
            model_dump = model.model_dump
            return model_dump()

        # Fallback to vars
        return dict(vars(model))
