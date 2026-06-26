# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Lineage service for UC table lineage queries.

Handles fetching and transforming table lineage data from the
Databricks lineage REST API.
"""

from __future__ import annotations

from starboard_core.domain.models.uc import (
    LineageNode,
    TableLineage,
)
from starboard_core.domain.transformers import LineageGraphTransformer

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import UCServiceBase

logger = get_logger(__name__)


class LineageService(UCServiceBase):
    """Service for table lineage operations."""

    async def fetch_table_lineage(
        self,
        table_name: str,
        max_items: int = 10,
    ) -> TableLineage:
        """Fetch table lineage with transformer for LLM context.

        The Databricks lineage REST API returns only direct (1-hop) dependencies.
        For transitive lineage, query system.access.table_lineage system table.

        Args:
            table_name: Fully qualified table name
            max_items: Maximum items to return per direction (upstream/downstream)

        Returns:
            TableLineage with summarized upstream/downstream
        """
        logger.debug("fetching_table_lineage", table_name=table_name)

        if not self.lineage_provider:
            logger.warning("lineage_provider_not_configured")
            return TableLineage(
                table_name=table_name,
                upstream=(),
                downstream=(),
                truncated=False,
            )

        raw_lineage = await self.lineage_provider.get_table_lineage(table_name)
        if not raw_lineage:
            logger.debug("no_lineage_found", table_name=table_name)
            return TableLineage(
                table_name=table_name,
                upstream=(),
                downstream=(),
                truncated=False,
            )

        # Transform raw API response
        transformer = LineageGraphTransformer(max_items=max_items)
        summary = transformer.transform(raw_lineage)

        # Convert to domain models
        upstream = tuple(
            LineageNode(
                table_name=n["table"],
                catalog=n["table"].split(".")[0] if "." in n["table"] else "",
                schema=n["table"].split(".")[1] if n["table"].count(".") >= 1 else "",
                table_type=n.get("table_type", "UNKNOWN"),
                job_count=n.get("job_count", 0),
                notebook_count=n.get("notebook_count", 0),
                job_ids=tuple(n.get("job_ids", [])),
                notebook_ids=tuple(n.get("notebook_ids", [])),
                last_updated=n.get("last_updated"),
            )
            for n in summary["upstream_summary"]
        )

        downstream = tuple(
            LineageNode(
                table_name=n["table"],
                catalog=n["table"].split(".")[0] if "." in n["table"] else "",
                schema=n["table"].split(".")[1] if n["table"].count(".") >= 1 else "",
                table_type=n.get("table_type", "UNKNOWN"),
                job_count=n.get("job_count", 0),
                notebook_count=n.get("notebook_count", 0),
                job_ids=tuple(n.get("job_ids", [])),
                notebook_ids=tuple(n.get("notebook_ids", [])),
                last_updated=n.get("last_updated"),
            )
            for n in summary["downstream_summary"]
        )

        return TableLineage(
            table_name=table_name,
            upstream=upstream,
            downstream=downstream,
            truncated=summary["truncated"],
        )
