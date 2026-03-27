"""Async tests for CLI main module.

Tests cover:
- async_main entry point
- handle_streaming_events
- create_agent_manager
"""

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from starboard_cli.cli.main import (
    async_main,
    create_agent_manager,
    handle_streaming_events,
)


@pytest.fixture
def mock_config():
    """Create a mock EnvConfig."""
    config = MagicMock()
    config.databricks_host = "https://test.databricks.com"
    config.databricks_token = "test_token"
    config.llm_api_key = "test_key_valid_length"
    config.llm_model = "gpt-4o-mini"
    config.llm_max_tokens = 100000
    config.llm_temperature = 0.4
    config.llm_base_url = None
    config.domain_model_overrides = None
    config.domain_temperature_overrides = None
    config.disabled_agent_domains = []
    return config


@pytest.fixture
def mock_args():
    """Create mock CLI args."""
    return argparse.Namespace(
        goal="test goal",
        config=None,
        databricks_host=None,
        databricks_token=None,
        llm_model=None,
        llm_api_key=None,
        llm_base_url=None,
        llm_temperature=None,
        llm_max_tokens=None,
        input_file=None,
        output_path=None,
        plain=False,
        quiet=False,
        log_level="ERROR",
        log_file=None,
        debug=False,
        mode="online",
        discover=False,
        lookback_days=30,
        discovery_domains=None,
        data_only=False,
    )


class TestCreateAgentManager:
    """Tests for create_agent_manager function."""

    @pytest.mark.asyncio
    async def test_creates_manager_successfully(self, mock_config):
        """Test that create_agent_manager creates a manager with all dependencies."""
        with (
            patch("starboard_cli.cli.main.create_llm_client") as mock_create_llm,
            patch("starboard_cli.cli.main.AsyncDatabricksClient") as mock_api_class,
            patch("starboard_cli.cli.main.SharedContextProvider"),
            patch("starboard_cli.cli.main.create_tool_registry") as mock_tools,
            patch("starboard_cli.cli.main.IntentRouter"),
            patch("starboard_cli.cli.main.AgentFactory"),
            patch("starboard_cli.cli.main.InMemoryConversationStateManager"),
            patch(
                "starboard_cli.cli.main.MultiAgentConversationManager"
            ) as mock_manager_class,
        ):
            mock_llm_client = MagicMock()
            mock_create_llm.return_value = mock_llm_client
            mock_api = MagicMock()
            mock_api._initialize = AsyncMock()
            mock_api_class.return_value = mock_api
            mock_tools.return_value = (MagicMock(), MagicMock())
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager

            result = await create_agent_manager(mock_config)

            manager, api_client, _vector_store = result
            assert manager is mock_manager
            assert api_client is mock_api
            mock_create_llm.assert_called_once_with(cfg=mock_config)
            mock_api_class.assert_called_once_with(cfg=mock_config)
            mock_manager_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_correct_config_to_agent_factory(self, mock_config):
        """Test that AgentConfig is created with correct parameters."""
        with (
            patch("starboard_cli.cli.main.create_llm_client") as mock_create_llm,
            patch("starboard_cli.cli.main.AsyncDatabricksClient") as mock_api_class,
            patch("starboard_cli.cli.main.SharedContextProvider"),
            patch("starboard_cli.cli.main.create_tool_registry") as mock_tools,
            patch("starboard_cli.cli.main.IntentRouter"),
            patch("starboard_cli.cli.main.AgentFactory") as mock_factory,
            patch("starboard_cli.cli.main.InMemoryConversationStateManager"),
            patch("starboard_cli.cli.main.MultiAgentConversationManager"),
        ):
            mock_llm_client = MagicMock()
            mock_create_llm.return_value = mock_llm_client
            mock_api = MagicMock()
            mock_api._initialize = AsyncMock()
            mock_api_class.return_value = mock_api
            mock_tools.return_value = (MagicMock(), MagicMock())

            await create_agent_manager(mock_config)

            # Verify AgentFactory was called with base_config
            factory_call = mock_factory.call_args
            assert "base_config" in factory_call.kwargs
            base_config = factory_call.kwargs["base_config"]
            assert base_config.model == "gpt-4o-mini"
            assert base_config.max_tokens == 100000
            assert base_config.temperature == 0.4


class TestHandleStreamingEvents:
    """Tests for handle_streaming_events function."""

    @pytest.mark.asyncio
    async def test_returns_final_output(self):
        """Test that final output is captured and returned."""
        from starboard_server.agents.events import FinalOutputEvent

        mock_manager = AsyncMock()
        mock_output = MagicMock()
        mock_output.to_dict.return_value = {"summary": "test summary"}

        async def mock_stream(*args, **kwargs):
            yield FinalOutputEvent(output=mock_output)

        mock_manager.handle_message_stream = mock_stream
        console = Console(quiet=True)

        final_output, _ = await handle_streaming_events(
            manager=mock_manager,
            conversation_id="test_conv",
            user_message="test message",
            mode=MagicMock(),
            console=console,
            plain=False,
            quiet=True,
        )

        assert final_output == {"summary": "test summary"}

    @pytest.mark.asyncio
    async def test_tracks_tool_calls(self):
        """Test that tool calls are tracked."""
        from starboard_server.agents.events import (
            FinalOutputEvent,
            ToolEndEvent,
            ToolStartEvent,
        )

        mock_manager = AsyncMock()
        mock_output = MagicMock()
        mock_output.to_dict.return_value = {"tools_used": ["tool1"]}

        async def mock_stream(*args, **kwargs):
            yield ToolStartEvent(
                step=1,
                tool_name="tool1",
                friendly_name="Tool 1",
                tool_call_id="call_123",
                args={},
            )
            yield ToolEndEvent(
                step=1,
                tool_name="tool1",
                friendly_name="Tool 1",
                tool_call_id="call_123",
                success=True,
                duration_seconds=1.0,
            )
            yield FinalOutputEvent(output=mock_output)

        mock_manager.handle_message_stream = mock_stream
        console = Console(quiet=True)

        final_output, _ = await handle_streaming_events(
            manager=mock_manager,
            conversation_id="test_conv",
            user_message="test message",
            mode=MagicMock(),
            console=console,
            plain=True,
            quiet=False,
        )

        assert final_output is not None

    @pytest.mark.asyncio
    async def test_raises_on_error_event(self):
        """Test that ErrorEvent raises RuntimeError."""
        from starboard_server.agents.events import ErrorEvent

        mock_manager = AsyncMock()

        async def mock_stream(*args, **kwargs):
            yield ErrorEvent(
                step=1,
                error_type="TestError",
                error="Test error message",
                recoverable=False,
            )

        mock_manager.handle_message_stream = mock_stream
        console = Console(quiet=True)

        with pytest.raises(RuntimeError, match="Agent error: TestError"):
            await handle_streaming_events(
                manager=mock_manager,
                conversation_id="test_conv",
                user_message="test message",
                mode=MagicMock(),
                console=console,
                plain=False,
                quiet=True,
            )

    @pytest.mark.asyncio
    async def test_handles_keyboard_interrupt(self):
        """Test that KeyboardInterrupt is re-raised."""
        mock_manager = AsyncMock()

        async def mock_stream(*args, **kwargs):
            raise KeyboardInterrupt()
            yield  # Make it a generator

        mock_manager.handle_message_stream = mock_stream
        console = Console(quiet=True)

        with pytest.raises(KeyboardInterrupt):
            await handle_streaming_events(
                manager=mock_manager,
                conversation_id="test_conv",
                user_message="test message",
                mode=MagicMock(),
                console=console,
                plain=False,
                quiet=False,
            )

    @pytest.mark.asyncio
    async def test_generates_formatted_markdown(self):
        """Test that formatted markdown is generated from complete_report."""
        from starboard_server.agents.events import FinalOutputEvent

        mock_manager = AsyncMock()
        mock_output = MagicMock()
        mock_output.to_dict.return_value = {
            "complete_report": {"summary": "test"},
        }

        async def mock_stream(*args, **kwargs):
            yield FinalOutputEvent(output=mock_output)

        mock_manager.handle_message_stream = mock_stream
        console = Console(quiet=True)

        with patch("starboard_server.bootstrap.format_agent_report") as mock_format:
            mock_format.return_value = "# Formatted Report"

            _, formatted_markdown = await handle_streaming_events(
                manager=mock_manager,
                conversation_id="test_conv",
                user_message="test message",
                mode=MagicMock(),
                console=console,
                plain=False,
                quiet=True,
            )

            assert formatted_markdown == "# Formatted Report"


class TestAsyncMain:
    """Tests for async_main entry point."""

    @pytest.mark.asyncio
    async def test_exits_on_missing_databricks_credentials(self, mock_args):
        """Test that missing Databricks credentials cause exit."""
        mock_args.goal = "test goal"

        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
        ):
            mock_config = MagicMock()
            mock_config.databricks_host = None
            mock_config.databricks_token = None
            mock_config.llm_api_key = "test_key_valid_length"
            mock_get_config.return_value = mock_config

            with pytest.raises(SystemExit) as exc_info:
                await async_main(mock_args)

            assert exc_info.value.code in (1, 3, 4)  # GENERAL, CONFIG, or AUTH error

    @pytest.mark.asyncio
    async def test_exits_on_missing_goal(self, mock_args, mock_config):
        """Test that missing goal causes exit."""
        mock_args.goal = None

        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
            patch("starboard_cli.cli.main.merge_env_config") as mock_merge,
        ):
            mock_get_config.return_value = mock_config
            mock_merge.return_value = mock_config

            with pytest.raises(SystemExit) as exc_info:
                await async_main(mock_args)

            assert exc_info.value.code in (1, 3)  # GENERAL or CONFIG error

    @pytest.mark.asyncio
    async def test_exits_on_input_file_not_found(self, mock_args, mock_config):
        """Test that non-existent input file causes exit."""
        mock_args.input_file = "/nonexistent/file.txt"

        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
            patch("starboard_cli.cli.main.merge_env_config") as mock_merge,
        ):
            mock_get_config.return_value = mock_config
            mock_merge.return_value = mock_config

            with pytest.raises(SystemExit) as exc_info:
                await async_main(mock_args)

            assert exc_info.value.code in (1, 3)  # GENERAL or CONFIG error

    @pytest.mark.asyncio
    async def test_loads_config_file_when_provided(
        self, mock_args, mock_config, tmp_path
    ):
        """Test that config file is loaded when --config is provided."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("databricks:\n  host: https://test.databricks.com")
        mock_args.config = str(config_file)

        # Mock create_agent_manager to raise so we don't try real initialization
        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
            patch("starboard_cli.cli.main.load_config_file") as mock_load_config,
            patch("starboard_cli.cli.main.merge_env_config") as mock_merge,
            patch(
                "starboard_cli.cli.main.create_agent_manager",
                side_effect=Exception("stop here"),
            ),
        ):
            mock_get_config.return_value = mock_config
            mock_load_config.return_value = {"databricks": {"host": "test"}}
            mock_merge.return_value = mock_config

            with pytest.raises(SystemExit):
                await async_main(mock_args)

            mock_load_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_execution(self, mock_args, mock_config):
        """Test successful execution path."""
        from starboard_server.agents.events import FinalOutputEvent

        mock_manager = AsyncMock()
        mock_output = MagicMock()
        mock_output.to_dict.return_value = {
            "summary": "test",
            "steps_taken": 1,
            "tools_used": [],
            "tokens_used": 100,
            "cost_usd": 0.01,
            "duration_seconds": 1.0,
        }

        async def mock_stream(*args, **kwargs):
            yield FinalOutputEvent(output=mock_output)

        mock_manager.handle_message_stream = mock_stream

        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
            patch("starboard_cli.cli.main.merge_env_config") as mock_merge,
            patch(
                "starboard_cli.cli.main.create_agent_manager",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_get_config.return_value = mock_config
            mock_merge.return_value = mock_config
            mock_create.return_value = (mock_manager, MagicMock(), None)

            # Should complete without raising
            await async_main(mock_args)

    @pytest.mark.asyncio
    async def test_handles_analysis_failure(self, mock_args, mock_config):
        """Test that analysis failure causes exit."""
        mock_manager = AsyncMock()

        async def mock_stream(*args, **kwargs):
            raise RuntimeError("Analysis failed")
            yield  # Make it a generator

        mock_manager.handle_message_stream = mock_stream

        with (
            patch("starboard_cli.cli.main.load_dotenv"),
            patch("starboard_cli.cli.main.setup_cli_logging"),
            patch("starboard_cli.cli.main.get_config") as mock_get_config,
            patch("starboard_cli.cli.main.merge_env_config") as mock_merge,
            patch(
                "starboard_cli.cli.main.create_agent_manager",
                new_callable=AsyncMock,
            ) as mock_create,
        ):
            mock_get_config.return_value = mock_config
            mock_merge.return_value = mock_config
            mock_create.return_value = (mock_manager, MagicMock(), None)

            with pytest.raises(SystemExit) as exc_info:
                await async_main(mock_args)

            assert exc_info.value.code in (1, 3)  # GENERAL or CONFIG error
