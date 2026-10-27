"""Database domain helper — list Databricks Lakebase database instances.

Lakebase spend in ``system.billing.usage`` lacks ``usage_metadata.database_instance_id``
on virtually all rows, so billing alone cannot attribute per-instance cost.  This
helper enumerates live instances from the workspace API so the host can join them to
the LAKEBASE billing line and push attribution to the instance level.

CLI::

    starboard-helper database instances
"""
from __future__ import annotations

from starboard_skills.helpers.contract import HelperError, raise_api_error
from starboard_skills.helpers.contract import make_client as _client


def register(subparsers) -> None:
    """Register the ``database`` domain parser."""
    p = subparsers.add_parser("database", help="Database / Lakebase operations")
    sp = p.add_subparsers(dest="command", required=True)

    instances = sp.add_parser(
        "instances",
        help="List database instances (Lakebase) — use for per-instance cost attribution",
    )
    instances.set_defaults(func=cmd_instances)


def cmd_instances(args) -> dict:  # noqa: ARG001
    """Return a list of Lakebase database instances from the workspace API."""
    w = _client()
    try:
        raw = list(w.database.list_database_instances())
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e)

    instances = []
    for inst in raw:
        # Use as_dict() when available; fall back to getattr for individual fields
        # so the shape remains stable across SDK versions.
        d: dict = inst.as_dict() if hasattr(inst, "as_dict") else {}
        instances.append(
            {
                "name": getattr(inst, "name", d.get("name")),
                "uid": getattr(
                    inst,
                    "uid",
                    getattr(inst, "id", d.get("uid", d.get("id"))),
                ),
                "capacity": getattr(inst, "capacity", d.get("capacity")),
                "state": str(getattr(inst, "state", d.get("state"))),
            }
        )

    return {"instances": instances, "count": len(instances)}
