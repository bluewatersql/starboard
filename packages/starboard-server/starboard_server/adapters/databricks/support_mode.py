"""Initialize Databricks support mode grants.

Executes system catalog grants for the Databricks support principal,
enabling Starboard to run inside Databricks support sessions.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from starboard_server.exceptions import DatabricksAPIError, PermissionDeniedError
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_server.adapters.databricks.services.sql import SQLService

logger = get_logger(__name__)

# The Databricks support principal name
_SUPPORT_PRINCIPAL = "DB - RESERVED - Databricks support"

# Session env var used as idempotency marker
_SUPPORT_ENV_KEY = "STARBOARD_DBX_SUPPORT"

# Grant statements to execute in order
_GRANT_STATEMENTS: tuple[str, ...] = (
    f"GRANT USE_CATALOG ON CATALOG system TO `{_SUPPORT_PRINCIPAL}`",
    f"GRANT USE_SCHEMA ON CATALOG system TO `{_SUPPORT_PRINCIPAL}`",
    f"GRANT SELECT ON CATALOG system TO `{_SUPPORT_PRINCIPAL}`",
)


class SupportModeInitializer:
    """Execute system catalog grants for Databricks support mode.

    Runs three GRANT statements against the system catalog to allow
    the Databricks support principal to read system tables. Uses a
    session environment variable as an idempotency marker so grants
    are only executed once per process lifecycle.

    Args:
        sql_service: Initialized SQLService with a valid warehouse ID.

    Example:
        >>> initializer = SupportModeInitializer(sql_service)
        >>> await initializer.initialize()
    """

    def __init__(self, sql_service: SQLService) -> None:
        self._sql = sql_service

    async def initialize(self) -> None:
        """Execute support mode grants if not already applied.

        Idempotency: checks STARBOARD_DBX_SUPPORT env var before
        executing. Sets it to "TRUE" after successful execution.

        Raises:
            DatabricksAPIError: If grant execution fails.
            PermissionDeniedError: If the current principal lacks GRANT privileges.
        """
        # Idempotency check
        if os.environ.get(_SUPPORT_ENV_KEY) == "TRUE":
            logger.debug("support_mode_already_initialized")
            return

        total = len(_GRANT_STATEMENTS)
        for idx, grant_sql in enumerate(_GRANT_STATEMENTS):
            logger.info(
                "support_mode_grant_executing",
                extra={
                    "grant_index": idx + 1,
                    "total_grants": total,
                    "grant_preview": grant_sql[:60],
                },
            )
            try:
                await self._sql.execute_polars(grant_sql)
            except Exception as exc:
                error_msg = str(exc).lower()
                if "403" in error_msg or "permission" in error_msg:
                    raise PermissionDeniedError(
                        "Permission denied executing GRANT on system catalog. "
                        "Verify the service principal has ADMIN or GRANT rights.",
                    ) from exc
                logger.error(
                    "support_mode_grant_failed",
                    extra={
                        "grant_index": idx + 1,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                raise DatabricksAPIError(
                    message=f"Support mode grant {idx + 1}/{total} failed: {exc}",
                ) from exc

            logger.info(
                "support_mode_grant_succeeded",
                extra={"grant_index": idx + 1, "total_grants": total},
            )

        # Only set idempotency marker after ALL grants succeed
        os.environ[_SUPPORT_ENV_KEY] = "TRUE"
        logger.info(
            "support_mode_initialized",
            extra={"grants_executed": total},
        )
