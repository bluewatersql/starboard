"""Query domain helper — fetch Databricks SQL query history data."""
import asyncio
import contextlib
import decimal
import math
import re
import time
from importlib import metadata as importlib_metadata
from types import SimpleNamespace

from starboard_skills.helpers.contract import (
    ApiError,
    ArgError,
    HelperError,
    raise_api_error,
)
from starboard_skills.helpers.contract import make_client as _client

# Read-only SQL verb guard: an evidence re-check surface, never a write path.
# Only these statement heads are allowed, a single statement only, rows capped.
_MAX_ROW_LIMIT = 1000
# The Statement Execution API holds a request open for at most 50s; longer waits
# poll ``get_statement`` until the caller's --timeout.
_MAX_WAIT_WINDOW_S = 50
_POLL_INTERVAL_S = 2.0
_IN_FLIGHT_STATES = ("PENDING", "RUNNING")
_READONLY_HEADS = ("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN")
# SQL semantic/analysis error code prefixes (D14). When the FAILED state carries one
# of these in the error message, the root cause is the query text itself (wrong column
# name, type mismatch, parse error, etc.) — not warehouse resources. Suppress the
# "Narrow the query / larger warehouse" capacity hint for these cases so the agent
# sees a clean SQL error, not confusing resource advice.
_SQL_ANALYSIS_ERRORS = (
    "DATATYPE_MISMATCH",
    "UNRESOLVED_COLUMN",
    "UNRESOLVED_RELATION",
    "AMBIGUOUS_COLUMN",
    "AMBIGUOUS_REFERENCE",
    "COLUMN_NOT_FOUND",
    "TABLE_OR_VIEW_NOT_FOUND",
    "PARSE_SYNTAX_ERROR",
    "SYNTAX_ERROR",
    "INVALID_SYNTAX",
    "INVALID_FIELD_NAME",
    "INVALID_PARAMETER_VALUE",
    "MISSING_ATTRIBUTES",
    "UNSUPPORTED_FEATURE",
)
_CAPACITY_HINT = (
    "Narrow the query or use a larger warehouse; a partial re-check is not 0 rows."
)
# Defense-in-depth: a read-only head (especially WITH) can still PREFIX a write —
# e.g. `WITH c AS (SELECT ...) INSERT INTO t SELECT * FROM c` starts with WITH but
# writes — and read_only is NOT enforced server-side, so the head allowlist alone is
# not a boundary. Reject any statement containing a write/DDL keyword (word-boundary,
# case-insensitive). Fails closed: a write word inside a string literal is rejected too.
_WRITE_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|OVERWRITE|INTO)\b",
    re.IGNORECASE,
)
# Trailing ``LIMIT n`` of the outermost statement — same rule as the discovery
# executor's ``_TRAILING_LIMIT`` (starboard.discovery.executor; not importable here:
# starboard-skills does not depend on the server wheel). Applied to the
# comment/literal-masked probe so a trailing ``-- note`` can't hide it.
_TRAILING_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*;?\s*\Z", re.IGNORECASE)
# ``query sql --rows``: positional lists (default, unchanged) or column-keyed dicts.
_ROW_MODES = ("arrays", "objects")
# Entry-point seam the gated internal package registers its discovery source on.
# Resolved by name at runtime, so no internal module is imported here.
_ADAPTER_GROUP = "starboard.port_adapters"
_INTERNAL_SOURCE_EP = "discovery_source"
# Fast network preflight ceiling (seconds): a DNS / connect failure otherwise sits
# in the SDK's host-metadata retry loop for ~1 min before surfacing.
_PREFLIGHT_TIMEOUT_S = 8.0


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

    sql = sp.add_parser(
        "sql",
        help="Run a READ-ONLY parameterized SQL statement (independent evidence re-check)",
        description=(
            "Run a single READ-ONLY SQL statement (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN) on an "
            "explicit warehouse and return columns + rows. Use --profile to pick a "
            "~/.databrickscfg profile (overrides DATABRICKS_HOST/DATABRICKS_TOKEN env auth). "
            "Use --timeout SECONDS for long aggregations: the statement is polled until it "
            "finishes or the timeout elapses, then cancelled (default: one 50s wait window). "
            "Values are typed from the result manifest: INT/LONG/SHORT/BYTE and DECIMAL(scale 0) "
            "-> integers, DOUBLE/FLOAT/DECIMAL -> floats, BOOLEAN -> true/false; other types stay strings."
        ),
    )
    sql.add_argument(
        "--sql",
        required=True,
        type=str,
        help="A single read-only statement (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN)",
    )
    sql.add_argument(
        "--warehouse-id",
        type=str,
        default=None,
        help=(
            "SQL warehouse to run on (explicit — never auto-selected). Required unless "
            "--internal-workspace-id is given"
        ),
    )
    sql.add_argument(
        "--internal-workspace-id",
        type=str,
        default=None,
        metavar="ID",
        help=(
            "Run on the internal source (gated; needs the internal package installed) "
            "scoped to this workspace id, instead of a customer warehouse"
        ),
    )
    sql.add_argument(
        "--rows",
        choices=list(_ROW_MODES),
        default="arrays",
        help=(
            "Row shape: 'arrays' (default) = positional lists aligned to 'columns'; "
            "'objects' = one {column: value} dict per row"
        ),
    )
    sql.add_argument(
        "--limit", type=int, default=100, help=f"Max rows returned (capped at {_MAX_ROW_LIMIT})"
    )
    sql.add_argument(
        "--param",
        action="append",
        default=None,
        metavar="NAME=VALUE",
        help="Bind a :NAME query parameter (repeatable) — parameterized, not string-interpolated",
    )
    sql.add_argument(
        "--profile",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Databricks CLI profile from ~/.databrickscfg to authenticate with. Takes "
            "precedence over DATABRICKS_HOST / DATABRICKS_TOKEN env vars "
            "(default: ambient SDK credential chain)"
        ),
    )
    sql.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Max seconds to wait for the statement to finish; it is polled until done "
            "and cancelled on timeout. Default: a single 50s wait window, no polling"
        ),
    )
    sql.set_defaults(func=cmd_sql)


def cmd_fetch(args):
    w = _client()
    try:
        q = w.query_history.get_query(args.query_id)
        return q.as_dict() if hasattr(q, "as_dict") else vars(q)
    except Exception as e:
        raise_api_error(e, not_found_message=f"Query {args.query_id} not found")


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
            except KeyError as ke:
                raise ArgError(f"Unknown status: {args.status}") from ke
        # query_history.list() returns a ListQueriesResponse (single page:
        # .res + .next_page_token), NOT an auto-paginating iterator. Bound the
        # page with max_results and cap client-side for safety.
        resp = w.query_history.list(filter_by=filter_by, max_results=args.limit)
        queries = (resp.res or [])[: args.limit]
        return {
            "queries": [_query_to_dict(q) for q in queries],
            "count": len(queries),
        }
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e)


def cmd_slow(args):
    w = _client()
    try:
        # Bound the scan to a single 200-row page (list() returns a
        # ListQueriesResponse, not an iterator — see cmd_history).
        queries = (w.query_history.list(max_results=200).res or [])
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
        raise_api_error(e)


def _is_sql_analysis_error(detail: str | None) -> bool:
    """Return True if the error detail matches a SQL semantic/analysis error.

    Used to suppress the 'larger warehouse' capacity hint (D14): when the query
    itself is malformed (wrong column, type mismatch, parse error, etc.) the fix
    is the SQL, not warehouse resources, so the hint is misleading.
    """
    if not detail:
        return False
    upper = detail.upper()
    return any(keyword in upper for keyword in _SQL_ANALYSIS_ERRORS)


def _strip_sql_noise(sql: str) -> str:
    """Mask comments and string literals for validation only (the original executes).

    So the head/write checks don't trip on a write word inside a string literal
    (`WHERE action = 'DELETE'`) or a leading `--`/`/* */` comment (the repo's own pack
    SQL starts with a comment). A ``;`` inside a string is masked away too.
    """
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)   # block comments
    s = re.sub(r"--[^\n]*", " ", s)                        # line comments
    s = re.sub(r"'(?:[^']|'')*'", "''", s)                 # single-quoted literals ('' escapes)
    return s.strip()


def _assert_read_only(sql: str) -> str:
    """Return the trimmed statement if it is a single read-only query, else ArgError.

    Guard model, applied to a comment-stripped / string-masked probe (the original
    statement is what executes): one statement (no embedded ``;``), a leading keyword in
    the read-only head allowlist, and no write/DDL keyword anywhere — a read-only head
    like ``WITH`` can still prefix a write. Evidence re-check surface, never a write path.
    """
    raw = (sql or "").strip().rstrip(";").strip()
    if not raw:
        raise ArgError("--sql is empty")
    probe = _strip_sql_noise(raw)
    if not probe:
        raise ArgError("--sql has no executable statement (only comments)")
    if ";" in probe:
        raise ArgError("only a single read-only statement is allowed (no ';')")
    head = probe.lstrip("(").split(None, 1)[0].upper()
    if head not in _READONLY_HEADS:
        raise ArgError(
            f"only read-only queries are allowed (must start with one of "
            f"{', '.join(_READONLY_HEADS)}); got {head or '?'!r}"
        )
    write = _WRITE_RE.search(probe)
    if write:
        raise ArgError(
            f"read-only only: statement contains write/DDL keyword "
            f"{write.group(1).upper()!r} — a read-only head like WITH can still prefix a write"
        )
    return raw


def _effective_limit(statement: str, cli_limit: int) -> tuple[int, int | None]:
    """Return ``(effective_limit, sql_limit)`` for the result population.

    ``sql_limit`` is the statement's own trailing ``LIMIT n`` (``None`` if absent).
    The rows returned are capped by whichever of the SQL LIMIT and the CLI
    ``--limit`` is smaller, so that is the limit a full result has "reached".
    """
    match = _TRAILING_LIMIT.search(_strip_sql_noise(statement))
    sql_limit = int(match.group(1)) if match else None
    effective = cli_limit if sql_limit is None else min(cli_limit, sql_limit)
    return effective, sql_limit


def _target_host(profile: str | None) -> str | None:
    """Workspace host the SDK client will use — no SDK call, no network.

    Mirrors :func:`make_client` precedence: an explicit ``--profile`` wins (env
    auth is masked), else ambient ``DATABRICKS_HOST``, else the
    ``DATABRICKS_CONFIG_PROFILE`` / ``DEFAULT`` section of ~/.databrickscfg.
    """
    import configparser
    import os

    if not profile:
        env_host = os.environ.get("DATABRICKS_HOST")
        if env_host:
            return env_host
        profile = os.environ.get("DATABRICKS_CONFIG_PROFILE") or "DEFAULT"
    cfg = configparser.ConfigParser()
    try:
        cfg.read(os.path.expanduser(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")))
    except configparser.Error:
        return None
    if profile == "DEFAULT":
        return cfg.defaults().get("host")
    return cfg.get(profile, "host", fallback=None) if cfg.has_section(profile) else None


def _preflight(profile: str | None) -> None:
    """Fail fast (seconds, not minutes) when the workspace host is unreachable.

    Uses the shared ``starboard.check_connectivity`` preflight when the full
    ``starboard`` wheel is installed (facade import, GUIDELINE-005); a skills-only
    install falls back to the same TCP reachability probe. Network-only — no
    token is sent; auth problems still surface from the SDK. No host → no-op.
    """
    host = _target_host(profile)
    if not host:
        return
    try:
        from starboard import check_connectivity
    except ImportError:
        pass  # skills-only install: stdlib probe below
    else:
        result = check_connectivity(host, None, timeout=_PREFLIGHT_TIMEOUT_S)
        if not result.ok:
            raise ApiError(f"network: {result.message}")
        return
    import socket
    import urllib.parse

    url = host if host.startswith(("http://", "https://")) else f"https://{host}"
    parsed = urllib.parse.urlparse(url)
    try:
        with socket.create_connection(
            (parsed.hostname or host, parsed.port or 443), timeout=_PREFLIGHT_TIMEOUT_S
        ):
            pass
    except OSError as exc:
        raise ApiError(
            f"network: cannot reach {url.rstrip('/')} — check network / VPN / sandbox "
            f"connectivity ({exc})"
        ) from exc


def _state_value(resp) -> str | None:
    state = getattr(getattr(resp, "status", None), "state", None)
    return getattr(state, "value", state)


def _cancel_quietly(w, resp) -> None:
    """Best-effort cancel of an in-flight statement so it doesn't keep burning warehouse time."""
    statement_id = getattr(resp, "statement_id", None)
    if not statement_id:
        return
    with contextlib.suppress(Exception):  # best-effort; the timeout error is what matters
        w.statement_execution.cancel_execution(statement_id)


_INT_TYPES = frozenset({"BYTE", "SHORT", "INT", "LONG"})
_FLOAT_TYPES = frozenset({"FLOAT", "DOUBLE"})


def _type_name(col) -> str | None:
    t = getattr(col, "type_name", None)
    t = getattr(t, "value", t)
    return str(t).upper() if t else None


def _to_number(value, type_name: str | None, scale: int | None):
    """One Statement Execution value (always a string) as its manifest type.

    BYTE/SHORT/INT/LONG → int; FLOAT/DOUBLE → float; DECIMAL → int when its scale is 0,
    else float (DBU / $ sums need ~15 significant digits, well inside a double);
    BOOLEAN → bool. Anything else, NULL, and non-finite values (NaN/Infinity — not
    valid JSON numbers) are returned unchanged."""
    if not isinstance(value, str) or type_name is None:
        return value
    try:
        if type_name in _INT_TYPES or (type_name == "DECIMAL" and scale == 0):
            return int(decimal.Decimal(value))
        if type_name in _FLOAT_TYPES or type_name == "DECIMAL":
            number = float(value)
            return number if math.isfinite(number) else value
        if type_name == "BOOLEAN":
            return {"true": True, "false": False}.get(value.lower(), value)
    except (ValueError, decimal.InvalidOperation):
        return value
    return value


def type_rows(schema_columns: list, rows: list) -> list:
    """Public path: convert each string cell to its manifest column type (see :func:`_to_number`)."""
    types = [(_type_name(c), getattr(c, "type_scale", None)) for c in schema_columns]
    if not any(t for t, _ in types):
        return rows
    return [
        [_to_number(v, *types[i]) if i < len(types) else v for i, v in enumerate(row)]
        for row in rows
    ]


def _plain(value):
    """Internal path: a ``Decimal`` cell as int (integral exponent) / float, like the public path."""
    if isinstance(value, decimal.Decimal):
        if not value.is_finite():
            return str(value)
        exponent = value.as_tuple().exponent
        return int(value) if isinstance(exponent, int) and exponent >= 0 else float(value)
    return value


def shape_rows(columns: list, rows: list, mode: str | None) -> list:
    """Return ``rows`` as positional lists (``arrays``) or column-keyed dicts (``objects``)."""
    if mode == "objects":
        return [dict(zip(columns, row, strict=False)) for row in rows]
    return rows


def _attempts_of(*objs) -> int | None:
    """Best-effort retry count an executor recorded (``attempts`` / ``last_attempts``)."""
    for obj in objs:
        for attr in ("attempts", "last_attempts"):
            value = getattr(obj, attr, None)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def _internal_source_builder():
    """Load the gated internal discovery-source builder from its entry point.

    The internal package registers a provider on ``starboard.port_adapters``; its
    ``create()`` yields a builder whose ``build(workspace_ids=...)`` returns a
    workspace-scoped source. Absent package → a clear error, never a fallback to
    a customer warehouse.
    """
    try:
        eps = importlib_metadata.entry_points(group=_ADAPTER_GROUP)
    except Exception as exc:  # noqa: BLE001 - metadata backends vary
        raise ApiError(f"internal source not available: {exc}") from exc
    for ep in eps:
        if ep.name == _INTERNAL_SOURCE_EP:
            provider = ep.load()
            return provider.create() if hasattr(provider, "create") else provider()
    raise ApiError(
        "internal source not available: the internal package is not installed. "
        "Use --profile/--warehouse-id for a customer workspace"
    )


def run_internal_sql(statement: str, workspace_id: str, limit: int) -> dict:
    """Run a read-only statement on the internal source, scoped to ``workspace_id``.

    Same path internal discovery uses: the source rewrites any public ``system.*``
    names and wraps every tenant-grained table in a ``workspace_id`` filter before
    executing, so a statement can never read another workspace's rows.
    """
    effective_limit, sql_limit = _effective_limit(statement, limit)
    builder = _internal_source_builder()
    try:
        source = builder.build(workspace_ids=(str(workspace_id),))
    except Exception as exc:  # noqa: BLE001 - scope resolution / auth failures
        raise ApiError(f"internal source unavailable for workspace {workspace_id}: {exc}") from exc
    adhoc = SimpleNamespace(query_id="adhoc-sql", required_tables=())
    prepared = source.prepare(adhoc, statement)
    if not hasattr(prepared, "executor"):
        raise ApiError(f"internal source refused the statement: {getattr(prepared, 'reason', prepared)}")
    try:
        frame = asyncio.run(prepared.executor.execute_sql(prepared.sql))
    except HelperError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as an API error, never 0 rows
        raise_api_error(RuntimeError(f"read-only query did not complete: {exc}"))
    columns = [str(c) for c in getattr(frame, "columns", [])]
    all_rows = [[_plain(v) for v in r] for r in frame.rows()] if columns else []
    rows = all_rows[:limit]
    out = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "row_limit": effective_limit,
        "limit_source": "sql" if sql_limit is not None and sql_limit <= limit else "cli",
        "sql_limit": sql_limit,
        "cli_row_limit": limit,
        "limit_reached": len(rows) >= effective_limit,
        "source": "internal",
        "workspace_scope": [str(workspace_id)],
        "state": "SUCCEEDED",
        "read_only": True,
    }
    attempts = _attempts_of(prepared.executor, getattr(prepared.executor, "_executor", None))
    if attempts is not None:
        out["attempts"] = attempts
    return out


def cmd_sql(args):
    """Run a READ-ONLY parameterized SQL statement for independent evidence re-check."""
    result = _run_sql(args)
    result["rows"] = shape_rows(result["columns"], result["rows"], getattr(args, "rows", None))
    if getattr(args, "rows", None) == "objects":
        result["rows_format"] = "objects"
    return result


def _run_sql(args):
    statement = _assert_read_only(args.sql)
    limit = max(1, min(int(args.limit), _MAX_ROW_LIMIT))
    internal_ws = getattr(args, "internal_workspace_id", None)
    if internal_ws:
        if getattr(args, "warehouse_id", None) or getattr(args, "profile", None) or args.param:
            raise ArgError(
                "--internal-workspace-id cannot be combined with --warehouse-id, "
                "--profile or --param"
            )
        return run_internal_sql(statement, internal_ws, limit)
    if not getattr(args, "warehouse_id", None):
        raise ArgError("--warehouse-id is required (or pass --internal-workspace-id)")
    params = None
    if args.param:
        from databricks.sdk.service.sql import StatementParameterListItem

        # NOTE: values bind as strings (no type inference). For a numeric predicate
        # (`... > :n`) cast in SQL (`:n::bigint`) — a string-bound param can implicitly
        # mis-compare and skew a re-check. (review G9 #4)
        params = []
        for kv in args.param:
            if "=" not in kv:
                raise ArgError(f"--param must be NAME=VALUE, got {kv!r}")
            name, _, value = kv.partition("=")
            params.append(StatementParameterListItem(name=name.strip(), value=value))
    profile = getattr(args, "profile", None)
    timeout = getattr(args, "timeout", None)
    if timeout is not None and timeout <= 0:
        raise ArgError("--timeout must be a positive number of seconds")
    effective_limit, sql_limit = _effective_limit(statement, limit)
    _preflight(profile)
    w = _client(profile) if profile else _client()
    try:
        if timeout is None:
            wait_s = _MAX_WAIT_WINDOW_S
        else:
            # The API accepts wait_timeout of 0s or 5s..50s; anything longer is polled.
            wait_s = 0 if timeout < 5 else min(int(timeout), _MAX_WAIT_WINDOW_S)
        started = time.monotonic()
        resp = w.statement_execution.execute_statement(
            warehouse_id=args.warehouse_id,
            statement=statement,
            parameters=params,
            row_limit=limit,
            wait_timeout=f"{wait_s}s",
        )
        state_val = _state_value(resp)
        if timeout is not None:
            while state_val in _IN_FLIGHT_STATES and time.monotonic() - started < timeout:
                time.sleep(min(_POLL_INTERVAL_S, max(0.0, timeout - (time.monotonic() - started))))
                resp = w.statement_execution.get_statement(resp.statement_id)
                state_val = _state_value(resp)
        status = getattr(resp, "status", None)
        state = getattr(status, "state", None)
        # A re-check that did not SUCCEED must NOT be read as "0 rows": a PENDING/RUNNING
        # (timed out) or FAILED statement returns result=None, and silently returning an
        # empty result would falsely refute a real finding. (review G9 #2)
        if state_val != "SUCCEEDED":
            err = getattr(status, "error", None)
            detail = getattr(err, "message", None) or err
            if not detail:
                detail = "did not finish within the wait window"
            if state_val in _IN_FLIGHT_STATES:
                waited = f"{timeout:g}s (--timeout)" if timeout is not None else f"{_MAX_WAIT_WINDOW_S}s"
                detail = f"{detail} ({waited}); statement cancelled. Raise --timeout for long aggregations"
                _cancel_quietly(w, resp)
                # Timeout / resource exhaustion: capacity hint is relevant.
                suffix = f" {_CAPACITY_HINT}"
            elif _is_sql_analysis_error(detail):
                # SQL semantic/analysis error (DATATYPE_MISMATCH, UNRESOLVED_COLUMN,
                # etc.): the fix is the query, not warehouse resources. Suppress the
                # capacity hint so the agent sees a clean SQL error (D14).
                suffix = ""
            else:
                # Other FAILED states (e.g. resource errors, auth, unexpected):
                # retain the capacity hint as a generic diagnostic nudge.
                suffix = f" {_CAPACITY_HINT}"
            raise_api_error(
                RuntimeError(
                    f"read-only query did not complete (state={state_val}): {detail}.{suffix}"
                )
            )
        manifest = getattr(resp, "manifest", None)
        schema = getattr(manifest, "schema", None) if manifest else None
        schema_columns = list(getattr(schema, "columns", None) or [])
        columns = [c.name for c in schema_columns]
        result = getattr(resp, "result", None)
        data_array = getattr(result, "data_array", None) if result else None
        # Statement Execution returns every value as a string: type them from the manifest
        # so DECIMAL/DOUBLE/INT/BOOLEAN columns come back as JSON numbers / booleans.
        rows = type_rows(schema_columns, [list(r) for r in data_array]) if data_array else []
        column_types = {c.name: _type_name(c) for c in schema_columns if _type_name(c)}
        return {
            "columns": columns,
            **({"column_types": column_types} if column_types else {}),
            "rows": rows,
            "row_count": len(rows),
            # The cap the returned population is actually bounded by: the smaller
            # of the statement's trailing SQL LIMIT and the CLI --limit. A result
            # that fills it is a ranked sample, not a full population.
            "row_limit": effective_limit,
            "limit_source": "sql" if sql_limit is not None and sql_limit <= limit else "cli",
            "sql_limit": sql_limit,
            "cli_row_limit": limit,
            "limit_reached": len(rows) >= effective_limit,
            "warehouse_id": args.warehouse_id,
            "state": getattr(state, "value", state),
            "read_only": True,
        }
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(e)
