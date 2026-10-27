# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Sliced job-run reconstruction and F-12 aggregate combining (D3-18). Stdlib only.

Job runs are recorded as hourly periods (``system.lakeflow.job_run_timeline``). The
verify template ``vt-job-run-states`` collapses them to one row per run (final state
= ``MAX_BY(result_state, period_end_time)``), filtered to a set of job IDs. This
module rebuilds **per-job** run counts from one or more such slices (customer and
mirrored copies, adjacent windows) without double counting:

- rows are de-duplicated by dedupe kind ``job_run`` across all slices;
- a run is in the interval iff its last period ends in
  ``[interval_start, interval_end + 1 day)`` and before the injected ``today``;
- runs with no terminal state are excluded and counted as ``in_flight``.

The output is per job only: there is no workspace roll-up, because a job-filtered
slice never stands in for the workspace failure rate (that comes from F-06).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from starboard_core.engagement.dedupe import DEDUPE_KEYS, dedupe_rows

__all__ = [
    "CANCELLED_STATE",
    "F12_CAP",
    "FAILED_STATES",
    "METHOD_VERSION",
    "UNCERTAINTY_INTERVAL_OVERLAP",
    "UNCERTAINTY_PARTIAL_SLICE",
    "UNCERTAINTY_PER_JOB_CAP",
    "UNCERTAINTY_SOURCE_CONFLICT",
    "UNCERTAINTY_VERIFY_LIMIT",
    "AggregateSlice",
    "JobReliability",
    "Reconstruction",
    "RunSlice",
    "combine_job_aggregates",
    "reconstruct_runs",
    "slice_from_verify",
]

#: Terminal result states counted as a failed run (F-06, F-12, verify templates).
FAILED_STATES: tuple[str, ...] = ("FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT")
#: Reported separately; never a failure.
CANCELLED_STATE = "CANCELLED"
#: Shared by F-06, F-12 and run reconstruction (same definitions).
METHOD_VERSION = "job_reliability_v1"
#: F-12 lists the top N jobs per workspace; the list is a truncation.
F12_CAP = 25

UNCERTAINTY_VERIFY_LIMIT = "verify_limit_reached"
UNCERTAINTY_PARTIAL_SLICE = "partial_slice"
UNCERTAINTY_SOURCE_CONFLICT = "source_conflict"
UNCERTAINTY_PER_JOB_CAP = "per_job_cap_25"
UNCERTAINTY_INTERVAL_OVERLAP = "interval_overlap"

_JobKey = tuple[str, str]
_RunKey = tuple[str, str, str]


@dataclass(frozen=True)
class RunSlice:
    """Per-run rows of one ``vt-job-run-states`` result.

    Attributes:
        source_kind: Evidence source kind of the slice (as on ``EvidenceRef``).
        window_start / window_end: Inclusive ISO dates the slice covers.
        job_ids: The job filter (non-empty: every slice is job-filtered).
        evidence_id: Evidence ID of the verify result.
        rows: One mapping per run (``workspace_id``, ``job_id``, ``run_id``,
            ``result_state``, ``first_period_start``, ``last_period_end``).
        limit_reached: The verify result hit its row limit (rows may be missing).
        workspace_id: Workspace of the slice (keys requested jobs with no rows).
    """

    source_kind: str
    window_start: str
    window_end: str
    job_ids: tuple[str, ...]
    evidence_id: str
    rows: tuple[Mapping[str, Any], ...]
    limit_reached: bool = False
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        job_ids = tuple(str(j) for j in self.job_ids)
        if not job_ids:
            raise ValueError(
                "RunSlice.job_ids must be non-empty (slices are job-filtered)"
            )
        object.__setattr__(self, "job_ids", job_ids)
        object.__setattr__(self, "rows", tuple(self.rows))
        if _as_date(self.window_start) > _as_date(self.window_end):
            raise ValueError("RunSlice.window_start must not be after window_end")


@dataclass(frozen=True)
class AggregateSlice:
    """Per-job aggregate rows of one F-12 result over one window.

    Attributes:
        source_kind / evidence_id: As on ``RunSlice``.
        window_start / window_end: Inclusive ISO dates of the F-12 window.
        rows: One mapping per job (``workspace_id``, ``job_id``, ``runs``,
            ``failed_runs``, ``cancelled_runs``).
        method_version: Definition version of the counts.
    """

    source_kind: str
    window_start: str
    window_end: str
    evidence_id: str
    rows: tuple[Mapping[str, Any], ...]
    method_version: str = METHOD_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if _as_date(self.window_start) > _as_date(self.window_end):
            raise ValueError("AggregateSlice.window_start must not be after window_end")


@dataclass(frozen=True)
class JobReliability:
    """Reconstructed reliability counts of one job over the interval.

    Counts are ``None`` when ``coverage == "unknown"``. ``failure_rate_pct`` is
    ``None`` when there were no runs.
    """

    workspace_id: str
    job_id: str
    runs: int | None
    failed_runs: int | None
    cancelled_runs: int | None
    failure_rate_pct: float | None
    coverage: str
    uncertainty: tuple[str, ...]
    source_windows: tuple[tuple[str, str], ...]
    evidence_ids: tuple[str, ...]
    duplicate_rows: int = 0
    superseded_rows: int = 0
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reconstruction:
    """Per-job results (no workspace roll-up) plus run-level bookkeeping."""

    jobs: tuple[JobReliability, ...]
    in_flight: int = 0
    duplicate_rows: int = 0
    superseded_rows: int = 0
    conflicts: tuple[tuple[str, ...], ...] = ()


# ---- parsing helpers -----------------------------------------------------------


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace(" ", "T", 1)
        parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _state(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _int(value: Any) -> int:
    if value is None:
        return 0
    return int(float(value))


def _rate(failed: int, runs: int) -> float | None:
    return round(failed / runs * 100.0, 2) if runs else None


def _windows_tile(windows: Iterable[tuple[str, str]], start: date, end: date) -> bool:
    """Whether the inclusive date windows cover ``[start, end]`` with no gap."""
    cursor = start
    for w_start, w_end in sorted((_as_date(a), _as_date(b)) for a, b in windows):
        if w_start > cursor:
            return False
        if w_end >= cursor:
            cursor = w_end + timedelta(days=1)
        if cursor > end:
            return True
    return cursor > end


def _uniq(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(sorted(set(values)))


# ---- slice_from_verify ---------------------------------------------------------


def _parse_job_ids(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip().strip("'\"") for v in value if str(v).strip())
    return tuple(
        part.strip().strip("'\"")
        for part in str(value or "").split(",")
        if part.strip().strip("'\"")
    )


def slice_from_verify(
    payload: Mapping[str, Any], *, source_kind: str, evidence_id: str
) -> RunSlice:
    """Build a :class:`RunSlice` from a ``vt-job-run-states`` verify envelope.

    Reads ``data.rows`` (objects, or arrays plus ``data.columns``),
    ``data.limit_reached`` and the window / job filter from ``data.verify.params``.
    """
    data = payload.get("data") or {}
    params = (data.get("verify") or {}).get("params") or {}
    job_ids = _parse_job_ids(params.get("job_ids") or params.get("job_id"))
    if not job_ids:
        raise ValueError(
            "verify payload has no job_ids filter (vt-job-run-states needs --job-ids)"
        )
    for name in ("start", "end"):
        if not params.get(name):
            raise ValueError(f"verify payload has no {name!r} param")
    raw_rows = data.get("rows") or []
    columns = data.get("columns")
    rows: list[Mapping[str, Any]] = []
    for raw in raw_rows:
        if isinstance(raw, Mapping):
            rows.append(dict(raw))
        elif columns:
            rows.append(dict(zip(columns, raw, strict=False)))
        else:
            raise ValueError("verify rows are arrays but data.columns is missing")
    ws = params.get("ws")
    return RunSlice(
        source_kind=source_kind,
        window_start=str(params["start"]),
        window_end=str(params["end"]),
        job_ids=job_ids,
        evidence_id=evidence_id,
        rows=tuple(rows),
        limit_reached=bool(data.get("limit_reached")),
        workspace_id=str(ws) if ws not in (None, "") else None,
    )


# ---- reconstruct_runs ------------------------------------------------------------


@dataclass
class _JobAcc:
    slices: list[RunSlice] = field(default_factory=list)
    runs: int = 0
    failed: int = 0
    cancelled: int = 0
    duplicates: int = 0
    superseded: int = 0
    conflicts: list[str] = field(default_factory=list)


def reconstruct_runs(
    slices: Sequence[RunSlice],
    *,
    interval_start: date | str,
    interval_end: date | str,
    today: date | str,
    expected_jobs: Iterable[tuple[str, str]] = (),
) -> Reconstruction:
    """Rebuild per-job run counts from job-filtered per-run slices (D3-18).

    ``expected_jobs`` lists ``(workspace_id, job_id)`` pairs that must appear in
    the output; one that no slice covers is reported with coverage ``unknown``.
    """
    start, end, today_d = (
        _as_date(interval_start),
        _as_date(interval_end),
        _as_date(today),
    )
    end_excl = end + timedelta(days=1)
    jobs: dict[_JobKey, _JobAcc] = {}
    for ws, job in expected_jobs:
        jobs.setdefault((str(ws), str(job)), _JobAcc())

    # Group every row by its job_run key, remembering which slices requested which job.
    by_run: dict[_RunKey, list[Mapping[str, Any]]] = {}
    for s in slices:
        row_ws = {
            str(r.get("workspace_id"))
            for r in s.rows
            if r.get("workspace_id") is not None
        }
        workspaces = {s.workspace_id} if s.workspace_id else row_ws
        for ws in workspaces:
            for job in s.job_ids:
                jobs.setdefault((str(ws), job), _JobAcc()).slices.append(s)
        for row in s.rows:
            key = tuple(str(row.get(f)) for f in DEDUPE_KEYS["job_run"])
            run_key: _RunKey = (key[0], key[1], key[2])
            acc = jobs.setdefault((run_key[0], run_key[1]), _JobAcc())
            if s not in acc.slices:
                acc.slices.append(s)
            by_run.setdefault(run_key, []).append(row)

    in_flight = 0
    conflicts: list[_RunKey] = []
    for run_key, rows in by_run.items():
        acc = jobs[(run_key[0], run_key[1])]
        distinct: dict[tuple[datetime, str | None], Mapping[str, Any]] = {}
        for row in rows:
            distinct.setdefault(
                (_ts(row.get("last_period_end")), _state(row.get("result_state"))), row
            )
        acc.duplicates += len(rows) - len(distinct)
        stated = [k for k in distinct if k[1] is not None]
        top_end = max(k[0] for k in (stated or distinct))
        at_top = [k for k in distinct if k[0] == top_end]
        if len(at_top) > 1:
            acc.conflicts.append(run_key[2])
            conflicts.append(run_key)
            continue
        acc.superseded += len(distinct) - 1
        last_end, state = at_top[0]
        last_day = last_end.date()
        if not start <= last_day < end_excl:
            continue
        if state is None:
            in_flight += 1
            continue
        if last_day >= today_d:
            continue
        acc.runs += 1
        if state in FAILED_STATES:
            acc.failed += 1
        elif state == CANCELLED_STATE:
            acc.cancelled += 1

    out: list[JobReliability] = []
    for (ws, job), acc in sorted(jobs.items()):
        windows = _uniq((s.window_start, s.window_end) for s in acc.slices)
        evidence = _uniq(s.evidence_id for s in acc.slices)
        common: dict[str, Any] = {
            "workspace_id": ws,
            "job_id": job,
            "source_windows": windows,
            "evidence_ids": evidence,
            "duplicate_rows": acc.duplicates,
            "superseded_rows": acc.superseded,
            "conflicts": tuple(sorted(acc.conflicts)),
        }
        if acc.conflicts:
            out.append(_unknown(common, (UNCERTAINTY_SOURCE_CONFLICT,)))
            continue
        if not acc.slices:
            out.append(_unknown(common, ()))
            continue
        uncertainty: list[str] = []
        if any(s.limit_reached for s in acc.slices):
            uncertainty.append(UNCERTAINTY_VERIFY_LIMIT)
        if not _windows_tile(windows, start, end):
            uncertainty.append(UNCERTAINTY_PARTIAL_SLICE)
        out.append(
            JobReliability(
                runs=acc.runs,
                failed_runs=acc.failed,
                cancelled_runs=acc.cancelled,
                failure_rate_pct=_rate(acc.failed, acc.runs),
                coverage="partial" if uncertainty else "complete",
                uncertainty=tuple(uncertainty),
                **common,
            )
        )
    return Reconstruction(
        jobs=tuple(out),
        in_flight=in_flight,
        duplicate_rows=sum(a.duplicates for a in jobs.values()),
        superseded_rows=sum(a.superseded for a in jobs.values()),
        conflicts=tuple(sorted(conflicts)),
    )


def _unknown(common: Mapping[str, Any], uncertainty: tuple[str, ...]) -> JobReliability:
    return JobReliability(
        runs=None,
        failed_runs=None,
        cancelled_runs=None,
        failure_rate_pct=None,
        coverage="unknown",
        uncertainty=uncertainty,
        **common,
    )


# ---- combine_job_aggregates --------------------------------------------------------


def combine_job_aggregates(
    slices: Sequence[AggregateSlice],
    *,
    interval_start: date | str,
    interval_end: date | str,
) -> Reconstruction:
    """Combine F-12 per-job aggregates over disjoint windows (D3-18).

    Identical windows (e.g. customer and mirror copies) are de-duplicated by
    ``job_aggregate_slice``; distinct windows that overlap raise ``ValueError``
    (``interval_overlap``). Every job carries ``per_job_cap_25``: F-12 is a top-N
    list, so a job's coverage is at most ``partial``.
    """
    start, end = _as_date(interval_start), _as_date(interval_end)
    windows = sorted(
        {(_as_date(s.window_start), _as_date(s.window_end)) for s in slices}
    )
    reach: date | None = None
    for w_start, w_end in windows:
        if reach is not None and w_start <= reach:
            raise ValueError(
                f"{UNCERTAINTY_INTERVAL_OVERLAP}: F-12 window {w_start}..{w_end} overlaps "
                f"an earlier window ending {reach}"
            )
        reach = w_end if reach is None else max(reach, w_end)

    keyed: list[dict[str, Any]] = []
    sources: dict[tuple[str, ...], list[AggregateSlice]] = {}
    key_fields = DEDUPE_KEYS["job_aggregate_slice"]
    for s in slices:
        for row in s.rows:
            item: dict[str, Any] = {
                "workspace_id": str(row.get("workspace_id")),
                "job_id": str(row.get("job_id")),
                "window_start": str(s.window_start),
                "window_end": str(s.window_end),
                "method_version": s.method_version,
                "runs": _int(row.get("runs")),
                "failed_runs": _int(row.get("failed_runs")),
                "cancelled_runs": _int(row.get("cancelled_runs")),
            }
            keyed.append(item)
            sources.setdefault(tuple(item[f] for f in key_fields), []).append(s)
    result = dedupe_rows("job_aggregate_slice", keyed)

    per_job: dict[_JobKey, dict[str, Any]] = {}

    def _acc(key: _JobKey) -> dict[str, Any]:
        return per_job.setdefault(
            key,
            {
                "runs": 0,
                "failed": 0,
                "cancelled": 0,
                "dups": 0,
                "slices": [],
                "conflict": False,
            },
        )

    for row in result.unique:
        acc = _acc((row["workspace_id"], row["job_id"]))
        acc["runs"] += row["runs"]
        acc["failed"] += row["failed_runs"]
        acc["cancelled"] += row["cancelled_runs"]
        group = sources[tuple(row[f] for f in key_fields)]
        acc["dups"] += len(group) - 1
        acc["slices"].extend(group)
    for key in result.conflicts:
        acc = _acc((str(key[0]), str(key[1])))
        acc["conflict"] = True
        acc["slices"].extend(sources[tuple(key)])

    out: list[JobReliability] = []
    for (ws, job), acc in sorted(per_job.items()):
        job_slices: list[AggregateSlice] = acc["slices"]
        job_windows = _uniq((s.window_start, s.window_end) for s in job_slices)
        common: dict[str, Any] = {
            "workspace_id": ws,
            "job_id": job,
            "source_windows": job_windows,
            "evidence_ids": _uniq(s.evidence_id for s in job_slices),
            "duplicate_rows": acc["dups"],
        }
        if acc["conflict"]:
            out.append(
                _unknown(common, (UNCERTAINTY_PER_JOB_CAP, UNCERTAINTY_SOURCE_CONFLICT))
            )
            continue
        uncertainty = [UNCERTAINTY_PER_JOB_CAP]
        if not _windows_tile(job_windows, start, end):
            uncertainty.append(UNCERTAINTY_PARTIAL_SLICE)
        out.append(
            JobReliability(
                runs=acc["runs"],
                failed_runs=acc["failed"],
                cancelled_runs=acc["cancelled"],
                failure_rate_pct=_rate(acc["failed"], acc["runs"]),
                coverage="partial",
                uncertainty=tuple(uncertainty),
                **common,
            )
        )
    return Reconstruction(
        jobs=tuple(out),
        duplicate_rows=result.duplicates,
        conflicts=tuple(tuple(str(v) for v in k) for k in result.conflicts),
    )
