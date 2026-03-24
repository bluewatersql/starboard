"""Starboard SDK — Python client for multi-turn Starboard AI Agent sessions.

Provides ``StarboardClient`` and ``ConversationSession`` for notebooks and
programmatic access with full multi-turn conversation support.

Example (Databricks notebook)::

    from starboard_sdk import StarboardClient

    client = StarboardClient.from_env()
    session = client.create_session(name="etl-tuning")

    r1 = await session.ask("Help me tune query 1111-2222-3333-4444")
    print(r1.report)

    r2 = await session.ask("Would liquid clustering help?")
    print(r2.report)
"""

__version__ = "0.1.0"

from starboard_sdk.client import ConversationSession, StarboardClient
from starboard_sdk.models import AgentResponse

__all__ = [
    "AgentResponse",
    "ConversationSession",
    "StarboardClient",
    "__version__",
]
