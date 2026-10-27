"""Diagnostic domain helper — fetch Databricks diagnostic/observability data."""
import base64
from urllib.parse import quote

from starboard_skills.helpers.contract import (
    ACQUIRE_DEFAULT_BYTES,
    ApiError,
    HelperError,
    NotFoundError,
    byte_budget,
    raise_api_error,
    redact_emails,
    scrub_identity,
)
from starboard_skills.helpers.contract import make_client as _client

#: Gap codes (exit 2): the cluster delivers no logs / to a store we cannot read.
CLUSTER_LOG_DELIVERY_OFF = "cluster_log_delivery_off"
CLUSTER_LOG_DESTINATION_UNSUPPORTED = "cluster_log_destination_unsupported"
_DRIVER_LOG_FILES = {"stdout": "stdout", "stderr": "stderr", "log4j": "log4j-active.log"}
_READ_CHUNK = 2**20  # DBFS read() caps a single call at 1 MB
#: Most bytes read from a Volumes log when the tail cannot be range-read (no
#: content length, or the Range header not honoured); the kept tail is then the
#: tail of what was read.
_VOLUMES_SCAN_CAP = 16 * 2**20


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

    driver_log = sp.add_parser(
        "driver-log", help="Tail a driver log from the cluster's log-delivery destination"
    )
    driver_log.add_argument("--cluster-id", required=True, type=str)
    driver_log.add_argument("--stream", choices=sorted(_DRIVER_LOG_FILES), default="stdout")
    driver_log.add_argument(
        "--tail-bytes", type=byte_budget, default=ACQUIRE_DEFAULT_BYTES,
        help="Keep at most this many bytes from the end of the log (default 64 KiB, max 1 MiB)",
    )
    driver_log.set_defaults(func=cmd_driver_log)


def cmd_workspace(args):  # noqa: ARG001
    w = _client()
    try:
        conf = w.workspace_conf.get_status(keys="enableIpAccessLists,enableTokensConfig")
        return {"workspace_config": dict(conf) if conf else {}}
    except Exception as e:
        raise_api_error(e)


def cmd_node_types(args):  # noqa: ARG001
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
        raise_api_error(e)


def cmd_spark_versions(args):  # noqa: ARG001
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
        raise_api_error(e)


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
        raise_api_error(e, not_found_message=f"Run {args.run_id} not found")


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
        raise_api_error(e)


def _log_destination(cluster) -> tuple[str, str]:
    """``(kind, destination)`` of a cluster's log delivery, or a gap (exit 2)."""
    conf = getattr(cluster, "cluster_log_conf", None)
    for kind in ("volumes", "dbfs"):
        store = getattr(conf, kind, None) if conf else None
        if store is not None and getattr(store, "destination", None):
            return kind, store.destination
    if conf is not None and any(
        getattr(conf, k, None) is not None for k in ("s3", "volumes", "dbfs")
    ):
        raise NotFoundError(
            f"{CLUSTER_LOG_DESTINATION_UNSUPPORTED}: cluster {cluster.cluster_id} delivers "
            "logs to a store this helper cannot read (only Volumes and DBFS are supported)"
        )
    raise NotFoundError(
        f"{CLUSTER_LOG_DELIVERY_OFF}: cluster {cluster.cluster_id} has no cluster log "
        "delivery configured"
    )


def _read_tail(stream, tail: int, cap: int) -> tuple[bytes, int]:
    """The last ``tail`` of at most ``cap`` bytes read from ``stream``, and the count read."""
    buf, total = b"", 0
    try:
        while total < cap and (chunk := stream.read(min(_READ_CHUNK, cap - total))):
            total += len(chunk)
            buf = (buf + chunk)[-tail:]
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return buf, total


def _volumes_range(w, path: str, offset: int):
    """``(stream from offset, range honoured?)``: a Files API ``Range`` download.

    The SDK ``files.download`` takes no offset; the Files API GET honours ``Range``
    (``206`` + ``Content-Range``), so the request goes through the client's
    ``api_client``.
    """
    headers = {"Accept": "application/octet-stream", "Range": f"bytes={offset}-"}
    workspace_id = getattr(getattr(w, "config", None), "workspace_id", None)
    if isinstance(workspace_id, str) and workspace_id:
        headers["X-Databricks-Workspace-Id"] = workspace_id
    res = w.api_client.do(
        "GET",
        f"/api/2.0/fs/files{quote(path)}",
        headers=headers,
        response_headers=["content-range"],
        raw=True,
    )
    return res["contents"], bool(res.get("content-range"))


def _tail_volumes(w, path: str, tail: int) -> tuple[bytes, int]:
    """The last ``tail`` bytes of a Volumes file and its size, reading at most the tail.

    The size comes from the file metadata and only the tail is range-read. Without a
    size, or when the range is not honoured, at most :data:`_VOLUMES_SCAN_CAP` bytes
    are streamed.
    """
    size = getattr(w.files.get_metadata(path), "content_length", None)
    if not isinstance(size, int):
        size = None  # no usable length: fall back to the capped stream
    if size is not None and size <= tail:
        buf, _ = _read_tail(w.files.download(path).contents, tail, tail)
        return buf, size
    if size is not None:
        stream, ranged = _volumes_range(w, path, size - tail)
        if ranged:
            buf, _ = _read_tail(stream, tail, tail)
            return buf, size
    else:
        stream = w.files.download(path).contents
    buf, read = _read_tail(stream, tail, _VOLUMES_SCAN_CAP)
    return buf, size if size is not None else read


def _tail_dbfs(w, path: str, tail: int) -> tuple[bytes, int]:
    size = w.dbfs.get_status(path).file_size or 0
    offset, parts = max(0, size - tail), []
    while offset < size:
        resp = w.dbfs.read(path, offset=offset, length=min(_READ_CHUNK, size - offset))
        data = base64.b64decode(resp.data or "")
        if not data:
            break
        parts.append(data)
        offset += len(data)
    return b"".join(parts), size


def cmd_driver_log(args):
    w = _client()
    try:
        cluster = w.clusters.get(args.cluster_id)
        # The path segment is the ID the API returned, never the user's argument.
        cluster_id = getattr(cluster, "cluster_id", None)
        if not cluster_id:
            raise ApiError(f"API error: cluster {args.cluster_id} returned no cluster_id")
        kind, dest = _log_destination(cluster)
        path = f"{dest.rstrip('/')}/{cluster_id}/driver/{_DRIVER_LOG_FILES[args.stream]}"
        reader = _tail_volumes if kind == "volumes" else _tail_dbfs
        raw, total = reader(w, path, args.tail_bytes)
        return scrub_identity({
            "cluster_id": cluster_id,
            "stream": args.stream,
            "destination_kind": kind,
            "path": path,
            "bytes": total,
            "truncated": total > len(raw),
            "tail_bytes": args.tail_bytes,
            "content": redact_emails(raw.decode("utf-8", errors="replace")),
        })
    except HelperError:
        raise
    except Exception as e:
        raise_api_error(
            e, not_found_message=f"Driver log for cluster {args.cluster_id} not found"
        )
