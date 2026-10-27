# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Health read projection (``health_read_v1``, spec §B3, D3-6, D3-7).

Projects the run's observations, findings and changes onto the six health
families. A family is *assessed* iff at least one catalog metric is measured
with known coverage; its coverage is *complete* iff every required metric is
measured with complete coverage. Severity is the maximum ``active`` / ``watch``
finding severity, else ``none``. There is no aggregate score, no "healthy"
label and no ``$`` metric; ``verdict`` is ``insufficient_evidence`` iff no
family is assessed.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date

from starboard_core.engagement.catalog import FAMILY_METRICS, SIX_FAMILIES, MetricSpec
from starboard_core.engagement.dedupe import AGGREGATE_KEY_PREFIX
from starboard_core.engagement.records import (
    SEVERITIES,
    UNCLASSIFIED,
    ChangeInput,
    FamilyRead,
    FindingRecord,
    HealthRead,
    Observation,
    unrecoverable_gap,
)

__all__ = [
    "ACQUISITION_METHOD",
    "DISCOVERY_COMMAND",
    "HEALTH_REVIEW_DOMAINS",
    "REVIEW_COMMAND",
    "WAREHOUSE_PLACEHOLDER",
    "RunTarget",
    "discovery_command",
    "finding_exposure",
    "health_eligible",
    "no_evidence",
    "placeholders",
    "project",
    "review_command",
    "severity_rank",
    "targeted_requests",
]

#: Method version of case acquisition observations (never a baseline or health input).
ACQUISITION_METHOD = "acquisition_v1"
#: The run-less discovery request; :func:`targeted_requests` gives it the run's form.
DISCOVERY_COMMAND = "starboard --discover --data-only --json --out-dir discovery"
#: Review domains a health read needs: the defaults plus the opt-in ``uc`` and
#: ``portfolio-readiness`` domains that hold the governance rules.
HEALTH_REVIEW_DOMAINS = "jobs,sql,warehouse,uc,portfolio-readiness"
REVIEW_COMMAND = (
    f"starboard review --from-discovery discovery --domains {HEALTH_REVIEW_DOMAINS} "
    "--json --out analysis/review.json --manifest-out findings-manifest.json"
)
#: The one placeholder a printed command may hold: the SQL warehouse of a public
#: command when the run does not know it (listed in the record's ``placeholders``).
WAREHOUSE_PLACEHOLDER = "<warehouse_id>"
_PLACEHOLDERS = ("warehouse_id",)
_RULE_SOURCE = "findings_manifest"
_RULE_METRICS = frozenset({"rules_evaluated", "active_rule_findings"})
_MISSING_SOURCE = "missing_source:"
_NOT_REVIEWED = "not_reviewed:"
_UNAVAILABLE_QUERY = "unavailable_query:"
#: A rule the review suppressed (its source lacks a required column).
_SUPPRESSED = "suppressed:"
#: A partial rule coverage's own gap codes (``families.rule_coverage``).
_RULE_GAP_CODES = frozenset({"manifest_degraded", "evidence_capped"})
#: ``discovery --lookback-days`` choices: a re-discovery keeps the run's window.
_LOOKBACK_DAYS = (7, 30, 60, 90)
_PER_JOB_CAP = "per_job_cap_25"
_OPEN_STATES = ("active", "watch")
_FAILED_METRIC = "failed_job_runs"
_DBU_METRIC = "evidence_dbu_estimate"


@dataclass(frozen=True)
class RunTarget:
    """Where a run's printed commands read and write, so they run as printed.

    Attributes:
        internal: An internal-only run (``--internal-workspace-id``; no customer
            warehouse, profile or entity fetch).
        run_folder: The Drive run folder ID (``--run-folder``), or ``None``.
        run_dir: The local run directory, or ``None`` (``run_folder`` wins).
        warehouse_id: The SQL warehouse a public command runs on; ``None`` prints
            :data:`WAREHOUSE_PLACEHOLDER` (listed in the record's ``placeholders``).
        profile: The run's verified ``--profile``: printed on a local public run
            only (a Drive run defaults to it).
        mirror_templates: ``--templates`` of an internal verify (the overlay's
            mirror templates, ``~/``-relative); ``None`` omits the flag.
    """

    internal: bool = False
    run_folder: str | None = None
    run_dir: str | None = None
    warehouse_id: str | None = None
    profile: str | None = None
    mirror_templates: str | None = None

    @property
    def local(self) -> bool:
        return not self.run_folder and bool(self.run_dir)

    @property
    def warehouse(self) -> str:
        return self.warehouse_id or WAREHOUSE_PLACEHOLDER

    def path(self, rel: str) -> str:
        """``rel`` as a command takes it: under the run dir on a local run."""
        if not self.local:
            return rel
        return shlex.quote(f"{str(self.run_dir).rstrip('/')}/{rel}")

    def profile_args(self) -> str:
        return f" --profile {shlex.quote(self.profile)}" if self.profile and self.local else ""


def placeholders(commands: Sequence[str]) -> tuple[str, ...]:
    """The placeholders (``warehouse_id``) any of ``commands`` prints."""
    return tuple(p for p in _PLACEHOLDERS if any(f"<{p}>" in c for c in commands))


def review_command(target: RunTarget | None = None) -> str:
    """The health review (``--from-discovery`` the run's discovery) in the run's form.

    A review of saved discovery never takes ``--internal-workspace-id``: the
    discovery output already carries its source. Drive: ``--run-folder``; a local
    internal-only run: ``--run-dir`` and run-dir paths; a local public run: run-dir
    paths; no target: :data:`REVIEW_COMMAND`.
    """
    if target is None or not (target.run_folder or target.run_dir):
        return REVIEW_COMMAND
    if target.run_folder:
        return (
            f"starboard review --from-discovery discovery --domains {HEALTH_REVIEW_DOMAINS} "
            f"--run-folder {target.run_folder} --json --out analysis/review.json "
            "--manifest-out findings-manifest.json"
        )
    run_dir = f" --run-dir {shlex.quote(str(target.run_dir))}" if target.internal else ""
    return (
        f"starboard review{run_dir} --from-discovery {target.path('discovery')} "
        f"--domains {HEALTH_REVIEW_DOMAINS} --json --out {target.path('analysis/review.json')} "
        f"--manifest-out {target.path('findings-manifest.json')}"
    )


def _lookback(interval: tuple[str, str]) -> str:
    try:
        days = (date.fromisoformat(interval[1][:10]) - date.fromisoformat(interval[0][:10])).days + 1
    except ValueError:
        return ""
    return f" --lookback-days {days}" if days in _LOOKBACK_DAYS else ""


def discovery_command(
    workspace_id: str, interval: tuple[str, str], target: RunTarget | None = None
) -> str:
    """A re-discovery of the run's workspace and window, in the run's form.

    Internal-only: ``--internal-workspace-id`` (``--no-cache``); public:
    ``--warehouse-id``. Drive: ``--run-folder``; local: ``--authorization <run dir>``
    and ``--out-dir <run dir>/discovery``. ``--lookback-days`` is the run's window
    (when it is a lookback choice). No target: :data:`DISCOVERY_COMMAND`.
    """
    if target is None:
        return DISCOVERY_COMMAND
    source = (
        f"--internal-workspace-id {workspace_id}"
        if target.internal
        else f"--warehouse-id {target.warehouse}{target.profile_args()}"
    )
    cache = " --no-cache" if target.internal else ""
    if target.run_folder:
        where = f" --run-folder {target.run_folder}"
    elif target.run_dir:
        where = f" --authorization {shlex.quote(str(target.run_dir))}"
    else:
        where = ""
    return (
        f"starboard --discover {source}{_lookback(interval)}{cache} --data-only --json "
        f"--out-dir {target.path('discovery')}{where}"
    )


def health_eligible(o: Observation) -> bool:
    """Whether ``o`` may feed a health read or a baseline (not a case acquisition)."""
    return o.method_version != ACQUISITION_METHOD


def severity_rank(severity: str | None) -> int:
    """``none`` < ``watch`` < ``serious`` < ``critical``; ``None`` ranks lowest."""
    return SEVERITIES.index(severity) if severity in SEVERITIES else -1


def finding_exposure(
    finding: FindingRecord, observations: Mapping[str, Observation]
) -> tuple[int | None, float | None]:
    """``(failed_runs, dbus)`` from the observations a finding cites.

    ``dbus`` is the list-price DBU *estimate* of the finding's review evidence —
    failed-run DBU only for a job-failure finding (see :mod:`plays`): the **sum**
    over every cited ``evidence_dbu_estimate`` (a workspace-grain rule finding
    collapsed from several manifest entries cites each entry's estimate).
    ``failed_runs`` is the first cited ``failed_job_runs``. Either element is
    ``None`` when the finding cites no measured observation of it.
    """
    failed: int | None = None
    dbus: float | None = None
    for oid in finding.observation_ids:
        o = observations.get(oid)
        if o is None or o.state != "measured" or o.value is None:
            continue
        if o.metric == _FAILED_METRIC and failed is None:
            failed = int(o.value)
        elif o.metric == _DBU_METRIC:
            dbus = (dbus or 0.0) + float(o.value)
    return failed, dbus


def _is_case(finding: FindingRecord) -> bool:
    return finding.concern_code.startswith("case:")


def _matches(spec: MetricSpec, o: Observation) -> bool:
    return o.metric == spec.metric and o.entity_kind == spec.entity_kind


def _measured(spec: MetricSpec, obs: Sequence[Observation], *, complete: bool) -> bool:
    wanted = ("complete",) if complete else ("complete", "partial")
    return any(
        _matches(spec, o) and o.state == "measured" and o.coverage in wanted
        for o in obs
    )


def _sources(specs: Sequence[MetricSpec]) -> tuple[str, ...]:
    out: list[str] = []
    for spec in specs:
        for source in spec.source.split("|"):
            if source not in out:
                out.append(source)
    return tuple(out)


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _rule_reason(obs: Sequence[Observation]) -> str | None:
    """The unknown reason the family's rule-coverage observations carry, if any."""
    return next(
        (
            o.unknown_reason
            for o in obs
            if o.metric in _RULE_METRICS
            and o.state == "unknown"
            and o.unknown_reason
            and o.unknown_reason != "no_family_rules"
        ),
        None,
    )


def _rule_gaps(obs: Sequence[Observation]) -> tuple[str, ...]:
    """The gap codes (``missing_source:<ID>``, ``not_reviewed:<domain>``,
    ``manifest_degraded``, ``unavailable_query:<ID>``, ``evidence_capped``) a
    partial rule coverage names in its observations' ``uncertainty``."""
    return _unique(
        [
            code
            for o in obs
            if o.metric in _RULE_METRICS
            for code in o.uncertainty
            if code.startswith((_MISSING_SOURCE, _NOT_REVIEWED, _UNAVAILABLE_QUERY))
            or code in _RULE_GAP_CODES
        ]
    )


def _family_read(
    family: str,
    obs: Sequence[Observation],
    findings: Sequence[FindingRecord],
    changes: Sequence[ChangeInput],
) -> FamilyRead:
    specs = FAMILY_METRICS[family]
    assessed = any(_measured(s, obs, complete=False) for s in specs)
    required = [s for s in specs if s.required]
    missing_specs = [s for s in required if not _measured(s, obs, complete=True)]
    if not assessed:
        missing_specs = required or list(specs)
    coverage = (
        "unknown" if not assessed else ("partial" if missing_specs else "complete")
    )
    missing = _sources(missing_specs)
    fact_missing = any(m != _RULE_SOURCE for m in missing)
    # A rule-only gap with a manifest present: the rule-coverage observations
    # say why (``not_reviewed:<domains>`` or ``missing_source:<query IDs>``).
    rule_reason = _rule_reason(obs) if missing == (_RULE_SOURCE,) else None
    if rule_reason is not None and rule_reason.startswith(_MISSING_SOURCE):
        missing = tuple(rule_reason.removeprefix(_MISSING_SOURCE).split(","))
        fact_missing = True
    elif rule_reason is None and missing == (_RULE_SOURCE,) and assessed:
        # Partial rule coverage with a manifest: name the real gap, not the manifest
        # (the query IDs a re-discovery recovers, else the review gaps).
        gaps = _rule_gaps(obs)
        queries = [
            q
            for g in gaps
            if g.startswith((_MISSING_SOURCE, _UNAVAILABLE_QUERY))
            for q in g.split(":", 1)[1].split(",")
        ]
        others = [
            g for g in gaps if not g.startswith((_MISSING_SOURCE, _UNAVAILABLE_QUERY))
        ]
        if queries or others:
            missing = _unique([*queries, *others])
            fact_missing = bool(queries)
    codes: list[str] = []
    for o in obs:
        if o.dedupe_key and o.dedupe_key.startswith(AGGREGATE_KEY_PREFIX):
            codes.append(_PER_JOB_CAP)
        codes.extend(o.uncertainty)
    # Only gaps no command recovers (a suppressed rule's column, capped evidence):
    # no request.
    nothing_to_acquire = (
        not fact_missing
        and bool(codes)
        and all(unrecoverable_gap(c) for c in codes)
        and all(m == _RULE_SOURCE or unrecoverable_gap(m) for m in missing)
        and (assessed or (rule_reason or "").startswith(_SUPPRESSED))
    )
    request = None
    if coverage != "complete" and not nothing_to_acquire:
        request = {
            "owner_role": "operator",
            "missing": missing,
            "command": DISCOVERY_COMMAND if fact_missing else REVIEW_COMMAND,
            "placeholders": (),
        }
    open_findings = [f for f in findings if f.state in _OPEN_STATES]
    severity: str | None = None
    if assessed:
        severity = max(
            (f.severity or "none" for f in open_findings),
            key=severity_rank,
            default="none",
        )
    return FamilyRead(
        family=family,
        assessment="assessed" if assessed else "unknown",
        coverage=coverage,
        severity=severity,
        observation_ids=_unique([o.observation_id for o in obs]),
        finding_ids=_unique([f.finding_id for f in open_findings]),
        change_ids=_unique([c.change_id for c in changes if c.family == family]),
        uncertainty=_unique(codes),
        unknown_reason=(
            None if assessed else rule_reason or _MISSING_SOURCE + ",".join(missing)
        ),
        acquisition_request=request,
    )


def project(
    current: Sequence[Observation],
    findings: Sequence[FindingRecord],
    changes: Sequence[ChangeInput] = (),
    *,
    run_id: str,
    account_key: str,
    workspace_id: str,
    interval: tuple[str, str],
) -> HealthRead:
    """Project one run onto the six health families.

    Args:
        current: The run's (merged) observations; case acquisitions are ignored.
        findings: The run's findings after ``finding_states``; case findings are
            excluded from health.
        changes: The run's ChangeInputs.
        run_id / account_key / workspace_id: Scope of the read.
        interval: The run's reporting interval ``(start, end)``.

    A family's ``uncertainty`` is the union of its observations' uncertainty
    codes, plus ``per_job_cap_25`` when it holds an F-12 aggregate.
    """
    obs = [o for o in current if health_eligible(o)]
    by_id = {o.observation_id: o for o in current}
    scoped = [f for f in findings if not _is_case(f)]
    families = tuple(
        _family_read(
            fam,
            [o for o in obs if o.family == fam],
            [f for f in scoped if f.family == fam],
            changes,
        )
        for fam in SIX_FAMILIES
    )
    unclassified_findings = [
        f for f in scoped if f.family == UNCLASSIFIED and f.state in _OPEN_STATES
    ]
    unclassified = None
    if unclassified_findings:
        unclassified = FamilyRead(
            family=UNCLASSIFIED,
            assessment="unknown",
            coverage="unknown",
            severity=None,
            observation_ids=_unique(
                [oid for f in unclassified_findings for oid in f.observation_ids]
            ),
            finding_ids=_unique([f.finding_id for f in unclassified_findings]),
            change_ids=(),
            uncertainty=(),
            unknown_reason="rule_family_unclassified",
            acquisition_request=None,
        )

    def concern_order(f: FindingRecord) -> tuple[int, int, float, str]:
        failed, dbus = finding_exposure(f, by_id)
        return (
            -severity_rank(f.severity),
            -(failed or 0),
            -(dbus or 0.0),
            f.finding_id,
        )

    top = sorted((f for f in scoped if f.state in _OPEN_STATES), key=concern_order)
    assessed_count = sum(f.assessment == "assessed" for f in families)
    return HealthRead(
        run_id=run_id,
        account_key=account_key,
        workspace_id=workspace_id,
        reporting_interval_start=interval[0],
        reporting_interval_end=interval[1],
        families=families,
        verdict="health_read" if assessed_count else "insufficient_evidence",
        assessed_count=assessed_count,
        top_concern_finding_ids=tuple(f.finding_id for f in top),
        material_unknowns=tuple(
            f.family for f in families if f.assessment == "unknown"
        ),
        unclassified=unclassified,
    )


def no_evidence(read: HealthRead, reason: str, missing: Sequence[str]) -> HealthRead:
    """``read`` with every family ``unknown``: the capture proved nothing.

    For a capture with zero successful queries, whatever the projection inferred.
    Each family's ``unknown_reason`` is ``reason``; its acquisition request asks
    for a new discovery naming ``missing`` (the capture's unsuccessful query IDs).
    """
    request = {
        "owner_role": "operator",
        "missing": tuple(missing) or ("discovery",),
        "command": DISCOVERY_COMMAND,
        "placeholders": (),
    }
    families = tuple(
        replace(
            f,
            assessment="unknown",
            coverage="unknown",
            severity=None,
            unknown_reason=reason,
            acquisition_request=request,
        )
        for f in read.families
    )
    return replace(
        read,
        families=families,
        verdict="insufficient_evidence",
        assessed_count=0,
        material_unknowns=tuple(f.family for f in families),
    )


def targeted_requests(read: HealthRead, target: RunTarget) -> HealthRead:
    """``read`` with every acquisition command in the run's form.

    A discovery request becomes :func:`discovery_command` (the run's workspace and
    window), a review request :func:`review_command`; the request's
    ``placeholders`` lists the placeholders its command prints.
    """
    interval = (read.reporting_interval_start, read.reporting_interval_end)

    def form(request: Mapping[str, object]) -> dict[str, object]:
        command = str(request["command"])
        if command.startswith("starboard --discover"):
            command = discovery_command(read.workspace_id, interval, target)
        elif command.startswith("starboard review"):
            command = review_command(target)
        return {**request, "command": command, "placeholders": placeholders([command])}

    families = tuple(
        replace(f, acquisition_request=form(f.acquisition_request))
        if f.acquisition_request is not None
        else f
        for f in read.families
    )
    return replace(read, families=families)
