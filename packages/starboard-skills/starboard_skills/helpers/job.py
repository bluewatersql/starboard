"""Job domain helper — fetch Databricks job data."""
import sys


def register(subparsers) -> None:
    p = subparsers.add_parser("job", help="Job operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser("fetch", help="Fetch job details")
    fetch.add_argument("--job-id", required=True, type=int)
    fetch.set_defaults(func=cmd_fetch)

    runs = sp.add_parser("runs", help="List recent runs")
    runs.add_argument("--job-id", required=True, type=int)
    runs.add_argument("--limit", type=int, default=10)
    runs.set_defaults(func=cmd_runs)

    list_jobs = sp.add_parser("list", help="List all jobs")
    list_jobs.add_argument("--limit", type=int, default=25)
    list_jobs.add_argument("--name-filter", type=str, default=None)
    list_jobs.set_defaults(func=cmd_list)


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
        job = w.jobs.get(args.job_id)
        return {
            "job_id": job.job_id,
            "name": job.settings.name if job.settings else None,
            "settings": job.settings.as_dict() if job.settings else {},
        }
    except Exception as e:
        if "not found" in str(e).lower():
            print(f"Job {args.job_id} not found", file=sys.stderr)
            sys.exit(2)
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_runs(args):
    w = _client()
    try:
        runs = list(w.jobs.list_runs(job_id=args.job_id, limit=args.limit))
        return {
            "job_id": args.job_id,
            "runs": [
                {
                    "run_id": r.run_id,
                    "state": r.state.as_dict() if r.state else {},
                    "start_time": r.start_time,
                    "end_time": r.end_time,
                    "execution_duration": r.execution_duration,
                }
                for r in runs
            ],
        }
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)


def cmd_list(args):
    w = _client()
    try:
        jobs = list(w.jobs.list(limit=args.limit))
        result = [
            {
                "job_id": j.job_id,
                "name": j.settings.name if j.settings else None,
            }
            for j in jobs
        ]
        if args.name_filter:
            result = [r for r in result if args.name_filter.lower() in (r["name"] or "").lower()]
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
