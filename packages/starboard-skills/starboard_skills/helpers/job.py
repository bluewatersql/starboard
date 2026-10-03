"""Job domain helper — fetch Databricks job data."""
import itertools

from starboard_skills.helpers.contract import make_client as _client
from starboard_skills.helpers.contract import raise_api_error


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
        raise_api_error(e, not_found_message=f"Job {args.job_id} not found")


def cmd_runs(args):
    w = _client()
    try:
        # SDK `limit` is the page size on an auto-paginating iterator, not a total
        # cap — enforce the requested cap client-side with islice.
        runs = list(
            itertools.islice(w.jobs.list_runs(job_id=args.job_id), args.limit)
        )
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
        raise_api_error(e)


def cmd_list(args):
    w = _client()
    try:
        # `w.jobs.list()` is an auto-paginating iterator (the SDK `limit` is only
        # the page size), so materializing it returns ALL jobs. Iterate and stop
        # once we have `--limit` results — applying `--name-filter` inline so the
        # cap counts matches, not raw rows.
        name_filter = args.name_filter.lower() if args.name_filter else None
        result = []
        for j in w.jobs.list():
            name = j.settings.name if j.settings else None
            if name_filter and name_filter not in (name or "").lower():
                continue
            result.append({"job_id": j.job_id, "name": name})
            if len(result) >= args.limit:
                break
        return {"jobs": result, "count": len(result)}
    except Exception as e:
        raise_api_error(e)
