"""Cluster domain helper — fetch Databricks cluster data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("cluster", help="Cluster operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser("fetch", help="Fetch cluster details")
    fetch.add_argument("--cluster-id", required=True, type=str)
    fetch.set_defaults(func=cmd_fetch)

    list_cmd = sp.add_parser("list", help="List clusters")
    list_cmd.add_argument("--filter-by-state", type=str, default=None, help="e.g. RUNNING, TERMINATED")
    list_cmd.set_defaults(func=cmd_list)

    events = sp.add_parser("events", help="List cluster events")
    events.add_argument("--cluster-id", required=True, type=str)
    events.add_argument("--limit", type=int, default=50)
    events.set_defaults(func=cmd_events)

    spark_ui = sp.add_parser("spark-context", help="Get Spark context info for a cluster")
    spark_ui.add_argument("--cluster-id", required=True, type=str)
    spark_ui.set_defaults(func=cmd_spark_context)


def _client():
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient()
    except Exception as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)


def _cluster_to_dict(c) -> dict:
    return {
        "cluster_id": getattr(c, "cluster_id", None),
        "cluster_name": getattr(c, "cluster_name", None),
        "state": str(getattr(c, "state", None)),
        "state_message": getattr(c, "state_message", None),
        "spark_version": getattr(c, "spark_version", None),
        "node_type_id": getattr(c, "node_type_id", None),
        "driver_node_type_id": getattr(c, "driver_node_type_id", None),
        "num_workers": getattr(c, "num_workers", None),
        "autoscale": c.autoscale.as_dict() if getattr(c, "autoscale", None) else None,
        "creator_user_name": getattr(c, "creator_user_name", None),
        "start_time": getattr(c, "start_time", None),
        "terminated_time": getattr(c, "terminated_time", None),
        "cluster_source": str(getattr(c, "cluster_source", None)),
    }


def cmd_fetch(args):
    w = _client()
    try:
        c = w.clusters.get(args.cluster_id)
        return _cluster_to_dict(c)
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"Cluster {args.cluster_id} not found", file=sys.stderr)
            sys.exit(2)
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_list(args):
    w = _client()
    try:
        clusters = list(w.clusters.list())
        result = [_cluster_to_dict(c) for c in clusters]
        if args.filter_by_state:
            result = [c for c in result if c["state"] == args.filter_by_state]
        return {"clusters": result, "count": len(result)}
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_events(args):
    w = _client()
    try:
        events = list(w.clusters.events(cluster_id=args.cluster_id))
        events = events[:args.limit]
        return {
            "cluster_id": args.cluster_id,
            "events": [
                {
                    "timestamp": getattr(e, "timestamp", None),
                    "type": str(getattr(e, "type", None)),
                    "details": e.details.as_dict() if getattr(e, "details", None) else None,
                }
                for e in events
            ],
            "count": len(events),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_spark_context(args):
    w = _client()
    try:
        c = w.clusters.get(args.cluster_id)
        return {
            "cluster_id": args.cluster_id,
            "state": str(getattr(c, "state", None)),
            "spark_conf": getattr(c, "spark_conf", {}),
            "spark_env_vars": getattr(c, "spark_env_vars", {}),
            "spark_version": getattr(c, "spark_version", None),
            "driver": c.driver.as_dict() if getattr(c, "driver", None) else None,
            "executors": [e.as_dict() for e in (getattr(c, "executors", None) or [])],
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
