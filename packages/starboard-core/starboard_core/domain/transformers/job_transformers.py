"""Job data transformation functions.

This module provides functions to transform Databricks job configurations,
runs, and task data into compact, LLM-optimized formats for analysis.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

MEGABYTE = 1_000_000.0
THOUSAND = 1_000.0


# =============================================================================
# Helper Functions
# =============================================================================


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _filter_none_values(d: dict[str, Any]) -> dict[str, Any]:
    """Remove None values from dictionary."""
    return {k: v for k, v in d.items() if v is not None}


def _extract_result_state(record: dict[str, Any]) -> str | None:
    """Extract result state from various Databricks record shapes."""
    # Try common field names in order of specificity
    for field in ["result_state", "state"]:
        if field in record:
            val = record[field]
            # Handle nested state object
            if isinstance(val, dict):
                return val.get("result_state") or val.get("life_cycle_state")
            return val

    # Check for state object
    state = record.get("state", {})
    if isinstance(state, dict):
        return state.get("result_state") or state.get("life_cycle_state")

    return None


# =============================================================================
# Transform Functions
# =============================================================================


def transform_task_sources(task_sources: dict[str, Any]) -> dict[str, Any]:
    """Transform task_sources dictionary into LLM-friendly format.

    Flattens the nested structure so source code is clearly visible
    to the LLM for analysis.

    Args:
        task_sources: Dictionary mapping task_key to source info
            {
                "task_key": {
                    "type": "notebook",
                    "path": "/path/to/notebook",
                    "source": "actual code..."
                }
            }

    Returns:
        Transformed dictionary with clearer structure:
            {
                "task_key": {
                    "task_type": "notebook",
                    "file_path": "/path/to/notebook",
                    "code": "actual code..."
                }
            }
    """
    if not task_sources or not isinstance(task_sources, dict):
        return {}

    transformed = {}
    for task_key, source_info in task_sources.items():
        if not isinstance(source_info, dict):
            continue

        # Extract and rename fields for clarity
        transformed[task_key] = _filter_none_values(
            {
                "task_type": source_info.get("type"),
                "file_path": source_info.get("path"),
                # Use "code" instead of "source" for clarity
                "code": source_info.get("source"),
            }
        )

    return transformed


def transform_job_config(job_config: dict[str, Any]) -> dict[str, Any]:
    """Simplify a Databricks job configuration for LLM analysis.

    Removes identifiers, timestamps, user info, and other metadata
    unrelated to job tuning or performance optimization.

    Args:
        job_config: Raw Databricks job configuration

    Returns:
        Simplified job configuration dict
    """
    settings = job_config.get("settings", {})

    # Build simplified job dict
    simplified: dict[str, Any] = {
        "job": {
            "name": settings.get("name"),
            "format": settings.get("format"),
            "max_concurrent_runs": settings.get("max_concurrent_runs"),
            "performance_target": settings.get("performance_target"),
            "queue_enabled": settings.get("queue", {}).get("enabled"),
            "job_clusters": [],
            "tasks": [],
        }
    }

    # Process job clusters
    for job_cluster in settings.get("job_clusters", []):
        cluster = job_cluster.get("new_cluster", {})
        aws_attrs = cluster.get("aws_attributes", {})
        log_conf = cluster.get("cluster_log_conf", {})

        # Clean data security mode string
        data_security_mode = cluster.get("data_security_mode", "")
        if isinstance(data_security_mode, str):
            data_security_mode = data_security_mode.replace("DATA_SECURITY_MODE_", "")

        simplified["job"]["job_clusters"].append(
            {
                "job_cluster_key": job_cluster.get("job_cluster_key"),
                "new_cluster": {
                    "aws_attributes": {"availability": aws_attrs.get("availability")},
                    "cluster_log_conf": {
                        "dbfs": {
                            "destination": log_conf.get("dbfs", {}).get("destination")
                        }
                    },
                    "data_security_mode": data_security_mode,
                    "is_single_node": cluster.get("is_single_node"),
                    "node_type_id": cluster.get("node_type_id"),
                    "num_workers": cluster.get("num_workers"),
                    "runtime_engine": cluster.get("runtime_engine"),
                    "spark_env_vars": cluster.get("spark_env_vars"),
                    "spark_version": cluster.get("spark_version"),
                },
            }
        )

    # Process tasks
    for task in settings.get("tasks", []):
        notebook_task = task.get("notebook_task", {})
        notebook_path = notebook_task.get("notebook_path", "")

        simplified["job"]["tasks"].append(
            {
                "task_key": task.get("task_key"),
                "job_cluster_key": task.get("job_cluster_key"),
                "notebook_task": {"notebook_path": notebook_path},
                "run_if": task.get("run_if"),
            }
        )

    return simplified


def transform_job_runs(
    runs: list[dict[str, Any]], context: dict[str, Any]
) -> dict[str, Any]:
    """Transform Databricks job run payloads + job context into compact, LLM-ready dict.

    Features:
      - Drops IDs, URLs, and timestamps (except cluster_id)
      - Flattens cluster config
      - Removes overlapping/duplicated metadata
      - Summarizes recent runs to setup/execution/total + result
      - Adds per-task summaries, cluster_id, and task metrics

    Args:
        runs: List of job run dictionaries
        context: Job context with configuration

    Returns:
        Transformed job runs dictionary
    """
    job_ctx = (context or {}).get("job", {})
    job = _filter_none_values(
        {
            "name": job_ctx.get("name"),
            "format": job_ctx.get("format"),
            "performance_target": job_ctx.get("performance_target"),
            "max_concurrent_runs": job_ctx.get("max_concurrent_runs"),
            "queue_enabled": job_ctx.get("queue_enabled"),
        }
    )

    # Flatten first job_cluster
    cluster: dict[str, Any] = {}
    try:
        job_clusters = job_ctx.get("job_clusters") or []
        if job_clusters:
            jc = job_clusters[0]
            new_cluster = (jc or {}).get("new_cluster", {})
            aws_attrs = new_cluster.get("aws_attributes") or {}
            env_vars = new_cluster.get("spark_env_vars") or {}
            log_conf = (new_cluster.get("cluster_log_conf") or {}).get("dbfs") or {}

            # Normalize data security mode
            dsm = new_cluster.get("data_security_mode")
            if isinstance(dsm, str):
                dsm = "DEDICATED" if "DEDICATED" in dsm.upper() else dsm

            cluster = _filter_none_values(
                {
                    "type": "job_cluster",
                    "key": jc.get("job_cluster_key"),
                    "node_type_id": new_cluster.get("node_type_id"),
                    "num_workers": new_cluster.get("num_workers"),
                    "runtime_engine": new_cluster.get("runtime_engine"),
                    "spark_version": new_cluster.get("spark_version"),
                    "availability": aws_attrs.get("availability"),
                    "data_security_mode": dsm,
                    "is_single_node": new_cluster.get("is_single_node", False),
                    "spark_env_vars": env_vars or None,
                    "cluster_logs": log_conf.get("destination"),
                }
            )
    except (IndexError, KeyError):
        cluster = {"type": "serverless"}

    # Tasks (definition)
    tasks_out: list[dict[str, Any]] = []
    for task in job_ctx.get("tasks") or []:
        task_out = {
            "task_key": task.get("task_key"),
            "job_cluster_key": task.get("job_cluster_key"),
            "run_if": task.get("run_if"),
        }

        # Extract task type-specific fields
        if "notebook_task" in task:
            task_out.update(
                {
                    "type": "notebook",
                    "notebook_path": (task["notebook_task"] or {}).get("notebook_path"),
                }
            )
        elif "spark_python_task" in task:
            task_out.update(
                {
                    "type": "spark_python",
                    "python_file": (task["spark_python_task"] or {}).get("python_file"),
                    "parameters": (task["spark_python_task"] or {}).get("parameters"),
                }
            )
        elif "sql_task" in task:
            task_out.update(
                {
                    "type": "sql",
                    "query": (task["sql_task"] or {}).get("query"),
                    "warehouse_id": (task["sql_task"] or {}).get("warehouse_id"),
                }
            )

        tasks_out.append(_filter_none_values(task_out))

    def _extract_task_metrics(task: dict[str, Any]) -> dict[str, Any]:
        """Extract common/interesting metrics if present."""
        metrics: dict[str, Any] = {}
        tm = task.get("task_metrics") or task.get("metrics") or {}

        # Shuffle metrics
        shuffle_read = tm.get("shuffle_read_metrics") or {}
        if isinstance(shuffle_read, dict):
            if shuffle_read.get("remote_bytes_read") is not None:
                metrics["shuffle_remote_bytes_read"] = shuffle_read["remote_bytes_read"]
            if shuffle_read.get("local_bytes_read") is not None:
                metrics["shuffle_local_bytes_read"] = shuffle_read["local_bytes_read"]

        shuffle_write = tm.get("shuffle_write_metrics") or {}
        if isinstance(shuffle_write, dict):
            if shuffle_write.get("shuffle_bytes_written") is not None:
                metrics["shuffle_bytes_written"] = shuffle_write[
                    "shuffle_bytes_written"
                ]
            if shuffle_write.get("shuffle_records_written") is not None:
                metrics["shuffle_records_written"] = shuffle_write[
                    "shuffle_records_written"
                ]

        # Input metrics
        input_metrics = tm.get("input_metrics") or {}
        if isinstance(input_metrics, dict):
            if input_metrics.get("bytes_read") is not None:
                metrics["input_bytes_read"] = input_metrics["bytes_read"]
            if input_metrics.get("records_read") is not None:
                metrics["input_records_read"] = input_metrics["records_read"]

        # Output metrics
        output_metrics = tm.get("output_metrics") or {}
        if isinstance(output_metrics, dict):
            if output_metrics.get("bytes_written") is not None:
                metrics["output_bytes_written"] = output_metrics["bytes_written"]
            if output_metrics.get("records_written") is not None:
                metrics["output_records_written"] = output_metrics["records_written"]

        # CPU / Memory metrics
        if tm.get("executor_cpu_time_ms") is not None:
            metrics["executor_cpu_time_ms"] = tm["executor_cpu_time_ms"]
        if tm.get("peak_executor_memory") is not None:
            metrics["peak_executor_memory"] = tm["peak_executor_memory"]

        # Fallback: if tm is a flat dict with small number of numeric items
        if not metrics and isinstance(tm, dict):
            compact = {
                k: v
                for k, v in tm.items()
                if isinstance(v, (int, float)) or (isinstance(v, str) and len(v) < 64)
            }
            if compact and len(compact) <= 10:
                metrics = compact

        return metrics

    # Recent runs with per-task and cluster ids
    recent_runs: list[dict[str, Any]] = []
    successful_runs = 0
    failed_runs = 0
    total_duration = 0.0
    run_count = 0

    for run in runs or []:
        result = _extract_result_state(run)
        run_duration = run.get("run_duration") or 0

        # Count successes and failures based on result
        if result in ["SUCCESS", "SUCCESSFUL"]:
            successful_runs += 1
        elif result in [
            "FAILED",
            "FAILED_WITH_RETRIES",
            "INTERNAL_ERROR",
            "TIMEOUT",
            "CANCELED",
        ]:
            failed_runs += 1

        # Track duration
        if run_duration > 0:
            total_duration += run_duration
            run_count += 1

        run_entry = _filter_none_values(
            {
                "setup_ms": run.get("setup_duration"),
                "execution_ms": run.get("execution_duration"),
                "run_ms": run_duration,
                "result": result,
                "tasks": [],
            }
        )

        # Process tasks in run
        task_list: list[dict[str, Any]] = []
        for task in run.get("tasks") or []:
            cluster_instance = task.get("cluster_instance") or {}

            task_entry = _filter_none_values(
                {
                    "task_key": task.get("task_key"),
                    "cluster_id": cluster_instance.get("cluster_id"),
                    "spark_context_id": cluster_instance.get("spark_context_id"),
                    "setup_ms": task.get("setup_duration"),
                    "execution_ms": task.get("execution_duration"),
                    "result": _extract_result_state(task),
                    "metrics": _extract_task_metrics(task) or None,
                }
            )
            task_list.append(task_entry)

        run_entry["tasks"] = task_list
        recent_runs.append(run_entry)

    # Compute runtime statistics
    total_runs = len(runs) if runs else 0
    success_rate = successful_runs / total_runs if total_runs > 0 else 0.0
    avg_duration_seconds = (
        (total_duration / run_count / 1000.0) if run_count > 0 else 0.0
    )

    # Final output
    return {
        "job": job,
        "cluster": cluster,
        "tasks": tasks_out,
        "recent_runs": recent_runs,
        "success_rate": success_rate,
        "failed_runs": failed_runs,
        "avg_duration_seconds": avg_duration_seconds,
    }


def transform_system_tables_job_detail(
    raw_input: list[dict[str, Any]],
) -> dict[str, Any]:
    """Transform Databricks job/run/task/statement data into compact LLM-optimized JSON.

    Args:
        raw_input: List of raw statement records from system tables

    Returns:
        Transformed job details dictionary
    """
    jobs: dict[Any, dict[Any, dict[Any, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(
                lambda: {"stmts": [], "cluster_id": None, "derived": {}}
            )
        )
    )

    for record in raw_input:
        jid = record.get("job_id")
        rid = record.get("run_id")
        trid = record.get("run_task_id")
        stmt_id = record.get("statement_id")

        # Process statement text
        stmt_text = record.get("statement_text")
        if stmt_text:
            stmt_text = (
                stmt_text.replace("result.", "").replace("(", ":").replace(")", "")
            )

        stmt = {
            "sid": stmt_id,
            "op": record.get("statement_type"),
            "text": stmt_text,
            "total_time": round(_safe_float(record.get("total_duration_ms")) / 1000, 3),
            "ex_time": round(
                _safe_float(record.get("execution_duration_ms")) / 1000, 3
            ),
            "compile_time": round(
                _safe_float(record.get("compilation_duration_ms")) / 1000, 3
            ),
            "read_files": int(_safe_float(record.get("read_files"))),
            "rows_read": round(_safe_float(record.get("read_rows")) / THOUSAND, 3),
            "read_mb": round(_safe_float(record.get("read_bytes")) / MEGABYTE, 3),
            "read_cache": int(_safe_float(record.get("read_io_cache_percent"))),
            "write_rows": round(_safe_float(record.get("written_rows")) / THOUSAND, 3),
            "write_mb": round(_safe_float(record.get("written_bytes")) / MEGABYTE, 3),
            "ok": (
                1
                if record.get("run_result") == "SUCCEEDED"
                or record.get("task_result") == "SUCCEEDED"
                else 0
            ),
        }

        task = jobs[jid][rid][trid]

        # Extract cluster ID from compute_ids JSON array
        compute_ids = record.get("compute_ids")
        if compute_ids:
            try:
                parsed = json.loads(compute_ids)
                task["cluster_id"] = parsed[0] if parsed else None
            except (json.JSONDecodeError, IndexError, TypeError):
                task["cluster_id"] = None

        task["stmts"].append(stmt)
        task["start"] = record.get("run_start")
        task["end"] = record.get("run_end")

    # Compute derived metrics
    out_jobs: dict[str, Any] = {
        "const": {
            "cluster_type": "SERVERLESS",
            "units": {"time": "s", "size": "MB", "rows": "k"},
        },
        "job": {"jid": None, "runs": []},
    }

    for jid, runs in jobs.items():
        out_jobs["job"]["jid"] = jid

        for rid, tasks in runs.items():
            run_obj: dict[str, Any] = {
                "rid": rid,
                "ts": None,
                "te": None,
                "ok": 1,
                "tasks": [],
            }

            for trid, task in tasks.items():
                stmts = task["stmts"]

                # Calculate totals
                total_exec = sum(s["ex_time"] for s in stmts if s["ex_time"] > 0)
                total_read_mb = sum(s["read_mb"] for s in stmts)
                total_write_mb = sum(s["write_mb"] for s in stmts)
                total_rows_k = sum(s["rows_read"] for s in stmts)

                task["derived"] = {
                    "ex_time": round(total_exec, 3),
                    "read_mb": round(total_read_mb, 3),
                    "write_mb": round(total_write_mb, 3),
                    "read_mbps": round(total_read_mb / total_exec, 2)
                    if total_exec > 0
                    else 0,
                    "rows_read_kps": round(total_rows_k / total_exec, 2)
                    if total_exec > 0
                    else 0,
                }

                run_obj["tasks"].append(
                    {
                        "trid": trid,
                        "cluster_id": task["cluster_id"],
                        "stmts": stmts,
                        "derived": task["derived"],
                    }
                )

            out_jobs["job"]["runs"].append(run_obj)

    return out_jobs
