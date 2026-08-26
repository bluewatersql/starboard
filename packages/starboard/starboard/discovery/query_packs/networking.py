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

# NOTE: system.access.outbound_network is Public Preview; column names verified
# against current docs (2026-08). Denials are recorded in `access_type` = 'DROP'
# (dry-run rows use a distinct value); the table exposes `event_time` (timestamp),
# not an `event_date` column. Still worth live-workspace validation before this
# pack is relied upon — see changes/2026_26_25_agents/impl/phase0_review_findings.md.
NET_01_SQL = """\
SELECT
  date(event_time)                AS event_date,
  destination_type,
  COUNT(*)                        AS denied_connections,
  COUNT(DISTINCT workspace_id)    AS affected_workspaces
FROM system.access.outbound_network
WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
  AND access_type = 'DROP'
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
