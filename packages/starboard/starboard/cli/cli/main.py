# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Starboard AI Agent - Command-line interface.

Simplified CLI that directly interfaces with the multi-agent conversation manager,
hiding conversation complexity and providing a clean command-line experience.

The CLI maps each invocation to a single conversation turn with the multi-agent system.
"""

import argparse
import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

# Pre-configure structlog to suppress DEBUG/INFO during module imports.
# This prevents module-level initialization in starboard from
# dumping debug logs to the console before CLI args are parsed.
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    cache_logger_on_first_use=False,
)

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.traceback import install as _rich_install  # noqa: E402

# D2: disable locals in Rich tracebacks globally so credential-shaped values
# can never leak into any traceback rendering (Rich hook, IDE, or logger).
_rich_install(show_locals=False)
from starboard_core.domain.models.llm import OptimizationMode  # noqa: E402

from starboard.bootstrap import (  # noqa: E402
    AgentConfig,
    AgentFactory,
    AsyncDatabricksClient,
    EnvConfig,
    # Events
    ErrorEvent,
    FinalOutputEvent,
    InMemoryConversationStateManager,
    IntentRouter,
    MultiAgentConversationManager,
    SharedContextProvider,
    StepCompleteEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserInputRequestEvent,
    create_llm_client,
    create_tool_registry,
    get_config,
)
from starboard.cli.cli.auth_commands import run_auth  # noqa: E402
from starboard.cli.cli.exit_codes import (  # noqa: E402
    AUTH_ERROR,
    CONFIG_ERROR,
    CONNECTION_ERROR,
    GENERAL_ERROR,
    INTERRUPTED,
)
from starboard.cli.sessions.session_manager import SessionManager  # noqa: E402

logger = structlog.get_logger("starboard.cli")


# =============================================================================
# CLI Logging Setup (Separate from Agent Telemetry)
# =============================================================================


def setup_cli_logging(
    log_level: str, log_file: str | None = None, quiet: bool = False
) -> Any:
    """
    Configure logging for CLI context.

    Strategy:
    - Default: Logs go to file or are suppressed (clean console for rich UI)
    - --debug: Logs go to stderr (rich UI still on stdout)
    - --log-file: Logs go to specified file
    - --quiet: Only errors to stderr

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file (optional)
        quiet: If True, suppress all output except errors

    Returns:
        Open log file handle if ``log_file`` was provided (caller must close
        it), otherwise ``None``.
    """
    # Determine log destination
    log_file_handle: Any = None
    if quiet:
        # Only errors to stderr
        log_level = "ERROR"
        log_stream = sys.stderr
    elif log_file:
        # Logs to file — keep handle so caller can close it on exit
        log_file_handle = open(log_file, "a")  # noqa: SIM115
        log_stream = log_file_handle
    elif log_level == "DEBUG":
        # Debug mode: logs to stderr (keeps stdout clean for rich)
        log_stream = sys.stderr
    else:
        # Normal mode: warnings+ to stderr, suppress info/debug
        log_stream = sys.stderr

    numeric_level = getattr(logging, log_level.upper())

    # force=True ensures this takes effect even if server-side imports
    # have already called basicConfig during module loading.
    logging.basicConfig(
        level=numeric_level,
        stream=log_stream,
        format="%(message)s",
        force=True,
    )

    # Configure structlog
    processors = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        (
            structlog.processors.JSONRenderer()
            if log_file
            else structlog.dev.ConsoleRenderer()
        ),
    ]

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_stream),
        cache_logger_on_first_use=False,
    )

    # Suppress noisy third-party loggers regardless of chosen level
    for noisy_logger in (
        "httpx",
        "httpcore",
        "openai",
        "opentelemetry",
        "urllib3",
        "asyncio",
        "databricks.sdk",
        "aiosqlite",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    return log_file_handle


# =============================================================================
# Configuration Loading
# =============================================================================


def load_config_file(config_path: Path) -> dict[str, Any]:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return config or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}") from e


def merge_env_config(
    file_config: dict[str, Any], args: argparse.Namespace
) -> EnvConfig:
    """
    Merge file config with CLI args and environment variables.

    Priority (highest to lowest):
    1. CLI arguments
    2. Config file
    3. Environment variables
    4. Defaults

    Args:
        file_config: Configuration from file
        args: CLI arguments

    Returns:
        EnvConfig instance with merged configuration
    """
    # Start with existing environment config
    base_config = get_config()

    # Build dictionary of overrides
    overrides = {}

    # Override from file config
    if "databricks" in file_config:
        db_config = file_config["databricks"]
        if "host" in db_config:
            overrides["databricks_host"] = db_config["host"]
        if "token" in db_config:
            overrides["databricks_token"] = db_config["token"]
        if "warehouse_id" in db_config:
            overrides["databricks_warehouse_id"] = db_config["warehouse_id"]
        if "default_catalog" in db_config:
            overrides["default_catalog"] = db_config["default_catalog"]
        if "default_schema" in db_config:
            overrides["default_schema"] = db_config["default_schema"]

    if "llm" in file_config:
        llm_config = file_config["llm"]
        if "provider" in llm_config:
            overrides["llm_provider"] = llm_config["provider"]
        if "model" in llm_config:
            overrides["llm_model"] = llm_config["model"]
        if "api_key" in llm_config:
            overrides["llm_api_key"] = llm_config["api_key"]
        if "base_url" in llm_config:
            overrides["llm_base_url"] = llm_config["base_url"]
        if "temperature" in llm_config:
            overrides["llm_temperature"] = llm_config["temperature"]
        if "max_tokens" in llm_config:
            overrides["llm_max_tokens"] = llm_config["max_tokens"]

    # Override from CLI args (highest priority)
    if args.databricks_host:
        overrides["databricks_host"] = args.databricks_host
    if args.databricks_token:
        overrides["databricks_token"] = args.databricks_token
    if args.llm_model:
        overrides["llm_model"] = args.llm_model
    if args.llm_api_key:
        overrides["llm_api_key"] = args.llm_api_key
    if args.llm_base_url:
        overrides["llm_base_url"] = args.llm_base_url
    if args.llm_temperature is not None:
        overrides["llm_temperature"] = args.llm_temperature
    if args.llm_max_tokens:
        overrides["llm_max_tokens"] = args.llm_max_tokens

    # Auth-by-subtraction (A1): profile / OAuth / auth-type flags steer the SDK
    # credential chain via env vars that the resolver reads. These are not fields
    # on EnvConfig; export them so resolve_workspace_client() and _auth_resolvable()
    # pick them up.
    if getattr(args, "profile", None):
        os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    if getattr(args, "client_id", None):
        os.environ["DATABRICKS_CLIENT_ID"] = args.client_id
    if getattr(args, "client_secret", None):
        os.environ["DATABRICKS_CLIENT_SECRET"] = args.client_secret
    if getattr(args, "auth_type", None):
        os.environ["DATABRICKS_AUTH_TYPE"] = args.auth_type

    # Create new config with overrides
    return base_config.model_copy(update=overrides)


# =============================================================================
# Agent Interface (Hide Conversation Complexity)
# =============================================================================
async def create_agent_manager(
    config: EnvConfig | None = None,
    state_manager: Any = None,
) -> tuple[
    MultiAgentConversationManager,
    AsyncDatabricksClient,
]:
    """
    Create multi-agent conversation manager with given configuration.

    This function encapsulates the complexity of creating the multi-agent system,
    hiding the internal wiring from the CLI.

    Args:
        config: Environment configuration
        state_manager: Optional conversation state manager. If provided, used
            instead of the default InMemoryConversationStateManager. Durable
            multi-turn CLI sessions are persisted separately by the JSON-file
            SessionManager (see starboard.cli.sessions).

    Returns:
        Tuple of (manager, api) — caller must close api when done to avoid
        dangling threads/connections.
    """
    if not config:
        config = get_config()

    logger.debug("initializing_agent_manager", model=config.llm_model)

    # Create LLM client using factory pattern
    llm_client = create_llm_client(cfg=config)

    # Create async Databricks client
    api = AsyncDatabricksClient(cfg=config)
    await api._initialize()  # Must initialize before use

    # Create shared context provider
    provider = SharedContextProvider(api)

    # Analytics context is built from on-disk curated reference files
    # (reference-file RAG); no vector store or embedding provider is constructed.

    # Create tool registry (all tools - AgentFactory will filter per domain)
    tool_registry, request_input_tool = create_tool_registry(
        api=api,
        provider=provider,
        events=None,
        input_callback=None,
        llm_client=llm_client,
    )

    # Create IntentRouter
    intent_router = IntentRouter(
        llm_client=llm_client, disabled_domains=config.disabled_agent_domains or []
    )

    # Create base agent config
    base_agent_config = AgentConfig(
        model=config.llm_model,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperature,
        domain_model_overrides=config.domain_model_overrides or {},
        domain_temperature_overrides=config.domain_temperature_overrides or {},
    )

    # Create AgentFactory
    agent_factory = AgentFactory(
        llm_client=llm_client,
        tool_registry=tool_registry,
        base_config=base_agent_config,
        events=None,
    )

    # Create ConversationStateManager (use injected or fall back to in-memory)
    if state_manager is None:
        state_manager = InMemoryConversationStateManager()

    # Create MultiAgentConversationManager
    manager = MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router,
        state_manager=state_manager,
        disabled_agent_domains=config.disabled_agent_domains or [],
        request_input_tool=request_input_tool,
    )

    logger.debug("agent_manager_ready", model=config.llm_model)
    return manager, api


# =============================================================================
# Output Saving
# =============================================================================


async def save_results(
    output: dict[str, Any],
    output_path: Path,
    conversation_id: str,
) -> tuple[Path, Path]:
    """
    Save results to JSON and Markdown files.

    Creates a friendly filename based on conversation context and saves
    both structured JSON and human-readable Markdown reports.
    Uses ``asyncio.to_thread()`` to avoid blocking the event loop.

    Args:
        output: Agent output dictionary
        output_path: Base directory for output files
        conversation_id: Conversation identifier

    Returns:
        Tuple of (json_path, markdown_path)
    """
    # Ensure output directory exists
    await asyncio.to_thread(output_path.mkdir, parents=True, exist_ok=True)

    # Generate friendly filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Extract first word of goal or use conversation_id
    goal = output.get("user_goal", "")
    goal_prefix = goal.split()[0][:20] if goal else conversation_id[:8]
    # Clean for filename (remove special chars)
    goal_prefix = "".join(c for c in goal_prefix if c.isalnum() or c in ("_", "-"))

    base_name = f"{timestamp}_{goal_prefix}"

    # Pre-render content (pure CPU, no I/O)
    json_path = output_path / f"{base_name}.json"
    json_content = json.dumps(output, indent=2, default=str)

    markdown_path = output_path / f"{base_name}.md"
    markdown_content = _generate_markdown_report(output)

    # Write both files in parallel via thread pool
    def _write_json() -> None:
        json_path.write_text(json_content, encoding="utf-8")

    def _write_markdown() -> None:
        markdown_path.write_text(markdown_content, encoding="utf-8")

    await asyncio.gather(
        asyncio.to_thread(_write_json),
        asyncio.to_thread(_write_markdown),
    )

    logger.debug(
        "results_saved",
        json_path=str(json_path),
        markdown_path=str(markdown_path),
    )

    return json_path, markdown_path


def _generate_markdown_report(output: dict[str, Any]) -> str:
    """
    Generate Markdown report from agent output.

    Tries to use complete_report with formatters first, falls back to basic formatting.

    Args:
        output: Agent output dictionary

    Returns:
        Markdown formatted report
    """
    # Use pre-rendered markdown if available (e.g. discovery reports)
    pre_rendered = output.get("formatted_markdown")
    if pre_rendered and isinstance(pre_rendered, str):
        lines = [
            "# Starboard Agent Analysis Report",
            "",
            f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            pre_rendered,
            "",
            "---",
            "",
            f"**Conversation ID**: {output.get('conversation_id', 'N/A')}",
            (
                f"**Tokens Used**: {output.get('tokens_used', 'N/A'):,}"
                if isinstance(output.get("tokens_used"), int)
                else f"**Tokens Used**: {output.get('tokens_used', 'N/A')}"
            ),
            f"**Cost**: ${output.get('cost_usd', 0):.4f}",
            "",
        ]
        return "\n".join(lines)

    # If we have a complete_report (structured), use the formatter
    if "complete_report" in output and isinstance(output["complete_report"], dict):
        try:
            from starboard.bootstrap import format_agent_report

            formatted = format_agent_report(output["complete_report"])
            if formatted:
                # Add header with metadata
                lines = [
                    "# Starboard Agent Analysis Report",
                    "",
                    f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    "",
                ]

                if "user_goal" in output:
                    lines.extend(["## Goal", "", output["user_goal"], ""])

                lines.append(formatted)

                # Add metadata footer
                lines.extend(
                    [
                        "",
                        "---",
                        "",
                        f"**Conversation ID**: {output.get('conversation_id', 'N/A')}",
                        (
                            f"**Tokens Used**: {output.get('tokens_used', 'N/A'):,}"
                            if isinstance(output.get("tokens_used"), int)
                            else f"**Tokens Used**: {output.get('tokens_used', 'N/A')}"
                        ),
                        f"**Cost**: ${output.get('cost_usd', 0):.4f}",
                        "",
                    ]
                )

                return "\n".join(lines)
        except Exception as e:
            logger.warning(
                "failed_to_format_complete_report",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Fall through to legacy formatting

    # Fallback: Legacy formatting for old-style output
    lines = [
        "# Starboard Agent Analysis Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # Add goal
    if "user_goal" in output:
        lines.extend(
            [
                "## Goal",
                "",
                output["user_goal"],
                "",
            ]
        )

    # Add summary
    if "summary" in output:
        lines.extend(
            [
                "## Summary",
                "",
                output["summary"],
                "",
            ]
        )

    # Add recommendations if present
    if "recommendations" in output:
        lines.extend(
            [
                "## Recommendations",
                "",
            ]
        )
        for i, rec in enumerate(output["recommendations"], 1):
            lines.append(f"### {i}. {rec.get('title', 'Recommendation')}")
            lines.append("")
            if "description" in rec:
                lines.append(rec["description"])
                lines.append("")
            if "implementation" in rec:
                lines.append("**Implementation:**")
                lines.append(rec["implementation"])
                lines.append("")

    # Add metadata
    lines.extend(
        [
            "---",
            "",
            "## Execution Metadata",
            "",
            f"- **Steps taken**: {output.get('steps_taken', 'N/A')}",
            f"- **Tools used**: {', '.join(output.get('tools_used', [])) if output.get('tools_used') else 'N/A'}",
            (
                f"- **Tokens used**: {output.get('tokens_used', 'N/A'):,}"
                if isinstance(output.get("tokens_used"), int)
                else f"- **Tokens used**: {output.get('tokens_used', 'N/A')}"
            ),
            f"- **Cost**: ${output.get('cost_usd', 0):.4f}",
            f"- **Duration**: {output.get('duration_seconds', 0):.2f}s",
            "",
        ]
    )

    return "\n".join(lines)


# =============================================================================
# Event Handling (Streaming Display)
# =============================================================================


async def handle_streaming_events(
    manager: MultiAgentConversationManager,
    user_message: str,
    *,
    conversation_id: str | None = None,
    mode: OptimizationMode = OptimizationMode.ONLINE,
    console: Console | None = None,
    plain: bool = False,
    quiet: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Handle streaming events from the agent, displaying progress to console.

    Args:
        manager: Multi-agent conversation manager
        conversation_id: Conversation identifier
        user_message: User's input message
        mode: Optimization mode
        console: Rich console for output
        plain: If True, use plain text instead of Rich formatting
        quiet: If True, suppress event output

    Returns:
        Tuple of (final_output dict, formatted_markdown), or (None, None) if no output
        Note: formatted_markdown is generated on-the-fly from complete_report

    Raises:
        RuntimeError: If agent encounters an error
        KeyboardInterrupt: If user interrupts with Ctrl+C
    """
    # Track state
    tools_called = []
    step_tools = []  # Track tools in current step
    final_output = None

    if console is None:
        console = Console()

    if not conversation_id:
        conversation_id = f"cli_{uuid4().hex[:12]}"

    if not quiet and not plain:
        # Rich streaming display (simplified - just print, no live updates)
        try:
            async for event in manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=mode,
            ):
                if isinstance(event, ToolStartEvent):
                    console.print(
                        f"[dim]⏳ {event.friendly_name}…[/dim]",
                    )

                elif isinstance(event, ToolEndEvent):
                    # Track tool usage
                    tools_called.append(event.tool_name)
                    step_tools.append(event.tool_name)

                    # Print tool completion
                    status_icon = "✅" if event.success else "❌"
                    status_color = "green" if event.success else "red"
                    console.print(
                        f"[{status_color}]{status_icon} {event.friendly_name} "
                        f"({event.duration_seconds:.2f}s)[/{status_color}]"
                    )

                elif isinstance(event, StepCompleteEvent):
                    # Reset step tools for next step
                    step_tools = []

                elif isinstance(event, FinalOutputEvent):
                    # Capture final output
                    final_output = (
                        event.output
                        if isinstance(event.output, dict)
                        else event.output.to_dict()
                    )

                elif isinstance(event, UserInputRequestEvent):
                    # Handle user input request (interruption)
                    await handle_user_input_request(event, console)

                elif isinstance(event, ErrorEvent):
                    raise RuntimeError(
                        f"Agent error: {event.error_type} - {event.error}"
                    )

        except KeyboardInterrupt:
            console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
            raise

    elif not quiet and plain:
        # Plain text streaming display (simplified - no thinking, just tools)
        try:
            async for event in manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=mode,
            ):
                if isinstance(event, ThinkingEvent):
                    # Ignore thinking events
                    pass

                elif isinstance(event, ToolStartEvent):
                    print(f"🔧 Tool: {event.tool_name}", flush=True)

                elif isinstance(event, ToolEndEvent):
                    tools_called.append(event.tool_name)
                    status = "✓" if event.success else "✗"
                    print(
                        f"{status} {event.tool_name} ({event.duration_seconds:.2f}s)",
                        flush=True,
                    )

                elif isinstance(event, StepCompleteEvent):
                    # Step complete (no additional output in plain mode)
                    pass

                elif isinstance(event, FinalOutputEvent):
                    final_output = event.output.to_dict()

                elif isinstance(event, UserInputRequestEvent):
                    await handle_user_input_request(event, console)

                elif isinstance(event, ErrorEvent):
                    print(
                        f"❌ Error: {event.error_type} - {event.error}",
                        file=sys.stderr,
                    )
                    raise RuntimeError(
                        f"Agent error: {event.error_type} - {event.error}"
                    )

        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
            raise

    else:
        # Quiet mode - just collect events
        try:
            async for event in manager.handle_message_stream(
                conversation_id=conversation_id,
                user_message=user_message,
                mode=mode,
            ):
                if isinstance(event, FinalOutputEvent):
                    final_output = event.output.to_dict()
                elif isinstance(event, UserInputRequestEvent):
                    await handle_user_input_request(event, console)
                elif isinstance(event, ErrorEvent):
                    raise RuntimeError(
                        f"Agent error: {event.error_type} - {event.error}"
                    )
        except KeyboardInterrupt:
            raise

    # Use pre-rendered markdown (e.g. from discovery pipeline) when available;
    # otherwise generate from complete_report via the formatter registry.
    formatted_markdown = None
    if final_output:
        formatted_markdown = final_output.get("formatted_markdown")

    if not formatted_markdown and (
        final_output
        and "complete_report" in final_output
        and final_output["complete_report"]
    ):
        try:
            from starboard.bootstrap import format_agent_report

            formatted_markdown = format_agent_report(final_output["complete_report"])
        except Exception as e:
            logger.warning(
                "failed_to_format_complete_report_in_cli",
                error=str(e),
                error_type=type(e).__name__,
            )

    return final_output, formatted_markdown


async def handle_user_input_request(
    event: UserInputRequestEvent, console: Console
) -> None:
    """
    Handle user input request event (interruptible reasoning).

    Note: This is a simplified implementation. Full interruptible reasoning
    requires additional state management that is better handled in the API/UI.

    For CLI context, we display the question but cannot easily inject the response
    back into the stream without additional complexity.

    Args:
        event: User input request event
        console: Rich console
    """
    # No live display to stop (removed for simpler output)

    # Display the question
    console.print("\n" + "=" * 70)
    console.print("[bold yellow]🤔 Agent needs input:[/bold yellow]")
    console.print(f"[yellow]{event.question}[/yellow]")
    console.print("=" * 70)

    # Note: In CLI context, we can't easily inject this back into the stream
    # This is a known limitation - interruptible reasoning works best in API/UI
    console.print(
        "[dim]Note: User input injection is not fully supported in CLI mode.[/dim]"
    )
    console.print("[dim]For interactive workflows, use the web UI or API.[/dim]\n")

    # For now, we'll just display the question and continue
    # The agent will timeout and continue without input


# =============================================================================
# Argument Parsing
# =============================================================================


def parse_args(argv: list | None = None) -> argparse.Namespace:
    """
    Parse command line arguments.

    Args:
        argv: Command line arguments (defaults to sys.argv)

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        prog="starboard",
        description="Starboard AI Agent - Databricks Optimization Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Query optimization
  starboard --goal "Optimize query with statement_id abc123"

  # Job optimization
  starboard --goal "Analyze job 456 for performance issues"

  # Multi-turn conversation (scripted)
  starboard --goal "Analyze query abc123" --session my-project
  starboard --goal "Would liquid clustering help?" --session my-project

  # Interactive chat
  starboard --chat
  starboard --chat --session my-project

  # With input file
  starboard --goal "Optimize this Spark code" --input-file job.py

  # Save results
  starboard --goal "Analyze table catalog.schema.table" --output-path ./results/

Environment Variables:
  DATABRICKS_HOST           Databricks workspace URL
  DATABRICKS_TOKEN          Databricks personal access token
  LLM_MODEL                 LLM model name (default: gpt-4o-mini)
  LLM_API_KEY               OpenAI API key (or compatible provider)
  LLM_BASE_URL              LLM API base URL (optional)
  LLM_TEMPERATURE           LLM temperature (0.0-1.0)
  LLM_MAX_TOKENS            Maximum tokens per session
        """,
    )

    # -- Input ----------------------------------------------------------------
    input_group = parser.add_argument_group("Input")
    input_group.add_argument(
        "--goal",
        type=str,
        required=False,
        help="What you want the agent to do (natural language)",
    )
    input_group.add_argument(
        "--input-file",
        type=str,
        help="File path to load and pass to the agent (e.g., source code, SQL)",
    )

    # -- Databricks Configuration ---------------------------------------------
    db_group = parser.add_argument_group("Databricks Configuration")
    db_group.add_argument(
        "--databricks-host",
        "--host",
        dest="databricks_host",
        type=str,
        help="Databricks workspace URL (or set DATABRICKS_HOST). Alias: --host",
    )
    db_group.add_argument(
        "--databricks-token",
        "--token",
        dest="databricks_token",
        type=str,
        help="Databricks personal access token (or set DATABRICKS_TOKEN). Alias: --token",
    )
    db_group.add_argument(
        "--profile",
        type=str,
        help=(
            "Databricks config profile name (~/.databrickscfg). "
            "Also settable via STARBOARD_WORKSPACE / DATABRICKS_CONFIG_PROFILE."
        ),
    )
    db_group.add_argument(
        "--client-id",
        dest="client_id",
        type=str,
        help="Databricks OAuth client ID / service-principal (or set DATABRICKS_CLIENT_ID)",
    )
    db_group.add_argument(
        "--client-secret",
        dest="client_secret",
        type=str,
        help="Databricks OAuth client secret (or set DATABRICKS_CLIENT_SECRET)",
    )
    db_group.add_argument(
        "--auth-type",
        dest="auth_type",
        type=str,
        help=(
            "Force an SDK auth strategy (e.g. pat, databricks-cli, oauth-m2m). "
            "Or set DATABRICKS_AUTH_TYPE."
        ),
    )

    # -- LLM Configuration ----------------------------------------------------
    llm_group = parser.add_argument_group("LLM Configuration")
    llm_group.add_argument(
        "--llm-model",
        type=str,
        help="LLM model name (e.g., gpt-4o, claude-3-5-sonnet)",
    )
    llm_group.add_argument(
        "--llm-api-key",
        type=str,
        help="LLM API key (or set LLM_API_KEY)",
    )
    llm_group.add_argument(
        "--llm-base-url",
        type=str,
        help="LLM API base URL for custom endpoints",
    )
    llm_group.add_argument(
        "--llm-temperature",
        type=float,
        help="LLM temperature (0.0-1.0, default: 0.4)",
    )
    llm_group.add_argument(
        "--llm-max-tokens",
        type=int,
        help="Maximum token budget for session (default: 120000)",
    )

    # -- Output & Display -----------------------------------------------------
    output_group = parser.add_argument_group("Output & Display")
    output_group.add_argument(
        "--output-path",
        type=str,
        help=(
            "Path to save results. For --discover: if the value ends in "
            "''.json'' the envelope is written to exactly that file (parent "
            "dirs are created); otherwise treated as a directory and the file "
            "is named discovery-<scope>.json inside it. For the goal agent: "
            "directory for JSON and Markdown reports."
        ),
    )
    output_group.add_argument(
        "--plain",
        action="store_true",
        help="Use plain text output instead of Rich formatting",
    )
    output_group.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output (only show final results)",
    )
    output_group.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON to stdout (implies --quiet)",
    )
    output_group.add_argument(
        "--no-color",
        action="store_true",
        default=bool(os.environ.get("NO_COLOR")),
        help="Disable color output (also respects NO_COLOR env var)",
    )

    # -- Session Management ---------------------------------------------------
    session_group = parser.add_argument_group("Session Management")
    session_group.add_argument(
        "--session",
        type=str,
        default=None,
        help="Named session for multi-turn conversations. Reuse a name to continue a prior conversation.",
    )
    session_group.add_argument(
        "--session-db",
        type=str,
        default=None,
        help="Path to session database (default: ~/.starboard/sessions.db)",
    )
    session_group.add_argument(
        "--chat",
        action="store_true",
        help="Start interactive chat mode for multi-turn conversations",
    )

    # -- Workspace Discovery --------------------------------------------------
    discovery_group = parser.add_argument_group("Workspace Discovery")
    discovery_group.add_argument(
        "--discover",
        action="store_true",
        help="Run workspace discovery and health assessment via the discovery agent",
    )
    discovery_group.add_argument(
        "--lookback-days",
        type=int,
        default=30,
        choices=[30, 60, 90],
        help="Discovery lookback period in days (default: 30)",
    )
    discovery_group.add_argument(
        "--discovery-domains",
        type=str,
        nargs="+",
        help="Specific domains to analyze (default: all active)",
    )
    discovery_group.add_argument(
        "--data-only",
        action="store_true",
        help="Skip LLM analysis in discovery mode (raw data only)",
    )
    discovery_group.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable discovery result caching (re-run every hot-table scan)",
    )
    discovery_group.add_argument(
        "--internal-account",
        type=str,
        default=None,
        help=(
            "Run discovery against the internal fleet mirror scoped to this "
            "Databricks account id (no customer-workspace connection). Requires "
            "the gated internal source to be installed and configured."
        ),
    )
    discovery_group.add_argument(
        "--internal-workspace-id",
        type=str,
        default=None,
        help=(
            "Run discovery against the INTERNAL fleet mirror scoped to this single "
            "workspace id (takes precedence over --internal-account)."
        ),
    )
    discovery_group.add_argument(
        "--out-dir",
        dest="out_dir",
        type=str,
        default=None,
        help=(
            "Write the discovery run layout into this directory: discovery.json "
            "(full envelope incl. data.facts), raw/<pack>.json (per-pack rows) and "
            "manifest.json — the same raw/ layout as "
            "`python -m starboard_x.discovery run --out-dir`. Works for both the "
            "customer and the --internal-* sources. raw/<pack>.json (and "
            "facts.json once the facts pack finishes) are written as each pack "
            "completes; discovery.json / manifest.json / final facts.json at the end."
        ),
    )
    discovery_group.add_argument(
        "--timeout-retries",
        dest="timeout_retries",
        type=int,
        default=None,
        help=(
            "Bounded re-submissions of a statement that hit its poll deadline "
            "(internal fleet path), with ~30s then ~60s back-off. SQL errors are "
            "never retried. Default: 2. 0 disables timeout retries."
        ),
    )
    discovery_group.add_argument(
        "--include-deep-dive",
        action="store_true",
        help=(
            "Enable DEEP_DIVE queries in addition to the standard GENERAL queries. "
            "Deep-dive queries run additional detailed scans that are skipped by "
            "default to keep discovery fast."
        ),
    )
    discovery_group.add_argument(
        "--full-stdout",
        action="store_true",
        help="Alias for --stdout full (kept for backward compatibility).",
    )
    discovery_group.add_argument(
        "--stdout",
        dest="stdout_mode",
        choices=["summary", "compact", "full"],
        default=None,
        help=(
            "Shape of the --json stdout envelope (stdout is always JSON-only; "
            "progress goes to stderr). summary: status, output path(s), counts, "
            "coverage summary, limit_reached_ids, skipped, pack_count, facts — "
            "no per-pack list. compact: the row-free envelope with the "
            "per-pack/per-query status list (the previous default). full: the "
            "complete row-bearing envelope. "
            "Default: summary when --out-dir/--output-path is given, else full."
        ),
    )

    # -- Agent Options --------------------------------------------------------
    agent_group = parser.add_argument_group("Agent Options")
    agent_group.add_argument(
        "--mode",
        choices=["online", "offline", "diagnostic"],
        default="online",
        help="Optimization mode: online (comprehensive), offline (fast), diagnostic (focused)",
    )

    # -- Logging & Debug ------------------------------------------------------
    logging_group = parser.add_argument_group("Logging & Debug")
    logging_group.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="WARNING",
        help="Logging level (default: WARNING — suppresses info/debug noise)",
    )
    logging_group.add_argument(
        "--log-file",
        type=str,
        help="Write logs to file instead of console (recommended for debugging)",
    )
    logging_group.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging to stderr (shows internal operations)",
    )
    logging_group.add_argument(
        "--config",
        type=str,
        help=(
            "Path to YAML config file. Schema:\n"
            "  databricks:\n"
            "    host: https://your-workspace.databricks.com\n"
            "    token: dapi...\n"
            "  llm:\n"
            "    model: gpt-4o\n"
            "    api_key: <your-api-key>\n"
            "    temperature: 0.4\n"
            "See examples/env.example for all options."
        ),
    )

    return parser.parse_args(argv)


# =============================================================================
# Main Entry Point
# =============================================================================


class _InternalUnusedExecutor:
    """Base ``SQLExecutor`` placeholder for internal-mirror discovery.

    An internal run executes entirely through the gated ``MirrorSource`` (which
    carries its own internal executor), so the engine's base executor must never
    be invoked. Raising here upholds the invariant that an internal discovery
    run makes **no** customer-workspace connection.
    """

    async def execute_sql(self, sql: str):  # noqa: ANN201, ARG002
        raise RuntimeError(
            "internal discovery must not use the customer SQL executor — all "
            "queries run via the gated MirrorSource"
        )


def _discovery_json_envelope(
    result: Any,
    source: str,
    internal_account: str | None,
    internal_workspace_ids: tuple[str, ...] | None,
    lookback_days: int | None = None,
    source_obj: Any = None,
) -> dict[str, Any]:
    """Build the deterministic ``--discover --json`` envelope.

    Converges on the **same nested shape** as ``python -m starboard_x.discovery``
    — rows grouped by pack under ``data.packs[].results[]`` via the shared
    serializer (:mod:`starboard_x.discovery._serialize`) — so a host has one
    parse path for both discovery entry points and the two cannot drift. Layers
    the internal-only fields on top: the ``source`` used and the resolved
    ``scope`` (so a caller can verify the dual-source routing), and three-state
    ``counts`` (succeeded / skipped / failed) — a skip (``unavailable on
    internal source``) is an expected coverage gap, NOT a failure. Each
    succeeded query carries its actual ``rows`` so the host can analyze the raw
    data; ``report_cards`` / ``top_priorities`` are present but empty on the
    ``--data-only`` path (no LLM analysis runs). Row counts are already capped
    per query, so the envelope stays bounded.

    Args:
        result: EngineResult from a discovery run.
        source: Source selector string (``"external"`` or ``"internal"``).
        internal_account: Internal account scope, if any.
        internal_workspace_ids: Internal workspace ids, if any.
        lookback_days: Run-level lookback window.
        source_obj: Resolved QuerySource object, if available.  When present
            and it exposes a ``coverage_caveats`` attribute, those strings are
            surfaced in ``data.coverage_caveats`` so a host can explain coverage
            gaps without hard-coding internal table names.
    """
    from starboard_x.contract import envelope as _contract_envelope
    from starboard_x.discovery._serialize import serialize_result

    # Base data block = the shared nested serialization (packs[].results[],
    # each query carrying columns/rows/truncated/status). Identical shape to the
    # external customer-identity path.
    data = serialize_result(result)

    # D5: populate top-level envelope fields that the compact stdout summary
    # already carries but the full (file) envelope was missing.  Computed from
    # the serialised packs so the logic is centralised here and never drifts
    # from the compact path.  Must come before the counts block so a host
    # parsing the full envelope gets the same contract as the compact one.
    _all_q_entries = [q for pk in data.get("packs", []) for q in pk.get("results", [])]
    data["pack_count"] = len(data.get("packs", []))
    data["limit_reached_ids"] = [
        q["query_id"] for q in _all_q_entries if q.get("limit_reached")
    ]
    # Per-query skips (status=="skipped") — the base list; D10 product-level
    # gaps are appended below.
    data["skipped"] = [
        {"query_id": q["query_id"], "reason": q.get("error")}
        for q in _all_q_entries
        if q.get("status") == "skipped"
    ]

    # D10: products detected by P-AUDIT01 for which no query pack ran.
    # Surfaced as coverage-gap entries in data.skipped so a host knows the
    # product was seen by the audit but not specifically analysed.
    for _product in getattr(result, "products_without_packs", []):
        data["skipped"].append(
            {
                "product": _product,
                "reason": "detected product has no query pack on this source",
            }
        )

    # Three-state coverage counts across every query — the internal path's
    # coverage-honesty signal (skipped is distinct from failed).
    all_results = [qr for pr in result.pack_results for qr in pr.results]
    data["counts"] = {
        "total": len(all_results),
        "succeeded": sum(1 for qr in all_results if qr.status == "succeeded"),
        "skipped": sum(1 for qr in all_results if qr.status == "skipped"),
        "failed": sum(1 for qr in all_results if qr.status == "failed"),
        # Queries in the selected packs that were never scheduled because their
        # discovery_mode (DEEP_DIVE) isn't enabled — kept OUT of ``total`` (which
        # is scheduled queries) so total == succeeded + skipped + failed.
        "filtered": int(getattr(result, "filtered_queries", 0) or 0),
    }

    # Internal-only routing / scope provenance (additive to the shared shape).
    data["source"] = source
    data["scope"] = {
        "account": internal_account,
        "workspace_ids": list(internal_workspace_ids or ()),
    }
    data["lookback_days"] = lookback_days

    # W32: per-pack/domain coverage summary so a skipped domain is explained
    # without enumerating all result rows.
    coverage: dict[str, Any] = {}
    for pr in result.pack_results:
        pack_key = getattr(pr, "pack_id", None) or getattr(pr, "domain", None) or "unknown"
        results = getattr(pr, "results", []) or []
        skipped_reasons = [
            qr.error
            for qr in results
            if getattr(qr, "skipped", False) and getattr(qr, "error", None)
        ]
        coverage[pack_key] = {
            "succeeded": sum(1 for qr in results if getattr(qr, "status", None) == "succeeded"),
            "skipped": sum(1 for qr in results if getattr(qr, "status", None) == "skipped"),
            "failed": sum(1 for qr in results if getattr(qr, "status", None) == "failed"),
            "skipped_reasons": skipped_reasons,
        }
    data["coverage"] = coverage

    # W32: surface source-level caveats (e.g. columns that are null in an
    # internal mirror) so a host can explain gaps.  The public SystemTablesSource
    # returns an empty tuple; the internal MirrorSource fills this in.
    data["coverage_caveats"] = list(
        getattr(source_obj, "coverage_caveats", ()) or ()
    )

    report_cards: list[dict[str, Any]] = []
    top_priorities: list[dict[str, Any]] = []
    if result.report is not None:
        report_cards = [
            {"domain": rc.domain, "grade": rc.grade, "score": rc.score}
            for rc in result.report.executive_summary.report_cards
        ]
        top_priorities = [
            {"priority": f.priority, "title": f.title, "domain": f.domain}
            for f in result.report.top_priorities[:5]
        ]
    data["report_cards"] = report_cards
    data["top_priorities"] = top_priorities

    return _contract_envelope(
        ok=True,
        domain="discovery",
        command="discover",
        data=data,
    )


def _summary_stdout_envelope(
    envelope: dict[str, Any],
    out_paths: dict[str, str | None],
) -> dict[str, Any]:
    """Smallest stdout envelope (``--stdout summary``): status + where the data is.

    No per-pack / per-query list and no rows — the full envelope (and the raw/
    layout for ``--out-dir``) is on disk at ``out_paths``. Carries only what a
    host needs to decide its next read: status, counts, a coverage summary that
    names just the packs with gaps, ``limit_reached_ids``, ``skipped``,
    ``pack_count`` and the deterministic headline ``facts``.
    """
    full_data = envelope.get("data", {})
    coverage = full_data.get("coverage") or {}
    packs_with_gaps = {
        pack: {k: entry.get(k, 0) for k in ("succeeded", "skipped", "failed")}
        for pack, entry in coverage.items()
        if entry.get("skipped") or entry.get("failed")
    }
    counts = full_data.get("counts") or {}
    if not envelope.get("ok"):
        status = "error"
    elif counts.get("failed"):
        status = "partial"
    else:
        status = "ok"
    return {
        "ok": envelope.get("ok"),
        "domain": envelope.get("domain"),
        "command": envelope.get("command"),
        "data": {
            "status": status,
            **out_paths,
            "source": full_data.get("source"),
            "scope": full_data.get("scope"),
            "lookback_days": full_data.get("lookback_days"),
            "counts": counts,
            "pack_count": full_data.get("pack_count"),
            "coverage_summary": {
                "packs_total": len(coverage),
                "packs_complete": len(coverage) - len(packs_with_gaps),
                "packs_with_gaps": packs_with_gaps,
            },
            "coverage_caveats": full_data.get("coverage_caveats"),
            "limit_reached_ids": full_data.get("limit_reached_ids", []),
            "skipped": full_data.get("skipped", []),
            "facts": full_data.get("facts"),
        },
    }


def _compact_stdout_envelope(
    envelope: dict[str, Any],
    output_path: str | None,
) -> dict[str, Any]:
    """Compact summary envelope emitted to stdout when ``--output-path`` is given.

    Same contract wrapper shape as the full envelope but ``data`` carries only
    metadata and per-query status — no rows — so agent context stays bounded.
    The full row-bearing envelope is on disk at ``output_path``.

    Shape::

        {
          "ok": true,
          "domain": "discovery",
          "command": "discover",
          "data": {
            "output_path": "<path>",
            "source": "...",
            "scope": {...},
            "counts": {...},
            "lookback_days": ...,
            "packs": [{"pack": "...", "queries": [
              {"query_id": "...", "status": "...", "row_count": ...,
               "limit_reached": ..., "lookback_days": ...}
            ]}],
            "limit_reached_ids": [...],
            "skipped": [{"query_id": "...", "reason": "..."}]
          }
        }
    """
    full_data = envelope.get("data", {})

    compact_packs = []
    limit_reached_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for pack in full_data.get("packs", []):
        compact_queries = []
        for q in pack.get("results", []):
            qid = q.get("query_id")
            compact_queries.append({
                "query_id": qid,
                "status": q.get("status"),
                "row_count": q.get("row_count"),
                "limit_reached": q.get("limit_reached"),
                "lookback_days": q.get("lookback_days"),
            })
            if q.get("limit_reached"):
                limit_reached_ids.append(qid)
            if q.get("status") == "skipped":
                skipped.append({"query_id": qid, "reason": q.get("error")})
        compact_packs.append({"pack": pack.get("pack"), "queries": compact_queries})

    # D10: include product-level coverage-gap entries from the full envelope
    # (entries in data.skipped that have a "product" key, not a "query_id").
    for entry in full_data.get("skipped", []):
        if "product" in entry and "query_id" not in entry:
            skipped.append(entry)

    compact_data: dict[str, Any] = {
        "output_path": output_path,
        "source": full_data.get("source"),
        "scope": full_data.get("scope"),
        "counts": full_data.get("counts"),
        "lookback_days": full_data.get("lookback_days"),
        "packs": compact_packs,
        "limit_reached_ids": limit_reached_ids,
        "skipped": skipped,
        # The deterministic headline numbers are small and are what the host
        # quotes first, so they ride along in the compact summary too.
        "facts": full_data.get("facts"),
        "coverage_caveats": full_data.get("coverage_caveats"),
    }

    return {
        "ok": envelope.get("ok"),
        "domain": envelope.get("domain"),
        "command": envelope.get("command"),
        "data": compact_data,
    }


async def run_discovery_mode(
    args: argparse.Namespace,
    config: Any,
    console: Console,
) -> None:
    """Run workspace discovery and health assessment.

    Args:
        args: CLI arguments including discovery-specific options.
        config: Merged environment configuration.
        console: Rich console for output.
    """
    from rich.table import Table

    from starboard.bootstrap import (
        AsyncSQLExecutor,
        DiscoveryEngine,
        EngineConfig,
        resolve_scheduled_source,
    )

    # In --json mode, stdout must carry ONLY the JSON envelope; route all
    # human-readable banner/progress output to stderr so it can't corrupt it.
    if getattr(args, "json", False):
        console = Console(stderr=True)

    console.print(
        "\n[bold blue]Starboard Workspace Discovery[/bold blue]\n"
        f"Lookback: {args.lookback_days} days | "
        f"Domains: {', '.join(args.discovery_domains) if args.discovery_domains else 'all active'} | "
        f"Data only: {args.data_only}\n"
    )

    output_dir = (
        config.discovery_output_dir
        if hasattr(config, "discovery_output_dir")
        else "./discovery_output"
    )

    # Auto-run wiring (internal_query_symmetry Task 9): an unattended run with a
    # preset internal target (env-configured, never asked interactively) selects
    # the gated internal mirror with no prompt. Unset => external, unchanged.
    # Interactive flags win over env-config (the env fields remain only for the
    # unattended scheduled run). So the skill/host prompts for the account or
    # workspace and passes it via --internal-account / --internal-workspace-id —
    # no env var needed to use the internal source interactively.
    source, internal_account, internal_workspace_ids = resolve_scheduled_source(
        internal_source_account=args.internal_account
        or getattr(config, "discovery_internal_source_account", None),
        internal_source_workspace_id=args.internal_workspace_id
        or getattr(config, "discovery_internal_source_workspace_id", None),
    )

    from starboard_core.domain.models.discovery.query import DiscoveryMode

    engine_config = EngineConfig(
        lookback_days=args.lookback_days,
        max_parallelism=config.discovery_max_parallelism
        if hasattr(config, "discovery_max_parallelism")
        else 4,
        domains=args.discovery_domains,
        data_only=args.data_only,
        output_dir=output_dir,
        llm_model=config.discovery_llm_model
        if hasattr(config, "discovery_llm_model")
        else None,
        llm_temperature=config.discovery_llm_temperature
        if hasattr(config, "discovery_llm_temperature")
        else 0.3,
        enable_cache=not getattr(args, "no_cache", False),
        source=source,
        internal_account=internal_account,
        internal_workspace_ids=internal_workspace_ids,
        discovery_mode=DiscoveryMode.DEEP_DIVE
        if getattr(args, "include_deep_dive", False)
        else DiscoveryMode.GENERAL,
    )
    # --timeout-retries unset -> EngineConfig's default (bounded retries).
    _timeout_retries = getattr(args, "timeout_retries", None)
    if _timeout_retries is not None:
        engine_config = dataclasses.replace(
            engine_config, timeout_retries=max(0, int(_timeout_retries))
        )

    # Internal-mirror discovery never touches a customer workspace: the gated
    # MirrorSource carries its own internal executor, so we neither build nor
    # connect a customer client. The base executor is a guard that fails loudly
    # if anything tries to use the customer path on an internal run.
    is_internal = source == "internal"
    databricks_client = None
    if is_internal:
        sql_executor: Any = _InternalUnusedExecutor()
    else:
        # Fast network/auth preflight: a DNS or connect failure otherwise stalls
        # ~5 min on host metadata and then surfaces as a large auth traceback.
        from starboard import check_connectivity, preflight_target

        # Preflight the host the run will actually use: an active --profile is
        # authoritative over ambient DATABRICKS_HOST/TOKEN (the resolver masks them).
        pf_host = getattr(config, "databricks_host", None)
        pf_token = getattr(config, "databricks_token", None)
        host, token = preflight_target(
            pf_host if isinstance(pf_host, str) else None,
            pf_token if isinstance(pf_token, str) else None,
        )
        preflight = check_connectivity(host, token, timeout=12)
        if not preflight.ok:
            Console(stderr=True).print(f"[bold red]{preflight.message}[/bold red]")
            sys.exit(AUTH_ERROR if preflight.kind == "AUTH" else CONNECTION_ERROR)
        databricks_client = AsyncDatabricksClient(cfg=config)
        sql_executor = AsyncSQLExecutor(databricks_client)

    llm_client = None
    if not args.data_only:
        try:
            llm_client = create_llm_client(config)
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not create LLM client: {e}[/yellow]\n"
                "Falling back to data-only mode."
            )

    # D2: wrap engine construction so that a ConnectionError from the internal
    # fleet preflight (_preflight_once via MirrorSourceBuilder.build) surfaces
    # as a clean one-line error instead of an uncaught exception traceback.
    # ConnectionError is the base class of InternalPreflightError (in
    # starboard-internal) so we can catch it without a cross-boundary import.
    try:
        engine = DiscoveryEngine(
            sql_executor=sql_executor,
            llm_client=llm_client,
            config=engine_config,
        )
    except ConnectionError as exc:
        _err = Console(stderr=True)
        _err.print(f"[bold red]Connection failed:[/bold red] {exc}")
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"ok": False, "error": str(exc), "error_type": "ConnectionError"},
                    indent=2,
                )
            )
        sys.exit(CONNECTION_ERROR)

    phase_start = time.monotonic()

    # B3: with --out-dir, persist each pack's rows (raw/<pack>.json) the moment
    # it finishes, and facts.json as soon as the facts pack is in — so a host can
    # start reading long before the slowest query returns. The final
    # discovery.json / manifest.json / facts.json are still written at the end.
    _incremental_dir = getattr(args, "out_dir", None)

    def _write_pack_incrementally(pack_result: Any) -> None:
        if not _incremental_dir or pack_result is None:
            return
        from starboard_x.discovery._serialize import write_facts_file, write_pack_file

        try:
            write_pack_file(pack_result, _incremental_dir)
            if getattr(pack_result, "pack_id", None) == "facts":
                write_facts_file(pack_result.results, _incremental_dir)
        except OSError as exc:  # an early write is best-effort; the final write is authoritative
            logger.warning("discovery_incremental_write_failed", error=str(exc))

    def _on_progress(phase: str, info: dict[str, Any]) -> None:
        nonlocal phase_start
        now = time.monotonic()
        elapsed = now - phase_start

        match phase:
            case "audit_start":
                console.print("  [dim]Phase 1/4[/dim]  Auditing active products …")
            case "audit_done":
                products = info.get("products", [])
                succeeded = info.get("succeeded", False)
                if not succeeded:
                    console.print(
                        f"  [yellow]![/yellow]  Audit query failed — "
                        f"running all packs  [dim]({elapsed:.1f}s)[/dim]"
                    )
                elif not products:
                    console.print(
                        f"  [yellow]![/yellow]  Audit returned no products — "
                        f"running always-on packs only  "
                        f"[dim]({elapsed:.1f}s)[/dim]"
                    )
                else:
                    label = ", ".join(products[:8])
                    if len(products) > 8:
                        label += f" (+{len(products) - 8} more)"
                    console.print(
                        f"  [green]✓[/green]  Audit complete — "
                        f"{len(products)} products detected  "
                        f"[dim]({elapsed:.1f}s)[/dim]"
                    )
                    console.print(f"           [dim]{label}[/dim]")
                phase_start = now
            case "queries_start":
                packs = info.get("pack_count", 0)
                queries = info.get("query_count", 0)
                filtered = info.get("filtered_count", 0)
                note = (
                    f" [dim]({filtered} deep-dive queries not enabled; "
                    f"pass --include-deep-dive)[/dim]"
                    if filtered
                    else ""
                )
                console.print(
                    f"  [dim]Phase 2/4[/dim]  Executing {queries} queries "
                    f"across {packs} packs{note} …"
                )
            case "query_progress":
                # D4: per-query liveness — fired every ~10 queries or ~30 s
                done = info.get("done", 0)
                total = info.get("total", 0)
                elapsed_s = info.get("elapsed_s", 0.0)
                console.print(
                    f"           [dim]{done}/{total} queries done "
                    f"({elapsed_s:.0f}s)[/dim]"
                )
            case "pack_done":
                _write_pack_incrementally(info.get("pack_result"))
                # D3: one line per finished pack so progress is visible even
                # when the 10-query throttle hasn't ticked.
                parts = [f"{info.get('succeeded', 0)} ok"]
                if info.get("skipped"):
                    parts.append(f"{info['skipped']} skipped")
                if info.get("failed"):
                    parts.append(f"[yellow]{info['failed']} failed[/yellow]")
                console.print(
                    f"           [dim]pack {info.get('pack_id')} done "
                    f"({', '.join(parts)}) — "
                    f"{info.get('packs_done', 0)}/{info.get('packs_total', 0)} packs "
                    f"({info.get('elapsed_s', 0.0):.0f}s)[/dim]"
                )
            case "query_heartbeat":
                # D3: timed liveness (~30 s) even when nothing completed; B3:
                # name the still-running query ids (truncated by the engine).
                ids = list(info.get("in_flight_ids") or [])
                more = int(info.get("in_flight_more") or 0)
                names = ""
                if ids:
                    names = ": " + ", ".join(str(i) for i in ids)
                    if more:
                        names += f" (+{more} more)"
                console.print(
                    f"           [dim]… still running: "
                    f"{info.get('done', 0)}/{info.get('total', 0)} queries done, "
                    f"{info.get('in_flight', 0)} in flight{names} "
                    f"({info.get('elapsed_s', 0.0):.0f}s elapsed)[/dim]"
                )
            case "queries_done":
                ok = info.get("succeeded", 0)
                skip = info.get("skipped", 0)
                fail = info.get("failed", 0)
                status = f"{ok} succeeded"
                if skip:
                    status += f", [dim]{skip} skipped (unavailable)[/dim]"
                if fail:
                    status += f", [yellow]{fail} failed[/yellow]"
                console.print(
                    f"  [green]✓[/green]  Queries complete — {status}  "
                    f"[dim]({elapsed:.1f}s)[/dim]"
                )
                phase_start = now
            case "analysis_start":
                domains = info.get("domains", [])
                console.print(
                    f"  [dim]Phase 3/4[/dim]  Analyzing {len(domains)} domains "
                    f"(heuristics + LLM) …"
                )
                if domains:
                    console.print(f"           [dim]{', '.join(domains)}[/dim]")
            case "analysis_done":
                grades = info.get("grades", {})
                grade_parts = []
                grade_colors = {
                    "A": "green",
                    "B": "blue",
                    "C": "yellow",
                    "D": "red",
                    "F": "red",
                }
                for domain, grade in grades.items():
                    color = grade_colors.get(grade, "white")
                    grade_parts.append(f"[{color}]{domain}={grade}[/{color}]")
                console.print(
                    f"  [green]✓[/green]  Analysis complete — "
                    f"{info.get('domains', 0)} domains graded  "
                    f"[dim]({elapsed:.1f}s)[/dim]"
                )
                if grade_parts:
                    console.print(f"           {' | '.join(grade_parts)}")
                phase_start = now
            case "synthesis_start":
                console.print("  [dim]Phase 4/4[/dim]  Assembling report …")
            case "output_done":
                console.print(
                    f"  [green]✓[/green]  Report written — "
                    f"{info.get('files', 0)} files  "
                    f"[dim]({elapsed:.1f}s)[/dim]"
                )
                phase_start = now

    if databricks_client is not None:
        async with databricks_client:
            result = await engine.run(on_progress=_on_progress)
    else:
        # Internal mirror run — no customer client context to enter.
        result = await engine.run(on_progress=_on_progress)

    # W32: pull coverage_caveats from the resolved source (if available).
    # _pack_executor._source is private but we're in the same package; use
    # getattr with defaults so _FakeEngine in tests never raises.
    _pack_exec = getattr(engine, "_pack_executor", None)
    source_obj = getattr(_pack_exec, "_source", None)

    envelope = _discovery_json_envelope(
        result,
        source,
        internal_account,
        internal_workspace_ids,
        lookback_days=args.lookback_days,
        source_obj=source_obj,
    )

    # Serialize the row-bearing envelope to --output-path when given, so the host
    # can read the raw scoped rows off disk for this engagement turn. This is
    # ephemeral per-turn serialization, NOT a cache — nothing is reused across
    # invocations. Works in --data-only (where the engine otherwise writes no
    # files), and this path honors --output-path rather than the default dir.
    #
    # W8: if the value ends in ".json" write to exactly that file (mkdir parents);
    # otherwise treat as a directory and name the file discovery-<scope>.json.
    out_path = getattr(args, "output_path", None)
    out_file: Path | None = None
    # Extra on-disk artifacts (--out-dir layout) for the summary envelope; the
    # full envelope file itself is always reported as ``output_path``.
    out_paths: dict[str, str] = {}
    run_out_dir = getattr(args, "out_dir", None)
    if run_out_dir:
        # Run-dir layout (the public discovery Step-4 shape): raw/<pack>.json +
        # manifest.json via the shared writer, plus the full envelope.
        from starboard_x.discovery._serialize import write_result_files

        layout_dir = Path(run_out_dir)
        layout_dir.mkdir(parents=True, exist_ok=True)
        layout_manifest = write_result_files(result, str(layout_dir))
        (layout_dir / "manifest.json").write_text(
            json.dumps(layout_manifest, indent=2, default=str), encoding="utf-8"
        )
        out_file = layout_dir / "discovery.json"
        out_file.write_text(
            json.dumps(envelope, indent=2, default=str), encoding="utf-8"
        )
        out_paths["out_dir"] = str(layout_dir)
        out_paths["manifest_path"] = str(layout_dir / "manifest.json")
        console.print(f"[dim]Discovery run layout written to {layout_dir}[/dim]")
    if out_path:
        if out_path.endswith(".json"):
            out_file = Path(out_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
        else:
            scope_tag = (
                internal_account
                or (internal_workspace_ids[0] if internal_workspace_ids else source)
            )
            out_dir = Path(out_path)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"discovery-{scope_tag}.json"
        out_file.write_text(
            json.dumps(envelope, indent=2, default=str), encoding="utf-8"
        )
        # In --json mode `console` is the stderr console, so this never pollutes
        # the JSON on stdout.
        console.print(f"[dim]Discovery data written to {out_file}[/dim]")

    # Machine-readable output: emit the deterministic discovery envelope and
    # return (no Rich rendering on stdout when --json).
    # D2 / W9: --stdout picks the stdout shape. Default: ``summary`` (status +
    # paths + counts + facts, no per-pack list) when the data is on disk via
    # --out-dir/--output-path; otherwise ``full`` (stdout is the only copy).
    # --full-stdout is a backward-compatible alias for --stdout full.
    if getattr(args, "json", False):
        stdout_mode = getattr(args, "stdout_mode", None)
        if stdout_mode is None:
            if getattr(args, "full_stdout", False):
                stdout_mode = "full"
            else:
                stdout_mode = "summary" if out_file is not None else "full"
        if stdout_mode == "summary":
            payload = _summary_stdout_envelope(
                envelope,
                {
                    "output_path": str(out_file) if out_file is not None else None,
                    **out_paths,
                },
            )
        elif stdout_mode == "compact":
            payload = _compact_stdout_envelope(
                envelope, str(out_file) if out_file is not None else None
            )
        else:
            payload = envelope
        print(json.dumps(payload, indent=2, default=str))
        return

    console.print(
        f"\n[bold green]✓ Discovery complete[/bold green] "
        f"[dim]({result.elapsed_ms / 1000:.1f}s)[/dim]"
    )

    if result.errors:
        console.print(f"\n[yellow]Warnings ({len(result.errors)}):[/yellow]")
        for err in result.errors:
            console.print(f"  [yellow]![/yellow] {err}")

    if result.report is not None:
        es = result.report.executive_summary
        console.print("\n[bold]Overview[/bold]")
        console.print(f"  {es.overview}")

        if es.report_cards:
            tbl = Table(title="Report Cards", show_header=True, padding=(0, 1))
            tbl.add_column("Grade", justify="center", width=5)
            tbl.add_column("Domain", min_width=12)
            tbl.add_column("Score", justify="right", width=5)
            tbl.add_column("Summary", ratio=1)
            grade_colors = {
                "A": "green",
                "B": "blue",
                "C": "yellow",
                "D": "red",
                "F": "red",
            }
            for rc in es.report_cards:
                color = grade_colors.get(rc.grade, "white")
                tbl.add_row(
                    f"[{color}]{rc.grade}[/{color}]",
                    rc.domain,
                    f"{rc.score:.0f}",
                    rc.discussion[:100],
                )
            console.print()
            console.print(tbl)

        if result.report.top_priorities:
            console.print("\n[bold]Top Findings[/bold]")
            for i, f in enumerate(result.report.top_priorities[:5], 1):
                priority_colors = {
                    "CRITICAL": "red",
                    "HIGH": "yellow",
                    "MEDIUM": "cyan",
                    "LOW": "dim",
                }
                color = priority_colors.get(f.priority, "white")
                console.print(
                    f"  {i}. [{color}]{f.priority:<8}[/{color}] "
                    f"{f.title}  [dim]({f.domain})[/dim]"
                )
    elif result.domain_analyses:
        console.print("\n[bold]Domain Summaries (data-only mode)[/bold]")
        for a in result.domain_analyses:
            console.print(f"  {a.domain}: grade={a.grade} score={a.score}")

    if result.output_files:
        console.print("\n[bold]Output[/bold]")
        for fp in result.output_files:
            console.print(f"  {fp}")

    console.print()


async def async_main(args: argparse.Namespace) -> None:
    """
    Async main function.

    Args:
        args: Command line arguments

    Raises:
        SystemExit: On configuration or execution errors
    """
    # Load .env file if it exists (for convenience)
    load_dotenv()

    # FIRST: Configure CLI-specific logging
    log_level = "DEBUG" if args.debug else args.log_level
    _log_file_handle = setup_cli_logging(
        log_level=log_level,
        log_file=args.log_file,
        quiet=args.quiet,
    )

    # --json implies quiet (no progress noise on stdout)
    if getattr(args, "json", False):
        args.quiet = True

    # Respect --no-color and NO_COLOR env var
    no_color = getattr(args, "no_color", False) or bool(os.environ.get("NO_COLOR"))
    console = Console(no_color=no_color)
    # stderr console for error messages so they don't pollute stdout
    err_console = Console(stderr=True, no_color=no_color)

    # Track resources that must be closed on exit to prevent dangling threads
    _api: AsyncDatabricksClient | None = None
    session_mgr: SessionManager | None = None

    try:
        # Load configuration
        file_config = {}
        if args.config:
            try:
                config_path = Path(args.config)
                file_config = load_config_file(config_path)
                logger.debug("config_loaded", path=str(config_path))
            except (FileNotFoundError, ValueError) as e:
                err_console.print(f"[bold red]Config error:[/bold red] {e}")
                sys.exit(CONFIG_ERROR)

        # Merge configuration
        config = merge_env_config(file_config, args)

        # Validate Databricks auth (auth by subtraction, A1): host/token are no
        # longer hard-required. Attempt to resolve *some* credential (inline
        # host+token, a --profile / env profile, OAuth client creds, a
        # ~/.databrickscfg, or an ambient runtime). Only error when nothing
        # resolves. The actual credential check happens in the client's
        # _verify_auth() during connection.
        if not config.offline_mode and not config._auth_resolvable():
            err_console.print(
                "[bold red]No Databricks auth resolved[/bold red]\n"
                "Provide one of:\n"
                "  --profile <name>            (a ~/.databrickscfg profile)\n"
                "  --databricks-host + --databricks-token   (or --host/--token)\n"
                "  --client-id + --client-secret            (OAuth service principal)\n"
                "or set DATABRICKS_CONFIG_PROFILE / STARBOARD_WORKSPACE,\n"
                "DATABRICKS_HOST + DATABRICKS_TOKEN, or run on a Databricks runtime."
            )
            sys.exit(CONFIG_ERROR)

        if config.llm_api_key:
            key = config.llm_api_key.strip()
            if len(key) < 10:
                err_console.print(
                    "[bold red]Error:[/bold red] LLM_API_KEY appears invalid (too short)."
                )
                sys.exit(AUTH_ERROR)
        elif not args.discover or not args.data_only:
            err_console.print(
                "[bold yellow]Warning:[/bold yellow] LLM_API_KEY not set.\n"
                "Some LLM providers may require an API key."
            )

        # Discovery mode — run the deterministic discovery pipeline directly
        # (NOT the LLM goal-agent). This honors the discovery source seam:
        # external by default, or the gated internal mirror when an
        # --internal-account / --internal-workspace-id flag (or the
        # DISCOVERY_INTERNAL_SOURCE_* env target) is set. Keeping it off the
        # agent path means no second LLM is spun up for discovery.
        if args.discover:
            await run_discovery_mode(args, config, console)
            return

        # Build user message (not required in chat mode)
        user_message = args.goal
        is_chat_mode = getattr(args, "chat", False)
        if not user_message and not is_chat_mode:
            err_console.print(
                "[bold yellow]No goal provided[/bold yellow]\n"
                "Please provide what you want the agent to do:\n"
                '  --goal "your goal"\n'
                'Example: starboard --goal "Optimize query with statement_id abc123"\n'
                "Or start an interactive session:\n"
                "  starboard --chat"
            )
            sys.exit(CONFIG_ERROR)

        # Load input file if provided
        if args.input_file:
            input_path = Path(args.input_file)
            if not input_path.exists():
                err_console.print(
                    f"[bold red]Input file not found:[/bold red] {input_path}"
                )
                sys.exit(CONFIG_ERROR)

            try:
                file_content = await asyncio.to_thread(
                    input_path.read_text, encoding="utf-8"
                )

                # Append file content to user message
                user_message = f"{user_message}\n\nFile content from {input_path.name}:\n```\n{file_content}\n```"
                logger.debug(
                    "input_file_loaded", path=str(input_path), size=len(file_content)
                )
            except Exception as e:
                err_console.print(f"[bold red]Error reading input file:[/bold red] {e}")
                sys.exit(CONFIG_ERROR)

        # =====================================================================
        # Session management: determine state manager and conversation_id
        # =====================================================================
        session_state_manager: Any = None
        session_name: str | None = getattr(args, "session", None)
        is_chat_mode = getattr(args, "chat", False)

        if session_name or is_chat_mode:
            db_path = getattr(args, "session_db", None) or "~/.starboard/sessions.db"
            session_mgr = SessionManager(db_path=db_path)
            await session_mgr.connect()
            session_state_manager = session_mgr.conversation_repo

        # Create agent manager
        if not args.quiet:
            err_console.print(
                "\n[bold blue]Initializing Starboard Agent...[/bold blue]"
            )

        try:
            manager, _api = await create_agent_manager(
                config, state_manager=session_state_manager
            )
        except Exception as e:
            err_console.print(f"[bold red]Failed to initialize agent:[/bold red] {e}")
            logger.exception("agent_initialization_failed")
            sys.exit(
                CONNECTION_ERROR
            )  # finally block below will still close any partial resources

        if not args.quiet:
            err_console.print(
                f"[green]Agent ready:[/green] model={config.llm_model}, "
                f"budget={config.llm_max_tokens:,} tokens"
            )

            # Display domain model configuration if any overrides exist
            if config.domain_model_overrides:
                err_console.print("\n[dim]Multi-Agent Configuration:[/dim]")
                domain_labels = {
                    "router": "Router",
                    "query": "Query Optimization",
                    "job": "Job Analysis",
                    "table": "Table & Lineage",
                    "compute": "Compute Resources",
                    "diagnostic": "Diagnostics & Troubleshooting",
                }
                for domain, model in config.domain_model_overrides.items():
                    label = domain_labels.get(domain, domain.capitalize())
                    temp_override = ""
                    if (
                        config.domain_temperature_overrides
                        and domain in config.domain_temperature_overrides
                    ):
                        temp_override = (
                            f" (temp: {config.domain_temperature_overrides[domain]})"
                        )
                    err_console.print(f"  {label}: [cyan]{model}[/cyan]{temp_override}")

            err_console.print()

        # =====================================================================
        # Interactive chat mode (REPL)
        # =====================================================================
        if is_chat_mode:
            from starboard.cli.cli.chat import run_interactive_chat

            await run_interactive_chat(
                manager=manager,
                session_mgr=session_mgr,
                session_name=session_name,
                console=console,
                mode=OptimizationMode[args.mode.upper()],
                plain=args.plain,
                no_color=no_color,
            )
            return

        # =====================================================================
        # Single-shot mode (original behavior, optionally with session)
        # =====================================================================

        # Resolve conversation_id (session-backed or ephemeral)
        if session_mgr and session_name:
            session_info = await session_mgr.get_or_create(session_name)
            conversation_id = session_info.conversation_id
            if not args.quiet and session_info.turn_count > 0:
                console.print(
                    f"[dim]Resuming session '{session_name}' "
                    f"(turn {session_info.turn_count + 1})[/dim]"
                )
        else:
            conversation_id = f"cli_{uuid4().hex[:12]}"

        logger.debug("conversation_created", conversation_id=conversation_id)

        # Get optimization mode
        mode = OptimizationMode[args.mode.upper()]

        # Run agent with streaming
        if not args.quiet:
            err_console.print("[bold green]Starting analysis...[/bold green]\n")

        try:
            final_output, formatted_markdown = await handle_streaming_events(
                manager=manager,
                conversation_id=conversation_id,
                user_message=user_message,
                mode=mode,
                console=console,
                plain=args.plain,
                quiet=args.quiet,
            )

            # Update session activity if using a named session
            if session_mgr and session_name:
                await session_mgr.update_session_activity(session_name, user_message)

        except KeyboardInterrupt:
            err_console.print("\n[yellow]Analysis interrupted by user[/yellow]")
            sys.exit(INTERRUPTED)
        except Exception as e:
            if getattr(args, "json", False):
                error_payload = {
                    "ok": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
                print(json.dumps(error_payload, indent=2))
            else:
                err_console.print(f"\n[bold red]Analysis failed:[/bold red] {e}")
            logger.exception("analysis_failed")
            sys.exit(GENERAL_ERROR)

        # Display results
        if final_output:
            # --json: emit structured JSON envelope to stdout, then stop
            if getattr(args, "json", False):
                envelope = {
                    "ok": True,
                    "data": final_output,
                    "formatted_markdown": formatted_markdown,
                }
                print(json.dumps(envelope, indent=2, default=str))
                return

            if not args.quiet:
                err_console.print("\n" + "=" * 70)
                err_console.print("[bold green]RESULTS[/bold green]")
                err_console.print("=" * 70 + "\n")

                # Display summary metrics
                err_console.print(
                    f"Steps taken: {final_output.get('steps_taken', 'N/A')}"
                )
                err_console.print(
                    f"Tools used: {', '.join(final_output.get('tools_used', [])) if final_output.get('tools_used') else 'N/A'}"
                )
                err_console.print(
                    f"Tokens used: {final_output.get('tokens_used', 'N/A'):,}"
                    if isinstance(final_output.get("tokens_used"), int)
                    else f"Tokens used: {final_output.get('tokens_used', 'N/A')}"
                )
                err_console.print(f"Cost: ${final_output.get('cost_usd', 0):.4f}")
                err_console.print(
                    f"Duration: {final_output.get('duration_seconds', 0):.2f}s\n"
                )

            # Display formatted markdown report if available
            if formatted_markdown:
                if not args.quiet:
                    # Display report header to stderr, report content to stdout
                    err_console.print("\n" + "=" * 70)
                    err_console.print("[bold]ANALYSIS REPORT[/bold]")
                    err_console.print("=" * 70 + "\n")

                    # Print markdown as plain text (Rich's Markdown renderer centers headers)
                    # This ensures all headers are left-aligned as intended
                    console.print(formatted_markdown)
                else:
                    # In quiet mode, just print the markdown report (no Rich formatting)
                    print(formatted_markdown)

            # Save results if requested
            if args.output_path:
                output_path = Path(args.output_path)
                try:
                    json_path, markdown_path = await save_results(
                        output=final_output,
                        output_path=output_path,
                        conversation_id=conversation_id,
                    )
                    if not args.quiet:
                        err_console.print("\nResults saved:")
                        err_console.print(f"   JSON: {json_path}")
                        err_console.print(f"   Markdown: {markdown_path}")
                except Exception as e:
                    err_console.print(
                        f"\n[bold yellow]⚠️  Failed to save results:[/bold yellow] {e}"
                    )
                    logger.exception("save_results_failed")

        else:
            err_console.print("\n[bold yellow]No results to display[/bold yellow]")

    except Exception as e:
        if getattr(args, "json", False):
            error_payload = {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }
            print(json.dumps(error_payload, indent=2))
        else:
            err_console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("unexpected_error")
        sys.exit(GENERAL_ERROR)

    finally:
        # Always close long-lived resources so their connection pools and threads
        # are released before the event loop exits. Without this the process hangs
        # waiting for non-daemon httpx / SDK threads to terminate.
        if session_mgr is not None:
            with contextlib.suppress(Exception):
                await session_mgr.close()
        if _api is not None:
            with contextlib.suppress(Exception):
                await _api.close()
        # Close log file handle if one was opened
        if _log_file_handle is not None:
            with contextlib.suppress(Exception):
                _log_file_handle.close()


def main(argv: list | None = None) -> None:
    """
    Main entry point for the CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv)
    """
    # Route the `auth` command group (login / status) before the main
    # flag-based parser, so `starboard auth …` bypasses the agent path.
    effective_argv = argv if argv is not None else sys.argv[1:]
    if effective_argv and effective_argv[0] == "auth":
        sys.exit(run_auth(effective_argv[1:]))

    # Route the `review` command (Workload Review flagship, Phase-3 D1b) before
    # the flag-based agent parser, so `starboard review …` runs the deterministic
    # public-data review path instead of the multi-agent conversation loop.
    if effective_argv and effective_argv[0] == "review":
        from starboard.cli.cli.review_command import run_review

        sys.exit(run_review(effective_argv[1:]))

    try:
        args = parse_args(argv)
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(INTERRUPTED)
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(GENERAL_ERROR)


if __name__ == "__main__":
    main()
