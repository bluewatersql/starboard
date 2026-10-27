# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Play candidates (``play_rules_v1``, spec §B4, D3-9).

Deterministic candidate next interactions for the run's open findings, plus one
``acquire_family_evidence`` play per unknown health family. Ordering is
severity, then OD-1 (a ``low`` review finding ranks last within its severity),
then exposure (the list-price DBU estimate, then failed runs), then ``play_id``. Exposure
carries ``failed_runs`` / ``failed_run_dbus`` on job-failure plays only and
``exposure_dbus`` (the finding's list-price DBU estimate over the window) on
every play — except a run-rate rule (``spend_step_change``), whose estimate is a
DBU/day lift and is carried as ``exposure_dbus_per_day`` instead (never summed
with window totals; the order weighs it as DBU/day x the interval's days). ``failed_run_dbus`` is set only with ``failed_runs``. Reasons
are fixed templates over measured values; the host may reorder only through
``host_rank`` / ``host_reorder_reason``. Workspace-grain
(``ws_job_failure_rise``) and case findings get no play.

``next_commands`` run as printed (:class:`PlayContext`, ``health.RunTarget``):
a verify line carries the run target (``--run-folder`` + ``--out analysis/verify``
on Drive, ``--out <run dir>/analysis/verify`` locally), a per-entity
``--suffix``, ``--limit`` within the template's verb cap and, on the public
path, ``--warehouse-id`` (``<warehouse_id>`` when unknown — the only
placeholder, listed in ``Play.placeholders``). A ``health_check`` run lists only
the optional verify re-check (a health review never fetches one entity); an
internal-only run lists the mirror verify form (``--internal-workspace-id``,
``--templates`` the overlay's mirror templates when known), never a
customer-workspace fetch. A rule play never prints a review re-run (it would
overwrite the run's review): with no verify template and no fetch it lists the
job-run timeline (a job id) or the workspace product totals. Acquisition plays carry
the health read's own acquisition command (``health.targeted_requests`` gives
it the run's form).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any

from starboard_core.domain.rules import rule_name
from starboard_core.engagement.dedupe import AGGREGATE_KEY_PREFIX
from starboard_core.engagement.health import (
    RunTarget,
    finding_exposure,
    placeholders,
    severity_rank,
)
from starboard_core.engagement.records import (
    RUN_RATE_RULES,
    ChangeInput,
    FindingRecord,
    HealthRead,
    Observation,
    Play,
    play_id,
)

__all__ = [
    "HEALTH_TASK",
    "QUERY_LIMIT",
    "RULE_VERIFY_TEMPLATES",
    "RUN_RATE_RULES",
    "VERIFY_LIMIT",
    "verify_limit",
    "PlayContext",
    "candidates",
]

#: Review rule → ``(verify template, id flag)`` for its follow-up check.
RULE_VERIFY_TEMPLATES: Mapping[str, tuple[str, str | None]] = MappingProxyType(
    {
        "job_high_failure_rate": ("vt-job-runs", "--job-ids"),
        "job_wasted_dbu_on_failures_retries": ("vt-job-runs", "--job-ids"),
        "portfolio_unreliable_production_workload": ("vt-job-runs", "--job-ids"),
        "job_high_runtime_variance": ("vt-job-run-tail", "--job-ids"),
        "warehouse_queueing": ("vt-warehouse-queue", "--warehouse-ids"),
        "warehouse_auto_stop_disabled": ("vt-warehouse-dbu", None),
        "warehouse_persistently_underutilized": ("vt-warehouse-dbu", None),
        "warehouse_recent_resize": ("vt-warehouse-config-history", None),
        "spend_step_change": ("vt-daily-totals", None),
        "portfolio_untracked_production_consumption": ("vt-product-totals", None),
    }
)
#: Re-check of a rule with no template and no fetch: the entity's job-run timeline
#: (a job id) or the workspace's product totals. Never a review re-run: that would
#: overwrite the run's review.
_JOB_FALLBACK = ("vt-job-runs", "--job-ids")
_WORKSPACE_FALLBACK = ("vt-product-totals", None)
#: ``verify run --limit`` of the run-state template (``verify.VERIFY_ROW_LIMIT``):
#: run states reconstruct runs, so they need every row.
VERIFY_LIMIT = 20000
#: ``--limit`` of every other verify template (one row per run / day / query).
QUERY_LIMIT = 1000
_FULL_ROW_TEMPLATES = frozenset({"vt-job-run-states"})
#: The run task whose plays never fetch a single entity (a workspace health read).
HEALTH_TASK = "health_check"
_SUFFIX_RE = re.compile(r"^[\w.-]+$")
_RUNS_LIMIT = 25
_RECOVERY_MARGIN_PP = 2.0
_MIN_RUNS = 50
_WATCH_RATE_PCT = 5.0
_OPEN_STATES = ("active", "watch")
_JOB_CODE = "job_failure_rise"
#: Review rules whose finding is a job-failure exposure (failed runs, their DBU).
_JOB_FAILURE_RULES = frozenset(
    {
        "job_high_failure_rate",
        "job_wasted_dbu_on_failures_retries",
        "portfolio_unreliable_production_workload",
    }
)
_NO_EXPOSURE: Mapping[str, Any] = MappingProxyType(
    {
        "failed_runs": None,
        "failed_run_dbus": None,
        "exposure_dbus": None,
        "exposure_dbus_per_day": None,
    }
)
_RATE, _RUNS = "job_failure_rate_pct", "job_runs"
_OWNERS = {
    "job": "job_owner",
    "warehouse": "warehouse_owner",
    "pipeline": "pipeline_owner",
}
_URGENCY = {"critical": "high", "serious": "high", "watch": "medium"}


@dataclass(frozen=True)
class PlayContext:
    """What the run is, for its plays' ``next_commands``.

    Attributes:
        task: The run's task (``RunAuthorization.intent``); ``None`` when unknown.
        target: Where the run's commands read and write; ``target.internal`` is an
            internal-only run (mirror verify, no customer-workspace fetch).
    """

    task: str | None = None
    target: RunTarget = field(default_factory=RunTarget)

    @property
    def internal(self) -> bool:
        return self.target.internal

    @property
    def fetches(self) -> bool:
        """Whether a play may list a single-entity customer-workspace fetch."""
        return not self.internal and self.task != HEALTH_TASK


def verify_limit(template: str) -> int:
    """``--limit`` of ``template``: :data:`VERIFY_LIMIT` for run states, else
    :data:`QUERY_LIMIT`."""
    return VERIFY_LIMIT if template in _FULL_ROW_TEMPLATES else QUERY_LIMIT


def _verify(
    template: str,
    ws: str,
    interval: tuple[str, str],
    ctx: PlayContext,
    id_flag: str | None = None,
    eid: str = "",
) -> str:
    """One ``verify run`` line that runs as printed (see the module docstring)."""
    target = ctx.target
    if target.internal:
        templates = (
            f" --templates {target.mirror_templates}" if target.mirror_templates else ""
        )
        source = f"{templates} --internal-workspace-id {ws}"
    else:
        source = f" --ws {ws}"
    ids = f" {id_flag} {eid}" if id_flag else ""
    warehouse = (
        ""
        if target.internal
        else f" --warehouse-id {target.warehouse}{target.profile_args()}"
    )
    suffix = f" --suffix {eid}" if eid and _SUFFIX_RE.fullmatch(eid) else ""
    where = f" --run-folder {target.run_folder}" if target.run_folder else ""
    return (
        f"starboard-helper verify run {template}{source}{ids} "
        f"--start {interval[0]} --end {interval[1]} --limit {verify_limit(template)}"
        f"{warehouse}{suffix}{where} --out {target.path('analysis/verify')}"
    )


def _entity_fetch(kind: str, eid: str) -> str | None:
    if kind == "job" and eid.isdigit():
        return f"starboard-helper job fetch --job-id {eid}"
    if kind == "warehouse":
        return f"starboard-helper warehouse fetch --warehouse-id {eid}"
    if kind == "query":
        return f"starboard-helper query fetch --query-id {eid}"
    if kind == "table":
        return f"starboard-helper uc table --full-name {eid}"
    return None


def _fallback_verify(
    f: FindingRecord, interval: tuple[str, str], ctx: PlayContext
) -> str:
    """The re-check of a rule with no verify template and no fetch."""
    if f.entity_kind == "job" and f.entity_id.isdigit():
        template, id_flag = _JOB_FALLBACK
        return _verify(template, f.workspace_id, interval, ctx, id_flag, f.entity_id)
    template, _ = _WORKSPACE_FALLBACK
    return _verify(template, f.workspace_id, interval, ctx, None, f.workspace_id)


def _cited(f: FindingRecord, by_id: Mapping[str, Observation]) -> list[Observation]:
    return [by_id[oid] for oid in f.observation_ids if oid in by_id]


def _audience(cited: Sequence[Observation]) -> str:
    internal = any(o.audience_class == "internal_only" for o in cited)
    return "internal_only" if internal else "customer_shareable"


def _strength(f: FindingRecord, cited: Sequence[Observation]) -> str:
    aggregate = any(
        o.dedupe_key and o.dedupe_key.startswith(AGGREGATE_KEY_PREFIX) for o in cited
    )
    if f.symptom_confidence == "confirmed" and not aggregate:
        return "strong"
    if f.symptom_confidence in ("confirmed", "probable"):
        return "moderate"
    return "weak"


def _windows(change: ChangeInput) -> str:
    spans = sorted({(s[:10], e[:10]) for s, e, _ in change.source_windows})
    return " + ".join(f"{s}..{e}" for s, e in spans)


def _interval_days(interval: tuple[str, str]) -> int:
    """Days in the reporting interval (``--start`` to ``--end``), at least 1."""
    try:
        start, end = (date.fromisoformat(d[:10]) for d in interval)
    except ValueError:
        return 1
    return max((end - start).days, 1)


def _failure_exposure(failed: int | None, dbus: float | None) -> dict[str, Any]:
    """A job-failure exposure: ``failed_run_dbus`` only alongside ``failed_runs``."""
    return {
        **_NO_EXPOSURE,
        "failed_runs": failed,
        "failed_run_dbus": dbus if failed is not None else None,
        "exposure_dbus": dbus,
    }


def _job_play(
    f: FindingRecord,
    by_id: Mapping[str, Observation],
    changes: Mapping[str, ChangeInput],
    interval: tuple[str, str],
    latest_failed_runs: Mapping[str, str],
    run_id: str,
    ctx: PlayContext,
) -> Play:
    cited = _cited(f, by_id)
    failed, dbus = finding_exposure(f, by_id)
    rate = next((o for o in cited if o.metric == _RATE), None)
    runs = next((o for o in cited if o.metric == _RUNS), None)
    change = changes.get(rate.observation_id) if rate is not None else None
    runs_text = f", {int(runs.value)} runs" if runs and runs.value is not None else ""
    baseline: float | None = None
    if change is not None:
        baseline = change.baseline_value
        reason = (
            f"job {f.entity_id} failure rate {change.baseline_value:.1f}% → "
            f"{change.current_value:.1f}% ({change.delta:+.1f} pp){runs_text}, "
            f"windows {_windows(change)}"
        )
    else:
        value = rate.value if rate is not None and rate.value is not None else 0.0
        reason = (
            f"job {f.entity_id} failure rate {value:.1f}% (no eligible baseline)"
            f"{runs_text}, window {interval[0]}..{interval[1]}"
        )
    session = f.severity in ("serious", "critical") and failed is not None
    code = "job_reliability_session" if session else "job_reliability_investigation"
    commands = [
        _verify(
            "vt-job-run-states", f.workspace_id, interval, ctx, "--job-ids", f.entity_id
        )
    ]
    if ctx.fetches and f.entity_id.isdigit():
        commands.append(
            f"starboard-helper job runs --job-id {f.entity_id} --limit {_RUNS_LIMIT}"
        )
    # A serious/critical finding with known exposure gets a working session even
    # without criticality (owner decision); only investigations list it as missing.
    missing = ["error_signature"] if session else ["criticality", "error_signature"]
    failed_run = latest_failed_runs.get(f.entity_id)
    if failed_run is not None and ctx.fetches:
        commands.append(f"starboard-helper job run-output --run-id {failed_run}")
    elif failed_run is None:
        missing.append("job_run_output")
    if failed is None:
        missing.append("exposure")
    if baseline is not None:
        target = baseline + _RECOVERY_MARGIN_PP
        criterion = (
            f"failure rate <= {target:.1f}% (baseline {baseline:.1f}% + "
            f"{_RECOVERY_MARGIN_PP:.1f} pp) over >= {_MIN_RUNS} runs"
        )
    else:
        criterion = f"failure rate < {_WATCH_RATE_PCT:.1f}% over >= {_MIN_RUNS} runs"
    return Play(
        play_id=play_id(code, f.finding_id),
        play_code=code,
        finding_ids=(f.finding_id,),
        interaction_type="working_session" if session else "investigation",
        owner_role="job_owner",
        audience_class=_audience(cited),
        target_entity_kind="job",
        target_entity_id=f.entity_id,
        reason=reason,
        urgency=_URGENCY.get(f.severity or "", "low"),
        exposure=_failure_exposure(failed, dbus),
        evidence_strength=_strength(f, cited),
        missing_evidence=tuple(missing),
        next_step_kind="act" if session else "investigate",
        next_commands=tuple(commands),
        placeholders=placeholders(commands),
        follow_up_check={
            "template": "vt-job-runs",
            "params": {
                "ws": f.workspace_id,
                "job_ids": f.entity_id,
                "limit": verify_limit("vt-job-runs"),
            },
            "success_criterion": criterion,
        },
        run_id=run_id,
    )


def _rule_play(
    f: FindingRecord,
    by_id: Mapping[str, Observation],
    interval: tuple[str, str],
    review_severity: str | None,
    run_id: str,
    ctx: PlayContext,
) -> Play:
    cited = _cited(f, by_id)
    failed, dbus = finding_exposure(f, by_id)
    rule_id = f.concern_code.removeprefix("rule:")
    mapped = RULE_VERIFY_TEMPLATES.get(rule_id)
    commands: list[str] = []
    missing = ["criticality"]
    follow_up: dict[str, Any] | None = None
    if mapped is not None:
        template, id_flag = mapped
        commands.append(
            _verify(template, f.workspace_id, interval, ctx, id_flag, f.entity_id)
        )
        params: dict[str, Any] = {"ws": f.workspace_id, "limit": verify_limit(template)}
        if id_flag:
            params[id_flag.removeprefix("--").replace("-", "_")] = f.entity_id
        follow_up = {
            "template": template,
            "params": params,
            "success_criterion": f"{rule_id} no longer present in the findings manifest",
        }
    else:
        missing.append("verify_template")
    fetch = _entity_fetch(f.entity_kind, f.entity_id) if ctx.fetches else None
    if fetch is not None and fetch not in commands:
        commands.append(fetch)
    if not commands:  # no verify template and no fetch: a read-only verify
        commands.append(_fallback_verify(f, interval, ctx))
    severity_text = (
        f"review severity {review_severity}"
        if review_severity
        else (f"severity {f.severity}")
    )
    name = rule_name(rule_id)
    rule_label = f"{rule_id} ({name})" if name else rule_id
    run_rate = rule_id in RUN_RATE_RULES
    if dbus is None:
        dbu_text = ""
    elif run_rate:
        dbu_text = f", ~{dbus:,.0f} DBU/day run-rate (list-price estimate)"
    else:
        dbu_text = f", ~{dbus:,.0f} DBU (list-price estimate)"
    if rule_id in _JOB_FAILURE_RULES:
        exposure = _failure_exposure(failed, dbus)
    elif run_rate:
        exposure = {**_NO_EXPOSURE, "exposure_dbus_per_day": dbus}
    else:
        exposure = {**_NO_EXPOSURE, "exposure_dbus": dbus}
    working = f.severity in ("serious", "critical")
    return Play(
        play_id=play_id("rule_finding_review", f.finding_id),
        play_code="rule_finding_review",
        finding_ids=(f.finding_id,),
        interaction_type="working_session" if working else "monitor",
        owner_role=_OWNERS.get(f.entity_kind, "platform_admin"),
        audience_class=_audience(cited),
        target_entity_kind=f.entity_kind,
        target_entity_id=f.entity_id,
        reason=f"{rule_label} on {f.entity_kind} {f.entity_id}: {severity_text}{dbu_text}",
        urgency=_URGENCY.get(f.severity or "", "low"),
        exposure=exposure,
        evidence_strength=_strength(f, cited),
        missing_evidence=tuple(missing),
        next_step_kind="investigate",
        next_commands=tuple(commands),
        placeholders=placeholders(commands),
        follow_up_check=follow_up,
        run_id=run_id,
    )


def _acquire_plays(health: HealthRead, run_id: str) -> list[Play]:
    out: list[Play] = []
    for fam in health.families:
        request = fam.acquisition_request
        if fam.assessment != "unknown" or request is None:
            continue
        missing = tuple(request["missing"])
        out.append(
            Play(
                play_id=play_id("acquire_family_evidence", fam.family),
                play_code="acquire_family_evidence",
                finding_ids=(),
                interaction_type="acquisition",
                owner_role="operator",
                audience_class="customer_shareable",
                target_entity_kind="workspace",
                target_entity_id=health.workspace_id,
                reason=f"{fam.family} not assessed: missing {', '.join(missing)}",
                urgency="low",
                exposure=_NO_EXPOSURE,
                evidence_strength="weak",
                missing_evidence=missing,
                next_step_kind="acquire",
                next_commands=(request["command"],),
                placeholders=tuple(request["placeholders"]),
                follow_up_check=None,
                run_id=run_id,
            )
        )
    return out


def candidates(
    findings: Sequence[FindingRecord],
    health: HealthRead,
    observations: Sequence[Observation],
    *,
    run_id: str,
    interval: tuple[str, str],
    changes: Sequence[ChangeInput] = (),
    review_severities: Mapping[str, str] | None = None,
    latest_failed_runs: Mapping[str, str] | None = None,
    context: PlayContext | None = None,
) -> tuple[Play, ...]:
    """Ordered ``play_rules_v1`` candidates for one run.

    Args:
        findings: The run's findings after ``finding_states``.
        health: The run's health read (unknown families → acquisition plays).
        observations: The run's observations (exposure, audience, strength).
        run_id: The current run.
        interval: Reporting interval for ``verify run`` ``--start`` / ``--end``.
        changes: The run's ChangeInputs (rate before → after in the reason).
        review_severities: ``ConcernResult.review_severities`` (OD-1 low-last).
        latest_failed_runs: ``job_id`` → latest failed run ID, for
            ``job run-output``; otherwise ``job_run_output`` is missing evidence.
        context: The run's task and source (``next_commands`` forms); default a
            public run of no particular task.
    """
    ctx = context or PlayContext()
    by_id = {o.observation_id: o for o in observations}
    by_change = {c.observation_id: c for c in changes}
    origins = review_severities or {}
    failed_runs = latest_failed_runs or {}
    severity_of: dict[str, str | None] = {}
    plays: list[Play] = []
    for f in findings:
        if f.state not in _OPEN_STATES:
            continue
        if f.concern_code == _JOB_CODE:
            play = _job_play(f, by_id, by_change, interval, failed_runs, run_id, ctx)
        elif f.concern_code.startswith("rule:"):
            play = _rule_play(
                f, by_id, interval, origins.get(f.finding_id), run_id, ctx
            )
        else:
            continue
        severity_of[play.play_id] = f.severity
        plays.append(play)

    days = _interval_days(interval)

    def order(p: Play) -> tuple[int, int, float, int, str]:
        fid = p.finding_ids[0] if p.finding_ids else ""
        failed = p.exposure["failed_runs"] or 0
        # A run-rate weighs as DBU/day x the interval's days: comparable, never summed.
        dbus = p.exposure["exposure_dbus"] or (
            (p.exposure["exposure_dbus_per_day"] or 0.0) * days
        )
        return (
            -severity_rank(severity_of.get(p.play_id)),
            1 if origins.get(fid) == "low" else 0,
            -dbus,
            -failed,
            p.play_id,
        )

    plays.sort(key=order)
    return (*plays, *_acquire_plays(health, run_id))
