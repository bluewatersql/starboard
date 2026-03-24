"""
Infrastructure observability.

Provides logging, events, output formatting, and reporting infrastructure.
"""

from starboard_server.infra.observability.context import (
    ObservabilityContext,
    create_observability_context,
)

__all__ = [
    "ObservabilityContext",
    "create_observability_context",
]
