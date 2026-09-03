# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the D8 internal ``NLQueryPort`` adapter (curated Genie rooms).

Driven by a stub Genie backend (no live internal call). Asserts room selection
from ``WorkspaceCtx.extra`` and that the adapter returns a well-formed
:class:`NLAnswer` (``success`` / ``sql`` / ``explanation``) with the
curated-room provenance added additively in ``metadata``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from starboard_core.ports.nl_query import NLAnswer, WorkspaceCtx
from starboard_internal._config import GenieConfig
from starboard_internal._genie_rooms import CURATED_ROOMS, GenieRoom, select_room
from starboard_internal.curated_genie_adapter import (
    CuratedGenieRoomAdapter,
    _SdkGenieBackend,
    _UnwiredGenieBackend,
)

_ENV_VARS = (
    "STARBOARD_INTERNAL_GENIE_SPACES",
    "STARBOARD_INTERNAL_GENIE_HOST",
    "STARBOARD_INTERNAL_GENIE_TOKEN",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class _StubGenieBackend:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self._result = result
        self.room_key: str | None = None

    async def ask(self, *, room: GenieRoom, question: str) -> Mapping[str, Any]:
        self.room_key = room.key
        return self._result


@pytest.mark.unit
class TestRoomSelection:
    def test_explicit_room_hint_wins(self) -> None:
        assert select_room({"genie_room": "hls_genie"}).key == "hls_genie"

    def test_segment_hint_used(self) -> None:
        assert select_room({"segment": "fins_genie"}).key == "fins_genie"

    def test_unknown_hint_falls_back_to_default(self) -> None:
        assert select_room({"genie_room": "nope"}).key == "global_genie"
        assert select_room(None).key == "global_genie"


@pytest.mark.unit
class TestCuratedGenieRoomAdapter:
    async def test_answer_has_public_fields_and_enrichment(self) -> None:
        backend = _StubGenieBackend(
            {
                "success": True,
                "sql": "SELECT 1",
                "explanation": "ARR trend for Acme",
                "conversation_id": "conv-9",
            }
        )
        adapter = CuratedGenieRoomAdapter(backend)
        answer = await adapter.ask(
            "What is ARR for Acme?",
            WorkspaceCtx(extra={"genie_room": "hls_genie"}),
        )

        assert isinstance(answer, NLAnswer)
        # Public capability whole.
        assert answer.success is True
        assert answer.sql == "SELECT 1"
        assert answer.explanation == "ARR trend for Acme"
        # Additive enrichment / provenance.
        assert answer.metadata["curated"] == "true"
        assert answer.metadata["room"] == "hls_genie"
        assert answer.metadata["room_go_link"] == "go/hls_genie"
        assert answer.metadata["conversation_id"] == "conv-9"
        assert backend.room_key == "hls_genie"

    async def test_answer_field_maps_to_explanation(self) -> None:
        adapter = CuratedGenieRoomAdapter(_StubGenieBackend({"answer": "42 rows"}))
        answer = await adapter.ask("q", WorkspaceCtx())
        assert answer.explanation == "42 rows"
        assert answer.metadata["room"] == "global_genie"

    async def test_default_backend_raises_until_wired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        adapter = CuratedGenieRoomAdapter()
        with pytest.raises(RuntimeError, match="Genie") as exc:
            await adapter.ask("q", WorkspaceCtx())
        assert "STARBOARD_INTERNAL_GENIE_SPACES" in str(exc.value)

    def test_default_backend_is_unwired_when_env_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_env(monkeypatch)
        assert isinstance(CuratedGenieRoomAdapter()._backend, _UnwiredGenieBackend)

    def test_real_backend_selected_when_env_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "STARBOARD_INTERNAL_GENIE_SPACES", '{"global_genie": "01efspace"}'
        )
        assert isinstance(CuratedGenieRoomAdapter()._backend, _SdkGenieBackend)

    async def test_sdk_backend_unmapped_room_raises_actionably(self) -> None:
        backend = _SdkGenieBackend(GenieConfig(spaces={"hls_genie": "01ef"}))
        with pytest.raises(RuntimeError, match="STARBOARD_INTERNAL_GENIE_SPACES"):
            await backend.ask(room=CURATED_ROOMS["global_genie"], question="q")

    async def test_sdk_backend_maps_genie_message(self) -> None:
        class _Query:
            query = "SELECT 1"
            description = "curated answer"

        class _Attachment:
            query = _Query()
            text = None

        class _Message:
            attachments = [_Attachment()]
            error = None
            conversation_id = "conv-1"

        class _Genie:
            def start_conversation_and_wait(self, space_id: str, content: str):
                self.space_id = space_id
                return _Message()

        class _FakeClient:
            genie = _Genie()

        backend = _SdkGenieBackend(GenieConfig(spaces={"global_genie": "01efspace"}))
        backend._client = lambda: _FakeClient()  # type: ignore[method-assign]
        result = await backend.ask(
            room=CURATED_ROOMS["global_genie"], question="What is ARR?"
        )
        assert result["sql"] == "SELECT 1"
        assert result["explanation"] == "curated answer"
        assert result["conversation_id"] == "conv-1"
        assert result["success"] is True
