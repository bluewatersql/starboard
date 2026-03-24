"""
Repository for clarification request persistence.

Provides CRUD operations for clarification requests and responses.
Uses PostgreSQL with the clarification_requests table from migration 005.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.clarification import (
    ClarificationOption,
    ClarificationRequest,
    ClarificationType,
)

from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from typing import Any as DatabaseClient  # type: ignore[attr-defined]

logger = get_logger(__name__)


class ClarificationRepository:
    """
    Repository for clarification request persistence.

    Handles saving and retrieving clarification requests and their resolutions.
    """

    def __init__(self, db_client: DatabaseClient) -> None:
        """
        Initialize the clarification repository.

        Args:
            db_client: PostgreSQL database client
        """
        self.db = db_client

    async def save(self, clarification: ClarificationRequest) -> None:
        """
        Save a clarification request to the database.

        Args:
            clarification: ClarificationRequest to save
        """
        query = """
        INSERT INTO clarification_requests (
            clarification_id,
            conversation_id,
            message_id,
            clarification_type,
            question,
            options,
            allow_custom_response,
            is_required,
            default_value,
            created_at,
            resolved_at,
            resolution
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        """

        options_json = None
        if clarification.options:
            options_json = json.dumps(
                [
                    {
                        "option_id": opt.option_id,
                        "display_text": opt.display_text,
                        "value": opt.value,
                        "is_recommended": opt.is_recommended,
                        "metadata": opt.metadata,
                    }
                    for opt in clarification.options
                ]
            )

        await self.db.execute(
            query,
            clarification.clarification_id,
            clarification.conversation_id,
            clarification.message_id,
            clarification.clarification_type.value,
            clarification.question,
            options_json,
            clarification.allow_custom_response,
            clarification.is_required,
            (
                json.dumps(clarification.default_value)
                if clarification.default_value
                else None
            ),
            clarification.created_at,
            clarification.resolved_at,
            json.dumps(clarification.resolution) if clarification.resolution else None,
        )

        logger.debug(
            "clarification_saved",
            clarification_id=clarification.clarification_id,
            conversation_id=clarification.conversation_id,
            clarification_type=clarification.clarification_type.value,
        )

    async def get_by_id(self, clarification_id: str) -> ClarificationRequest | None:
        """
        Retrieve a clarification request by ID.

        Args:
            clarification_id: Clarification identifier

        Returns:
            ClarificationRequest if found, None otherwise
        """
        query = """
        SELECT
            clarification_id,
            conversation_id,
            message_id,
            clarification_type,
            question,
            options,
            allow_custom_response,
            is_required,
            default_value,
            created_at,
            resolved_at,
            resolution
        FROM clarification_requests
        WHERE clarification_id = $1
        """

        row = await self.db.fetchone(query, clarification_id)

        if not row:
            return None

        options = None
        if row["options"]:
            options_data = json.loads(row["options"])
            options = tuple(
                ClarificationOption(
                    option_id=opt["option_id"],
                    display_text=opt["display_text"],
                    value=opt["value"],
                    is_recommended=opt.get("is_recommended", False),
                    metadata=opt.get("metadata"),
                )
                for opt in options_data
            )

        return ClarificationRequest(
            clarification_id=row["clarification_id"],
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
            clarification_type=ClarificationType(row["clarification_type"]),
            question=row["question"],
            options=options,
            allow_custom_response=row["allow_custom_response"],
            is_required=row["is_required"],
            default_value=(
                json.loads(row["default_value"]) if row["default_value"] else None
            ),
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolution=json.loads(row["resolution"]) if row["resolution"] else None,
        )

    async def update_resolution(
        self,
        clarification_id: str,
        resolution: Any,
    ) -> None:
        """
        Update the resolution for a clarification request.

        Args:
            clarification_id: Clarification identifier
            resolution: Resolution value
        """
        query = """
        UPDATE clarification_requests
        SET resolved_at = $1, resolution = $2
        WHERE clarification_id = $3
        """

        await self.db.execute(
            query,
            datetime.now(UTC),
            json.dumps(resolution),
            clarification_id,
        )

        logger.debug(
            "clarification_resolved",
            clarification_id=clarification_id,
        )
