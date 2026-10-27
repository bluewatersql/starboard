"""Pipeline domain helper — fetch Lakeflow Declarative Pipelines (DLT) evidence.

``pipeline fetch`` reads the pipeline's spec and state, ``pipeline updates`` its
recent updates and ``pipeline events`` its event log (error messages and
exceptions included), every one identity-scrubbed and size-bounded.
"""
import argparse
import itertools
import re
from typing import Any

from starboard_skills.helpers.contract import (
    ArgError,
    HelperError,
    byte_budget,
    clip_text,
    raise_api_error,
    redact_emails,
    scrub_identity,
)
from starboard_skills.helpers.contract import make_client as _client

#: ``--limit`` defaults and hard caps (an event log can hold millions of rows).
UPDATES_DEFAULT, UPDATES_MAX = 10, 100
EVENTS_DEFAULT, EVENTS_MAX = 50, 500
#: Events read at most per call when ``--update-id`` filters them client-side.
EVENTS_SCAN_MAX = 5_000
#: Default cap per event text field (message, exception message) in bytes.
EVENT_TEXT_DEFAULT_BYTES = 8 * 1024
#: Stack frames kept per exception (the top of the stack names the failure).
STACK_FRAMES_MAX = 20
_PAGE_SIZE = 100
#: ``--level`` is a minimum severity: each level reads itself and everything above it.
_LEVELS = ("ERROR", "WARN", "INFO")
_UPDATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
#: Origin fields an event keeps (the rest is workspace plumbing).
_ORIGIN_KEYS = (
    "update_id",
    "flow_id",
    "flow_name",
    "dataset_name",
    "table_id",
    "cluster_id",
    "batch_id",
    "maintenance_id",
)


def _limit(cap: int):
    """argparse ``type=``: an integer in ``1..cap`` (else exit 4)."""

    def parse(value: str) -> int:
        try:
            n = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from exc
        if not 1 <= n <= cap:
            raise argparse.ArgumentTypeError(f"must be 1..{cap}, got {n}")
        return n

    return parse


def register(subparsers) -> None:
    p = subparsers.add_parser("pipeline", help="Pipeline (Lakeflow / DLT) operations")
    sp = p.add_subparsers(dest="command", required=True)

    fetch = sp.add_parser(
        "fetch", help="Fetch a pipeline's spec, state and latest updates (identity scrubbed)"
    )
    fetch.add_argument("--pipeline-id", required=True)
    fetch.set_defaults(func=cmd_fetch)

    updates = sp.add_parser("updates", help="List a pipeline's recent updates, newest first")
    updates.add_argument("--pipeline-id", required=True)
    updates.add_argument(
        "--limit", type=_limit(UPDATES_MAX), default=UPDATES_DEFAULT,
        help=f"Max updates returned (default {UPDATES_DEFAULT}, at most {UPDATES_MAX})",
    )
    updates.set_defaults(func=cmd_updates)

    events = sp.add_parser(
        "events",
        help="Read a pipeline's event log: messages, error exceptions and stack heads",
    )
    events.add_argument("--pipeline-id", required=True)
    events.add_argument(
        "--update-id", default=None,
        help="Only the events of this update (matched on the event origin)",
    )
    events.add_argument(
        "--level", choices=_LEVELS, default="INFO",
        help="Minimum severity: ERROR, WARN (+ERROR) or INFO (+WARN, ERROR; the default)",
    )
    events.add_argument(
        "--limit", type=_limit(EVENTS_MAX), default=EVENTS_DEFAULT,
        help=f"Max events returned, newest first (default {EVENTS_DEFAULT}, at most {EVENTS_MAX})",
    )
    events.add_argument(
        "--max-bytes", type=byte_budget, default=EVENT_TEXT_DEFAULT_BYTES,
        help=f"Cap per event text field in bytes (default {EVENT_TEXT_DEFAULT_BYTES})",
    )
    events.set_defaults(func=cmd_events)


def _not_found(pipeline_id: str) -> str:
    return f"Pipeline {pipeline_id} not found"


def cmd_fetch(args):
    """``pipelines.get`` → spec, state, health, compute and the latest updates."""
    w = _client()
    try:
        p = w.pipelines.get(args.pipeline_id)
    except Exception as e:
        raise_api_error(e, not_found_message=_not_found(args.pipeline_id))
    doc = p.as_dict()
    # Identity: the run-as principal and every user name / email are dropped.
    doc.pop("run_as", None)
    spec = doc.get("spec") or {}
    return scrub_identity(
        {
            "pipeline_id": p.pipeline_id,
            "name": p.name,
            "state": doc.get("state"),
            "health": doc.get("health"),
            "cause": p.cause,
            "cluster_id": p.cluster_id,
            "serverless": spec.get("serverless"),
            "effective_serverless_compute_id": p.effective_serverless_compute_id,
            "channel": spec.get("channel"),
            "edition": spec.get("edition"),
            "continuous": spec.get("continuous"),
            "development": spec.get("development"),
            "trigger": spec.get("trigger"),
            "photon": spec.get("photon"),
            "catalog": spec.get("catalog"),
            "target_schema": spec.get("schema") or spec.get("target"),
            "last_modified": p.last_modified,
            "latest_updates": doc.get("latest_updates") or [],
            "spec": spec,
        }
    )


def cmd_updates(args):
    """``pipelines.list_updates`` paged with ``page_token`` up to ``--limit``, newest first."""
    w = _client()
    rows: list[dict[str, Any]] = []
    token = None
    more = False
    try:
        while len(rows) < args.limit:
            page = w.pipelines.list_updates(
                args.pipeline_id,
                max_results=min(args.limit - len(rows), _PAGE_SIZE),
                page_token=token,
            )
            rows += [u.as_dict() for u in page.updates or []]
            token = page.next_page_token
            if not token or not page.updates:
                break
        more = bool(token) or len(rows) > args.limit
    except Exception as e:
        raise_api_error(e, not_found_message=_not_found(args.pipeline_id))
    updates = []
    for u in rows[: args.limit]:
        u.pop("config", None)  # the full spec snapshot: `pipeline fetch` has it
        updates.append(u)
    return scrub_identity(
        {
            "pipeline_id": args.pipeline_id,
            "updates": updates,
            "count": len(updates),
            "has_more": more,
            "limit": args.limit,
        }
    )


def _level_filter(level: str) -> str:
    """The server-side filter for ``level`` and every more severe level."""
    wanted = _LEVELS[: _LEVELS.index(level) + 1]
    if len(wanted) == 1:
        return f"level='{wanted[0]}'"
    return "level in (" + ", ".join(f"'{v}'" for v in wanted) + ")"


def _frame(f: Any) -> str:
    where = f"{f.file_name}:{f.line_number}" if f.file_name else "?"
    return f"{f.declaring_class or '?'}.{f.method_name or '?'}({where})"


class _Clipper:
    """Clip free text to ``max_bytes`` (emails redacted) and count what was cut."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.cut = 0

    def __call__(self, text: str | None) -> str | None:
        out, cut = clip_text(redact_emails(text), self.max_bytes)
        self.cut += cut
        return out


def _event(e: Any, clip: _Clipper) -> dict[str, Any]:
    origin = e.origin.as_dict() if e.origin is not None else {}
    error = None
    if e.error is not None:
        exceptions = []
        for x in e.error.exceptions or []:
            stack = x.stack or []
            exceptions.append(
                {
                    "class_name": x.class_name,
                    "message": clip(x.message),
                    "stack": [_frame(f) for f in stack[:STACK_FRAMES_MAX]],
                    "stack_frames": len(stack),
                }
            )
        error = {"fatal": e.error.fatal, "exceptions": exceptions}
    return {
        "id": e.id,
        "timestamp": e.timestamp,
        "level": e.level.value if e.level is not None else None,
        "event_type": e.event_type,
        "message": clip(e.message),
        "origin": {k: origin[k] for k in _ORIGIN_KEYS if k in origin},
        "error": error,
    }


def cmd_events(args):
    """``pipelines.list_pipeline_events`` (level filter server-side), newest first.

    ``--update-id`` is matched on each event's ``origin.update_id`` (the API filter
    has no update field), reading at most :data:`EVENTS_SCAN_MAX` events.
    """
    if args.update_id is not None and not _UPDATE_ID.match(args.update_id):
        raise ArgError(f"--update-id: invalid update id {args.update_id!r}")
    w = _client()
    clip = _Clipper(args.max_bytes)
    scan_cap = EVENTS_SCAN_MAX if args.update_id else args.limit
    events: list[dict[str, Any]] = []
    scanned = 0
    try:
        stream = w.pipelines.list_pipeline_events(
            args.pipeline_id,
            filter=_level_filter(args.level),
            max_results=min(scan_cap, _PAGE_SIZE),
        )
        for e in itertools.islice(stream, scan_cap):
            scanned += 1
            if args.update_id and (e.origin is None or e.origin.update_id != args.update_id):
                continue
            events.append(_event(e, clip))
            if len(events) >= args.limit:
                break
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e, not_found_message=_not_found(args.pipeline_id))
    return scrub_identity(
        {
            "pipeline_id": args.pipeline_id,
            "update_id": args.update_id,
            "level": args.level,
            "events": events,
            "count": len(events),
            "scanned": scanned,
            "scan_capped": bool(args.update_id) and scanned >= scan_cap
            and len(events) < args.limit,
            "limit": args.limit,
            "max_bytes": args.max_bytes,
            "truncated_fields": clip.cut,
        }
    )
