# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Fast connectivity + auth preflight for Databricks workspace entry points.

Avoids the default 5-minute TCP/host-metadata timeout on DNS / network failures
by attempting a quick socket connection first, then one cheap authenticated API
call — both with a short ceiling (10–15 s). Errors are classified so the CLI
can report a one-line actionable message instead of a huge traceback.

Usage (discovery entry points call this before building the full engine)::

    result = check_connectivity(host, token_or_none, timeout=12)
    if not result.ok:
        # result.kind is "NETWORK" or "AUTH"
        print(result.message, file=sys.stderr)
        sys.exit(1)
"""

from __future__ import annotations

import socket
import urllib.parse
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of a connectivity + auth preflight check.

    Attributes:
        ok: ``True`` when the workspace is reachable and credentials resolved.
        kind: ``"NETWORK"`` (DNS / TCP failure), ``"AUTH"`` (credentials), or
              ``""`` (success).
        message: One-line user-facing message (empty when ok=True).
        host: The workspace host that was checked (for error attribution).
    """

    ok: bool
    kind: str  # "NETWORK" | "AUTH" | ""
    message: str
    host: str


def _parse_host(workspace_url: str) -> tuple[str, int]:
    """Return (hostname, port) from a workspace URL or bare hostname.

    Defaults to HTTPS port 443.
    """
    url = workspace_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urllib.parse.urlparse(url)
    hostname = parsed.hostname or url
    port = parsed.port or 443
    return hostname, port


def _tcp_reachable(hostname: str, port: int, timeout: float) -> bool:
    """Return True if we can open a TCP socket to (hostname, port)."""
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_connectivity(
    workspace_url: str | None,
    token: str | None = None,
    *,
    timeout: float = 12.0,
    _http_get: Any = None,
) -> PreflightResult:
    """Run a fast preflight check against a Databricks workspace.

    Steps:
    1. Resolve the workspace host from ``workspace_url``.
    2. TCP connect with ``timeout`` — classify ``NETWORK`` on failure.
    3. Perform one cheap authenticated GET (``/api/2.0/clusters/spark-versions``)
       with the same timeout — classify ``AUTH`` on 401/403 or missing token.

    Args:
        workspace_url: Workspace URL or hostname (e.g.
            ``https://myws.cloud.databricks.com`` or ``myws.cloud.databricks.com``).
            ``None`` or empty string skips the check (returns ok=True with a note).
        token: PAT or OAuth token for the quick auth check.  When ``None`` the
            auth step is skipped (the caller may use a profile-based client that
            doesn't need an inline token).
        timeout: Total seconds budget for each network operation (default 12 s).
        _http_get: Internal override for unit tests — callable matching
            ``requests.get`` / ``httpx.get`` signature, injected to avoid real
            network I/O in tests.

    Returns:
        A :class:`PreflightResult`.
    """
    if not workspace_url:
        return PreflightResult(ok=True, kind="", message="", host="(unknown)")

    url = workspace_url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    hostname, port = _parse_host(url)
    display_host = url.rstrip("/")

    # Step 1 — TCP reachability.
    if not _tcp_reachable(hostname, port, timeout=min(timeout, 10.0)):
        return PreflightResult(
            ok=False,
            kind="NETWORK",
            message=(
                f"cannot reach {display_host} — "
                "check network / VPN / sandbox connectivity"
            ),
            host=display_host,
        )

    # Step 2 — Quick authenticated API call (only when a token is available).
    if token:
        api_url = f"{display_host}/api/2.0/clusters/spark-versions"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if _http_get is not None:
                resp = _http_get(api_url, headers=headers, timeout=timeout)
                status = getattr(resp, "status_code", None) or getattr(resp, "code", 200)
                if isinstance(status, int) and status in (401, 403):
                    return PreflightResult(
                        ok=False,
                        kind="AUTH",
                        message=(
                            f"authentication failed for {display_host} "
                            f"(HTTP {status}) — check token / credentials"
                        ),
                        host=display_host,
                    )
            else:
                import urllib.error
                import urllib.request

                req = urllib.request.Request(api_url, headers=headers)
                ctx = _ssl_ctx()
                try:
                    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                        _ = r.read(1)
                except urllib.error.HTTPError as exc:
                    if exc.code in (401, 403):
                        return PreflightResult(
                            ok=False,
                            kind="AUTH",
                            message=(
                                f"authentication failed for {display_host} "
                                f"(HTTP {exc.code}) — check token / credentials"
                            ),
                            host=display_host,
                        )
                    # Other HTTP errors (404, 500, …) mean the host is reachable
                    # and auth passed (or is not being checked) — treat as ok.
        except OSError:
            # Network-level failure on the API call itself.
            return PreflightResult(
                ok=False,
                kind="NETWORK",
                message=(
                    f"cannot reach {display_host} — "
                    "check network / VPN / sandbox connectivity"
                ),
                host=display_host,
            )

    return PreflightResult(ok=True, kind="", message="", host=display_host)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ssl_ctx() -> Any:
    """Return an SSL context for the urllib request."""
    import ssl

    return ssl.create_default_context()


def profile_host(profile: str | None) -> str | None:
    """Host configured for ``profile`` in ~/.databrickscfg (no SDK call, no network)."""
    if not profile:
        return None
    import configparser
    import os

    cfg = configparser.ConfigParser()
    cfg.read(os.path.expanduser(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")))
    return cfg.get(profile, "host", fallback=None) if cfg.has_section(profile) else None


def preflight_target(
    ambient_host: str | None, ambient_token: str | None
) -> tuple[str | None, str | None]:
    """The (host, token) the run will actually use, for :func:`check_connectivity`.

    An active profile (``DATABRICKS_CONFIG_PROFILE``, set by ``--profile``) is
    authoritative over ambient ``DATABRICKS_HOST``/``DATABRICKS_TOKEN`` — the
    resolver masks the ambient vars — so preflight the profile's host and skip
    the inline-token auth step (the profile carries its own credentials).
    """
    import os

    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE")
    if profile:
        host = profile_host(profile)
        if host:
            return host, None
    return ambient_host, ambient_token
