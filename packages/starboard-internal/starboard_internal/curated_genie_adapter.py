# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``NLQueryPort`` adapter — curated Genie rooms (Phase-3 D8).

On the public path, NL Q&A is delegated to the host's native Genie (there is no
public ``NLQueryPort`` adapter). This gated internal adapter routes the question
to a **curated Genie room** (selected from :mod:`starboard_internal._genie_rooms`)
for a higher-fidelity answer. The returned :class:`NLAnswer` carries the standard
``success`` / ``sql`` / ``explanation`` fields; the room provenance (key, ``go/``
link, conversation id) is added additively in ``metadata`` (UNIFIED_PLAN §3.5).

The zero-arg factory builds the **real** Genie backend (Databricks Genie
Conversation API) when the internal deployment env is present
(:class:`GenieConfig`); when it is absent it builds an *unwired* backend whose
``ask`` raises a clean, actionable :class:`MissingInternalConfigError` (never a
silent stub). Tests inject their own :class:`GenieBackend`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.nl_query import NLAnswer, NLQueryPort, WorkspaceCtx

from starboard_internal._config import (
    GenieConfig,
    MissingInternalConfigError,
    missing_config_message,
)
from starboard_internal._genie_rooms import (
    CURATED_ROOMS,
    DEFAULT_ROOM_KEY,
    GenieRoom,
    select_room,
)

#: Stable backend tag (internal-index-only identifier).
_BACKEND_SOURCE = "genie"


@runtime_checkable
class GenieBackend(Protocol):
    """Curated-Genie-room query backend. Test-injectable."""

    async def ask(self, *, room: GenieRoom, question: str) -> Mapping[str, Any]:
        """Return a mapping with at least ``explanation`` or ``answer``;
        optionally ``success``, ``sql``, ``conversation_id``."""
        ...


class _UnwiredGenieBackend:
    """Backend used when the internal deployment env is absent.

    Not a silent stub: ``ask`` raises with the exact env vars to set.
    """

    async def ask(self, *, room: GenieRoom, question: str) -> Mapping[str, Any]:  # noqa: ARG002
        raise MissingInternalConfigError(
            missing_config_message(
                "CuratedGenieRoomAdapter",
                "Genie",
                GenieConfig.REQUIRED,
                "GenieBackend",
            )
        )


class _SdkGenieBackend:
    """Real backend: routes questions to a curated Genie space via the SDK.

    Resolves the selected room to its Genie space id (from the deployment's
    ``STARBOARD_INTERNAL_GENIE_SPACES`` mapping) and starts a Genie conversation.
    The blocking SDK call runs in a worker thread; the client is created per call.
    """

    def __init__(self, config: GenieConfig) -> None:
        self._config = config

    async def ask(self, *, room: GenieRoom, question: str) -> Mapping[str, Any]:
        space_id = self._config.spaces.get(room.key)
        if not space_id:
            raise MissingInternalConfigError(
                f"CuratedGenieRoomAdapter has no Genie space mapped for room "
                f"{room.key!r}: add it to STARBOARD_INTERNAL_GENIE_SPACES "
                f"(internal deployment env)."
            )
        return await asyncio.to_thread(self._run, space_id, question)

    def _client(self) -> Any:
        from databricks.sdk import WorkspaceClient

        kwargs: dict[str, Any] = {}
        if self._config.host:
            kwargs["host"] = self._config.host
        if self._config.token:
            kwargs["token"] = self._config.token
        return WorkspaceClient(**kwargs)

    def _run(self, space_id: str, question: str) -> Mapping[str, Any]:
        client = self._client()
        message = client.genie.start_conversation_and_wait(space_id, question)
        sql = ""
        explanation = ""
        for attachment in getattr(message, "attachments", None) or []:
            query = getattr(attachment, "query", None)
            if query is not None:
                sql = sql or str(getattr(query, "query", "") or "")
                explanation = explanation or str(
                    getattr(query, "description", "") or ""
                )
            text = getattr(attachment, "text", None)
            if text is not None:
                explanation = explanation or str(getattr(text, "content", "") or "")
        error = getattr(message, "error", None)
        return {
            "success": error is None,
            "sql": sql,
            "explanation": explanation,
            "conversation_id": str(getattr(message, "conversation_id", "") or ""),
        }


def _default_backend() -> GenieBackend:
    """Build the real backend from the internal env, else an unwired backend."""
    config = GenieConfig.from_env()
    if config is None:
        return _UnwiredGenieBackend()
    return _SdkGenieBackend(config)


class CuratedGenieRoomAdapter(NLQueryPort):
    """Answer NL questions by routing to a curated Genie room.

    Args:
        backend: The Genie backend. When omitted, the real Genie backend is built
            from the internal deployment env when present, else an unwired backend
            that raises an actionable error on use.
        rooms: The curated room registry (defaults to :data:`CURATED_ROOMS`).
        default_room_key: Room used when the caller supplies no known hint.
    """

    def __init__(
        self,
        backend: GenieBackend | None = None,
        *,
        rooms: Mapping[str, GenieRoom] = CURATED_ROOMS,
        default_room_key: str = DEFAULT_ROOM_KEY,
    ) -> None:
        self._backend: GenieBackend = backend or _default_backend()
        self._rooms = rooms
        self._default_room_key = default_room_key

    async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer:
        room = select_room(
            ctx.extra, rooms=self._rooms, default_key=self._default_room_key
        )
        result = await self._backend.ask(room=room, question=question)
        explanation = str(result.get("explanation", result.get("answer", "")))
        metadata: dict[str, Any] = {
            # --- additive enrichment (superset) ---
            "backend": _BACKEND_SOURCE,
            "curated": "true",
            "room": room.key,
            "room_go_link": room.go_link,
            "conversation_id": str(result.get("conversation_id", "")),
        }
        return NLAnswer(
            success=bool(result.get("success", True)),
            sql=str(result.get("sql", "")),
            explanation=explanation,
            metadata=metadata,
        )
