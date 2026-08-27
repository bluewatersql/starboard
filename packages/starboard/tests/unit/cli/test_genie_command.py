# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ``starboard genie ask`` (Phase-3 D8-public) with an injected stub adapter.

A real run builds an ``LLMSQLGenerator`` over a live model client; these tests
inject a fake ``NLQueryPort`` adapter via ``adapter_factory`` so no model is hit.
"""

from __future__ import annotations

from starboard.cli.cli.genie_command import run_genie
from starboard_core.ports.nl_query import NLAnswer, WorkspaceCtx


class _StubAdapter:
    def __init__(self, answer: NLAnswer) -> None:
        self._answer = answer
        self.asked: list[str] = []

    async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer:  # noqa: ARG002
        self.asked.append(question)
        return self._answer


def _factory(answer: NLAnswer):
    stub = _StubAdapter(answer)

    def factory(_config):  # noqa: ANN001
        return stub

    factory.stub = stub  # type: ignore[attr-defined]
    return factory


def test_ask_success_returns_ok(capsys):
    factory = _factory(NLAnswer(success=True, sql="SELECT 1", explanation="trivial"))
    rc = run_genie(["ask", "why is my bill high?", "--json"], adapter_factory=factory)
    assert rc == 0
    out = capsys.readouterr().out
    assert "SELECT 1" in out
    assert '"domain": "genie"' in out or '"domain":"genie"' in out
    assert factory.stub.asked == ["why is my bill high?"]


def test_ask_failure_maps_to_api_exit(capsys):
    factory = _factory(NLAnswer(success=False, sql="", explanation=""))
    rc = run_genie(["ask", "nonsense", "--json"], adapter_factory=factory)
    assert rc == 3  # EXIT_API


def test_empty_question_is_arg_error():
    factory = _factory(NLAnswer(success=True, sql="SELECT 1"))
    rc = run_genie(["ask", "   "], adapter_factory=factory)
    assert rc == 4  # EXIT_ARG


def test_missing_subcommand_is_arg_error():
    rc = run_genie([], adapter_factory=_factory(NLAnswer(success=True)))
    assert rc == 4  # EXIT_ARG


def test_adapter_build_failure_maps_to_exit_code(capsys):
    def boom(_config):  # noqa: ANN001
        raise RuntimeError("default auth credentials not found")

    rc = run_genie(["ask", "q", "--json"], adapter_factory=boom)
    assert rc == 1  # EXIT_AUTH (message mentions credentials)
