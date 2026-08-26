"""Analyze domain helper — combined multi-domain workload snapshot.

Maps the ``starboard-analyze`` skill. Composes the existing thin domain fetchers
(jobs + warehouses + clusters) into a single envelope. Per-domain failures are
captured under ``errors`` so a partial outage does not sink the whole snapshot.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from starboard_skills.helpers import cluster, job, warehouse
from starboard_skills.helpers.contract import HelperError


def register(subparsers) -> None:
    p = subparsers.add_parser("analyze", help="Combined multi-domain snapshot")
    sp = p.add_subparsers(dest="command", required=True)

    snapshot = sp.add_parser(
        "snapshot", help="Gather a jobs+warehouses+clusters summary"
    )
    snapshot.add_argument("--limit", type=int, default=25)
    snapshot.set_defaults(func=cmd_snapshot)


def cmd_snapshot(args) -> dict[str, Any]:
    """Compose existing domain fetchers into one snapshot envelope payload."""
    sections: dict[str, Any] = {
        "jobs": (job.cmd_list, SimpleNamespace(limit=args.limit, name_filter=None)),
        "warehouses": (warehouse.cmd_list, SimpleNamespace()),
        "clusters": (cluster.cmd_list, SimpleNamespace(filter_by_state=None)),
    }

    snapshot: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for name, (fn, ns) in sections.items():
        try:
            snapshot[name] = fn(ns)
        except HelperError as exc:
            snapshot[name] = None
            errors[name] = {"exit_code": exc.exit_code, "error": exc.message}

    return {"snapshot": snapshot, "errors": errors}
