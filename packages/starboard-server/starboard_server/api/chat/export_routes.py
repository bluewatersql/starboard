"""Conversation export endpoints.

Provides HTTP endpoints for exporting conversations:
- GET /conversations/{id}/export - Export conversation in markdown or JSON format
"""

from enum import StrEnum
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from starboard_server.api.dependencies import MultiAgentManagerDep
from starboard_server.api.ownership import verify_conversation_ownership
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ExportFormat(StrEnum):
    """Supported export formats."""

    MARKDOWN = "markdown"
    JSON = "json"


def _format_markdown(
    conversation_id: str,
    messages: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Format conversation as markdown."""
    lines: list[str] = []
    lines.append("# Conversation Export")
    lines.append("")
    lines.append(f"**Conversation ID:** {conversation_id}")

    if metadata:
        if metadata.get("created_at"):
            lines.append(f"**Created:** {metadata['created_at']}")
        if metadata.get("total_messages"):
            lines.append(f"**Messages:** {metadata['total_messages']}")
        if metadata.get("total_tokens"):
            lines.append(f"**Total Tokens:** {metadata['total_tokens']}")

    lines.append("")
    lines.append("---")
    lines.append("")

    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")

        lines.append(f"## {role}")
        if timestamp:
            lines.append(f"*{timestamp}*")
        lines.append("")
        lines.append(content)
        lines.append("")

        # Include tool calls if present
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            lines.append("> **Tool Calls:**")
            for tc in tool_calls:
                name = tc.get("tool_name", tc.get("friendly_name", "Unknown tool"))
                tc_status = tc.get("status", "")
                lines.append(f"> - {name} ({tc_status})")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


@router.get(
    "/conversations/{conversation_id}/export",
    summary="Export Conversation",
    description="Export a conversation in markdown or JSON format",
    responses={
        200: {"description": "Conversation exported successfully"},
        404: {"description": "Conversation not found"},
    },
)
async def export_conversation(
    conversation_id: str,
    request: Request,
    manager: MultiAgentManagerDep,
    format: ExportFormat = Query(
        default=ExportFormat.MARKDOWN, description="Export format"
    ),
) -> Any:
    """Export a conversation in the requested format.

    Args:
        conversation_id: Unique conversation identifier
        request: HTTP request (for ownership verification)
        manager: ConversationManager instance (injected)
        format: Export format (markdown or json)

    Returns:
        Conversation content in the requested format

    Raises:
        HTTPException: 404 if conversation not found
    """
    try:
        await verify_conversation_ownership(request, conversation_id, manager)

        history = await manager.get_history(conversation_id)

        if history is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        logger.info(
            "conversation_exported",
            conversation_id=conversation_id,
            format=format,
            message_count=len(history.messages),
        )

        # Serialize messages to dicts
        messages = [
            msg.model_dump(mode="json") if hasattr(msg, "model_dump") else dict(msg)
            for msg in history.messages
        ]
        metadata = (
            history.metadata.model_dump(mode="json")
            if hasattr(history, "metadata")
            and history.metadata
            and hasattr(history.metadata, "model_dump")
            else getattr(history, "metadata", None)
        )

        if format == ExportFormat.JSON:
            return JSONResponse(
                content={
                    "conversation_id": conversation_id,
                    "messages": messages,
                    "metadata": metadata,
                    "export_format": "json",
                },
                headers={
                    "Content-Disposition": f'attachment; filename="conversation_{conversation_id}.json"',
                },
            )

        # Markdown format
        markdown = _format_markdown(conversation_id, messages, metadata)
        return PlainTextResponse(
            content=markdown,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="conversation_{conversation_id}.md"',
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "conversation_export_failed",
            conversation_id=conversation_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to export conversation",
        ) from e
