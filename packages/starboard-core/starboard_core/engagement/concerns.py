# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Concern rules (``concern_rules_v1``, spec §D, D3-20).

Pure functions over the current run's observations, its
:class:`~starboard_core.engagement.records.BaselineSelection` and the prior
findings. Two rule families:

- ``reliability_rule_v1``: per job (``job_failure_rise``) and at workspace grain
  (``ws_job_failure_rise``), from the ``job_runs`` / ``failed_job_runs`` /
  ``job_failure_rate_pct`` observations and the rate's *eligible* baseline. It
  emits one ``job_failure_concern`` flag observation per entity.
- Review-rule concerns: a triggered ``finding_present`` observation of a
  findings-manifest entry becomes a ``rule:<rule_id>`` concern with the review
  severity mapped per OD-1 (``critical→critical``, ``high→serious``,
  ``medium→watch``, ``low→watch``).

Consumption, adoption and concentration have no concern rule (OD-2). Starboard
only ever writes ``cause_confidence="unassessed"`` on a new episode.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from starboard_core.domain.rules.registry import rule_entity_kind, rule_family
from starboard_core.engagement.evidence import SOURCE_KIND_ORDER
from starboard_core.engagement.history import TRIGGER_UNIT
from starboard_core.engagement.observations import composite_key
from starboard_core.engagement.records import (
    UNCLASSIFIED,
    BaselineSelection,
    FindingRecord,
    FindingRevision,
    Observation,
    audience_class_for,
    concern_key,
    episode_id,
    finding_id,
    observation_id,
)

__all__ = [
    "BELOW_MIN_VOLUME",
    "FLAG_METRIC",
    "RELIABILITY_RULE_ID",
    "REVIEW_SEVERITY",
    "ConcernResult",
    "error_signature",
    "evaluate",
    "reliability_severity",
    "strip_ansi",
]

RELIABILITY_RULE_ID = "reliability_rule_v1"
FLAG_METRIC = "job_failure_concern"
_RULE_VERSION = 1
_GRAIN = "interval"
_RELIABILITY = "reliability"
_RUNS, _FAILED, _RATE = "job_runs", "failed_job_runs", "job_failure_rate_pct"
_CODES = {"job": "job_failure_rise", "workspace": "ws_job_failure_rise"}
_PRESENT = "finding_present"
_DBU_METRIC = "evidence_dbu_estimate"

# reliability_rule_v1 thresholds (provisional technical trigger, OD-3).
_MIN_RUNS = 50
_MIN_FAILED = 5
_RISE_PP = 5.0
_WATCH_RATE_PCT = 5.0
_CRITICAL_RATE_PCT = 50.0
_CRITICAL_FAILED = 25

#: Review severity → concern severity (OD-1).
REVIEW_SEVERITY: Mapping[str, str] = MappingProxyType(
    {"critical": "critical", "high": "serious", "medium": "watch", "low": "watch"}
)
_REVIEW_ORDER = ("low", "medium", "high", "critical")
_CONTINUING_STATES = ("active", "watch", "unknown_current")
#: ``unknown_reason`` of a flag whose open concern lacks the run volume to re-test.
BELOW_MIN_VOLUME = "below_min_volume"
_EXCEPTION_RE = re.compile(r"\w+(?:Error|Exception)")
#: ``RestException: NOT_FOUND:`` - the error code right after the exception name.
_ERROR_CODE_RE = re.compile(r"\s*:\s*([A-Z][A-Z0-9_]{2,})\s*:")
#: ANSI escape sequences (a coloured traceback): ``\x1b[0;31m`` is not part of a name.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_SIGNATURE_PART_RE = re.compile(r"[^a-z0-9_.-]+")


@dataclass(frozen=True)
class ConcernResult:
    """Output of :func:`evaluate`.

    Attributes:
        flags: One ``job_failure_concern`` flag observation per reliability entity
            (``unknown`` when the rule cannot be evaluated).
        findings: Current findings (``watch`` / ``serious`` / ``critical`` only),
            chained onto the prior record of the same concern key.
        review_severities: ``finding_id`` → the original review severity of each
            ``rule:`` finding (so a ``low`` origin can rank last, OD-1).
    """

    flags: tuple[Observation, ...]
    findings: tuple[FindingRecord, ...]
    review_severities: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


def reliability_severity(
    runs: float | None,
    failed: float | None,
    rate_pct: float | None,
    baseline_rate_pct: float | None,
) -> str | None:
    """``reliability_rule_v1`` severity; ``None`` when runs are not measured.

    ``baseline_rate_pct`` is the eligible baseline's rate, or ``None`` when no
    baseline was selected.
    """
    if runs is None or failed is None or rate_pct is None:
        return None
    if runs < _MIN_RUNS or failed < _MIN_FAILED:
        return "none"
    if (
        baseline_rate_pct is not None
        and rate_pct - baseline_rate_pct >= _RISE_PP - 1e-9
    ):
        if rate_pct >= _CRITICAL_RATE_PCT and failed >= _CRITICAL_FAILED:
            return "critical"
        return "serious"
    if rate_pct >= _WATCH_RATE_PCT:
        return "watch"
    return "none"


def strip_ansi(text: str) -> str:
    """``text`` without ANSI colour escapes (a coloured traceback)."""
    return _ANSI_RE.sub("", text)


def error_signature(text: str | None, *, category: str | None = None) -> str:
    """``error_signature_v1``: ``<category>/<exception>`` or ``unknown/unknown``.

    ``category`` is the ``starboard_x.diagnostic extract-evidence`` category of
    the error text; ``exception`` is the lower-cased first
    ``\\w+(Error|Exception)`` match in ``text``, plus ``:<code>`` when an
    UPPER_SNAKE error code follows it (``restexception:not_found``).
    """
    clean = strip_ansi(text or "")
    match = _EXCEPTION_RE.search(clean)
    exception = match.group(0).lower() if match else "unknown"
    if match:
        # A traceback names the exception in its header first and carries the
        # code on the final ``Name: CODE: message`` line: first occurrence wins.
        for m in _EXCEPTION_RE.finditer(clean):
            code = (
                _ERROR_CODE_RE.match(clean, m.end())
                if m.group(0).lower() == exception
                else None
            )
            if code:
                exception = f"{exception}:{code.group(1).lower()}"
                break
    cat = _SIGNATURE_PART_RE.sub("_", (category or "").strip().lower()).strip("_")
    return f"{cat or 'unknown'}/{exception}"


# ---- helpers -------------------------------------------------------------------


def _restrictive_source(observations: Sequence[Observation]) -> str:
    return min((o.source_kind for o in observations), key=SOURCE_KIND_ORDER.index)


def _union(*groups: Sequence[str]) -> tuple[str, ...]:
    out: list[str] = []
    for group in groups:
        out.extend(x for x in group if x not in out)
    return tuple(out)


def _confidence(coverage: str) -> str:
    return {"complete": "confirmed", "partial": "probable"}.get(coverage, "unverified")


def _latest_prior(
    prior: Sequence[FindingRecord], run_id: str
) -> dict[str, FindingRecord]:
    """Highest revision per key (ties: first given), ignoring this run's records."""
    out: dict[str, FindingRecord] = {}
    for p in prior:
        if p.run_id == run_id:
            continue
        held = out.get(p.finding_key)
        if held is None or p.revision > held.revision:
            out[p.finding_key] = p
    return out


def _finding(
    *,
    key: str,
    family: str,
    severity: str,
    coverage: str,
    rule_id: str,
    observation_ids: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    run_id: str,
    prior: FindingRecord | None,
) -> FindingRecord:
    parts = key.split("|")
    fid = finding_id(key)
    continues = prior is not None and prior.state in _CONTINUING_STATES
    started = (
        prior.episode_started_run_id if prior is not None and continues else run_id
    )
    cause = prior.cause_confidence if prior is not None and continues else "unassessed"
    symptom = _confidence(coverage)
    revision = FindingRevision(
        revision=prior.revision + 1 if prior is not None else 1,
        run_id=run_id,
        reason="reassessed" if continues else "detected",
        severity=severity,
        symptom_confidence=symptom,
        cause_confidence=cause,
        observation_ids=observation_ids,
        evidence_ids=evidence_ids,
    )
    return FindingRecord(
        finding_id=fid,
        finding_key=key,
        concern_code=parts[5],
        family=family,
        account_key=parts[1],
        workspace_id=parts[2],
        entity_kind=parts[3],
        entity_id=parts[4],
        episode_id=episode_id(fid, started),
        episode_started_run_id=started,
        state="watch" if severity == "watch" else "active",
        severity=severity,
        last_confirmed_severity=severity,
        symptom_confidence=symptom,
        cause_confidence=cause,
        rule_id=rule_id,
        rule_version=_RULE_VERSION,
        revision=revision.revision,
        revisions=(*prior.revisions, revision) if prior is not None else (revision,),
        observation_ids=observation_ids,
        run_id=run_id,
        evidence_ids=evidence_ids,
        possible_links=prior.possible_links if prior is not None else (),
        case_ids=prior.case_ids if prior is not None else (),
        action_ids=prior.action_ids if prior is not None else (),
    )


def _flag(
    anchor: Observation,
    support: Sequence[Observation],
    value: float | None,
    coverage: str,
    run_id: str,
    unknown_reason: str | None,
) -> Observation:
    key = (
        anchor.account_key,
        anchor.workspace_id,
        _RELIABILITY,
        anchor.entity_kind,
        anchor.entity_id,
        FLAG_METRIC,
        anchor.interval_start,
        anchor.interval_end,
        RELIABILITY_RULE_ID,
    )
    source = _restrictive_source(support)
    return Observation(
        observation_id=observation_id(key),
        run_id=run_id,
        account_key=anchor.account_key,
        workspace_id=anchor.workspace_id,
        family=_RELIABILITY,
        entity_kind=anchor.entity_kind,
        entity_id=anchor.entity_id,
        metric=FLAG_METRIC,
        value=value,
        unit=TRIGGER_UNIT,
        grain=_GRAIN,
        method_version=RELIABILITY_RULE_ID,
        interval_start=anchor.interval_start,
        interval_end=anchor.interval_end,
        as_of=anchor.as_of,
        coverage=coverage if value is not None else "unknown",
        coverage_fraction=None,
        state="measured" if value is not None else "unknown",
        unknown_reason=unknown_reason if value is None else None,
        evidence_ids=_union(*(o.evidence_ids for o in support)),
        source_kind=source,
        audience_class=audience_class_for(source),
    )


def _baseline_value(
    rate: Observation,
    selection: BaselineSelection,
    baselines: Mapping[str, Observation],
) -> float | None:
    for entry in selection.selected:
        if entry["current_observation_id"] != rate.observation_id:
            continue
        base_id = entry["baseline_observation_id"]
        if base_id is None or entry["comparison"] != "continuing":
            return None
        base = baselines.get(base_id)
        if base is None:
            raise ValueError(
                f"selected baseline {base_id} for {rate.observation_id} is not in "
                "baselines"
            )
        return base.value
    return None


def _reliability(
    current: Sequence[Observation],
    selection: BaselineSelection,
    prior: Mapping[str, FindingRecord],
    baselines: Mapping[str, Observation],
    run_id: str,
) -> tuple[list[Observation], list[FindingRecord]]:
    groups: dict[tuple[str, str, str, str], dict[str, Observation]] = {}
    for o in current:
        if (
            o.family != _RELIABILITY
            or o.entity_kind not in _CODES
            or o.metric not in (_RUNS, _FAILED, _RATE)
        ):
            continue
        ident = (o.account_key, o.workspace_id, o.entity_kind, o.entity_id)
        groups.setdefault(ident, {})[o.metric] = o

    flags: list[Observation] = []
    findings: list[FindingRecord] = []
    for (account, ws, kind, eid), metrics in groups.items():
        runs, failed, rate = (metrics.get(m) for m in (_RUNS, _FAILED, _RATE))
        anchor = rate or runs or failed
        assert anchor is not None
        support = [o for o in (runs, failed, rate) if o is not None]
        measured = all(
            o is not None and o.state == "measured" and o.coverage != "unknown"
            for o in (runs, failed, rate)
        )
        if not measured or runs is None or failed is None or rate is None:
            flags.append(
                _flag(
                    anchor, support, None, "unknown", run_id, "rule_inputs_not_measured"
                )
            )
            continue
        key = concern_key(account, ws, kind, eid, _CODES[kind])
        held = prior.get(key)
        if (
            runs.value is not None
            and runs.value < _MIN_RUNS
            and held is not None
            and held.state in _CONTINUING_STATES
        ):
            # Too few runs to re-measure an open concern: unknown, never recovered
            # (D3-13 lost coverage; the play success rule needs >= 50 runs).
            flags.append(
                _flag(anchor, support, None, "unknown", run_id, BELOW_MIN_VOLUME)
            )
            continue
        baseline = _baseline_value(rate, selection, baselines)
        severity = reliability_severity(runs.value, failed.value, rate.value, baseline)
        coverage = (
            "complete" if all(o.coverage == "complete" for o in support) else "partial"
        )
        triggered = severity in ("watch", "serious", "critical")
        flag = _flag(anchor, support, 1.0 if triggered else 0.0, coverage, run_id, None)
        flags.append(flag)
        if not triggered or severity is None:
            continue
        findings.append(
            _finding(
                key=key,
                family=_RELIABILITY,
                severity=severity,
                coverage=coverage,
                rule_id=RELIABILITY_RULE_ID,
                observation_ids=(
                    flag.observation_id,
                    *(o.observation_id for o in support),
                ),
                evidence_ids=flag.evidence_ids,
                run_id=run_id,
                prior=held,
            )
        )
    return flags, findings


def _review_entity(
    entry: Mapping[str, Any], rule_id: str, workspace_id: str
) -> tuple[str, str]:
    kind = rule_entity_kind(rule_id) or "workspace"
    if kind == "workspace":
        return kind, workspace_id
    raw = str(entry.get("entity_id") or "").strip()
    try:
        concern_key("a", "w", kind, raw, "rule:x")
    except ValueError:
        raw = "h:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return kind, raw


def _review(
    current: Sequence[Observation],
    manifest: Mapping[str, Any] | None,
    prior: Mapping[str, FindingRecord],
    run_id: str,
) -> tuple[list[FindingRecord], dict[str, str]]:
    if not manifest:
        return [], {}
    entries: dict[str, Mapping[str, Any]] = {}
    for entry in manifest.get("findings") or ():
        if isinstance(entry, Mapping):
            entries.setdefault(composite_key(entry), entry)
    dbu = {
        (o.workspace_id, o.entity_id): o
        for o in current
        if o.metric == _DBU_METRIC and o.state == "measured"
    }
    # Manifest entries that map to one concern key (a workspace-grain rule with
    # one entry per product, ``ws:<PRODUCT>``) collapse into ONE finding citing
    # every entry's support (so its DBU exposure is the sum, not the first's) at
    # the highest review severity.
    groups: dict[str, tuple[str, str, str, list[Observation]]] = {}
    for o in current:
        if (
            o.metric != _PRESENT
            or o.state != "measured"
            or o.value is None
            or o.value < 0.5
        ):
            continue
        entry = entries.get(o.entity_id)
        if entry is None:
            continue
        review = str(entry.get("severity") or "").lower()
        rule_id = entry.get("rule_id")
        if review not in REVIEW_SEVERITY or not isinstance(rule_id, str) or not rule_id:
            continue
        family = o.family if o.family not in ("other",) else rule_family(rule_id)
        if family == "other":
            family = UNCLASSIFIED
        kind, eid = _review_entity(entry, rule_id, o.workspace_id)
        key = concern_key(o.account_key, o.workspace_id, kind, eid, f"rule:{rule_id}")
        support = [o] + [d for d in (dbu.get((o.workspace_id, o.entity_id)),) if d]
        if key in groups:
            first_family, first_rule, first_review, cited = groups[key]
            top = max(first_review, review, key=_REVIEW_ORDER.index)
            groups[key] = (first_family, first_rule, top, [*cited, *support])
        else:
            groups[key] = (family, rule_id, review, support)
    findings: list[FindingRecord] = []
    origins: dict[str, str] = {}
    for key, (family, rule_id, review, support) in groups.items():
        record = _finding(
            key=key,
            family=family,
            severity=REVIEW_SEVERITY[review],
            coverage=(
                "partial"
                if any(s.coverage == "partial" for s in support)
                else support[0].coverage
            ),
            rule_id=rule_id,
            observation_ids=_union(tuple(s.observation_id for s in support)),
            evidence_ids=_union(*(s.evidence_ids for s in support)),
            run_id=run_id,
            prior=prior.get(key),
        )
        findings.append(record)
        origins[record.finding_id] = review
    return findings, origins


def evaluate(
    current: Sequence[Observation],
    selection: BaselineSelection,
    prior_findings: Sequence[FindingRecord],
    *,
    run_id: str,
    baselines: Sequence[Observation],
    manifest: Mapping[str, Any] | None = None,
) -> ConcernResult:
    """Evaluate ``concern_rules_v1`` for one run.

    Args:
        current: The run's (merged) observations.
        selection: ``select_baselines`` over ``current``; the rise uses the
            eligible baseline of each ``job_failure_rate_pct`` observation.
        prior_findings: Prior findings (any runs); the current record of a key
            extends the highest-revision prior chain by one revision (a new
            episode when the prior is ``recovered`` / ``historical``).
        run_id: The current run.
        baselines: Prior observations holding the selected baseline IDs.
        manifest: The findings-manifest 2.0 dict (review severities), if any.

    Raises:
        ValueError: When a selected baseline ID is not in ``baselines``.
    """
    by_id = {o.observation_id: o for o in baselines}
    prior = _latest_prior(prior_findings, run_id)
    flags, reliability = _reliability(current, selection, prior, by_id, run_id)
    review, origins = _review(current, manifest, prior, run_id)
    return ConcernResult(
        flags=tuple(flags),
        findings=(*reliability, *review),
        review_severities=MappingProxyType(origins),
    )
