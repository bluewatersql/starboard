"""Cluster data transformation functions.

This module provides functions to transform Databricks cluster metrics and references
into compact, LLM-optimized formats for analysis.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from starboard_core.domain.models.databricks import (
    ClusterJobReference,
    ClusterReference,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def _ts_ms_to_iso(ts_ms: int | None) -> str | None:
    """Convert timestamp in milliseconds to ISO format string."""
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
    except Exception:
        return None


def _ts_ms_to_day_key(ts_ms: int | None) -> str | None:
    """Convert timestamp in milliseconds to day key string (YYYY-MM-DD)."""
    if ts_ms is None:
        return None
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
    except Exception:
        return None


def _first(d: dict[str, Any], *paths: str, default: Any = None) -> Any:
    """Return first non-empty value among dotted key paths."""
    for path in paths:
        cur = d
        try:
            for p in path.split("."):
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    raise KeyError
            if cur not in (None, "", {}):
                return cur
        except KeyError:
            continue
    return default


def _strip_nulls(data: Any) -> Any:
    """Recursively remove None, empty strings, dicts, and lists from data structure."""
    if isinstance(data, dict):
        cleaned_dict = {}
        for key, value in data.items():
            cleaned_value = _strip_nulls(value)
            if cleaned_value not in (None, "", {}, []):
                cleaned_dict[key] = cleaned_value
        return cleaned_dict

    if isinstance(data, list):
        cleaned_list = [
            _strip_nulls(item) for item in data if item not in (None, "", {}, [])
        ]
        return [item for item in cleaned_list if item not in (None, "", {}, [])]

    return data


# =============================================================================
# Transform Functions
# =============================================================================


def transform_job_run_clusters(
    job_runs: list[dict[str, Any]],
) -> dict[str, ClusterReference]:
    """Extract cluster references from job runs.

    Args:
        job_runs: List of job run dictionaries

    Returns:
        Dictionary mapping cluster_id to ClusterReference objects
    """
    jobclusters: dict[str, ClusterReference] = {}

    for run in job_runs:
        job_id = run["job_id"]
        run_id = run["run_id"]

        for task in run["tasks"]:
            cluster_instance = task.get("cluster_instance", {})
            cluster_id = cluster_instance.get("cluster_id")

            if not cluster_id:
                continue

            task_name = task.get("task_key")
            context_id = cluster_instance.get("spark_context_id")

            if cluster_id not in jobclusters:
                jobclusters[cluster_id] = ClusterReference(cluster_id=cluster_id)

            cluster_job = jobclusters[cluster_id]

            if run_id not in cluster_job.runs:
                cluster_job.runs[run_id] = ClusterJobReference(
                    job_id=job_id, run_id=run_id
                )

            job_reference = cluster_job.runs[run_id]
            job_reference.tasks[task_name] = context_id

    return jobclusters


def _log_conf_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize cluster_log_conf. Supports common keys: volumes/dbfs/s3/abfss/gs.

    For volumes, the destination path is normalized to dbfs:/Volumes/... format
    since the DBFS API is used to access Unity Catalog Volumes.
    """
    if not cfg or not isinstance(cfg, dict):
        return {}
    for key in ("volumes", "dbfs", "s3", "abfss", "gs"):
        block = cfg.get(key)
        if isinstance(block, dict) and "destination" in block and block["destination"]:
            destination = block["destination"]
            # Normalize volumes paths to dbfs:/Volumes/... format for DBFS API access
            if key == "volumes" and destination.startswith("/Volumes/"):
                destination = f"dbfs:{destination}"
            return {"type": key, "destination": destination}
    dest = _first(cfg, "destination")
    if dest:
        return {"type": "unknown", "destination": dest}
    return {}


def _filter_spark_conf(spark_conf: dict[str, Any]) -> dict[str, Any]:
    """Keep only confs that meaningfully affect behavior or are helpful context."""
    if not spark_conf:
        return {}
    allow_prefixes = (
        "spark.databricks.cluster.profile",
        "spark.master",
        "spark.sql.",
        "spark.databricks.io.",
        "spark.executor.",
        "spark.driver.",
        "spark.task.",
        "spark.python.",
        "spark.databricks.clusterUsageTags.",
    )
    keep = {}
    for k, v in spark_conf.items():
        if any(k.startswith(pref) for pref in allow_prefixes):
            keep[k] = v
    return keep


def transform_cluster_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Distill Databricks clusters/get response into LLM-friendly context.

    - Removes low-signal IDs and internals
    - Preserves meaningful compute/runtime/security settings
    - Normalizes timestamps to ISO8601
    - Preserves log configuration (destination + type)
    - Adds spec_delta when live values differ from cluster.spec
    """
    raw = raw or {}
    spec = raw.get("spec") or {}

    id = raw.get("cluster_id") or spec.get("cluster_id")
    name = raw.get("cluster_name") or spec.get("cluster_name")

    runtime = {
        "spark_version": raw.get("spark_version") or spec.get("spark_version"),
        "ml_runtime": bool(raw.get("use_ml_runtime") or spec.get("use_ml_runtime")),
        "runtime_engine": raw.get("runtime_engine"),
        "kind": raw.get("kind") or spec.get("kind"),
    }

    compute = {
        "is_single_node": bool(
            raw.get("is_single_node")
            if raw.get("is_single_node") is not None
            else spec.get("is_single_node")
        ),
        "node_type_id": raw.get("node_type_id") or spec.get("node_type_id"),
        "driver_node_type_id": raw.get("driver_node_type_id")
        or spec.get("driver_node_type_id"),
        "num_workers": (
            raw.get("num_workers")
            if raw.get("num_workers") is not None
            else spec.get("num_workers")
        ),
        "enable_elastic_disk": raw.get("enable_elastic_disk"),
        "enable_local_disk_encryption": raw.get("enable_local_disk_encryption"),
        "aws": None,
        "azure": None,
        "gcp": None,
    }
    if isinstance(raw.get("aws_attributes"), dict):
        aa = raw["aws_attributes"]
        compute["aws"] = {
            "availability": aa.get("availability"),
            "first_on_demand": aa.get("first_on_demand"),
            "spot_bid_price_percent": aa.get("spot_bid_price_percent"),
            "zone_id": aa.get("zone_id"),
        }

    security = {
        "data_security_mode": raw.get("data_security_mode")
        or spec.get("data_security_mode")
    }

    log_conf = _first(raw, "cluster_log_conf", "spec.cluster_log_conf", default={})
    logs = _log_conf_view(log_conf if isinstance(log_conf, dict) else {})

    spark_conf = _filter_spark_conf(raw.get("spark_conf") or {})

    distilled = {
        "id": id,
        "name": name,
        "runtime": runtime,
        "compute": compute,
        "security": security,
        "spark_conf": spark_conf,
        "logs": logs,
    }

    return _strip_nulls(distilled)


def _reason_view(details: dict[str, Any]) -> dict[str, Any]:
    r = details.get("reason") or {}
    out = {
        "code": r.get("code"),
        "type": r.get("type"),
        "username": (r.get("parameters") or {}).get("username") or details.get("user"),
    }
    return {k: v for k, v in out.items() if v}


def _normalize_event(e: dict[str, Any]) -> dict[str, Any]:
    details = e.get("details") or {}
    user = details.get("user") or (
        (details.get("reason") or {}).get("parameters") or {}
    ).get("username")
    return {
        "cluster_id": e.get("cluster_id"),
        "type": e.get("type"),
        "timestamp_ms": e.get("timestamp"),
        "timestamp": _ts_ms_to_iso(e.get("timestamp")),
        "user": user,
        "reason": _reason_view(details) or None,
    }


# Sessionization constants
_START = {"CREATING", "STARTING", "RESTARTING"}
_RUN = "RUNNING"
_END = "TERMINATING"


def _close_session(
    sess: dict[str, Any],
    end_ts_ms: int | None,
    end_reason: dict[str, Any] | None,
    end_user: str | None,
) -> None:
    if end_ts_ms is not None:
        sess["end_ms"] = end_ts_ms
        sess["end"] = _ts_ms_to_iso(end_ts_ms)
    if end_reason:
        sess["end_reason"] = end_reason
    if end_user:
        sess.setdefault("users", set()).add(end_user)
    sess["open"] = False


def _finalize_session(sess: dict[str, Any]) -> dict[str, Any]:
    s = {
        "start_ms": sess.get("start_ms"),
        "end_ms": sess.get("end_ms"),
        "start": sess.get("start"),
        "end": sess.get("end"),
        "end_reason": sess.get("end_reason"),
        "users": sorted(sess.get("users", set())),
    }
    start_ms = s["start_ms"]
    end_ms = s["end_ms"]
    if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)):
        s["duration_sec"] = max(0, int((end_ms - start_ms) / 1000))
    return s


def _sessionize(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ev = sorted(
        (_normalize_event(e) for e in events if isinstance(e, dict)),
        key=lambda x: x.get("timestamp_ms") or 0,
    )
    sessions: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    for e in ev:
        et, ts = e.get("type"), e.get("timestamp_ms")
        if et in _START:
            if cur and cur.get("open"):
                _close_session(cur, cur.get("start_ms"), None, None)
                sessions.append(_finalize_session(cur))
            cur = {
                "start_ms": ts,
                "start": e.get("timestamp"),
                "users": set(),
                "open": True,
            }
            if e.get("user"):
                cur["users"].add(e["user"])
        elif et == _RUN:
            if not cur:
                cur = {
                    "start_ms": ts,
                    "start": e.get("timestamp"),
                    "users": set(),
                    "open": True,
                }
            if e.get("user"):
                cur["users"].add(e["user"])
        elif et == _END:
            if not cur:
                cur = {
                    "start_ms": ts,
                    "start": e.get("timestamp"),
                    "users": set(),
                    "open": True,
                }
            _close_session(cur, ts, e.get("reason"), e.get("user"))
            sessions.append(_finalize_session(cur))
            cur = None
        else:
            if e.get("user") and cur and cur.get("open"):
                cur["users"].add(e["user"])

    if cur and cur.get("open"):
        _close_session(cur, cur.get("start_ms"), None, None)
        sessions.append(_finalize_session(cur))

    return [
        s
        for s in sessions
        if s.get("start_ms") is not None and s.get("end_ms") is not None
    ]


def _split_duration_by_day(start_ms: int, end_ms: int) -> list[tuple[str, int]]:
    """Split a [start_ms, end_ms] session duration into daily buckets (UTC)."""
    if end_ms <= start_ms:
        return []
    start_dt = datetime.fromtimestamp(start_ms / 1000, tz=UTC)
    end_dt = datetime.fromtimestamp(end_ms / 1000, tz=UTC)

    buckets: list[tuple[str, int]] = []
    cur = start_dt
    while cur.date() <= end_dt.date():
        next_midnight = datetime(cur.year, cur.month, cur.day, tzinfo=UTC) + timedelta(
            days=1
        )
        seg_end = min(end_dt, next_midnight)
        dur = (seg_end - cur).total_seconds()
        if dur > 0:
            buckets.append((cur.strftime("%Y-%m-%d"), int(dur)))
        cur = next_midnight
    return buckets


def transform_cluster_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Databricks cluster events by UTC day, ignoring config payloads.

    Returns:
        {
          "cluster_id": "...",
          "window": {"start": iso, "end": iso, "days": int},
          "per_day": {
             "YYYY-MM-DD": {
                 "events_by_type": {...},
                 "terminations_by_code": {...},
                 "users": {...},
                 "lifecycle": {"starts": int, "running": int, "terminations": int},
                 "incidents": [{"type": "..._DOWN", "timestamp": iso}, ...],
                 "active_time_sec": int
             },
             ...
          },
          "totals": {...same counters summed...}
        }
    """
    if not events:
        return {"per_day": {}, "totals": {}}

    ev = sorted(
        (_normalize_event(e) for e in events if isinstance(e, dict)),
        key=lambda x: x.get("timestamp_ms") or 0,
    )
    cluster_id = next(
        (e.get("cluster_id") for e in events if e.get("cluster_id")), None
    )

    DayData = dict[str, Any]
    per_day: defaultdict[str, DayData] = defaultdict(
        lambda: {
            "events_by_type": Counter(),
            "terminations_by_code": Counter(),
            "users": Counter(),
            "lifecycle": {"starts": 0, "running": 0, "terminations": 0},
            "incidents": [],
            "active_time_sec": 0,
        }
    )

    for e in ev:
        ts = e.get("timestamp_ms")
        if ts is None:
            continue
        day = _ts_ms_to_day_key(ts)
        if day is None:
            continue
        et = e.get("type") or "UNKNOWN"
        per_day[day]["events_by_type"][et] += 1
        if e.get("user"):
            per_day[day]["users"][e["user"]] += 1
        if et in _START:
            per_day[day]["lifecycle"]["starts"] += 1
        elif et == _RUN:
            per_day[day]["lifecycle"]["running"] += 1
        elif et == _END:
            per_day[day]["lifecycle"]["terminations"] += 1
            if e.get("reason") and e["reason"].get("code"):
                per_day[day]["terminations_by_code"][e["reason"]["code"]] += 1
        if et.endswith("_DOWN"):
            per_day[day]["incidents"].append(
                {"type": et, "timestamp": e.get("timestamp")}
            )

    sessions = _sessionize(events)
    for s in sessions:
        for day, sec in _split_duration_by_day(s["start_ms"], s["end_ms"]):
            per_day[day]["active_time_sec"] += sec

    start_ts = ev[0]["timestamp_ms"]
    end_ts = ev[-1]["timestamp_ms"]
    window = {
        "start": _ts_ms_to_iso(start_ts),
        "end": _ts_ms_to_iso(end_ts),
        "days": max(1, int(((end_ts - start_ts) / 1000) // 86400)),
    }

    per_day_out: dict[str, Any] = {}
    totals: dict[str, Any] = {
        "events_by_type": Counter(),
        "terminations_by_code": Counter(),
        "users": Counter(),
        "lifecycle": {"starts": 0, "running": 0, "terminations": 0},
        "incidents": 0,
        "active_time_sec": 0,
    }

    for day, d in per_day.items():
        per_day_out[day] = {
            "events_by_type": dict(d["events_by_type"]),
            "terminations_by_code": dict(d["terminations_by_code"]),
            "users": dict(d["users"]),
            "lifecycle": dict(d["lifecycle"]),
            "incidents": d["incidents"],
            "active_time_sec": d["active_time_sec"],
        }
        totals["events_by_type"].update(d["events_by_type"])
        totals["terminations_by_code"].update(d["terminations_by_code"])
        totals["users"].update(d["users"])
        for k in ("starts", "running", "terminations"):
            totals["lifecycle"][k] += d["lifecycle"][k]
        totals["incidents"] += len(d["incidents"])
        totals["active_time_sec"] += d["active_time_sec"]

    return {
        "cluster_id": cluster_id,
        "window": window,
        "per_day": dict(sorted(per_day_out.items())),
        "totals": {
            "events_by_type": dict(totals["events_by_type"]),
            "terminations_by_code": dict(totals["terminations_by_code"]),
            "users": dict(totals["users"]),
            "lifecycle": totals["lifecycle"],
            "incidents": totals["incidents"],
            "active_time_sec": totals["active_time_sec"],
        },
    }
