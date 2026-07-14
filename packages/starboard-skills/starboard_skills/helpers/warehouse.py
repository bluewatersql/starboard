"""Warehouse domain helper — fetch Databricks SQL warehouse data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("warehouse", help="SQL warehouse operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser("fetch", help="Fetch warehouse details")
    fetch.add_argument("--warehouse-id", required=True, type=str)
    fetch.set_defaults(func=cmd_fetch)

    list_cmd = sp.add_parser("list", help="List all warehouses")
    list_cmd.set_defaults(func=cmd_list)

    metrics = sp.add_parser("metrics", help="Fetch warehouse metrics/events")
    metrics.add_argument("--warehouse-id", required=True, type=str)
    metrics.set_defaults(func=cmd_metrics)


def _client():
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient()
    except Exception as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)


def _warehouse_to_dict(w) -> dict:
    return {
        "id": getattr(w, "id", None),
        "name": getattr(w, "name", None),
        "state": str(getattr(w, "state", None)),
        "cluster_size": getattr(w, "cluster_size", None),
        "max_num_clusters": getattr(w, "max_num_clusters", None),
        "min_num_clusters": getattr(w, "min_num_clusters", None),
        "num_clusters": getattr(w, "num_clusters", None),
        "num_active_sessions": getattr(w, "num_active_sessions", None),
        "auto_stop_mins": getattr(w, "auto_stop_mins", None),
        "warehouse_type": str(getattr(w, "warehouse_type", None)),
        "enable_serverless_compute": getattr(w, "enable_serverless_compute", None),
        "spot_instance_policy": str(getattr(w, "spot_instance_policy", None)),
    }


def cmd_fetch(args):
    w = _client()
    try:
        wh = w.warehouses.get(args.warehouse_id)
        return _warehouse_to_dict(wh)
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"Warehouse {args.warehouse_id} not found", file=sys.stderr)
            sys.exit(2)
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_list(args):
    w = _client()
    try:
        warehouses = list(w.warehouses.list())
        return {
            "warehouses": [_warehouse_to_dict(wh) for wh in warehouses],
            "count": len(warehouses),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_metrics(args):
    w = _client()
    try:
        events = w.warehouses.get_permission_levels(args.warehouse_id)
        # Also try to get the warehouse state
        wh = w.warehouses.get(args.warehouse_id)
        return {
            "warehouse_id": args.warehouse_id,
            "state": str(getattr(wh, "state", None)),
            "num_clusters": getattr(wh, "num_clusters", None),
            "num_active_sessions": getattr(wh, "num_active_sessions", None),
            "health": wh.health.as_dict() if getattr(wh, "health", None) else None,
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
