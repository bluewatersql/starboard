# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""LLM-related data models and enums."""

from enum import Enum


class OptimizationMode(Enum):
    """Optimization modes for Databricks resource processing.

    Attributes:
        ONLINE: Real-time optimization with live API connections.
        OFFLINE: Batch processing mode using cached or historical data.
        DIAGNOSTIC: Read-only analysis mode for troubleshooting and inspection.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    DIAGNOSTIC = "diagnostic"
