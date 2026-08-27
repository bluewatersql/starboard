# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Gated internal ``NLQueryPort`` adapter — curated Genie rooms (Phase-3 D8).

Where the PUBLIC adapter (``AnalyticsSqlAdapter``) answers NL questions with
native analytics-SQL generation, this internal adapter routes the question to a
**curated Genie room** (selected from :mod:`starboard_internal._genie_rooms`) for
a higher-fidelity answer. It is a strict SUPERSET (UNIFIED_PLAN §3.5): the
returned :class:`NLAnswer` still carries the public ``success`` / ``sql`` /
``explanation`` fields; the room provenance (key, ``go/`` link, conversation id)
is added additively in ``metadata``.

Internal runtime access is not available in this repo; the adapter is driven by
an injected :class:`GenieBackend`. The zero-arg factory builds a default backend
that raises unless real Genie access is wired.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from starboard_core.ports.nl_query import NLAnswer, NLQueryPort, WorkspaceCtx

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


class _DefaultGenieBackend:
    """Placeholder backend: real Genie room access is external to this repo."""

    async def ask(self, *, room: GenieRoom, question: str) -> Mapping[str, Any]:  # noqa: ARG002
        raise RuntimeError(
            "CuratedGenieRoomAdapter requires internal Genie runtime access; "
            "inject a GenieBackend to use this adapter."
        )


class CuratedGenieRoomAdapter(NLQueryPort):
    """Answer NL questions by routing to a curated Genie room.

    Args:
        backend: The Genie backend. When omitted, a default backend is used that
            raises on use (real internal access is wired at deploy time).
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
        self._backend: GenieBackend = backend or _DefaultGenieBackend()
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
