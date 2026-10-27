"""Serving domain helper — read a model serving endpoint's config.

``serving fetch`` reads one endpoint's current and pending config: per served entity
the workload type and size, scale to zero, provisioned concurrency / throughput, and
the traffic routes. ``system.serving.served_entities`` has the config history but no
scale-to-zero column, so this is the read for that setting. Read-only, identity
scrubbed; environment variable values and external-model provider configs (which can
hold API keys) are never returned.
"""

from typing import Any

from starboard_skills.helpers.contract import (
    NotFoundError,
    raise_api_error,
    scrub_identity,
)
from starboard_skills.helpers.contract import make_client as _client

#: Served-entity fields kept as-is (the rest is credentials, identity or plumbing).
_ENTITY_KEYS = (
    "name",
    "entity_name",
    "entity_version",
    "workload_type",
    "workload_size",
    "scale_to_zero_enabled",
    "min_provisioned_concurrency",
    "max_provisioned_concurrency",
    "min_provisioned_throughput",
    "max_provisioned_throughput",
    "provisioned_model_units",
    "burst_scaling_enabled",
    "creation_timestamp",
    "state",
)


def register(subparsers) -> None:
    p = subparsers.add_parser("serving", help="Model serving endpoint operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser(
        "fetch",
        help="Fetch a serving endpoint's config: scale to zero, workload size, concurrency, "
        "served entities and traffic routes (read-only)",
    )
    target = fetch.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--endpoint-id",
        default=None,
        help="Endpoint id (billing usage_metadata.endpoint_id); resolved to its name by listing",
    )
    target.add_argument("--endpoint-name", default=None, help="Endpoint name")
    fetch.set_defaults(func=cmd_fetch)


def _not_found(endpoint: str) -> str:
    return f"Serving endpoint {endpoint} not found"


def _entity(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: e.get(k) for k in _ENTITY_KEYS}
    # A legacy served model names its model as model_name / model_version.
    out["entity_name"] = out["entity_name"] or e.get("model_name")
    out["entity_version"] = out["entity_version"] or e.get("model_version")
    ext = e.get("external_model")
    out["external_model"] = (
        {k: ext.get(k) for k in ("provider", "name", "task")}
        if isinstance(ext, dict)
        else None
    )
    fm = e.get("foundation_model")
    out["foundation_model"] = fm.get("name") if isinstance(fm, dict) else None
    out["environment_var_names"] = sorted(e.get("environment_vars") or {})
    return out


def _config(cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    if not cfg:
        return None
    entities = cfg.get("served_entities") or cfg.get("served_models") or []
    return {
        "config_version": cfg.get("config_version"),
        "start_time": cfg.get("start_time"),
        "served_entities": [_entity(e) for e in entities],
        "traffic_routes": (cfg.get("traffic_config") or {}).get("routes") or [],
    }


def _resolve_name(w: Any, endpoint_id: str) -> str:
    try:
        for ep in w.serving_endpoints.list():
            if ep.id == endpoint_id:
                return ep.name
    except Exception as e:
        raise_api_error(e)
    # The list holds only endpoints this identity can view: an endpoint without View
    # permission is absent here although it exists.
    raise NotFoundError(
        f"{_not_found(endpoint_id)} among the endpoints this identity can view (it may "
        "exist without View permission); --endpoint-name reads it by name"
    )


def cmd_fetch(args):
    """``serving_endpoints.get`` → state, the current and pending config, per-entity scaling."""
    w = _client()
    name = args.endpoint_name or _resolve_name(w, args.endpoint_id)
    try:
        ep = w.serving_endpoints.get(name)
    except Exception as e:
        raise_api_error(e, not_found_message=_not_found(args.endpoint_id or name))
    doc = ep.as_dict()
    current = _config(doc.get("config")) or {}
    return scrub_identity(
        {
            "endpoint_id": ep.id,
            "name": ep.name,
            "task": ep.task,
            "state": doc.get("state"),
            "route_optimized": ep.route_optimized,
            "creation_timestamp": ep.creation_timestamp,
            "last_updated_timestamp": ep.last_updated_timestamp,
            "config_version": current.get("config_version"),
            "served_entities": current.get("served_entities", []),
            "traffic_routes": current.get("traffic_routes", []),
            "pending_config": _config(doc.get("pending_config")),
            "tags": doc.get("tags") or [],
        }
    )
