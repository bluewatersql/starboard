# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Identity-only customer-workspace check (engagement-drive spec §1, bootstrap).

Before any row, log or code acquisition, the provisional account's expected
workspace is compared with what the workspace itself proves: its server
workspace ID and host, plus the calling principal's opaque ID and kind. The
expected workspace ID comes from the operator (``--workspace-id`` or a
``ws-<id>`` task name), never from a profile name. The caller performs the
read-only SDK calls; this module only compares and records.

Standard library only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from starboard_core.engagement.records import (
    IdentityCheck,
    IdentityStatus,
    PrincipalKind,
    ProvisionalSource,
    RunAuthorization,
)

_DEFAULT_PORTS = {"https": 443, "http": 80}

SCIM_ME_PATH = "/api/2.0/preview/scim/v2/Me"
"""Read-only current-principal endpoint whose response proves the workspace ID."""

ORG_ID_HEADER = "X-Databricks-Org-Id"
"""Response header carrying the server-reported workspace ID."""


def parse_org_id(value: object) -> str:
    """Return the server-reported workspace ID from an ``ORG_ID_HEADER`` value.

    Raises:
        ValueError: Missing, empty or not ASCII digits.
    """
    workspace_id = str(value or "").strip()
    if not (workspace_id.isascii() and workspace_id.isdigit()):
        raise ValueError(
            f"server did not report a numeric workspace ID ({ORG_ID_HEADER})"
        )
    return workspace_id


def normalize_host(url: str) -> str:
    """Return ``https://<lowercase hostname>[:port]`` for a workspace URL or host.

    Drops the path, query, fragment, user info, a trailing dot and the scheme's
    default port; a bare host gets ``https://``. ``http`` URLs normalize to
    ``https`` (identity is the host, not the transport).

    Raises:
        ValueError: Empty input, a scheme other than ``http``/``https`` or no
            hostname.
    """
    raw = url.strip() if isinstance(url, str) else ""
    if not raw:
        raise ValueError("host must be a non-empty URL or hostname")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError(f"host must use https, got {url!r}")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise ValueError(f"no hostname in {url!r}")
    port = parts.port
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"https://{host}"
    return f"https://{host}:{port}"


def check_identity(
    *,
    run_id: str,
    provisional_account_key: str,
    provisional_account_name: str,
    provisional_source: ProvisionalSource,
    expected_workspace_id: str,
    expected_host: str | None,
    observed_workspace_id: str,
    observed_host: str,
    principal_id: str,
    principal_kind: PrincipalKind,
    checked_at: str | None = None,
    workspace_profile: str | None = None,
) -> IdentityCheck:
    """Compare the expected workspace with the server-proven one.

    The result is ``verified`` only when an expected workspace ID was supplied
    and equals the observed one, and (when ``expected_host`` is given) the
    normalized hosts are equal. Otherwise it is ``mismatch`` with one reason per
    failed comparison; an empty expected workspace ID is itself the reason
    ``"no expected workspace id"``. ``workspace_profile`` (the ``--profile`` the
    caller's client used, ``None`` for ``--host``) is recorded as-is and compared
    with nothing.

    Raises:
        ValueError: Invalid inputs (see :class:`IdentityCheck`), including an
            email address passed as ``principal_id``.
    """
    expected_ws = str(expected_workspace_id).strip()
    observed_ws = str(observed_workspace_id).strip()
    observed = normalize_host(observed_host)
    expected = None if expected_host is None else normalize_host(expected_host)

    reasons: list[str] = []
    if not expected_ws:
        reasons.append("no expected workspace id")
    elif expected_ws != observed_ws:
        reasons.append(
            f"workspace id differs: expected {expected_ws}, observed {observed_ws}"
        )
    if expected is not None and expected != observed:
        reasons.append(f"host differs: expected {expected}, observed {observed}")
    status: IdentityStatus = "mismatch" if reasons else "verified"

    return IdentityCheck(
        run_id=run_id,
        provisional_account_key=provisional_account_key,
        provisional_account_name=provisional_account_name,
        provisional_source=provisional_source,
        expected_workspace_id=expected_ws,
        expected_host=expected,
        observed_workspace_id=observed_ws,
        observed_host=observed,
        principal_id=principal_id,
        principal_kind=principal_kind,
        checked_at=checked_at or datetime.now(UTC).isoformat(),
        status=status,
        reasons=tuple(reasons),
        workspace_profile=workspace_profile or None,
    )


class ProfileMismatch(ValueError):
    """A fetch named a profile other than the one the run was verified with.

    The message starts with ``PROFILE_MISMATCH``.
    """


def run_profile(auth: RunAuthorization, given: str | None) -> str | None:
    """Return the profile a workspace read on this run must use.

    On a run whose customer identity was verified (``authorized_scope.basis ==
    "verified"``) the verified identity is the one that fetches: an omitted
    ``given`` becomes the recorded ``workspace_profile``, and a different one is
    refused. A run verified with ``--host`` recorded no profile, so any ``given``
    is refused there (its reads use the same ambient auth the check did). Other
    runs (declared / internal-only scope) return ``given`` unchanged.

    Raises:
        ProfileMismatch: ``given`` differs from the verified profile.
    """
    if auth.authorized_scope.get("basis") != "verified":
        return given
    recorded = auth.workspace_profile
    if not given or given == recorded:
        return recorded
    if recorded is None:
        raise ProfileMismatch(
            f"PROFILE_MISMATCH: run {auth.run_id} was verified with --host, not a "
            f"profile; omit --profile {given!r} (reads use the verified ambient auth), "
            "or start a new run verified with that profile"
        )
    raise ProfileMismatch(
        f"PROFILE_MISMATCH: run {auth.run_id} was verified with --profile "
        f"{recorded!r}; --profile {given!r} is a different identity. Omit --profile "
        f"(it defaults to {recorded!r}) or start a new run verified with {given!r}"
    )


__all__ = [
    "ORG_ID_HEADER",
    "SCIM_ME_PATH",
    "ProfileMismatch",
    "check_identity",
    "normalize_host",
    "parse_org_id",
    "run_profile",
]
