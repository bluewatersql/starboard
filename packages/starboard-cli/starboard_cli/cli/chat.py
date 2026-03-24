"""Interactive chat mode for multi-turn CLI conversations.

Provides a REPL interface for conversational interaction with the
Starboard agent, maintaining context across turns via session persistence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Console
from starboard_server.agents.events import (
    ErrorEvent,
    FinalOutputEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserInputRequestEvent,
)
from starboard_server.infra.observability.logging import get_logger

from starboard_cli.sessions.session_manager import SessionManager

if TYPE_CHECKING:
    from starboard_core.domain.models.llm import OptimizationMode
    from starboard_server.agents.conversation import MultiAgentConversationManager

logger = get_logger(__name__)

_META_COMMANDS = {
    "/exit": "End the chat session",
    "/quit": "End the chat session",
    "/sessions": "List all saved sessions",
    "/history": "Show conversation turn count",
    "/new": "Start a new conversation (keep session name)",
    "/help": "Show available commands",
}


async def run_interactive_chat(
    manager: MultiAgentConversationManager,
    session_mgr: SessionManager | None,
    session_name: str | None,
    console: Console,
    mode: OptimizationMode,
    plain: bool = False,
) -> None:
    """Run the interactive chat REPL.

    Args:
        manager: Multi-agent conversation manager.
        session_mgr: Session manager for persistence (creates one if None).
        session_name: Named session to resume/create.
        console: Rich console for output.
        mode: Optimization mode for agent.
        plain: Use plain text output instead of Rich formatting.
    """
    if session_mgr is None:
        session_mgr = SessionManager()
        await session_mgr.connect()

    session_info = await session_mgr.get_or_create(session_name)
    conversation_id = session_info.conversation_id

    console.print(
        "\n[bold blue]━━━ Starboard Interactive Chat ━━━[/bold blue]"
    )
    console.print(
        f"[dim]Session: {session_info.session_name} | "
        f"Turns: {session_info.turn_count} | "
        f"Type /help for commands[/dim]\n"
    )

    if session_info.turn_count > 0:
        console.print(
            f"[dim]Resuming session with {session_info.turn_count} prior turn(s).[/dim]\n"
        )

    while True:
        try:
            user_input = _prompt_user(console)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        stripped = user_input.strip().lower()

        if stripped in ("/exit", "/quit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if stripped == "/help":
            _show_help(console)
            continue

        if stripped == "/sessions":
            await _show_sessions(session_mgr, console)
            continue

        if stripped == "/history":
            _show_history(session_info, console)
            continue

        if stripped == "/new":
            session_info = await session_mgr.get_or_create()
            conversation_id = session_info.conversation_id
            console.print(
                f"[green]New session started:[/green] {session_info.session_name}\n"
            )
            continue

        # Send message to agent
        console.print()
        try:
            await _stream_agent_response(
                manager=manager,
                conversation_id=conversation_id,
                user_message=user_input,
                mode=mode,
                console=console,
                plain=plain,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]\n")
            continue
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")
            logger.exception("chat_turn_failed")
            continue

        # Update session activity
        await session_mgr.update_session_activity(
            session_info.session_name, user_input
        )
        # Refresh local session_info to reflect new turn_count
        session_info = await session_mgr.get_or_create(session_info.session_name)

        console.print()


def _prompt_user(console: Console) -> str:  # noqa: ARG001
    """Prompt user for input with a styled prompt.

    Args:
        console: Rich console (unused for input, but available for styling).

    Returns:
        User input string, stripped of leading/trailing whitespace.
    """
    try:
        return input("starboard> ").strip()
    except EOFError:
        raise


def _show_help(console: Console) -> None:
    """Display available meta commands."""
    console.print("\n[bold]Available commands:[/bold]")
    for cmd, desc in _META_COMMANDS.items():
        console.print(f"  [cyan]{cmd:<12}[/cyan] {desc}")
    console.print()


async def _show_sessions(session_mgr: SessionManager, console: Console) -> None:
    """List all saved sessions."""
    sessions = await session_mgr.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]\n")
        return

    console.print(f"\n[bold]Saved sessions ({len(sessions)}):[/bold]")
    for s in sessions:
        preview = f" — {s.last_message_preview}" if s.last_message_preview else ""
        console.print(
            f"  [cyan]{s.session_name:<20}[/cyan] "
            f"turns={s.turn_count:<3} "
            f"updated={s.updated_at:%Y-%m-%d %H:%M}"
            f"[dim]{preview}[/dim]"
        )
    console.print()


def _show_history(session_info: Any, console: Console) -> None:
    """Show conversation metadata."""
    console.print(
        f"\n[bold]Session:[/bold] {session_info.session_name}\n"
        f"  Conversation ID: {session_info.conversation_id}\n"
        f"  Turns: {session_info.turn_count}\n"
        f"  Created: {session_info.created_at:%Y-%m-%d %H:%M}\n"
        f"  Updated: {session_info.updated_at:%Y-%m-%d %H:%M}\n"
    )


async def _stream_agent_response(
    manager: MultiAgentConversationManager,
    conversation_id: str,
    user_message: str,
    mode: OptimizationMode,
    console: Console,
    plain: bool = False,
) -> None:
    """Stream agent response for a single turn in the REPL.

    Args:
        manager: Multi-agent conversation manager.
        conversation_id: Conversation identifier.
        user_message: User's input message.
        mode: Optimization mode.
        console: Rich console for output.
        plain: Use plain text output.

    Raises:
        RuntimeError: If agent encounters a fatal error.
        KeyboardInterrupt: If user interrupts with Ctrl+C.
    """
    formatted_markdown = None

    async for event in manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message=user_message,
        mode=mode,
    ):
        if isinstance(event, ToolStartEvent):
            if plain:
                print(f"  🔧 {event.tool_name}…", flush=True)
            else:
                console.print(f"  [dim]⏳ {event.friendly_name}…[/dim]")

        elif isinstance(event, ToolEndEvent):
            if plain:
                status = "✓" if event.success else "✗"
                print(
                    f"  {status} {event.tool_name} ({event.duration_seconds:.2f}s)",
                    flush=True,
                )
            else:
                icon = "✅" if event.success else "❌"
                color = "green" if event.success else "red"
                console.print(
                    f"  [{color}]{icon} {event.friendly_name} "
                    f"({event.duration_seconds:.2f}s)[/{color}]"
                )

        elif isinstance(event, FinalOutputEvent):
            output = (
                event.output
                if isinstance(event.output, dict)
                else event.output.to_dict()
            )
            if (
                "complete_report" in output
                and output["complete_report"]
            ):
                try:
                    from starboard_server.agents.report_formatters import (
                        format_agent_report,
                    )

                    formatted_markdown = format_agent_report(
                        output["complete_report"]
                    )
                except Exception:
                    pass

        elif isinstance(event, UserInputRequestEvent):
            console.print(
                f"\n[yellow]🤔 Agent asks: {event.question}[/yellow]"
            )

        elif isinstance(event, ErrorEvent):
            console.print(
                f"\n[bold red]❌ {event.error_type}: {event.error}[/bold red]"
            )
            raise RuntimeError(f"{event.error_type}: {event.error}")

    # Display the report
    if formatted_markdown:
        console.print()
        if plain:
            print(formatted_markdown)
        else:
            console.print(formatted_markdown)
