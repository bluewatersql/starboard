# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Starboard SDK — Python client for multi-turn Starboard AI Agent sessions.

Provides ``StarboardClient`` and ``ConversationSession`` for notebooks and
programmatic access with full multi-turn conversation support.

Example (Databricks notebook)::

    from starboard.sdk import StarboardClient

    client = await StarboardClient.from_env()
    session = await client.create_session(name="etl-tuning")

    r1 = await session.ask("Help me tune query 1111-2222-3333-4444")
    print(r1.report)

    r2 = await session.ask("Would liquid clustering help?")
    print(r2.report)
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("starboard")
except PackageNotFoundError:
    __version__ = "0.0.0"

from starboard_core.domain.models.llm import OptimizationMode

from starboard.sdk.client import ConversationSession, StarboardClient
from starboard.sdk.event_types import (
    AgentEvent,
    ErrorEvent,
    FinalOutputEvent,
    StreamingEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from starboard.sdk.exceptions import (
    AgentError,
    AuthenticationError,
    ConfigError,
    ConnectionError,
    DiscoveryError,
    SessionError,
    StarboardError,
    TimeoutError,
)
from starboard.sdk.models import AgentResponse, RawAgentOutput

__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentResponse",
    "AuthenticationError",
    "ConfigError",
    "ConnectionError",
    "ConversationSession",
    "DiscoveryError",
    "ErrorEvent",
    "FinalOutputEvent",
    "OptimizationMode",
    "RawAgentOutput",
    "SessionError",
    "StarboardClient",
    "StarboardError",
    "StreamingEvent",
    "TimeoutError",
    "ToolEndEvent",
    "ToolStartEvent",
    "__version__",
]
