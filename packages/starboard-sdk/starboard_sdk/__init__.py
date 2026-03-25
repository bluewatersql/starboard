"""Starboard SDK — Python client for multi-turn Starboard AI Agent sessions.

Provides ``StarboardClient`` and ``ConversationSession`` for notebooks and
programmatic access with full multi-turn conversation support.

Example (Databricks notebook)::

    from starboard_sdk import StarboardClient

    client = await StarboardClient.from_env()
    session = await client.create_session(name="etl-tuning")

    r1 = await session.ask("Help me tune query 1111-2222-3333-4444")
    print(r1.report)

    r2 = await session.ask("Would liquid clustering help?")
    print(r2.report)
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("starboard-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0"

from starboard_core.domain.models.llm import OptimizationMode

from starboard_sdk.client import ConversationSession, StarboardClient
from starboard_sdk.exceptions import (
    AuthenticationError,
    ConnectionError,
    SessionError,
    StarboardError,
    TimeoutError,
)
from starboard_sdk.models import AgentResponse

__all__ = [
    "AgentResponse",
    "AuthenticationError",
    "ConnectionError",
    "ConversationSession",
    "OptimizationMode",
    "SessionError",
    "StarboardClient",
    "StarboardError",
    "TimeoutError",
    "__version__",
]
