"""Diagnostic domain helper — fetch Databricks diagnostic/observability data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("diagnostic", help="Diagnostic and observability operations")
    sp = p.add_subparsers(dest="command", required=True)

    workspace = sp.add_parser("workspace", help="Fetch workspace configuration summary")
    workspace.set_defaults(func=cmd_workspace)

    node_types = sp.add_parser("node-types", help="List available node types")
    node_types.set_defaults(func=cmd_node_types)

    spark_versions = sp.add_parser("spark-versions", help="List available Spark versions")
    spark_versions.set_defaults(func=cmd_spark_versions)

    run_state = sp.add_parser("run-state", help="Fetch detailed state for a job run")
    run_state.add_argument("--run-id", required=True, type=int)
    run_state.set_defaults(func=cmd_run_state)

    cluster_log = sp.add_parser("cluster-log", help="Fetch cluster event log summary")
    cluster_log.add_argument("--cluster-id", required=True, type=str)
    cluster_log.add_argument("--limit", type=int, default=100)
    cluster_log.set_defaults(func=cmd_cluster_log)


def _client():
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient()
    except Exception as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_workspace(args):
    w = _client()
    try:
        conf = w.workspace_conf.get_status(keys="enableIpAccessLists,enableTokensConfig")
        return {"workspace_config": dict(conf) if conf else {}}
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_node_types(args):
    w = _client()
    try:
        node_types = list(w.clusters.list_node_types().node_types or [])
        return {
            "node_types": [
                {
                    "node_type_id": getattr(n, "node_type_id", None),
                    "memory_mb": getattr(n, "memory_mb", None),
                    "num_cores": getattr(n, "num_cores", None),
                    "num_gpus": getattr(n, "num_gpus", None),
                    "instance_type_id": getattr(n, "instance_type_id", None),
                    "is_deprecated": getattr(n, "is_deprecated", None),
                }
                for n in node_types
            ],
            "count": len(node_types),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_spark_versions(args):
    w = _client()
    try:
        versions = list(w.clusters.spark_versions().versions or [])
        return {
            "spark_versions": [
                {
                    "key": getattr(v, "key", None),
                    "name": getattr(v, "name", None),
                }
                for v in versions
            ],
            "count": len(versions),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_run_state(args):
    w = _client()
    try:
        run = w.jobs.get_run(run_id=args.run_id, include_history=True)
        return {
            "run_id": run.run_id,
            "state": run.state.as_dict() if run.state else {},
            "tasks": [
                {
                    "task_key": t.task_key,
                    "state": t.state.as_dict() if t.state else {},
                    "cluster_instance": t.cluster_instance.as_dict() if getattr(t, "cluster_instance", None) else None,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "execution_duration": t.execution_duration,
                    "attempt_number": getattr(t, "attempt_number", None),
                }
                for t in (run.tasks or [])
            ],
            "cluster_spec": run.cluster_spec.as_dict() if getattr(run, "cluster_spec", None) else None,
            "start_time": run.start_time,
            "end_time": run.end_time,
            "execution_duration": run.execution_duration,
        }
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"Run {args.run_id} not found", file=sys.stderr)
            sys.exit(2)
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_cluster_log(args):
    w = _client()
    try:
        events = list(w.clusters.events(cluster_id=args.cluster_id))
        events = events[:args.limit]
        error_events = [e for e in events if "error" in str(getattr(e, "type", "")).lower()]
        return {
            "cluster_id": args.cluster_id,
            "total_events": len(events),
            "error_events": len(error_events),
            "events": [
                {
                    "timestamp": getattr(e, "timestamp", None),
                    "type": str(getattr(e, "type", None)),
                    "details": e.details.as_dict() if getattr(e, "details", None) else None,
                }
                for e in events
            ],
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
