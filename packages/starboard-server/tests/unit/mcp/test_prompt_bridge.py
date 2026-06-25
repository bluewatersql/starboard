# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP prompt bridge."""

from unittest.mock import patch

from starboard_server.mcp.agent_bridge import AGENT_DOMAINS
from starboard_server.mcp.prompt_bridge import (
    PROMPT_METADATA,
    build_prompt_messages,
)

_MOCK_TARGET = "starboard_server.prompts.factories.get_system_prompt"


class TestPromptMetadata:
    """Tests for PROMPT_METADATA structure."""

    def test_eight_prompts_registered(self) -> None:
        assert len(PROMPT_METADATA) == 8

    def test_all_domains_have_prompts(self) -> None:
        domains = {p["domain"] for p in PROMPT_METADATA}
        assert domains == set(AGENT_DOMAINS)

    def test_prompt_names_follow_convention(self) -> None:
        for prompt_def in PROMPT_METADATA:
            assert prompt_def["name"].endswith("_agent_prompt")
            domain = prompt_def["domain"]
            assert prompt_def["name"] == f"{domain}_agent_prompt"

    def test_all_prompts_have_descriptions(self) -> None:
        for prompt_def in PROMPT_METADATA:
            assert "description" in prompt_def
            assert len(prompt_def["description"]) > 10

    def test_prompt_metadata_has_required_keys(self) -> None:
        for prompt_def in PROMPT_METADATA:
            assert "name" in prompt_def
            assert "description" in prompt_def
            assert "domain" in prompt_def


class TestBuildPromptMessages:
    """Tests for build_prompt_messages function."""

    @patch(_MOCK_TARGET)
    def test_returns_list_of_messages(self, mock_get: object) -> None:
        mock_get.return_value = "System prompt content"  # type: ignore[attr-defined]
        msgs = build_prompt_messages("query")
        assert isinstance(msgs, list)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    @patch(_MOCK_TARGET)
    def test_includes_system_prompt_content(self, mock_get: object) -> None:
        mock_get.return_value = "You are the query agent."  # type: ignore[attr-defined]
        msgs = build_prompt_messages("query")
        assert "You are the query agent." in msgs[0]["content"]

    @patch(_MOCK_TARGET)
    def test_includes_goal_when_provided(self, mock_get: object) -> None:
        mock_get.return_value = "prompt"  # type: ignore[attr-defined]
        msgs = build_prompt_messages("query", goal="Optimize slow query")
        assert "Optimize slow query" in msgs[0]["content"]

    @patch(_MOCK_TARGET)
    def test_includes_workspace_when_provided(self, mock_get: object) -> None:
        mock_get.return_value = "prompt"  # type: ignore[attr-defined]
        msgs = build_prompt_messages("query", workspace_id="ws-123")
        assert "ws-123" in msgs[0]["content"]

    @patch(_MOCK_TARGET)
    def test_omits_workspace_when_empty(self, mock_get: object) -> None:
        mock_get.return_value = "prompt"  # type: ignore[attr-defined]
        msgs = build_prompt_messages("query")
        assert "workspace" not in msgs[0]["content"].lower().split("system prompt")[0]

    @patch(_MOCK_TARGET)
    def test_passes_domain_to_get_system_prompt(self, mock_get: object) -> None:
        mock_get.return_value = "prompt"  # type: ignore[attr-defined]
        build_prompt_messages("analytics", goal="Cost analysis")
        mock_get.assert_called_once_with(  # type: ignore[attr-defined]
            domain="analytics",
            goal="Cost analysis",
            token_budget=120_000,
            mode="online",
        )

    @patch(_MOCK_TARGET)
    def test_default_goal_when_empty(self, mock_get: object) -> None:
        mock_get.return_value = "prompt"  # type: ignore[attr-defined]
        build_prompt_messages("job")
        call_kwargs = mock_get.call_args[1]  # type: ignore[attr-defined]
        assert call_kwargs["goal"] == "General analysis and optimization"
