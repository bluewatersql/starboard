"""Query domain helper — fetch Databricks SQL query history data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("query", help="SQL query operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser("fetch", help="Fetch query details by ID")
    fetch.add_argument("--query-id", required=True, type=str)
    fetch.set_defaults(func=cmd_fetch)

    history = sp.add_parser("history", help="List recent query history")
    history.add_argument("--warehouse-id", type=str, default=None)
    history.add_argument("--limit", type=int, default=25)
    history.add_argument("--status", type=str, default=None, help="Filter by status (FINISHED, FAILED, CANCELED)")
    history.set_defaults(func=cmd_history)

    slow = sp.add_parser("slow", help="List slow queries above duration threshold")
    slow.add_argument("--warehouse-id", type=str, default=None)
    slow.add_argument("--min-duration-ms", type=int, default=10000)
    slow.add_argument("--limit", type=int, default=25)
    slow.set_defaults(func=cmd_slow)


def _client():
    try:
        from databricks.sdk import WorkspaceClient
        return WorkspaceClient()
    except Exception as e:
        print(f"Authentication error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fetch(args):
    w = _client()
    try:
        q = w.query_history.get_query(args.query_id)
        return q.as_dict() if hasattr(q, "as_dict") else vars(q)
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"Query {args.query_id} not found", file=sys.stderr)
            sys.exit(2)
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def _query_to_dict(q) -> dict:
    return {
        "query_id": getattr(q, "query_id", None),
        "status": getattr(q, "status", None),
        "query_text": getattr(q, "query_text", None),
        "duration": getattr(q, "duration", None),
        "executed_as_user_name": getattr(q, "executed_as_user_name", None),
        "warehouse_id": getattr(q, "warehouse_id", None),
        "start_time": getattr(q, "query_start_time_ms", None),
        "error_message": getattr(q, "error_message", None),
        "rows_produced": getattr(q, "rows_produced", None),
        "bytes_produced": getattr(q, "bytes_produced", None),
    }


def cmd_history(args):
    w = _client()
    try:
        from databricks.sdk.service.sql import QueryStatus
        filter_by = None
        if args.status:
            try:
                status = QueryStatus[args.status.upper()]
                from databricks.sdk.service.sql import QueryFilter
                filter_by = QueryFilter(query_start_time_range=None, statuses=[status], warehouse_ids=[args.warehouse_id] if args.warehouse_id else None)
            except KeyError:
                print(f"Unknown status: {args.status}", file=sys.stderr)
                sys.exit(4)
        queries = list(w.query_history.list(filter_by=filter_by, max_results=args.limit))
        return {
            "queries": [_query_to_dict(q) for q in queries],
            "count": len(queries),
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_slow(args):
    w = _client()
    try:
        queries = list(w.query_history.list(max_results=200))
        slow = [
            q for q in queries
            if (getattr(q, "duration", 0) or 0) >= args.min_duration_ms
        ]
        slow.sort(key=lambda q: getattr(q, "duration", 0) or 0, reverse=True)
        slow = slow[:args.limit]
        if args.warehouse_id:
            slow = [q for q in slow if getattr(q, "warehouse_id", None) == args.warehouse_id]
        return {
            "slow_queries": [_query_to_dict(q) for q in slow],
            "count": len(slow),
            "min_duration_ms": args.min_duration_ms,
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
