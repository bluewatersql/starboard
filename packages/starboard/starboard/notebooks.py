# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Synchronous bootstrap helpers for Databricks notebooks.

These utilities run *inside* a Databricks notebook cell, before the async
:class:`~starboard.sdk.StarboardClient` is created. They operate directly on a
raw Databricks SDK :class:`~databricks.sdk.WorkspaceClient` to:

- authenticate to a workspace (:func:`get_workspace`),
- resolve a SQL warehouse from an id, name, or ``"serverless"``
  (:func:`resolve_warehouse`),
- start a warehouse and optionally wait for it (:func:`start_warehouse`),
- enumerate model-serving endpoints for interactive widgets
  (:func:`list_serving_endpoints`).

They are deliberately **synchronous** — notebook cells are synchronous and these
run before any event loop / async client exists — and dependency-light so they
can populate widgets and set environment variables prior to bootstrap. The async
equivalents used at runtime live in
``starboard.adapters.databricks.services``; these are the notebook-time
counterparts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from starboard.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)

SERVERLESS = "serverless"
"""Sentinel target accepted by :func:`resolve_warehouse` for auto-selection."""

DEFAULT_START_TIMEOUT_S = 600
"""Default seconds to wait for a warehouse to reach the RUNNING state."""

DEFAULT_SERVING_PREFIX = "databricks-"
"""Default name prefix for foundation-model serving endpoints."""


def get_workspace(host: str, token: str) -> WorkspaceClient:
    """Authenticate to a Databricks workspace.

    Args:
        host: Workspace host (with or without scheme).
        token: Personal access token or notebook API token.

    Returns:
        An authenticated ``WorkspaceClient``.
    """
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(host=host, token=token)
    user = client.current_user.me().user_name
    logger.info("notebook_workspace_authenticated", host=host, user=user)
    print(f"Authenticated to {host} as: {user}")
    return client


def _is_serverless(endpoint: Any) -> bool:
    """Return True if the warehouse endpoint is serverless-enabled."""
    return bool(getattr(endpoint, "enable_serverless_compute", False))


def _state_name(endpoint_or_state: Any) -> str:
    """Normalize an SDK state (or endpoint) to a bare state name.

    Handles enum reprs like ``State.RUNNING`` -> ``RUNNING`` and accepts either a
    warehouse endpoint (reads ``.state``) or a state value directly.
    """
    state = getattr(endpoint_or_state, "state", endpoint_or_state)
    if state is None:
        return ""
    return str(state).split(".")[-1]


def resolve_warehouse(
    client: WorkspaceClient,
    target: str = SERVERLESS,
) -> dict[str, Any]:
    """Resolve a warehouse *id*, *name*, or ``"serverless"`` to a concrete one.

    Args:
        client: Authenticated ``WorkspaceClient``.
        target: A warehouse id, a warehouse name, or ``"serverless"`` (the
            default) to auto-select a serverless warehouse, preferring one that
            is already RUNNING.

    Returns:
        A dict with ``warehouse_id``, ``name``, ``serverless``, ``type``, and
        ``state`` keys.

    Raises:
        RuntimeError: If no serverless warehouse exists (for ``"serverless"``)
            or ``target`` matches no known id or name.
    """
    warehouses = list(client.warehouses.list())
    by_id = {wh.id: wh for wh in warehouses}

    if target in by_id:
        endpoint = by_id[target]
    elif target.lower() == SERVERLESS:
        serverless = [wh for wh in warehouses if _is_serverless(wh)]
        if not serverless:
            raise RuntimeError("No serverless-enabled SQL warehouse found.")
        # Prefer an already-RUNNING warehouse to avoid a cold start.
        serverless.sort(key=lambda wh: _state_name(wh) != "RUNNING")
        endpoint = serverless[0]
    else:
        matches = [wh for wh in warehouses if (wh.name or "").lower() == target.lower()]
        if not matches:
            available = [wh.name for wh in warehouses]
            raise RuntimeError(
                f"Warehouse {target!r} is not a known warehouse id or name. "
                f"Available: {available}"
            )
        endpoint = matches[0]

    return {
        "warehouse_id": endpoint.id,
        "name": endpoint.name,
        "serverless": _is_serverless(endpoint),
        "type": str(getattr(endpoint, "warehouse_type", "")),
        "state": _state_name(endpoint),
    }


def start_warehouse(
    client: WorkspaceClient,
    warehouse: dict[str, Any] | str,
    *,
    wait: bool = True,
    timeout_s: int = DEFAULT_START_TIMEOUT_S,
) -> dict[str, Any]:
    """Start a SQL warehouse, optionally waiting for it to be RUNNING.

    Args:
        client: Authenticated ``WorkspaceClient``.
        warehouse: A :func:`resolve_warehouse` result dict, or a warehouse id.
        wait: When True, block until the warehouse is RUNNING.
        timeout_s: Maximum seconds to wait when ``wait`` is True.

    Returns:
        A dict with ``warehouse_id``, ``name``, ``state``, and ``started`` (True
        if this call initiated the start).

    Raises:
        RuntimeError: If the warehouse is being deleted and cannot be started.
    """
    warehouse_id = (
        warehouse["warehouse_id"] if isinstance(warehouse, dict) else warehouse
    )
    endpoint = client.warehouses.get(warehouse_id)
    name = endpoint.name
    state = _state_name(endpoint)

    if state == "RUNNING":
        print(f"Warehouse {name} ({warehouse_id}) already RUNNING.")
        return {
            "warehouse_id": warehouse_id,
            "name": name,
            "state": "RUNNING",
            "started": False,
        }

    if state in ("DELETING", "DELETED"):
        raise RuntimeError(f"Warehouse {name} ({warehouse_id}) is {state}; cannot start.")

    # Kick off the start unless the warehouse is already starting.
    started = state != "STARTING"
    if started:
        print(f"Starting warehouse {name} ({warehouse_id}) [state={state or 'UNKNOWN'}]...")
        client.warehouses.start(warehouse_id)

    if not wait:
        return {
            "warehouse_id": warehouse_id,
            "name": name,
            "state": "STARTING",
            "started": started,
        }

    client.warehouses.wait_get_warehouse_running(
        warehouse_id, timeout=timedelta(seconds=timeout_s)
    )
    print(f"Warehouse {name} ({warehouse_id}) is RUNNING.")
    return {
        "warehouse_id": warehouse_id,
        "name": name,
        "state": "RUNNING",
        "started": started,
    }


def list_serving_endpoints(
    client: WorkspaceClient,
    prefix: str = DEFAULT_SERVING_PREFIX,
) -> list[str]:
    """List model-serving endpoint names, filtered by prefix and sorted.

    Args:
        client: Authenticated ``WorkspaceClient``.
        prefix: Only return endpoints whose name starts with this prefix.
            Defaults to ``"databricks-"`` (foundation-model endpoints).

    Returns:
        A sorted, de-duplicated list of serving-endpoint names.
    """
    names = {
        ep.name
        for ep in client.serving_endpoints.list()
        if ep.name and ep.name.startswith(prefix)
    }
    return sorted(names)
