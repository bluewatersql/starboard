# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Internal-deployment configuration for the gated adapters (Phase-3 O1).

Internal-index-only. This module reads the **internal deployment env** that wires
the four gated adapters (D6 logs-summariser + dbr-doctor, D7 centralized fleet,
D8 curated Genie) to their real backends. It is the single place the internal
endpoint/credential env-var names live, so governance stays confined here.

Design (matches the additive-gate invariant, UNIFIED_PLAN §3.5):

* Each ``*Config.from_env`` returns a populated config when **all** required env
  vars are present, else ``None``. A ``None`` config is not an error — it means
  "this deployment has not wired the internal backend", and the adapter falls
  back to an *unwired* backend whose methods raise a clean, actionable
  :class:`MissingInternalConfigError` (never a silent stub).
* Reading the env never performs I/O and never raises; construction stays cheap
  so ``PortAdapterProvider.create()`` succeeds with the gate closed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

#: Default HTTP timeout (seconds) for the bespoke internal services.
_DEFAULT_TIMEOUT = 30.0


class MissingInternalConfigError(RuntimeError):
    """A gated internal adapter was invoked without its deployment env wired.

    Subclasses :class:`RuntimeError` so existing ``pytest.raises(RuntimeError)``
    call sites keep matching; the message names the exact env vars to set.
    """


def missing_config_message(
    adapter: str, backend: str, required: tuple[str, ...], inject_hint: str
) -> str:
    """Build the actionable "not wired" message for an unwired backend."""
    return (
        f"{adapter} requires internal {backend} runtime access and is not wired: "
        f"set {', '.join(required)} in the internal deployment env, "
        f"or inject a {inject_hint} (tests do this). "
        "With the gate closed the public adapter remains the universal path."
    )


def _timeout(env: Mapping[str, str], name: str) -> float:
    raw = env.get(name)
    if not raw:
        return _DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT


@dataclass(frozen=True)
class LogsSummariserConfig:
    """Connection config for the logs-summariser indexed-triage service (D6)."""

    url: str
    token: str
    kube_context: str | None = None
    timeout: float = _DEFAULT_TIMEOUT

    #: Env vars that must all be present for the backend to be wired.
    REQUIRED: ClassVar[tuple[str, ...]] = (
        "STARBOARD_INTERNAL_LOGS_SUMMARISER_URL",
        "STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN",
    )

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> LogsSummariserConfig | None:
        env = os.environ if env is None else env
        url = env.get("STARBOARD_INTERNAL_LOGS_SUMMARISER_URL")
        token = env.get("STARBOARD_INTERNAL_LOGS_SUMMARISER_TOKEN")
        if not url or not token:
            return None
        return cls(
            url=url.rstrip("/"),
            token=token,
            kube_context=env.get("STARBOARD_INTERNAL_LOGS_SUMMARISER_KUBE_CONTEXT")
            or None,
            timeout=_timeout(env, "STARBOARD_INTERNAL_LOGS_SUMMARISER_TIMEOUT"),
        )


@dataclass(frozen=True)
class DbrDoctorConfig:
    """Connection config for the dbr-doctor semantic-layer + trace-RCA service (D6)."""

    url: str
    token: str
    timeout: float = _DEFAULT_TIMEOUT

    REQUIRED: ClassVar[tuple[str, ...]] = (
        "STARBOARD_INTERNAL_DBR_DOCTOR_URL",
        "STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN",
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DbrDoctorConfig | None:
        env = os.environ if env is None else env
        url = env.get("STARBOARD_INTERNAL_DBR_DOCTOR_URL")
        token = env.get("STARBOARD_INTERNAL_DBR_DOCTOR_TOKEN")
        if not url or not token:
            return None
        return cls(
            url=url.rstrip("/"),
            token=token,
            timeout=_timeout(env, "STARBOARD_INTERNAL_DBR_DOCTOR_TIMEOUT"),
        )


@dataclass(frozen=True)
class FleetSqlConfig:
    """Databricks SQL-warehouse config for the centralized cross-account tables (D7).

    The workspace host/token fall through to the SDK's default credential chain
    when not set explicitly; only the warehouse id is strictly required (the
    centralized tables live behind one governed warehouse).
    """

    warehouse_id: str
    host: str | None = None
    token: str | None = None
    catalog: str | None = None
    wait_timeout: str = "50s"

    REQUIRED: ClassVar[tuple[str, ...]] = ("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID",)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> FleetSqlConfig | None:
        env = os.environ if env is None else env
        warehouse_id = env.get("STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID")
        if not warehouse_id:
            return None
        return cls(
            warehouse_id=warehouse_id,
            host=env.get("STARBOARD_INTERNAL_FLEET_HOST") or None,
            token=env.get("STARBOARD_INTERNAL_FLEET_TOKEN") or None,
            catalog=env.get("STARBOARD_INTERNAL_FLEET_CATALOG") or None,
        )


@dataclass(frozen=True)
class GenieConfig:
    """Databricks Genie config for the curated rooms (D8).

    ``spaces`` maps a curated-room key (see :mod:`starboard_internal._genie_rooms`)
    to its Genie space id; it is supplied as a JSON object in
    ``STARBOARD_INTERNAL_GENIE_SPACES`` so no space id is hard-coded in source.
    """

    spaces: Mapping[str, str] = field(default_factory=dict)
    host: str | None = None
    token: str | None = None

    REQUIRED: ClassVar[tuple[str, ...]] = ("STARBOARD_INTERNAL_GENIE_SPACES",)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GenieConfig | None:
        env = os.environ if env is None else env
        raw_spaces = env.get("STARBOARD_INTERNAL_GENIE_SPACES")
        if not raw_spaces:
            return None
        try:
            parsed = json.loads(raw_spaces)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict) or not parsed:
            return None
        spaces = {str(k): str(v) for k, v in parsed.items()}
        return cls(
            spaces=spaces,
            host=env.get("STARBOARD_INTERNAL_GENIE_HOST") or None,
            token=env.get("STARBOARD_INTERNAL_GENIE_TOKEN") or None,
        )
