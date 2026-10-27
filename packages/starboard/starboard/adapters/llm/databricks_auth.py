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
from urllib.parse import urlsplit

from starboard_core.engagement.identity import normalize_host

from starboard.infra.auth.resolver import WorkspaceTarget, resolve_workspace_client
from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard.infra.core.config import EnvConfig

logger = get_logger(__name__)

_BEARER_PREFIX = "Bearer "


# Databricks-operated DNS suffixes (AWS/Azure/GCP, GovCloud, DoD, Apps). A host
# is trusted only when it equals one of these or is a subdomain of one.
DATABRICKS_HOST_SUFFIXES: tuple[str, ...] = (
    "cloud.databricks.com",
    "azuredatabricks.net",
    "gcp.databricks.com",
    "databricks.com",
    "cloud.databricks.us",
    "cloud.databricks.mil",
    "databricksapps.com",
)


def is_databricks_serving_url(base_url: str | None) -> bool:
    """Return True when ``base_url`` targets a Databricks serving endpoint.

    The workspace bearer token is sent to this URL, so the check is exact: the
    URL must use ``https`` and its parsed hostname must equal, or end with
    ``.`` + one of, :data:`DATABRICKS_HOST_SUFFIXES`. A ``databricks`` substring
    elsewhere (another domain, the path, query, fragment or userinfo) does not
    match. Non-matches fall back to ``LLM_API_KEY``.
    """
    if not base_url:
        return False
    try:
        parsed = urlsplit(base_url.strip())
        hostname = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not hostname:
        return False
    hostname = hostname.rstrip(".")
    return any(
        hostname == suffix or hostname.endswith("." + suffix)
        for suffix in DATABRICKS_HOST_SUFFIXES
    )


def _host(url_or_host: object) -> str | None:
    """Normalized ``https://<host>[:port]`` of a URL or bare host, or None."""
    if not isinstance(url_or_host, str):
        return None
    try:
        return normalize_host(url_or_host)
    except ValueError:
        return None


def resolve_serving_bearer_token(cfg: EnvConfig) -> str | None:
    """Return a fresh Databricks bearer token for the LLM serving endpoint, or None.

    ``None`` means "not a Databricks serving endpoint, or no credential that is
    valid for the serving host" — the caller then falls back to ``LLM_API_KEY``.

    The serving identity is independent of the customer data profile:

    - ``LLM_DATABRICKS_PROFILE`` set: that profile only; its host must equal the
      serving URL host.
    - Overlay install without it: never the data profile (``None``).
    - Public install: the data credential is reused only when its host equals the
      serving URL host; a different host never receives the data token.

    Args:
        cfg: Environment configuration (reads ``llm_base_url``,
            ``llm_databricks_profile`` + Databricks auth).
    """
    base_url = getattr(cfg, "llm_base_url", None)
    if not is_databricks_serving_url(base_url):
        return None
    serving_host = _host(base_url)

    serving_profile = (getattr(cfg, "llm_databricks_profile", "") or "").strip()
    if serving_profile:
        target = WorkspaceTarget(profile=serving_profile)
    elif cfg.overlay_enabled:
        logger.warning(
            "llm_serving_identity_not_configured",
            extra={"hint": "set LLM_DATABRICKS_PROFILE or LLM_API_KEY"},
        )
        return None
    else:
        target = None

    try:
        client = resolve_workspace_client(
            target if target is not None else WorkspaceTarget.resolve(cfg=cfg)
        )
        credential_host = _host(client.config.host)
        if credential_host is None or credential_host != serving_host:
            logger.debug(
                "llm_serving_credential_host_mismatch",
                extra={
                    "credential_host": credential_host,
                    "serving_host": serving_host,
                },
            )
            return None
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
