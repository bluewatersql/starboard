# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Per-observation baseline selection and finding states.

Pure functions, no I/O. Selection is per comparison key across the whole
account registry, not per task (D-18). Unreadable registrations are reported in
``unavailable`` and never treated as a baseline (D-19).

"Triggered" convention: an observation whose ``unit`` is :data:`TRIGGER_UNIT`
(``"flag"``) is a presence flag; it is triggered when ``value >= 0.5``. Flag
observations map to ``continuing`` / ``recovered`` / ``new``; any other measured
pair is ``continuing``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from starboard_core.engagement.health import ACQUISITION_METHOD
from starboard_core.engagement.jobruns import METHOD_VERSION as RELIABILITY_METHOD
from starboard_core.engagement.records import (
    BaselineSelection,
    FindingRecord,
    FindingRevision,
    Observation,
    Registration,
)

__all__ = [
    "TRIGGER_UNIT",
    "WINDOW_TOLERANCE",
    "Candidate",
    "UnavailableView",
    "comparison_key",
    "finding_states",
    "intervals_overlap",
    "same_lookback",
    "same_window_length",
    "select_baselines",
    "selection_reason",
    "window_comparison",
    "window_days",
]

TRIGGER_UNIT = "flag"
_TRIGGER_THRESHOLD = 0.5

#: Two reporting windows are the same length when they differ by at most this much.
#: One day absorbs clock jitter of a few hours and date-only vs timestamp ends on the
#: same nominal window, yet separates the 7 / 30 / 90-day health-review windows.
WINDOW_TOLERANCE = timedelta(days=1)


class UnavailableView(Protocol):
    """The slice of a registry ``RegistrationView`` this module reads."""

    @property
    def registration(self) -> Registration | None: ...

    @property
    def object_id(self) -> str: ...

    @property
    def reason(self) -> str: ...


@dataclass(frozen=True)
class Candidate:
    """One prior observation offered as a baseline.

    Attributes:
        observation: The prior observation.
        committed_revision: Manifest revision that committed it (>= 1).
        registration_id: Registration it was read through.
        run_task: The task of the prior run that recorded it (``None``: unknown).
        run_manifest: Whether that run committed a ``findings-manifest.json``
            (``None``: unknown, e.g. an imported local summary).
    """

    observation: Observation
    committed_revision: int
    registration_id: str
    run_task: str | None = None
    run_manifest: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation, Observation):
            raise TypeError("Candidate.observation must be an Observation")
        if (
            isinstance(self.committed_revision, bool)
            or not isinstance(self.committed_revision, int)
            or self.committed_revision < 1
        ):
            raise ValueError("Candidate.committed_revision must be an int >= 1")
        if not isinstance(self.registration_id, str) or not self.registration_id:
            raise ValueError("Candidate.registration_id must be a non-empty string")
        if self.run_task is not None and (
            not isinstance(self.run_task, str) or not self.run_task
        ):
            raise ValueError("Candidate.run_task must be None or a non-empty string")
        if self.run_manifest is not None and not isinstance(self.run_manifest, bool):
            raise ValueError("Candidate.run_manifest must be None or a bool")


def comparison_key(o: Observation) -> tuple[str, ...]:
    """``(account_key, workspace_id, family, entity_kind, entity_id, metric)``."""
    return (
        o.account_key,
        o.workspace_id,
        o.family,
        o.entity_kind,
        o.entity_id,
        o.metric,
    )


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _window(start: str, end: str) -> timedelta:
    return _ts(end) - _ts(start)


def same_window_length(first: timedelta, second: timedelta) -> bool:
    """Whether two window lengths match within :data:`WINDOW_TOLERANCE`."""
    return abs(first - second) <= WINDOW_TOLERANCE


def same_lookback(first: int, second: int) -> bool:
    """Whether two declared lookbacks (days) match within :data:`WINDOW_TOLERANCE`.

    The one length rule of ``engagement analyze`` and both ``run recur`` forms: a
    31-day prior and a 30-day current run are the same length; 7 and 30 are not.
    """
    return abs(first - second) <= WINDOW_TOLERANCE.days


def intervals_overlap(prior_end: str, current_start: str) -> bool:
    """Whether a prior window ending ``prior_end`` overlaps a current window starting
    ``current_start`` — the ``interval_overlap`` rule of :func:`select_baselines`, also
    applied to whole findings manifests by ``compute_cost_delta`` and ``run recur``."""
    return _ts(prior_end) > _ts(current_start)


def window_days(start: str, end: str) -> int:
    """Lookback days of a window: inclusive for date-only ends, rounded otherwise.

    ``2026-09-01``..``2026-09-07`` is 7 days; ``...T00:00Z``..``...T00:00Z`` a week
    apart is 7 days too.
    """
    if len(start) == 10 and len(end) == 10:
        return (_ts(end) - _ts(start)).days + 1
    return round((_ts(end) - _ts(start)) / timedelta(days=1))


# Rejections of a prior that measured nothing: present on every run with unmeasured
# families, so never the reason a whole run is not comparable while another exists.
_UNMEASURED = frozenset({"prior_not_measured", "prior_coverage_unknown"})


def selection_reason(
    selection: BaselineSelection, run_id: str | None = None
) -> str | None:
    """Why no key of ``selection`` has a baseline, or ``None`` when one does.

    The reason is the most frequent rejection of a measured prior
    (``interval_overlap``, ``window_mismatch``, ...; ties alphabetical,
    ``current_run`` ignored) — an unmeasured prior (``prior_not_measured`` /
    ``prior_coverage_unknown``) only when nothing else was rejected — else
    ``history_unavailable`` with unreadable registrations, else
    ``no_prior_measurement``. With ``run_id`` only that prior run's rejections
    count (all of them when it has none), so the reason is the compared run's.
    """
    if any(e.get("baseline_observation_id") for e in selection.selected):
        return None
    rejected = [r for r in selection.rejected if r["reason"] != "current_run"]
    if run_id is not None:
        rejected = [r for r in rejected if r.get("candidate_run_id") == run_id] or rejected
    reasons = Counter(str(r["reason"]) for r in rejected)
    if reasons:
        return min(reasons, key=lambda r: (r in _UNMEASURED, -reasons[r], r))
    return "history_unavailable" if selection.unavailable else "no_prior_measurement"


#: Observations measured over their own window, not the run's declared lookback:
#: job reliability spans (F-06 / F-12) and troubleshooting acquisitions.
_OWN_WINDOW_METHODS = frozenset({RELIABILITY_METHOD, ACQUISITION_METHOD})


def _run_interval(observations: Sequence[Observation]) -> tuple[str, str]:
    """The run's declared reporting window: the one most of its lookback-window
    observations cover (latest on a tie). Reliability spans and case acquisitions
    carry their own windows, so they count only when the run has nothing else; a
    union would invent a span no observation measured."""
    declared = [o for o in observations if o.method_version not in _OWN_WINDOW_METHODS]
    windows = Counter((o.interval_start, o.interval_end) for o in declared or observations)
    return max(windows, key=lambda w: (windows[w], _ts(w[1]), _ts(w[0])))


def _skip_reason(group: Sequence[Candidate], task: str | None) -> str | None:
    """Why a prior run is never the compared run, or ``None`` when it may be."""
    run_task = next((c.run_task for c in group if c.run_task is not None), None)
    if task is not None and run_task is not None and run_task != task:
        return "other_task"
    if any(c.run_manifest is False for c in group):
        return "no_findings_manifest"
    return None


def window_comparison(
    candidates: Sequence[Candidate],
    reporting_interval: tuple[str, str],
    selection: BaselineSelection | None = None,
    *,
    task: str | None = None,
    pinned: bool = False,
) -> dict[str, Any]:
    """Run-level comparability of the current run against its prior runs.

    Per-key baselines (:func:`select_baselines`) reject a different-length prior
    with ``window_mismatch``; this is the run-level summary of the same rule,
    and — given the run's ``selection`` — of every other rejection too.

    Only an eligible prior run is ever the compared run: one of the current
    ``task`` (when both are known) that committed a findings manifest (unless
    unknown). ``pinned`` (an explicit ``--prior``) waives both rules. A prior
    run's window is its declared lookback window (:func:`_run_interval`), and
    lengths compare by :func:`same_lookback`.

    Returns:
        ``{comparable, reason, prior_run_id, prior_lookback_days,
        current_lookback_days, prior_runs}``. ``prior_runs`` is
        ``[{run_id, interval: {start, end}, task, skipped_reason}]`` per prior run
        (newest first); ``skipped_reason`` is ``other_task`` /
        ``no_findings_manifest`` for a run that is never compared, else ``None``.
        ``comparable`` is True with no prior run (``reason`` ``None``). With prior
        runs but no eligible one it is False with ``no_eligible_prior``; with no
        eligible same-length run False with ``window_mismatch``; else False with
        :func:`selection_reason` of the compared run when ``selection`` selected
        no baseline for any key (e.g. ``interval_overlap``); else True.
        ``prior_run_id`` is the compared run — the newest eligible same-length
        one, else the newest eligible (``None`` without one) — and
        ``prior_lookback_days`` its lookback.
    """
    groups: dict[str, list[Candidate]] = {}
    for c in candidates:
        groups.setdefault(c.observation.run_id, []).append(c)
    spans = {
        run_id: _run_interval([c.observation for c in group])
        for run_id, group in groups.items()
    }
    skipped = {
        run_id: None if pinned else _skip_reason(group, task)
        for run_id, group in groups.items()
    }
    runs = sorted(spans.items(), key=lambda kv: (_ts(kv[1][1]), kv[0]), reverse=True)
    current_days = window_days(*reporting_interval)
    eligible = [r for r in runs if skipped[r[0]] is None]
    same = [r for r in eligible if same_lookback(window_days(*r[1]), current_days)]
    compared = (same or eligible)[0] if eligible else None
    reason: str | None = None
    if runs and compared is None:
        reason = "no_eligible_prior"
    elif compared is not None and not same:
        reason = "window_mismatch"
    elif compared is not None and selection is not None:
        reason = selection_reason(selection, compared[0])
    return {
        "comparable": reason is None,
        "reason": reason,
        "prior_run_id": None if compared is None else compared[0],
        "prior_lookback_days": None if compared is None else window_days(*compared[1]),
        "current_lookback_days": current_days,
        "prior_runs": [
            {
                "run_id": run_id,
                "interval": {"start": span[0], "end": span[1]},
                "task": next(
                    (c.run_task for c in groups[run_id] if c.run_task is not None), None
                ),
                "skipped_reason": skipped[run_id],
            }
            for run_id, span in runs
        ],
    }


def _is_flag(o: Observation) -> bool:
    return o.unit == TRIGGER_UNIT


def _triggered(o: Observation) -> bool:
    return o.value is not None and o.value >= _TRIGGER_THRESHOLD


def _rank(c: Candidate) -> tuple[datetime, datetime, int]:
    o = c.observation
    return (_ts(o.interval_end), _ts(o.as_of), c.committed_revision)


def _current_rank(o: Observation) -> tuple[bool, datetime, datetime]:
    return (o.state == "measured", _ts(o.interval_end), _ts(o.as_of))


def _unavailable_entries(views: Sequence[UnavailableView]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for view in views:
        status = getattr(view, "status", "history_unavailable")
        if status == "ok":
            continue
        reg = view.registration
        rid = reg.registration_id if reg is not None else view.object_id
        reason = f"{status}: {view.reason}" if view.reason else str(status)
        entries.append({"registration_id": rid, "reason": reason})
    return entries


def _flag_comparison(current: Observation, baseline: Observation) -> str:
    if _triggered(current):
        return "continuing" if _triggered(baseline) else "new"
    return "recovered" if _triggered(baseline) else "continuing"


def select_baselines(
    current: Sequence[Observation],
    candidates: Sequence[Candidate],
    *,
    reporting_interval: tuple[str, str],
    unavailable: Sequence[UnavailableView] = (),
    overlap_adjusted: bool = False,
    run_id: str | None = None,
    computed_at: str | None = None,
) -> BaselineSelection:
    """Pick one baseline per comparison key (D-18) and classify the comparison.

    A candidate is rejected with ``window_mismatch`` when its window length
    (``interval_end - interval_start``) differs from the current observation's
    (``reporting_interval`` for keys with no current observation) by more than
    :data:`WINDOW_TOLERANCE`; for a key with a current observation that makes the
    comparison ``not_comparable`` unless a same-length prior exists.

    Args:
        current: Observations of the current run.
        candidates: Prior observations from every accessible registration.
        reporting_interval: ``(start, end)`` of the current run; ``start`` is the
            reference point for keys with no current observation.
        unavailable: Registry views; any whose ``status`` is not ``"ok"`` is
            listed in ``unavailable`` and contributes nothing (D-19).
        overlap_adjusted: Allow candidates whose window overlaps the current one.
            Window length must still match (see below).
        run_id: Current run (defaults to ``current[0].run_id``).
        computed_at: ISO-8601 time (defaults to now, UTC).

    Raises:
        ValueError: When no run ID is given and ``current`` is empty.
    """
    if run_id is None:
        if not current:
            raise ValueError("select_baselines needs run_id when current is empty")
        run_id = current[0].run_id
    if computed_at is None:
        computed_at = datetime.now(UTC).isoformat()

    current_by_key: dict[tuple[str, ...], Observation] = {}
    for o in current:
        key = comparison_key(o)
        held = current_by_key.get(key)
        if held is None or _current_rank(o) > _current_rank(held):
            current_by_key[key] = o

    cands_by_key: dict[tuple[str, ...], dict[tuple[str, str], Candidate]] = {}
    for c in candidates:
        o = c.observation
        bucket = cands_by_key.setdefault(comparison_key(o), {})
        ident = (o.run_id, o.observation_id)
        held_c = bucket.get(ident)
        if held_c is None or c.committed_revision > held_c.committed_revision:
            bucket[ident] = c

    unavailable_entries = _unavailable_entries(unavailable)
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    keys = list(current_by_key) + sorted(
        k for k in cands_by_key if k not in current_by_key
    )

    for key in keys:
        cur = current_by_key.get(key)
        reference_start = cur.interval_start if cur else reporting_interval[0]
        reference_window = (
            _window(cur.interval_start, cur.interval_end)
            if cur
            else _window(*reporting_interval)
        )
        eligible: list[Candidate] = []
        incomparable = False

        def reject(c: Candidate, reason: str, key: tuple[str, ...] = key) -> None:
            rejected.append(
                {
                    "key": key,
                    "candidate_observation_id": c.observation.observation_id,
                    "candidate_run_id": c.observation.run_id,
                    "interval": {
                        "start": c.observation.interval_start,
                        "end": c.observation.interval_end,
                    },
                    "reason": reason,
                }
            )

        for c in cands_by_key.get(key, {}).values():
            o = c.observation
            if o.run_id == run_id:
                reject(c, "current_run")
                continue
            if cur is not None:
                mismatch = next(
                    (
                        f"{name}_mismatch"
                        for name, attr in (
                            ("unit", "unit"),
                            ("grain", "grain"),
                            ("method", "method_version"),
                        )
                        if getattr(o, attr) != getattr(cur, attr)
                    ),
                    None,
                )
                if mismatch:
                    reject(c, mismatch)
                    incomparable = True
                    continue
            if not same_window_length(
                _window(o.interval_start, o.interval_end), reference_window
            ):
                # 7 / 30 / 90-day runs never baseline each other.
                reject(c, "window_mismatch")
                incomparable = True
                continue
            if o.state != "measured":
                reject(c, "prior_not_measured")
                continue
            if o.coverage == "unknown":
                reject(c, "prior_coverage_unknown")
                continue
            if not overlap_adjusted and intervals_overlap(o.interval_end, reference_start):
                reject(c, "interval_overlap")
                incomparable = True
                continue
            eligible.append(c)

        best: Candidate | None = None
        seen_dedupe: set[str] = set()
        for c in sorted(eligible, key=_rank, reverse=True):
            dk = c.observation.dedupe_key
            if dk is not None and dk in seen_dedupe:
                reject(c, "duplicate_dedupe_key")
                continue
            if dk is not None:
                seen_dedupe.add(dk)
            if best is None:
                best = c

        if best is None:
            if cur is None:
                continue
            if incomparable:
                comparison = "not_comparable"
            elif unavailable_entries:
                comparison = "history_unavailable"
            else:
                comparison = "no_prior_measurement"
        else:
            base = best.observation
            if cur is None:
                if _is_flag(base) and not _triggered(base):
                    continue
                comparison = "missing_current_evidence"
            elif cur.state != "measured" or cur.coverage == "unknown":
                comparison = "missing_current_evidence"
            elif _is_flag(cur):
                comparison = _flag_comparison(cur, base)
            else:
                comparison = "continuing"

        selected.append(
            {
                "key": key,
                "current_observation_id": cur.observation_id if cur else None,
                "baseline_observation_id": best.observation.observation_id
                if best
                else None,
                "comparison": comparison,
            }
        )

    return BaselineSelection(
        run_id=run_id,
        selected=tuple(selected),
        rejected=tuple(rejected),
        unavailable=tuple(unavailable_entries),
        reporting_interval=reporting_interval,
        computed_at=computed_at,
    )


def _comparisons_by(
    selection: BaselineSelection, field: str
) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for entry in selection.selected:
        oid = entry[field]
        if oid is not None:
            out.setdefault(oid, []).append(entry)
    return out


def _union(first: Sequence[str], second: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _append(
    rec: FindingRecord, entry: FindingRevision, **changes: Any
) -> FindingRecord:
    """``rec`` with ``entry`` chained as revision ``rec.revision + 1``."""
    entry = replace(entry, revision=rec.revision + 1)
    return replace(
        rec,
        revisions=(*rec.revisions, entry),
        revision=entry.revision,
        **changes,
    )


def finding_states(
    prior: Sequence[FindingRecord],
    selection: BaselineSelection,
    current: Sequence[FindingRecord],
) -> tuple[FindingRecord, ...]:
    """Carry finding episodes, states and revision chains across runs (D3-4, D3-5).

    Identity is the concern key (``finding_key``); every returned record is
    written by ``selection.run_id`` and its chain gains one revision per run.

    - Current findings: ``continuing`` keeps the prior episode (state ``active``,
      or ``watch`` if already watch); ``new`` starts the record's own episode;
      ``missing_current_evidence`` gives ``unknown_current`` (severity ``None``)
      keeping the last confirmed severity. With a prior, the current revision is
      appended to the prior chain (``detected`` becomes ``reassessed`` unless the
      episode is new) and prior ``case_ids`` / ``action_ids`` are kept.
    - Prior findings absent from ``current``: ``recovered`` when the selection
      says so (severity ``none``); a prior ``recovered`` becomes ``historical``; a
      prior ``historical`` is dropped; anything else becomes ``unknown_current``
      (severity ``None``, last confirmed severity kept).

    ``prior`` may hold records from several runs in any order; per key the highest
    ``revision`` wins (ties: the first given). Prior records written by the
    current run are ignored.
    """
    run_id = selection.run_id
    by_current = _comparisons_by(selection, "current_observation_id")
    by_baseline = _comparisons_by(selection, "baseline_observation_id")
    prior_by_key: dict[str, FindingRecord] = {}
    for p in prior:
        if p.run_id == run_id:
            continue
        held_p = prior_by_key.get(p.finding_key)
        if held_p is None or p.revision > held_p.revision:
            prior_by_key[p.finding_key] = p

    out: list[FindingRecord] = []
    current_keys: set[str] = set()
    for rec in current:
        current_keys.add(rec.finding_key)
        held = prior_by_key.get(rec.finding_key)
        comps = {
            e["comparison"]
            for oid in rec.observation_ids
            for e in by_current.get(oid, [])
        }
        missing = "missing_current_evidence" in comps
        new = not missing and "new" in comps
        state, severity = rec.state, rec.severity
        last = rec.last_confirmed_severity
        if missing:
            state, severity = "unknown_current", None
            if last is None and held is not None:
                last = held.last_confirmed_severity
        elif "continuing" in comps:
            state = "watch" if rec.state == "watch" else "active"
        latest = replace(rec.revisions[-1], run_id=run_id)
        if missing:
            latest = replace(latest, reason="unknown_current", severity=None)

        if held is None:
            out.append(
                replace(
                    rec,
                    state=state,
                    severity=severity,
                    last_confirmed_severity=last,
                    revisions=(*rec.revisions[:-1], latest),
                    run_id=run_id,
                )
            )
            continue

        changes: dict[str, Any] = {
            "state": state,
            "severity": severity,
            "last_confirmed_severity": last,
            "case_ids": _union(held.case_ids, rec.case_ids),
            "action_ids": _union(held.action_ids, rec.action_ids),
            "run_id": run_id,
        }
        if not new:
            changes["episode_id"] = held.episode_id
            changes["episode_started_run_id"] = held.episode_started_run_id
        already_chained = (
            len(rec.revisions) > len(held.revisions)
            and rec.revisions[: len(held.revisions)] == held.revisions
        )
        if already_chained:
            chained = (*rec.revisions[:-1], latest)
            out.append(
                replace(rec, revisions=chained, revision=len(chained), **changes)
            )
            continue
        if latest.reason == "detected" and not new:
            latest = replace(latest, reason="reassessed")
        base = replace(rec, revisions=held.revisions, revision=held.revision)
        out.append(_append(base, latest, **changes))

    for p in prior_by_key.values():
        if p.finding_key in current_keys or p.state == "historical":
            continue
        last_rev = p.revisions[-1]
        if p.state == "recovered":
            entry = replace(last_rev, run_id=run_id, reason="historical")
            out.append(_append(p, entry, state="historical", run_id=run_id))
            continue
        entries = [e for oid in p.observation_ids for e in by_baseline.get(oid, [])]
        recovered = [e for e in entries if e["comparison"] == "recovered"]
        if recovered:
            # The recovery cites the cleared flag plus the measured values that
            # show it (D3-13: the outcome comes from the measured comparison).
            measured = [e for e in entries if e["comparison"] == "continuing"]
            ids = tuple(
                dict.fromkeys(
                    e["current_observation_id"]
                    for e in (*recovered, *measured)
                    if e["current_observation_id"]
                )
            )
            entry = replace(
                last_rev,
                run_id=run_id,
                reason="recovered",
                severity="none",
                observation_ids=ids,
            )
            out.append(
                _append(
                    p,
                    entry,
                    state="recovered",
                    severity="none",
                    observation_ids=ids,
                    run_id=run_id,
                )
            )
        else:
            entry = replace(
                last_rev, run_id=run_id, reason="unknown_current", severity=None
            )
            out.append(
                _append(p, entry, state="unknown_current", severity=None, run_id=run_id)
            )
    return tuple(out)
