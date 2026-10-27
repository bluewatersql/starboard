# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""ChangeInput construction (``change_inputs_v1``, spec §B5, D3-11).

One :class:`~starboard_core.engagement.records.ChangeInput` per selected
``continuing`` / ``new`` / ``recovered`` pair with numeric values: the measured
delta, co-moving metrics on the same entity, and dated context events (config
changes, the consumption step change, recorded action events). It carries no
prose and asserts no cause (``causality="not_assessed"``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from starboard_core.engagement.catalog import SIX_FAMILIES
from starboard_core.engagement.records import (
    ENTITY_KINDS,
    UNCLASSIFIED,
    UNITS,
    Action,
    BaselineSelection,
    ChangeInput,
    FindingRecord,
    Observation,
    change_id,
)

__all__ = ["ChangeContext", "build"]

_COMPARISONS = ("continuing", "new", "recovered")
_FAMILIES = (*SIX_FAMILIES, UNCLASSIFIED)


@dataclass(frozen=True)
class ChangeContext:
    """Dated context and supporting records for :func:`build`.

    Attributes:
        baselines: Prior observations holding the selected baseline IDs.
        superseded: ``dedupe.merge`` superseded pairs ``(kept_id, superseded_obs)``;
            a superseded aggregate becomes a co-movement of the kept observation.
        config_changes: ``recent_config_changes`` fact rows (``warehouse_id``,
            ``change_time``, ``change``).
        step_change: The F-03 ``step_change`` fact (``date``), if any.
        actions: Prior actions; their events become ``action_event`` context.
        findings: Current findings; an action's events attach to the changes of
            the observations its finding cites.
        source_windows: ``observation_id`` → ``(start, end, source_kind)`` windows
            the observation was reconstructed from (defaults to its interval).
    """

    baselines: Sequence[Observation] = ()
    superseded: Sequence[tuple[str, Observation]] = ()
    config_changes: Sequence[Mapping[str, Any]] = ()
    step_change: Mapping[str, Any] | None = None
    actions: Sequence[Action] = ()
    findings: Sequence[FindingRecord] = ()
    source_windows: Mapping[str, Sequence[tuple[str, str, str]]] | None = None


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _within(at: str, start: str, end: str) -> bool:
    try:
        moment = _ts(at)
    except ValueError:
        return False
    # Date-only ends cover the whole day.
    end_ts = _ts(end)
    if len(end) == 10:
        end_ts = end_ts.replace(hour=23, minute=59, second=59)
    return _ts(start) <= moment <= end_ts


def _numeric(o: Observation) -> bool:
    return (
        o.state == "measured"
        and o.coverage != "unknown"
        and isinstance(o.value, (int, float))
    )


def _context_events(
    cur: Observation,
    base: Observation,
    context: ChangeContext,
    cited_actions: Sequence[Action],
) -> list[dict[str, str]]:
    start, end = base.interval_start, cur.interval_end
    events: list[dict[str, str]] = []
    for row in context.config_changes:
        at = str(row.get("change_time") or "")
        wid, change = row.get("warehouse_id"), row.get("change")
        if not at or not wid or not change or not _within(at, start, end):
            continue
        if cur.entity_kind == "warehouse" and cur.entity_id != str(wid):
            continue
        events.append(
            {"kind": "config_change", "ref": f"warehouse:{wid}:{change}", "at": at}
        )
    step = context.step_change
    if step and step.get("date") and _within(str(step["date"]), start, end):
        date = str(step["date"])
        events.append({"kind": "step_change", "ref": f"step_change:{date}", "at": date})
    for action in cited_actions:
        for event in action.events:
            if _within(event.at, start, end):
                events.append(
                    {
                        "kind": "action_event",
                        "ref": f"{action.action_id}:{event.kind}",
                        "at": event.at,
                    }
                )
    events.sort(key=lambda e: (_ts(e["at"]), e["kind"], e["ref"]))
    return events


def build(
    current: Sequence[Observation],
    selection: BaselineSelection,
    *,
    context: ChangeContext | None = None,
) -> tuple[ChangeInput, ...]:
    """Build the run's ChangeInputs from a baseline selection.

    Args:
        current: The run's (merged) observations.
        selection: ``select_baselines`` output for ``current``.
        context: Baselines, superseded aggregates and dated context.

    Raises:
        ValueError: When a selected baseline ID is not in ``context.baselines``.
    """
    ctx = context or ChangeContext()
    by_id = {o.observation_id: o for o in current}
    baselines = {o.observation_id: o for o in ctx.baselines}
    base_for: dict[str, Observation] = {}
    for entry in selection.selected:
        cur_id, base_id = (
            entry["current_observation_id"],
            entry["baseline_observation_id"],
        )
        if cur_id is None or base_id is None or entry["comparison"] not in _COMPARISONS:
            continue
        base = baselines.get(base_id)
        if base is None:
            raise ValueError(f"selected baseline {base_id} is not in context.baselines")
        base_for[cur_id] = base

    superseded: dict[str, list[Observation]] = {}
    for kept_id, dropped in ctx.superseded:
        superseded.setdefault(kept_id, []).append(dropped)
    finding_by_id = {f.finding_id: f for f in ctx.findings}
    actions_for: dict[str, list[Action]] = {}
    for action in ctx.actions:
        finding = finding_by_id.get(action.finding_id)
        for oid in finding.observation_ids if finding is not None else ():
            actions_for.setdefault(oid, []).append(action)

    comparison = {
        e["current_observation_id"]: e["comparison"] for e in selection.selected
    }
    out: list[ChangeInput] = []
    for cur_id, base in base_for.items():
        cur = by_id.get(cur_id)
        if (
            cur is None
            or not _numeric(cur)
            or not _numeric(base)
            or cur.unit not in UNITS
            or cur.entity_kind not in ENTITY_KINDS
            or cur.family not in _FAMILIES
        ):
            continue
        assert cur.value is not None and base.value is not None
        co: list[dict[str, Any]] = []
        for other in current:
            if (
                other.observation_id == cur.observation_id
                or (other.entity_kind, other.entity_id)
                != (cur.entity_kind, cur.entity_id)
                or (other.interval_start, other.interval_end)
                != (cur.interval_start, cur.interval_end)
                or other.unit not in UNITS
                or not _numeric(other)
            ):
                continue
            move: dict[str, Any] = {
                "metric": other.metric,
                "unit": other.unit,
                "observation_id": other.observation_id,
            }
            other_base = base_for.get(other.observation_id)
            if other_base is not None and other_base.value is not None:
                assert other.value is not None
                move["delta"] = other.value - other_base.value
            co.append(move)
        for dropped in superseded.get(cur.observation_id, ()):
            if dropped.unit in UNITS:
                co.append(
                    {
                        "metric": dropped.metric,
                        "unit": dropped.unit,
                        "observation_id": dropped.observation_id,
                    }
                )
        windows = (ctx.source_windows or {}).get(cur.observation_id) or (
            (base.interval_start, base.interval_end, base.source_kind),
            (cur.interval_start, cur.interval_end, cur.source_kind),
        )
        delta = cur.value - base.value
        out.append(
            ChangeInput(
                change_id=change_id(cur.observation_id, base.observation_id),
                observation_id=cur.observation_id,
                baseline_observation_id=base.observation_id,
                family=cur.family,
                metric=cur.metric,
                unit=cur.unit,
                entity_kind=cur.entity_kind,
                entity_id=cur.entity_id,
                baseline_value=base.value,
                baseline_interval_start=base.interval_start,
                baseline_interval_end=base.interval_end,
                current_value=cur.value,
                current_interval_start=cur.interval_start,
                current_interval_end=cur.interval_end,
                delta=delta,
                delta_unit="pp" if cur.unit == "pct" else cur.unit,
                relative_pct=None if base.value == 0 else delta / base.value * 100.0,
                comparison=comparison[cur_id],
                co_movements=tuple(co),
                context_events=tuple(
                    _context_events(cur, base, ctx, actions_for.get(cur_id, ()))
                ),
                source_windows=tuple(tuple(w) for w in windows),  # type: ignore[misc]
                evidence_ids=tuple(
                    dict.fromkeys((*base.evidence_ids, *cur.evidence_ids))
                ),
            )
        )
    return tuple(out)
