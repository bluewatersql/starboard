from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def extract_job_clusters(runs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Extract cluster information from job runs with dates.

    Returns a list of cluster entries sorted by run date (newest to oldest).
    Each entry contains:
    - cluster_id: The cluster identifier
    - spark_context_ids: List of unique spark context IDs
    - run_date: The run start time (epoch milliseconds)
    - run_id: The run identifier

    Args:
        runs: Iterable of run dictionaries (should be pre-sorted newest first for optimal performance)

    Returns:
        List of cluster info dicts sorted by run_date descending (newest first)

    Note:
        The first cluster in the returned list represents the most recent run,
        which should be used when fetching Spark logs.
    """
    cluster_entries = []
    seen_clusters = set()

    # Convert to list and ensure runs are sorted by start_time descending (newest first)
    runs_list = list(runs)
    runs_list.sort(key=lambda r: r.get("start_time", 0), reverse=True)

    for run in runs_list:
        run_id = run.get("run_id")
        run_date = run.get("start_time")  # Epoch milliseconds

        # Track unique cluster_ids per run
        run_clusters: defaultdict[str, set[str]] = defaultdict(set)

        for task in run.get("tasks", ()):
            ci = task.get("cluster_instance") or {}
            cluster_id = ci.get("cluster_id")
            spark_context_id = ci.get("spark_context_id")
            if cluster_id and spark_context_id:
                run_clusters[cluster_id].add(spark_context_id)

        # Add entry for each cluster in this run
        for cluster_id, spark_context_ids in run_clusters.items():
            cluster_key = (cluster_id, run_id)
            if cluster_key not in seen_clusters:
                seen_clusters.add(cluster_key)
                cluster_entries.append(
                    {
                        "cluster_id": cluster_id,
                        "spark_context_ids": sorted(spark_context_ids),
                        "run_date": run_date,
                        "run_id": run_id,
                    }
                )

    # Sort by run_date descending (newest first), handling None values
    # This ensures consistent ordering even if runs were not pre-sorted
    cluster_entries.sort(key=lambda x: x.get("run_date") or 0, reverse=True)

    return cluster_entries
