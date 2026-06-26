# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Backward-compatible shim for the streaming-event converter.

The implementation moved to the adapters layer
(``starboard_server.adapters.conversation.event_converter``) to preserve the
clean-architecture dependency direction (domain no longer depends on api). This
module re-exports the public symbols so existing
``from starboard_server.api.event_converter import ...`` callers keep working.
"""

# ruff: noqa: F401 — re-exports
from starboard_server.adapters.conversation.event_converter import (
    EVENT_TYPE_MAPPING,
    convert_streaming_event_to_chat_event,
    validate_event_coverage,
)

__all__ = [
    "EVENT_TYPE_MAPPING",
    "convert_streaming_event_to_chat_event",
    "validate_event_coverage",
]
