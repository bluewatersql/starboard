# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Networking / security-posture query pack.

Surfaces denied network access attempts and egress blocks from
``system.access.inbound_network`` and ``system.access.outbound_network``.

Note: the network-access system tables are in Public Preview; queries are
marked ``required=False`` so a missing table degrades the individual query
rather than the whole domain.
"""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

NET_01_SQL = """\
SELECT
  event_date,
  destination_type,
  COUNT(*)                        AS denied_connections,
  COUNT(DISTINCT workspace_id)    AS affected_workspaces
FROM system.access.outbound_network
WHERE event_date >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND access_result = 'DENIED'
GROUP BY ALL
ORDER BY event_date DESC, denied_connections DESC
LIMIT 200
"""


NETWORKING_PACK = QueryPack(
    pack_id="networking",
    domain="governance",
    name="Networking & Egress",
    description=(
        "Denied network connections and egress blocks from the network-access "
        "system tables — a security-posture signal."
    ),
    queries=(
        SystemQuery(
            query_id="NET-01",
            name="Denied outbound connections by day",
            description=(
                "Denied outbound network connections grouped by day and "
                "destination type over the lookback window."
            ),
            sql_template=NET_01_SQL,
            required_tables=("system.access.outbound_network",),
            domain="governance",
            required=False,  # Preview table — degrade gracefully if absent
            category=QueryCategory.GOVERNANCE,
            metadata=QueryMetadata(
                summary="Surfaces denied egress / network-policy blocks over time.",
                output_hint="Rows per day with denied-connection counts.",
                tags=("networking", "security", "egress"),
            ),
        ),
    ),
    gating_products=frozenset({"NETWORKING"}),
)
