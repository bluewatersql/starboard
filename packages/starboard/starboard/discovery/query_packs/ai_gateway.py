# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""AI Gateway discovery query pack.\n\nCovers endpoint requests, error rates, latency, and token usage."""

from __future__ import annotations

from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryCategory,
    QueryMetadata,
    QueryPack,
    SystemQuery,
)

_QUERIES = [
    SystemQuery(
        query_id="P-AG01", name="Endpoint Requests, Success Rate, and Tokens",
        description="Serving endpoint request volume and token counts",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT se.endpoint_name, se.served_entity_name, se.entity_type,
  COUNT(*) AS total_requests, COUNT_IF(eu.status_code BETWEEN 200 AND 299) AS successful_requests,
  COUNT_IF(eu.status_code >= 500) AS server_errors,
  SUM(eu.input_token_count + eu.output_token_count) AS total_tokens
FROM system.serving.endpoint_usage eu, cutoff
JOIN system.serving.served_entities se USING (served_entity_id)
WHERE eu.request_time >= cutoff.dt
GROUP BY se.endpoint_name, se.served_entity_name, se.entity_type
ORDER BY total_requests DESC
LIMIT {result_limit}""",
        required_tables=("system.serving.endpoint_usage", "system.serving.served_entities",), domain="ai_gateway", required=False,
        max_lookback_days=90,  # G5: serving.endpoint_usage retains ~90 days
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Serving endpoint request volume, success rate, and token counts", output_hint="Endpoints ranked by request volume"),
    ),
    SystemQuery(
        query_id="P-AG02", name="Error-Heavy Endpoints (AI Gateway)",
        description="AI Gateway endpoints with highest error rates",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT endpoint_name, COUNT(*) AS total_requests, COUNT_IF(status_code >= 500) AS server_errors,
  ROUND(COUNT_IF(status_code >= 500) * 100.0 / COUNT(*), 2) AS error_rate_pct
FROM system.ai_gateway.usage, cutoff
WHERE event_time >= cutoff.dt
GROUP BY endpoint_name HAVING COUNT(*) >= 50
ORDER BY error_rate_pct DESC, total_requests DESC
LIMIT {result_limit}""",
        required_tables=("system.ai_gateway.usage",), domain="ai_gateway", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.OPTIMIZATION,
        metadata=QueryMetadata(summary="AI Gateway endpoints with highest error rates", output_hint="Endpoints ranked by error rate"),
    ),
    SystemQuery(
        query_id="P-AG03", name="Endpoint Usage, Tokens, and Latency",
        description="Per-endpoint usage, total tokens, and latency percentiles",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT endpoint_name, COUNT(*) AS total_requests, SUM(total_tokens) AS total_tokens,
  ROUND(AVG(latency_ms), 1) AS avg_latency_ms,
  ROUND(APPROX_PERCENTILE(latency_ms, 0.95), 1) AS p95_latency_ms,
  COUNT_IF(status_code BETWEEN 200 AND 299) AS successful_requests,
  COUNT_IF(status_code >= 500) AS server_errors
FROM system.ai_gateway.usage, cutoff
WHERE event_time >= cutoff.dt
GROUP BY endpoint_name
ORDER BY total_requests DESC
LIMIT {result_limit}""",
        required_tables=("system.ai_gateway.usage",), domain="ai_gateway", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.PROFILE,
        metadata=QueryMetadata(summary="Per-endpoint usage, total tokens, and latency percentiles", output_hint="Endpoints with latency and token metrics"),
    ),
    SystemQuery(
        query_id="P-AG04", name="Cost by Requester and Endpoint",
        description="Token consumption attributed to requester identities",
        sql_template="""\
WITH cutoff AS (SELECT DATEADD(DAY, -{lookback_days}, CURRENT_TIMESTAMP()) AS dt)
SELECT requester, endpoint_name, COUNT(*) AS total_requests, SUM(total_tokens) AS total_tokens
FROM system.ai_gateway.usage, cutoff
WHERE event_time >= cutoff.dt
GROUP BY requester, endpoint_name
ORDER BY total_tokens DESC
LIMIT {result_limit}""",
        required_tables=("system.ai_gateway.usage",), domain="ai_gateway", required=False,
        discovery_mode=DiscoveryMode.GENERAL, category=QueryCategory.BILLING,
        metadata=QueryMetadata(summary="Token consumption attributed to requester identities", output_hint="Requesters ranked by token usage"),
    ),
]

AI_GATEWAY_PACK = QueryPack(
    pack_id="ai_gateway", domain="ai_gateway", name="AI Gateway",
    description="AI Gateway and model serving endpoint health and usage",
    queries=tuple(_QUERIES),
    gating_products=frozenset({"AI_GATEWAY", "MODEL_SERVING"}),
)
