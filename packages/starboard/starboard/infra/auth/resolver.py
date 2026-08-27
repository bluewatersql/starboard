# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unified Databricks auth resolver (auth by subtraction).

One resolver builds every ``WorkspaceClient`` in the codebase. Host/token are
optional: only the inputs that are explicitly set are passed to the SDK; the
rest fall through to the SDK's ``DefaultCredentials`` chain (PAT, OAuth,
profile, .databrickscfg, ambient runtime, ...).

Precedence (highest first)::

    explicit --profile
      > explicit --host/--token/--client-id/...        (inline overrides)
        > STARBOARD_WORKSPACE -> profile
          > DATABRICKS_CONFIG_PROFILE
            > DATABRICKS_HOST (+ TOKEN | CLIENT_ID/SECRET)   [SDK env layer]
              > .databrickscfg DEFAULT profile              [SDK file layer]
                > ambient runtime / model serving          [SDK runtime layer]

``resolve()`` decides layers 1-4; the SDK handles 5-7.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config


@dataclass(frozen=True)
class WorkspaceTarget:
    """Everything needed to point the SDK at a workspace.

    All fields are optional — absence means "let the SDK unified auth chain
    decide". Only populated fields are ever passed to :class:`Config`.
    """

    host: str | None = None
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    profile: str | None = None
    config_file: str | None = None
    # Force a strategy: "pat" | "databricks-cli" | "oauth-m2m" | ...
    auth_type: str | None = None
    warehouse_id: str | None = None

    @classmethod
    def resolve(
        cls,
        *,
        profile: str | None = None,
        host: str | None = None,
        token: str | None = None,
        cfg: Any | None = None,
    ) -> WorkspaceTarget:
        """Apply Starboard precedence into a target.

        Only fields that are explicitly set are populated; everything else falls
        to the SDK. ``cfg`` (an ``EnvConfig``-like object) supplies host/token/
        warehouse when not passed inline.

        Args:
            profile: Explicit profile name (highest precedence).
            host: Explicit workspace host.
            token: Explicit PAT.
            cfg: Optional config object with ``databricks_host`` /
                ``databricks_token`` / ``databricks_warehouse_id`` attributes.
        """
        profile = (
            profile
            or os.environ.get("STARBOARD_WORKSPACE")  # friendly alias
            or os.environ.get("DATABRICKS_CONFIG_PROFILE")
        )
        return cls(
            profile=profile,
            host=host or (getattr(cfg, "databricks_host", None) if cfg else None),
            token=token or (getattr(cfg, "databricks_token", None) if cfg else None),
            client_id=os.environ.get("DATABRICKS_CLIENT_ID"),
            client_secret=os.environ.get("DATABRICKS_CLIENT_SECRET"),
            auth_type=os.environ.get("DATABRICKS_AUTH_TYPE"),
            warehouse_id=(
                getattr(cfg, "databricks_warehouse_id", None) if cfg else None
            ),
        )


def build_config(target: WorkspaceTarget) -> Config:
    """Build an SDK ``Config`` passing ONLY the fields that are set.

    Unset fields are omitted so the SDK's credential chain can resolve them.
    Crucially, this never injects an empty host/token (the previous behavior).

    Precedence is enforced by *subtraction* so the SDK is never handed conflicting
    authorization methods (which raises "more than one authorization method
    configured"):

    - When ``profile`` is set it is the source of truth (it carries its own host
      and auth), so inline ``host``/``token`` and ambient ``client_id``/``client_secret``
      are dropped — honoring the documented ``--profile`` > host/token precedence.
    - Otherwise, an explicit ``token`` (PAT) wins over ambient env
      ``client_id``/``client_secret``. ``host`` + ``client_id``/``client_secret``
      (OAuth M2M) remain valid together.
    """
    host = target.host
    token = target.token
    client_id = target.client_id
    client_secret = target.client_secret

    if target.profile:
        host = token = client_id = client_secret = None
    elif token:
        client_id = client_secret = None

    kwargs: dict[str, Any] = {
        k: v
        for k, v in {
            "host": host,
            "token": token,
            "client_id": client_id,
            "client_secret": client_secret,
            "profile": target.profile,
            "config_file": target.config_file,
            "auth_type": target.auth_type,
            "warehouse_id": target.warehouse_id,
        }.items()
        if v
    }
    return Config(**kwargs)


def resolve_workspace_client(
    target: WorkspaceTarget | None = None,
    *,
    credentials_strategy: Any | None = None,
) -> WorkspaceClient:
    """Build a ``WorkspaceClient`` from a target (or a fully-resolved default).

    Args:
        target: The workspace target; if omitted, resolved from env/ambient.
        credentials_strategy: Optional SDK credentials strategy (e.g.
            ``ModelServingUserCredentials()`` for Apps OBO).
    """
    target = target or WorkspaceTarget.resolve()
    cfg = build_config(target)
    if credentials_strategy is not None:
        return WorkspaceClient(config=cfg, credentials_strategy=credentials_strategy)
    return WorkspaceClient(config=cfg)


def describe_auth(w: WorkspaceClient) -> dict[str, Any]:
    """Return a redacted description of the resolved auth — safe to log/show.

    Only exposes host / auth_type / profile / user. Never returns token or
    client-secret values.
    """
    return {
        "host": w.config.host,
        "auth_type": w.config.auth_type,
        "profile": w.config.profile,
        "user": w.current_user.me().user_name,
    }


# =============================================================================
# Internal-data enablement gate — employee-context detector (Phase-2 C5, D-2.7)
# =============================================================================
# A closed-by-default detector on the auth resolver. It reports whether an
# *internal context* is present using three signals, and whether the gate should
# open (context AND authorized). It reuses ``describe_auth()``'s host/user and
# never inspects secrets.
#
# The allowlist is CONFIG-DRIVEN and EMPTY by default — no customer (or internal)
# host is ever hard-coded here, so the default is closed (public path). Because
# no internal adapter ships in Phase 2, a wrong signal cannot leak data: the port
# registry still selects the public adapter (additive invariant, §3.5).

# Env markers that indicate internal MCP tools / entitlements are present.
# Values are conventional Starboard env keys; their mere presence is the signal
# (never their content). No internal tool identifier is hard-coded.
_INTERNAL_MCP_ENV_MARKERS: tuple[str, ...] = (
    "STARBOARD_INTERNAL_MCP",
    "STARBOARD_INTERNAL_ADAPTERS",
)

# Env markers that indicate an Isaac-managed identity.
_ISAAC_IDENTITY_ENV_MARKERS: tuple[str, ...] = (
    "ISAAC_MANAGED_IDENTITY",
    "ISAAC_SESSION_ID",
)


@dataclass(frozen=True)
class EmployeeContext:
    """Result of employee-context detection.

    Attributes:
        is_internal_context: Whether ≥1 internal-context signal matched.
        authorized: Whether the user/deployment is an authorized employee.
        signals: The signals that matched (for observability; never secrets).
    """

    is_internal_context: bool
    authorized: bool
    signals: tuple[str, ...] = ()

    @property
    def gate_open(self) -> bool:
        """The gate opens only with an internal context AND authorization."""
        return self.is_internal_context and self.authorized


def detect_employee_context(
    *,
    host: str | None = None,
    user: str | None = None,  # noqa: ARG001 - reserved for future identity checks
    allowlist: list[str] | tuple[str, ...] | None = None,
    authorized: bool = True,
    env: dict[str, str] | None = None,
) -> EmployeeContext:
    """Detect internal context from host allowlist + identity + MCP signals.

    Default is **closed**: with an empty allowlist and no env markers, no signal
    matches and ``gate_open`` is ``False`` (the public path).

    Args:
        host: Resolved workspace host (from ``describe_auth``); matched
            case-insensitively as a substring against ``allowlist`` entries.
        user: Resolved user (reserved; not required to detect context today).
        allowlist: Config-driven internal workspace hosts. **Empty/None =>
            closed.** Never hard-code a customer host here.
        authorized: Whether the caller is an authorized employee. The gate never
            opens when this is ``False``, even with a context signal.
        env: Environment mapping to inspect (defaults to ``os.environ``).

    Returns:
        An :class:`EmployeeContext`.
    """
    env = env if env is not None else dict(os.environ)
    allowlist = tuple(allowlist or ())
    signals: list[str] = []

    # Signal 1: resolved workspace host is in the internal allowlist.
    if host and allowlist:
        host_lower = host.lower()
        for entry in allowlist:
            if entry and entry.lower() in host_lower:
                signals.append(f"host_allowlist:{entry}")
                break

    # Signal 2: an Isaac-managed identity is present.
    if any(env.get(marker) for marker in _ISAAC_IDENTITY_ENV_MARKERS):
        signals.append("isaac_identity")

    # Signal 3: internal MCP tools / entitlements are present.
    for marker in _INTERNAL_MCP_ENV_MARKERS:
        if env.get(marker):
            signals.append(f"internal_mcp:{marker}")
            break

    return EmployeeContext(
        is_internal_context=bool(signals),
        authorized=authorized,
        signals=tuple(signals),
    )


def detect_employee_context_for_client(
    w: WorkspaceClient,
    *,
    allowlist: list[str] | tuple[str, ...] | None = None,
    authorized: bool = True,
    env: dict[str, str] | None = None,
) -> EmployeeContext:
    """Detect employee context for a resolved client via ``describe_auth``.

    Reuses the redacted ``describe_auth()`` output (host/user only — never a
    token) so detection can never observe secrets.
    """
    info = describe_auth(w)
    return detect_employee_context(
        host=info.get("host"),
        user=info.get("user"),
        allowlist=allowlist,
        authorized=authorized,
        env=env,
    )
