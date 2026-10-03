# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Derive a Databricks serving-endpoint bearer token from the unified auth resolver.

When the LLM endpoint is a Databricks Foundation Model serving endpoint
(``LLM_BASE_URL`` points at a Databricks workspace), the bearer token should come
from the **same authenticated credential** the rest of the app already resolves
(``--profile`` / OAuth / PAT / ambient), obtained *fresh* via the SDK — not from a
separate, easily-stale ``LLM_API_KEY``. This mirrors the data client, which
authenticates via ``sdk.config.authenticate()`` under every auth mode.

Resolution is best-effort: when the endpoint is not a Databricks serving endpoint,
or the credential cannot be resolved, callers fall back to the configured
``LLM_API_KEY`` (see :func:`starboard.adapters.llm.create_llm_client`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starboard.infra.auth.resolver import WorkspaceTarget, resolve_workspace_client
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.core.config import EnvConfig

logger = get_logger(__name__)

_BEARER_PREFIX = "Bearer "


def is_databricks_serving_url(base_url: str | None) -> bool:
    """Return True when ``base_url`` targets a Databricks serving endpoint.

    Databricks workspace hosts (AWS/Azure/GCP) all contain ``databricks`` in the
    domain (e.g. ``*.cloud.databricks.com``, ``*.azuredatabricks.net``,
    ``*.gcp.databricks.com``), so a substring check is sufficient. A false match
    only costs a best-effort token resolution that falls back to ``LLM_API_KEY``.
    """
    return bool(base_url) and "databricks" in (base_url or "").lower()


def resolve_serving_bearer_token(cfg: EnvConfig) -> str | None:
    """Return a fresh Databricks bearer token for the LLM serving endpoint, or None.

    ``None`` means "not a Databricks serving endpoint, or the credential could not
    be resolved" — the caller then falls back to the configured ``LLM_API_KEY``.

    Args:
        cfg: Environment configuration (reads ``llm_base_url`` + Databricks auth).
    """
    if not is_databricks_serving_url(getattr(cfg, "llm_base_url", None)):
        return None
    try:
        target = WorkspaceTarget.resolve(cfg=cfg)
        client = resolve_workspace_client(target)
        headers = client.config.authenticate() or {}
    except Exception as exc:  # noqa: BLE001 - auth boundary; caller falls back to env
        logger.debug(
            "llm_databricks_token_resolution_failed", extra={"error": str(exc)}
        )
        return None

    auth = str(headers.get("Authorization", ""))
    if auth.startswith(_BEARER_PREFIX):
        return auth[len(_BEARER_PREFIX) :].strip() or None
    return None
