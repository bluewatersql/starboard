# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery query packs — declarative collections of system table queries."""

from starboard_server.discovery.query_packs.registry import (
    ALWAYS_RUN_PACKS,
    PRODUCT_TO_DOMAIN_PACKS,
    QueryPackRegistry,
    create_default_registry,
)

__all__ = [
    "ALWAYS_RUN_PACKS",
    "PRODUCT_TO_DOMAIN_PACKS",
    "QueryPackRegistry",
    "create_default_registry",
]
