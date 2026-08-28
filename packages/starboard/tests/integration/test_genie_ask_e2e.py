# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""DOC-2: exercise `starboard genie ask` end-to-end with a deterministic fake adapter.

Drives the full `run_genie` flow — parse → resolve config → adapter → JSON envelope →
exit code — without a live LLM or workspace, by injecting a fake `NLQueryPort` through the
`adapter_factory` seam. Pins the Phase-0 exit-code contract
(``0 ok · 1 auth · 3 api-error · 4 arg-error``) and the ``{ok, domain, command, data|error, meta}``
envelope shape. The intentional argparse ``--help`` → exit 4 quirk is also pinned.
"""

from __future__ import annotations

import json
from typing import Any

from starboard.cli.cli.genie_command import run_genie
from starboard_x.contract import EXIT_API, EXIT_ARG, EXIT_AUTH, EXIT_OK


class _FakeAnswer:
    def __init__(
        self,
        sql: str | None,
        explanation: str,
        *,
        success: bool = True,
        metadata: dict | None = None,
    ) -> None:
        self.sql = sql
        self.explanation = explanation
        self.success = success
        self.metadata = metadata or {}


class _FakeAdapter:
    def __init__(self, *, answer: _FakeAnswer | None = None, ask_exc: Exception | None = None) -> None:
        self._answer = answer
        self._ask_exc = ask_exc

    async def ask(self, question: str, ctx: Any) -> _FakeAnswer:  # noqa: ARG002 - port signature
        if self._ask_exc is not None:
            raise self._ask_exc
        assert self._answer is not None
        return self._answer


def _factory(
    *,
    answer: _FakeAnswer | None = None,
    build_exc: Exception | None = None,
    ask_exc: Exception | None = None,
):
    def make(_config: Any) -> _FakeAdapter:
        if build_exc is not None:
            raise build_exc
        return _FakeAdapter(answer=answer, ask_exc=ask_exc)

    return make


def _envelope(capsys) -> dict:
    out = capsys.readouterr().out
    return json.loads(out)


def test_success_json_envelope(capsys) -> None:
    answer = _FakeAnswer("SELECT 1", "Trivial probe query.", success=True, metadata={"model": "fake"})
    code = run_genie(["ask", "count rows", "--json"], adapter_factory=_factory(answer=answer))
    assert code == EXIT_OK
    env = _envelope(capsys)
    assert env["ok"] is True
    assert env["domain"] == "genie"
    assert env["command"] == "ask"
    assert env["data"]["sql"] == "SELECT 1"
    assert env["data"]["explanation"] == "Trivial probe query."
    assert "meta" in env


def test_success_text_output(capsys) -> None:
    answer = _FakeAnswer("SELECT count(*) FROM t", "Counts rows.", success=True)
    code = run_genie(["ask", "count rows"], adapter_factory=_factory(answer=answer))
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "SELECT count(*) FROM t" in out


def test_empty_question_is_arg_error() -> None:
    # No adapter should be built for a blank question.
    code = run_genie(["ask", "   ", "--json"], adapter_factory=_factory(answer=_FakeAnswer("x", "y")))
    assert code == EXIT_ARG


def test_auth_failure_maps_to_exit_auth(capsys) -> None:
    code = run_genie(
        ["ask", "q", "--json"],
        adapter_factory=_factory(build_exc=RuntimeError("default auth credentials not found")),
    )
    assert code == EXIT_AUTH
    env = _envelope(capsys)
    assert env["ok"] is False
    assert "error" in env


def test_adapter_build_error_maps_to_exit_api() -> None:
    code = run_genie(
        ["ask", "q"],
        adapter_factory=_factory(build_exc=RuntimeError("gateway exploded")),
    )
    assert code == EXIT_API


def test_ask_exception_maps_to_exit_api() -> None:
    code = run_genie(
        ["ask", "q"],
        adapter_factory=_factory(ask_exc=RuntimeError("model timeout")),
    )
    assert code == EXIT_API


def test_unsuccessful_answer_maps_to_exit_api() -> None:
    answer = _FakeAnswer(None, "no SQL", success=False)
    code = run_genie(["ask", "q"], adapter_factory=_factory(answer=answer))
    assert code == EXIT_API


def test_help_exits_arg_code() -> None:
    # Intentional quirk: argparse --help raises SystemExit, mapped to EXIT_ARG (not a bug).
    assert run_genie(["ask", "--help"]) == EXIT_ARG
