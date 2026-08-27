# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog native state adapters (Phase 2 C2).

Protocol-compliant state/memory/user/feedback stores over the ``UCStorageAdapter``
/ ``UCRepository`` building blocks. Selected by ``database_backend="uc"`` — the
durable, zero-external-DB server backend for low-write governed state (D-2.4).
"""

from starboard.adapters.state.uc.feedback_repository import UCFeedbackRepository
from starboard.adapters.state.uc.memory_store import UCMemoryStore
from starboard.adapters.state.uc.state_store import UCStateStore
from starboard.adapters.state.uc.tables import (
    UC_STATE_REGISTRY,
    build_state_registry,
    register_state_tables,
)
from starboard.adapters.state.uc.user_store import UCUserStore

__all__ = [
    "UC_STATE_REGISTRY",
    "UCFeedbackRepository",
    "UCMemoryStore",
    "UCStateStore",
    "UCUserStore",
    "build_state_registry",
    "register_state_tables",
]
