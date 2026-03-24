"""
Agent output envelope models.

This module provides standardized models for agent responses:
- AgentResultEnvelope: Wrapper for all domain agent responses
- AgentMetrics: Execution metrics (tokens, cost, duration)
- PartialInfo: Metadata for partial/incomplete responses
- StructuredError: Typed validation/execution errors
- EnvelopeTranslator: Converts AgentOutput to envelope format
- BoundaryValidator: Consolidated validation/repair at agent boundary

Example:
    >>> from starboard_server.agents.output import BoundaryValidator, EnvelopeTranslator
    >>> validator = BoundaryValidator()
    >>> result = validator.validate_and_repair(raw, domain="query")
    >>> if result.is_valid:
    ...     translator = EnvelopeTranslator()
    ...     envelope = translator.translate(output, domain="query", trace_id="abc")
"""

from starboard_server.agents.output.boundary_validator import (
    BoundaryValidator,
    ValidationResult,
)
from starboard_server.agents.output.envelope import (
    ENVELOPE_VERSION,
    AgentMetrics,
    AgentResultEnvelope,
    PartialInfo,
    StructuredError,
)
from starboard_server.agents.output.envelope_translator import EnvelopeTranslator

__all__ = [
    "BoundaryValidator",
    "ENVELOPE_VERSION",
    "AgentMetrics",
    "AgentResultEnvelope",
    "EnvelopeTranslator",
    "PartialInfo",
    "StructuredError",
    "ValidationResult",
]
