# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Versioned engagement run records (engagement-drive spec §2).

``RunAuthorization`` freezes the preflight decisions (account, scope, source
mode, storage policy); ``RunState`` records the evolving observed scope and
statuses and is updated by producing a new revision. ``DriveContext`` records
the resolved Drive destination. ``IdentityCheck`` captures the identity-only
customer-workspace check that turns a provisional account into a verified one;
``RunManifest`` is the append-only commit record of a Drive-backed run, citing
typed ``StorageRef`` objects. Alongside them are the evidence / observation / finding
records, the account ``Registration``, and the publication records
(``ReportRevision``, ``Approval``, ``DeliveryReceipt``) plus the per-observation
``BaselineSelection``. All are frozen dataclasses with JSON-safe ``to_dict`` /
``from_dict``.

Principals are opaque IDs (SCIM / Drive permission IDs); emails and user names
are never stored.

No credentials: any key in a nested mapping that looks like a credential
(``token``, ``secret``, ``password``, ``api_key`` ...) is rejected. The internal
only ``TicketRef`` type is never imported here; a ticket travels as an opaque
serialized snapshot.

Standard library only.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, field, fields, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal, cast, get_args
from urllib.parse import unquote

from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.profiles import WORKFLOW_PROFILES
from starboard_core.engagement.run_id import is_run_id

SCHEMA_VERSION = 1

DriveRoute = Literal["account", "ticket", "override"]
RunStatus = Literal["pending", "in_progress", "complete", "failed", "skipped"]
ProvisionalSource = Literal["operator", "mapping", "salesforce", "ticket"]
PrincipalKind = Literal["user", "service_principal"]
IdentityStatus = Literal["verified", "mismatch"]

EvidenceSourceKind = Literal[
    "customer_workspace",
    "internal_mirror",
    "internal_telemetry",
    "drive_object",
    "operator_input",
]
AudienceClass = Literal["internal_only", "customer_shareable"]
Coverage = Literal["complete", "partial", "unknown"]
ObservationState = Literal["measured", "unknown"]
FindingState = Literal["active", "watch", "recovered", "historical", "unknown_current"]
RegistrationKind = Literal["run", "imported_local"]
ReportAudience = Literal["internal", "customer"]
ReportState = Literal[
    "draft", "ready", "blocked_audience", "approved", "pending_delivery", "delivered"
]
DeliveryChannel = Literal["drive", "google_doc", "slides", "slack"]
#: Per-key comparison outcome of :func:`starboard_core.engagement.history.select_baselines`.
#: ``history_unavailable`` replaces ``no_prior_measurement`` when no eligible
#: candidate exists and at least one registration could not be read (D-19).
Comparison = Literal[
    "no_prior_measurement",
    "history_unavailable",
    "missing_current_evidence",
    "not_comparable",
    "continuing",
    "recovered",
    "new",
]

#: Observation families (spec §3). The observation adapters emit ``other`` unless the
#: source is already family-tagged (D-13).
FAMILIES: tuple[str, ...] = (
    "consumption_trajectory",
    "efficiency",
    "reliability",
    "adoption_breadth",
    "concentration",
    "governance",
    "other",
)

#: Rules whose DBU estimate is a run-rate (DBU/day), not a window total: never
#: summed with window totals.
RUN_RATE_RULES = frozenset({"spend_step_change"})

#: Observation units (D3-14); ``Observation.unit`` must be one of these.
UNITS: tuple[str, ...] = (
    "DBU",
    "DSU",
    "DBU/day",
    "count",
    "pct",
    "pp",
    "flag",
    "ratio",
    "s",
    "ms",
    "bytes",
)
#: Family of a finding whose rule carries no family tag (D3-17). It is never a
#: health family and is reported only in ``HealthRead.unclassified``.
UNCLASSIFIED = "unclassified"
_HEALTH_FAMILIES: tuple[str, ...] = tuple(f for f in FAMILIES if f != "other")
_FINDING_FAMILIES: tuple[str, ...] = (*_HEALTH_FAMILIES, UNCLASSIFIED)
_OBSERVATION_FAMILIES: tuple[str, ...] = (*FAMILIES, UNCLASSIFIED)

EntityKind = Literal[
    "workspace", "job", "warehouse", "pipeline", "query", "endpoint", "table", "product"
]
Severity = Literal["none", "watch", "serious", "critical"]
SymptomConfidence = Literal["confirmed", "probable", "unverified"]
CauseConfidence = Literal["unassessed", "hypothesis", "supported"]
RevisionReason = Literal[
    "detected",
    "reassessed",
    "investigated",
    "recovered",
    "unknown_current",
    "historical",
]
PlayCode = Literal[
    "job_reliability_session",
    "job_reliability_investigation",
    "rule_finding_review",
    "acquire_family_evidence",
]
OwnerRole = Literal[
    "job_owner",
    "warehouse_owner",
    "pipeline_owner",
    "platform_admin",
    "operator",
    "account_team",
]
#: Concern entity kinds (spec §B2).
ENTITY_KINDS: tuple[str, ...] = get_args(EntityKind)
#: Finding / family severities, lowest first.
SEVERITIES: tuple[str, ...] = get_args(Severity)
_SYMPTOM_CONFIDENCES: tuple[str, ...] = get_args(SymptomConfidence)
_CAUSE_CONFIDENCES: tuple[str, ...] = get_args(CauseConfidence)
_REVISION_REASONS: tuple[str, ...] = get_args(RevisionReason)
_PLAY_CODES: tuple[str, ...] = get_args(PlayCode)
_OWNER_ROLES: tuple[str, ...] = get_args(OwnerRole)
_ASSESSMENTS: tuple[str, ...] = ("assessed", "unknown")
_VERDICTS: tuple[str, ...] = ("health_read", "insufficient_evidence")
_INTERACTION_TYPES: tuple[str, ...] = (
    "working_session",
    "investigation",
    "acquisition",
    "monitor",
)
_URGENCIES: tuple[str, ...] = ("high", "medium", "low")
_CRITICALITIES: tuple[str, ...] = ("unknown", "low", "medium", "high")
_EVIDENCE_STRENGTHS: tuple[str, ...] = ("strong", "moderate", "weak")
_NEXT_STEP_KINDS: tuple[str, ...] = ("investigate", "act", "acquire")
_CHANGE_COMPARISONS: tuple[str, ...] = ("continuing", "new", "recovered")
_CONTEXT_EVENT_KINDS: tuple[str, ...] = ("config_change", "action_event", "step_change")
_CASE_ORIGINS: tuple[str, ...] = ("finding", "clue", "drive_object")
_CASE_TARGET_KINDS: tuple[str, ...] = (*ENTITY_KINDS, "run", "drive_object")
_CASE_STATES: tuple[str, ...] = ("open", "answered", "closed")
_HYPOTHESIS_STATUSES: tuple[str, ...] = ("untested", "supported", "refuted")
_PROPOSAL_STATES: tuple[str, ...] = ("proposed", "withdrawn")
_ACCEPTANCE_STATES: tuple[str, ...] = ("pending", "accepted", "rejected")
_EXECUTION_STATES: tuple[str, ...] = ("not_started", "executed", "unknown")
_OUTCOME_STATES: tuple[str, ...] = (
    "not_observed",
    "improved",
    "unchanged",
    "worsened",
    "unknown",
)
_ATTRIBUTIONS: tuple[str, ...] = ("not_established", "consistent_with_action")
_EVENT_KINDS: tuple[str, ...] = (
    "proposed",
    "accepted",
    "rejected",
    "executed",
    "withdrawn",
    "outcome_observed",
)
_RECORDED_BY: tuple[str, ...] = ("rule", "host", "operator")
HEALTH_METHOD_VERSION = "health_read_v1"
CHANGE_METHOD_VERSION = "change_inputs_v1"
PLAY_RULE_ID = "play_rules_v1"
#: Maximum length of host free text (questions, notes, labels, statements).
FREE_TEXT_MAX = 500

_ROUTES: tuple[str, ...] = get_args(DriveRoute)
_SOURCE_KINDS: tuple[str, ...] = get_args(EvidenceSourceKind)
_AUDIENCE_CLASSES: tuple[str, ...] = get_args(AudienceClass)
_COVERAGES: tuple[str, ...] = get_args(Coverage)
_OBSERVATION_STATES: tuple[str, ...] = get_args(ObservationState)
_FINDING_STATES: tuple[str, ...] = get_args(FindingState)
_REGISTRATION_KINDS: tuple[str, ...] = get_args(RegistrationKind)
_REPORT_AUDIENCES: tuple[str, ...] = get_args(ReportAudience)
_REPORT_STATES: tuple[str, ...] = get_args(ReportState)
_CHANNELS: tuple[str, ...] = get_args(DeliveryChannel)
_COMPARISONS: tuple[str, ...] = get_args(Comparison)
_STATUSES: tuple[str, ...] = get_args(RunStatus)
_PROVISIONAL_SOURCES: tuple[str, ...] = get_args(ProvisionalSource)
_PRINCIPAL_KINDS: tuple[str, ...] = get_args(PrincipalKind)
_IDENTITY_STATUSES: tuple[str, ...] = get_args(IdentityStatus)
MANIFEST_STATE_KEYS: tuple[str, ...] = ("capture", "analysis", "check", "publication")
_MD5_RE = re.compile(r"[0-9a-f]{32}")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# Credential markers are matched against whole key segments (``snake``, ``kebab``,
# ``camelCase`` and dotted keys are split), so ``max_tokens`` or ``secretary``
# stay allowed while ``access_token`` and ``apiKey`` are rejected.
_CREDENTIAL_SEGMENTS = frozenset(
    {
        "token",
        "secret",
        "secrets",
        "password",
        "passwd",
        "apikey",
        "credential",
        "credentials",
        "bearer",
    }
)
_CREDENTIAL_PAIRS = frozenset(
    {("api", "key"), ("private", "key"), ("client", "secret")}
)
_EVIDENCE_ID_RE = re.compile(r"ev_[0-9a-f]{24}")
_OBSERVATION_ID_RE = re.compile(r"obs_[0-9a-f]{24}")
_FINDING_ID_RE = re.compile(r"fnd_[0-9a-f]{24}")
_EPISODE_ID_RE = re.compile(r"ep_[0-9a-f]{24}")
_PLAY_ID_RE = re.compile(r"play_[0-9a-f]{24}")
_CASE_ID_RE = re.compile(r"case_[0-9a-f]{24}")
_ACTION_ID_RE = re.compile(r"act_[0-9a-f]{24}")
_CHANGE_ID_RE = re.compile(r"chg_[0-9a-f]{24}")
# A short machine code (uncertainty, unknown reasons, gaps): no whitespace.
_CODE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:.,/+-]{0,199}")
# Concern keys (spec §B1).
_CONCERN_KEY_VERSION = "ck1"
_CONCERN_CODE_RE = re.compile(
    r"job_failure_rise|ws_job_failure_rise|rule:[A-Za-z0-9][A-Za-z0-9_.-]*|case:[a-z_]+"
)
_DISCRIMINATOR_RE = re.compile(r"-|sig:\S+")
_KEY_PART_FORBIDDEN_RE = re.compile(r"[\s\x00-\x1f\x7f]")
_EMBEDDED_RUN_ID_RE = re.compile(
    r"\d{8}_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
#: A standalone case's clue kinds (``<kind>:<id>``; ``run`` is a job run).
CLUE_KINDS: tuple[str, ...] = ("job", "query", "pipeline", "run")
_CLUE_REF_RE = re.compile(
    rf"(?:{'|'.join(CLUE_KINDS)}):[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}"
)
_DRIVE_REF_RE = re.compile(r"drive:[A-Za-z0-9_-]{1,256}")
_COMMAND_PREFIXES: tuple[str, ...] = (
    "starboard-helper ",
    "starboard ",
    "python -m starboard_x.",
)
_COMMAND_FORBIDDEN_RE = re.compile(r"[;`\n\r]|\$\(|&&|\|")
_LIMIT_FLAG_RE = re.compile(r"(?:^|\s)--limit(?:[\s=]|$)")
# Host free text (D3-24): checked after NFKC + HTML-entity + percent decoding, so
# ``jane＠example.com``, ``jane&#64;example.com`` and ``jane%40example.com`` are
# caught. ``job 42 @ 10:00``, ``@decorator`` and ``x@y`` stay allowed: an ``@``
# right after a quote, bracket or separator (`` `@app.route('/ping')` ``) or after
# a space with none following it (``under @app.route``) starts a decorator, not
# an address.
_EMAIL_TEXT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"[^@\s]*[^@\s'\"`()\[\]{}<>,;:]@[^@\s]+\.[^@\s]+"),
    re.compile(
        r"[\w.+-]+(?:@\s*|\s+@\s+)[\w-]+(?:\s*\.\s*[\w-]+)*\s*\.\s*[A-Za-z]{2,}\b"
    ),
    re.compile(
        r"[\w.+-]+\s*[\[({<]\s*at\s*[\])}>]\s*[\w-]+"
        r"(?:\s*(?:[\[({<]\s*dot\s*[\])}>]|\.)\s*[\w-]+)+",
        re.IGNORECASE,
    ),
    re.compile(r"[\w.+-]+\s+at\s+[\w-]+(?:\s+dot\s+[\w-]+)+", re.IGNORECASE),
    re.compile(r"mailto:", re.IGNORECASE),
)
# Obfuscated separators, folded before the email probe: the ideographic / halfwidth
# / fullwidth full stops, ``[at]`` / ``(at)`` -> ``@`` and ``[.]`` / ``(.)`` /
# `` dot `` -> ``.`` (so ``jane@example dot com`` is caught; ``see the dot
# product`` has no ``@`` and stays allowed). Spaced-out letters (``j a n e @ ...``)
# are not folded: too many false positives on ordinary prose.
_OBFUSCATED_DOTS = str.maketrans({"\u3002": ".", "\uff61": ".", "\uff0e": "."})
_OBFUSCATED_AT_RE = re.compile(r"\s*[\[(]\s*at\s*[\])]\s*", re.IGNORECASE)
_OBFUSCATED_DOT_RE = re.compile(r"\s*[\[(]\s*\.\s*[\])]\s*|\s+dot\s+", re.IGNORECASE)
_CREDENTIAL_TEXT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"dapi[0-9a-f]{32}", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(
        r"(?<![A-Za-z])(?:token|secret|password|passwd|pwd|api[_-]?key|"
        r"client[_-]?secret|access[_-]?key)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{16,}"),
)
_IMPORT_REG_ID_RE = re.compile(r"reg_imp_[0-9a-f]{8,64}")
# Report / approval / receipt IDs become Drive path segments.
_SEGMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_DERIVED_FROM_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,127})@([1-9][0-9]*)")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEGMENT_SPLIT = re.compile(r"[^a-z0-9]+")


# ---- helpers -----------------------------------------------------------------


def _freeze(value: Any) -> Any:
    """Deep-copy JSON-like data into immutable containers."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    """Inverse of :func:`_freeze`: plain dicts and lists, safe for ``json.dumps``."""
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(v) for v in value]
    return value


def _looks_like_credential(key: str) -> bool:
    segments = [
        seg
        for seg in _SEGMENT_SPLIT.split(_CAMEL_BOUNDARY.sub("_", key).lower())
        if seg
    ]
    if any(seg in _CREDENTIAL_SEGMENTS for seg in segments):
        return True
    return any(pair in _CREDENTIAL_PAIRS for pair in zip(segments, segments[1:]))


def _reject_credentials(value: Any, where: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _looks_like_credential(str(key)):
                raise ValueError(
                    f"{where}: key {key!r} looks like a credential; records must not "
                    "contain credentials"
                )
            _reject_credentials(item, where)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_credentials(item, where)


def _check_timestamp(value: str, name: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be an ISO-8601 timestamp, got {value!r}"
        ) from exc


def _non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _check_version(data: Mapping[str, Any], kind: str) -> None:
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported {kind} schema_version: {version!r}")


def _require(data: Mapping[str, Any], kind: str, *names: str) -> None:
    missing = [n for n in names if n not in data]
    if missing:
        raise ValueError(f"{kind} is missing required field(s): {', '.join(missing)}")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _one_of(value: Any, allowed: tuple[str, ...], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")


def _positive_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be an int >= 1, got {value!r}")


def _parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 date/timestamp; naive values are taken as UTC."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _not_email(value: str, name: str) -> None:
    if "@" in value:
        raise ValueError(f"{name} must be an opaque ID, not an email address")


def _str_tuple(value: Any, name: str) -> tuple[str, ...]:
    items = tuple(value)
    for item in items:
        _non_empty(item, name)
    return items


def _segment_id(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SEGMENT_ID_RE.fullmatch(value):
        raise ValueError(
            f"{name} must match {_SEGMENT_ID_RE.pattern} (it is a path segment), got {value!r}"
        )


def _check_md5(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _MD5_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase MD5 hex digest, got {value!r}")


def _check_bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a bool, got {value!r}")


def _storage_ref(value: Any, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, StorageRef):
        raise TypeError(f"{name} must be a StorageRef")


def _digest(*parts: str) -> str:
    payload = json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _required_fields(cls: Any) -> list[str]:
    return [
        f.name
        for f in fields(cls)
        if f.default is MISSING and f.default_factory is MISSING
    ]


def _ref_or_none(value: Any) -> StorageRef | None:
    return None if value is None else StorageRef.from_dict(value)


def _plain(value: Any) -> Any:
    """JSON-safe form of a field value (nested records via ``to_dict``)."""
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return _thaw(value)


def _record_to_dict(record: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(record, f.name)) for f in fields(record)}


def _record_from_dict(
    cls: Any, data: Mapping[str, Any], kind: str, **nested: Any
) -> Any:
    _check_version(data, kind)
    _reject_credentials(data, kind)
    _require(data, kind, *_required_fields(cls))
    values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
    for name, convert in nested.items():
        if name in values:
            values[name] = convert(values[name])
    return cls(**values)


def _id(value: Any, regex: re.Pattern[str], name: str) -> None:
    if not isinstance(value, str) or not regex.fullmatch(value):
        raise ValueError(f"{name} must match {regex.pattern}, got {value!r}")


def _optional_id(value: Any, regex: re.Pattern[str], name: str) -> None:
    if value is not None:
        _id(value, regex, name)


def _id_tuple(value: Any, regex: re.Pattern[str], name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a sequence of IDs, got {value!r}")
    items = tuple(value)
    for item in items:
        _id(item, regex, f"{name}[]")
    return items


def unrecoverable_gap(code: str) -> bool:
    """Whether no command recovers this coverage gap code.

    A ``suppressed:<rule_id>...`` rule lacks a source column; ``evidence_capped`` is
    a rule's evidence query at its row limit (no discovery flag lifts the cap, and a
    review re-run reads the same rows).
    """
    return code.startswith("suppressed:") or code == "evidence_capped"


def _code(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _CODE_RE.fullmatch(value):
        raise ValueError(
            f"{name} must be a short code ({_CODE_RE.pattern}), got {value!r}"
        )


def _code_tuple(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a sequence of codes, got {value!r}")
    items = tuple(value)
    for item in items:
        _code(item, f"{name}[]")
    return items


def _number(value: Any, name: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _non_negative_int(value: Any, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be an int >= 0, got {value!r}")


def _exact_keys(value: Any, keys: frozenset[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{name} needs exactly the keys {sorted(keys)}, got {value!r}")
    return value


def _interval(start: Any, end: Any, name: str) -> None:
    _check_timestamp(start, f"{name} start")
    _check_timestamp(end, f"{name} end")
    if _parse_ts(start) > _parse_ts(end):
        raise ValueError(f"{name}: start {start!r} is after end {end!r}")


def _decoded_variants(value: str) -> str:
    """``value`` plus its NFKC / HTML-entity / percent-decoded forms, joined."""
    seen = [value]
    current = value
    for _ in range(3):
        decoded = unicodedata.normalize(
            "NFKC", unquote(html.unescape(unicodedata.normalize("NFKC", current)))
        )
        if decoded in seen:
            break
        seen.append(decoded)
        current = decoded
    return "\n".join(seen)


def _check_free_text(value: Any, name: str) -> None:
    """Host free text (D3-24): bounded, no emails, no credential-like strings."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > FREE_TEXT_MAX:
        raise ValueError(f"{name} must be at most {FREE_TEXT_MAX} characters")
    if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t" for ch in value):
        raise ValueError(f"{name} must not contain control characters")
    _check_no_email_or_credential(value, name)


def _fold_obfuscation(text: str) -> str:
    """``text`` with obfuscated ``@`` / ``.`` separators folded (email probe only)."""
    text = _OBFUSCATED_AT_RE.sub("@", text.translate(_OBFUSCATED_DOTS))
    return _OBFUSCATED_DOT_RE.sub(".", text)


def _check_no_email_or_credential(value: str, name: str) -> None:
    probe = _decoded_variants(value)
    email_probe = f"{probe}\n{_fold_obfuscation(probe)}"
    if any(p.search(email_probe) for p in _EMAIL_TEXT_RES):
        raise ValueError(
            f"{name} must not contain an email address (emails are never stored)"
        )
    if any(p.search(probe) for p in _CREDENTIAL_TEXT_RES):
        raise ValueError(
            f"{name} looks like it contains a credential; records must not contain "
            "credentials"
        )


def _check_optional_free_text(value: Any, name: str) -> None:
    if value is not None:
        _check_free_text(value, name)


def _check_command(value: Any, name: str) -> None:
    """A real Starboard CLI string; ``verify run`` always carries ``--limit``."""
    _non_empty(value, name)
    if not value.startswith(_COMMAND_PREFIXES):
        raise ValueError(
            f"{name} must start with one of {_COMMAND_PREFIXES}, got {value!r}"
        )
    if _COMMAND_FORBIDDEN_RE.search(value):
        raise ValueError(f"{name} must be a single command, got {value!r}")
    if " verify run " in f" {value} " and not _LIMIT_FLAG_RE.search(value):
        raise ValueError(f"{name}: a verify run command needs --limit, got {value!r}")
    _check_no_email_or_credential(value, name)


# ---- ID helpers --------------------------------------------------------------


def evidence_id(run_id: str, relpath: str, md5: str) -> str:
    """Deterministic evidence ID: ``ev_`` + sha256(run_id, relpath, md5)[:24]."""
    return "ev_" + _digest(run_id, relpath, md5)


def observation_id(o_key: tuple[str, ...]) -> str:
    """Deterministic observation ID: ``obs_`` + sha256(key)[:24].

    ``o_key`` is :attr:`Observation.key`: ``(account_key, workspace_id, family,
    entity_kind, entity_id, metric, interval_start, interval_end, method_version)``.
    """
    return "obs_" + _digest(*o_key)


def concern_key(
    account_key: str,
    workspace_id: str,
    entity_kind: str,
    entity_id: str,
    concern_code: str,
    discriminator: str = "-",
) -> str:
    """Canonical concern key ``ck1|account|workspace|kind|id|code|discriminator``.

    No component may contain ``|``, whitespace or a run ID; the account,
    workspace and entity components carry no path separators, so a ticket,
    folder path, report title or prose is never part of the key.

    Raises:
        ValueError: On any invalid component.
    """
    parts = {
        "account_key": account_key,
        "workspace_id": workspace_id,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "concern_code": concern_code,
        "discriminator": discriminator,
    }
    for name, value in parts.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"concern_key {name} must be a non-empty string")
        if "|" in value:
            raise ValueError(f"concern_key {name} must not contain '|': {value!r}")
        if _KEY_PART_FORBIDDEN_RE.search(value):
            raise ValueError(
                f"concern_key {name} must not contain whitespace or control "
                f"characters: {value!r}"
            )
        if _EMBEDDED_RUN_ID_RE.search(value):
            raise ValueError(f"concern_key {name} must not contain a run ID: {value!r}")
    for name in ("account_key", "workspace_id", "entity_id"):
        if "/" in parts[name] or "\\" in parts[name]:
            raise ValueError(f"concern_key {name} must not be a path: {parts[name]!r}")
    _one_of(entity_kind, ENTITY_KINDS, "concern_key entity_kind")
    if not _CONCERN_CODE_RE.fullmatch(concern_code):
        raise ValueError(
            f"concern_key concern_code must match {_CONCERN_CODE_RE.pattern}, "
            f"got {concern_code!r}"
        )
    if concern_code.startswith("case:"):
        _one_of(concern_code[5:], _CASE_TARGET_KINDS, "concern_key case target kind")
    if not _DISCRIMINATOR_RE.fullmatch(discriminator):
        raise ValueError(
            f"concern_key discriminator must be '-' or 'sig:<family>', got {discriminator!r}"
        )
    return "|".join((_CONCERN_KEY_VERSION, *parts.values()))


def _split_concern_key(key: Any) -> tuple[str, ...]:
    """The six components of a valid concern key (``ValueError`` otherwise)."""
    parts = key.split("|") if isinstance(key, str) else []
    if len(parts) != 7 or parts[0] != _CONCERN_KEY_VERSION:
        raise ValueError(f"not a ck1 concern key: {key!r}")
    if concern_key(*parts[1:]) != key:  # pragma: no cover - concern_key raises first
        raise ValueError(f"not a canonical concern key: {key!r}")
    return tuple(parts[1:])


def finding_id(key: str) -> str:
    """Finding ID: ``fnd_`` + sha256(concern key)[:24]."""
    _split_concern_key(key)
    return "fnd_" + _digest(key)


def episode_id(finding_id: str, episode_started_run_id: str) -> str:
    """Episode ID: ``ep_`` + sha256(finding_id, started run)[:24] (the only builder)."""
    _id(finding_id, _FINDING_ID_RE, "episode_id finding_id")
    if not is_run_id(episode_started_run_id):
        raise ValueError(f"not a valid run ID: {episode_started_run_id!r}")
    return "ep_" + _digest(finding_id, episode_started_run_id)


def play_id(play_code: str, finding_id: str) -> str:
    """Play ID: ``play_`` + sha256(play_code, finding_id)[:24].

    ``finding_id`` is the cited finding; an ``acquire_family_evidence`` play,
    which cites none, passes its family name instead.
    """
    _one_of(play_code, _PLAY_CODES, "play_id play_code")
    _non_empty(finding_id, "play_id finding_id")
    return "play_" + _digest(play_code, finding_id)


def case_id(
    account_key: str, origin_ref: str, opened_run_id: str, question: str
) -> str:
    """Case ID: ``case_`` + sha256(account_key, origin_ref, opened run, question)[:24].

    The question keeps two cases on one origin in one run (e.g. two failed runs
    of the same job) distinct; re-asking the same question names the same case.
    """
    _non_empty(account_key, "case_id account_key")
    _non_empty(origin_ref, "case_id origin_ref")
    _non_empty(question, "case_id question")
    if not is_run_id(opened_run_id):
        raise ValueError(f"not a valid run ID: {opened_run_id!r}")
    return "case_" + _digest(account_key, origin_ref, opened_run_id, question)


def action_id(finding_id: str, play_code: str, proposed_run_id: str) -> str:
    """Action ID: ``act_`` + sha256(finding_id, play_code, proposed run)[:24]."""
    _id(finding_id, _FINDING_ID_RE, "action_id finding_id")
    _one_of(play_code, _PLAY_CODES, "action_id play_code")
    if not is_run_id(proposed_run_id):
        raise ValueError(f"not a valid run ID: {proposed_run_id!r}")
    return "act_" + _digest(finding_id, play_code, proposed_run_id)


def case_action_id(case_id: str, finding_id: str, next_step: str) -> str:
    """Case action ID: ``act_`` + sha256(case_id, finding_id, next step)[:24].

    Re-proposing the same next step on the same case and finding names the same
    action; a different next step is a different action.
    """
    _id(case_id, _CASE_ID_RE, "case_action_id case_id")
    _id(finding_id, _FINDING_ID_RE, "case_action_id finding_id")
    _non_empty(next_step, "case_action_id next_step")
    return "act_" + _digest(case_id, finding_id, next_step)


def change_id(current_observation_id: str, baseline_observation_id: str) -> str:
    """Change ID: ``chg_`` + sha256(current, baseline observation IDs)[:24]."""
    _id(current_observation_id, _OBSERVATION_ID_RE, "change_id current_observation_id")
    _id(
        baseline_observation_id, _OBSERVATION_ID_RE, "change_id baseline_observation_id"
    )
    return "chg_" + _digest(current_observation_id, baseline_observation_id)


def registration_id(run_id: str) -> str:
    """Registration ID of a Drive run: ``reg_<run_id>``."""
    if not is_run_id(run_id):
        raise ValueError(f"not a valid run ID: {run_id!r}")
    return f"reg_{run_id}"


def audience_class_for(source_kind: str) -> str:
    """Computed audience class (D-14): any ``internal_*`` source is ``internal_only``."""
    _one_of(source_kind, _SOURCE_KINDS, "source_kind")
    return (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )


def _check_audience(source_kind: Any, audience_class: Any, where: str) -> None:
    _one_of(source_kind, _SOURCE_KINDS, f"{where}.source_kind")
    _one_of(audience_class, _AUDIENCE_CLASSES, f"{where}.audience_class")
    if source_kind.startswith("internal_") and audience_class != "internal_only":
        raise ValueError(
            f"{where}: an {source_kind} source is always internal_only (D-14)"
        )


# ---- AccountRef --------------------------------------------------------------


@dataclass(frozen=True)
class AccountRef:
    """Verified account identity.

    Attributes:
        id: Stable account identifier.
        display_name: Verified human-readable name (presentation only).
        verifier: What verified the account (for example ``salesforce``).
    """

    id: str
    display_name: str
    verifier: str

    def __post_init__(self) -> None:
        _non_empty(self.id, "AccountRef.id")
        _non_empty(self.display_name, "AccountRef.display_name")
        _non_empty(self.verifier, "AccountRef.verifier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "verifier": self.verifier,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AccountRef:
        _require(data, "AccountRef", "id", "display_name", "verifier")
        return cls(data["id"], data["display_name"], data["verifier"])


# ---- DriveContext ------------------------------------------------------------


@dataclass(frozen=True)
class DriveContext:
    """Resolved Drive destination for a run (``DriveContext v1``).

    Folder names are presentation; the IDs here are authority.

    Attributes:
        provider: Storage provider name (for example ``google_drive``).
        principal: Opaque identifier of the authenticated operator.
        route: ``account``, ``ticket`` or ``override``.
        base_folder_id / root_folder_id / run_folder_id / registry_folder_id:
            Folder IDs.
        account_key: Verified account key the destination belongs to.
        acl_classification: ACL classification string for the destination.
        permission_fingerprints: Folder ID -> permission fingerprint.
        capabilities: Capability results (for example ``{"upload": True}``).
        created_at: ISO-8601 creation time.
        idempotency_key: Immutable key reused on retry.
        links: Name -> URL for folders and objects.
        preflight_folder_id: Restricted ``_preflight`` staging folder, if any.
        fallback_warning: Set when the requested destination was not writable
            and the run fell back to My Drive (owner decision D6).
    """

    provider: str
    principal: str
    route: str
    base_folder_id: str
    root_folder_id: str
    run_folder_id: str
    registry_folder_id: str
    account_key: str
    acl_classification: str
    permission_fingerprints: Mapping[str, str]
    capabilities: Mapping[str, bool]
    created_at: str
    idempotency_key: str
    links: Mapping[str, str] = field(default_factory=dict)
    preflight_folder_id: str | None = None
    fallback_warning: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "principal",
            "base_folder_id",
            "root_folder_id",
            "run_folder_id",
            "registry_folder_id",
            "account_key",
            "acl_classification",
            "idempotency_key",
        ):
            _non_empty(getattr(self, name), f"DriveContext.{name}")
        if self.route not in _ROUTES:
            raise ValueError(
                f"DriveContext.route must be one of {_ROUTES}, got {self.route!r}"
            )
        _check_timestamp(self.created_at, "DriveContext.created_at")
        for name in ("permission_fingerprints", "capabilities", "links"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
            _reject_credentials(getattr(self, name), f"DriveContext.{name}")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _thaw(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DriveContext:
        _check_version(data, "DriveContext")
        required = [
            f.name
            for f in fields(cls)
            if f.default is MISSING and f.default_factory is MISSING
        ]
        _require(data, "DriveContext", *required)
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


# ---- RunAuthorization --------------------------------------------------------


@dataclass(frozen=True)
class RunAuthorization:
    """Immutable preflight decisions for a run (``RunAuthorization v1``).

    Attributes:
        engagement_id: Stable review-series ID.
        run_id: The run's ID (validated with ``is_run_id``).
        intent: ``health_check``, ``troubleshooting``, ``discovery`` ...
        task: Task name.
        account: Verified account.
        requested_scope / authorized_scope: JSON-like scope mappings.
        reporting_interval / timezone: Reporting window and its timezone.
        source_mode / storage_policy: Preflight classification results.
        audience: Intended audience of the outputs.
        methodology_version: Methodology version used.
        drive: Resolved Drive context, if Drive-backed.
        ticket: Opaque serialized ticket snapshot (the internal-only TicketRef
            type is deliberately not imported here).
        workspace_profile: The ``~/.databrickscfg`` profile the customer identity
            was verified with (``None``: verified with ``--host``, or not verified).
            A ``--run-folder`` fetch defaults to it and refuses any other profile.
    """

    engagement_id: str
    run_id: str
    intent: str
    task: str
    account: AccountRef
    requested_scope: Mapping[str, Any]
    authorized_scope: Mapping[str, Any]
    reporting_interval: str
    timezone: str
    source_mode: SourceMode
    storage_policy: StoragePolicy
    audience: str
    methodology_version: str
    drive: DriveContext | None = None
    ticket: Mapping[str, Any] | None = None
    workspace_profile: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"RunAuthorization.run_id is not a valid run ID: {self.run_id!r}"
            )
        for name in (
            "engagement_id",
            "intent",
            "task",
            "reporting_interval",
            "timezone",
            "audience",
            "methodology_version",
        ):
            _non_empty(getattr(self, name), f"RunAuthorization.{name}")
        object.__setattr__(self, "source_mode", SourceMode(self.source_mode))
        object.__setattr__(self, "storage_policy", StoragePolicy(self.storage_policy))
        for name in ("requested_scope", "authorized_scope"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        if self.ticket is not None:
            object.__setattr__(self, "ticket", _freeze(self.ticket))
        _reject_credentials(self.requested_scope, "RunAuthorization.requested_scope")
        _reject_credentials(self.authorized_scope, "RunAuthorization.authorized_scope")
        _reject_credentials(self.ticket, "RunAuthorization.ticket")
        if self.workspace_profile is not None:
            _non_empty(self.workspace_profile, "RunAuthorization.workspace_profile")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engagement_id": self.engagement_id,
            "run_id": self.run_id,
            "intent": self.intent,
            "task": self.task,
            "account": self.account.to_dict(),
            "requested_scope": _thaw(self.requested_scope),
            "authorized_scope": _thaw(self.authorized_scope),
            "reporting_interval": self.reporting_interval,
            "timezone": self.timezone,
            "source_mode": self.source_mode.value,
            "storage_policy": self.storage_policy.value,
            "audience": self.audience,
            "methodology_version": self.methodology_version,
            "drive": None if self.drive is None else self.drive.to_dict(),
            "ticket": None if self.ticket is None else _thaw(self.ticket),
            "workspace_profile": self.workspace_profile,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunAuthorization:
        _check_version(data, "RunAuthorization")
        _require(
            data,
            "RunAuthorization",
            "engagement_id",
            "run_id",
            "intent",
            "task",
            "account",
            "requested_scope",
            "authorized_scope",
            "reporting_interval",
            "timezone",
            "source_mode",
            "storage_policy",
            "audience",
            "methodology_version",
        )
        drive = data.get("drive")
        return cls(
            engagement_id=data["engagement_id"],
            run_id=data["run_id"],
            intent=data["intent"],
            task=data["task"],
            account=AccountRef.from_dict(data["account"]),
            requested_scope=data["requested_scope"],
            authorized_scope=data["authorized_scope"],
            reporting_interval=data["reporting_interval"],
            timezone=data["timezone"],
            source_mode=SourceMode(data["source_mode"]),
            storage_policy=StoragePolicy(data["storage_policy"]),
            audience=data["audience"],
            methodology_version=data["methodology_version"],
            drive=None if drive is None else DriveContext.from_dict(drive),
            ticket=data.get("ticket"),
            workspace_profile=data.get("workspace_profile"),
        )


# ---- RunState ----------------------------------------------------------------

_PROTECTED = frozenset({"schema_version", "run_id", "revision", "created_at"})


@dataclass(frozen=True)
class RunState:
    """Evolving state of a run (``RunState v1``), updated by new revisions.

    A pending publication does not invalidate committed observations: the four
    statuses move independently.

    Attributes:
        run_id: The run's ID.
        created_at / updated_at: ISO-8601 timestamps.
        revision: Starts at 1; incremented by :meth:`advance`.
        observed_scope: What was actually observed (JSON-like mapping).
        source_attempts: One mapping per acquisition attempt.
        capture_status / analysis_status / check_status / publication_status:
            One of ``pending``, ``in_progress``, ``complete``, ``failed``,
            ``skipped``.
        warnings: Visible warnings (for example a Drive fallback).
    """

    run_id: str
    created_at: str
    updated_at: str
    revision: int = 1
    observed_scope: Mapping[str, Any] = field(default_factory=dict)
    source_attempts: tuple[Mapping[str, Any], ...] = ()
    capture_status: RunStatus = "pending"
    analysis_status: RunStatus = "pending"
    check_status: RunStatus = "pending"
    publication_status: RunStatus = "pending"
    warnings: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(f"RunState.run_id is not a valid run ID: {self.run_id!r}")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError(
                f"RunState.revision must be an int >= 1, got {self.revision!r}"
            )
        _check_timestamp(self.created_at, "RunState.created_at")
        _check_timestamp(self.updated_at, "RunState.updated_at")
        for name in (
            "capture_status",
            "analysis_status",
            "check_status",
            "publication_status",
        ):
            if getattr(self, name) not in _STATUSES:
                raise ValueError(
                    f"RunState.{name} must be one of {_STATUSES}, got {getattr(self, name)!r}"
                )
        object.__setattr__(self, "observed_scope", _freeze(self.observed_scope))
        object.__setattr__(
            self, "source_attempts", _freeze(tuple(self.source_attempts))
        )
        object.__setattr__(self, "warnings", tuple(self.warnings))
        _reject_credentials(self.observed_scope, "RunState.observed_scope")
        _reject_credentials(self.source_attempts, "RunState.source_attempts")

    @classmethod
    def new(cls, run_id: str, now_iso: str | None = None) -> RunState:
        """Create the initial (revision 1, all-pending) state for a run."""
        stamp = now_iso or _now_iso()
        return cls(run_id=run_id, created_at=stamp, updated_at=stamp)

    def advance(self, **changes: Any) -> RunState:
        """Return a new state with ``changes`` applied and ``revision`` + 1.

        ``updated_at`` is set to now unless supplied.

        Raises:
            ValueError: for unknown fields, protected fields (``run_id``,
                ``revision``, ``schema_version``, ``created_at``) or invalid values.
        """
        allowed = {f.name for f in fields(self)}
        bad = sorted(set(changes) - allowed)
        if bad:
            raise ValueError(f"unknown RunState field(s): {', '.join(bad)}")
        protected = sorted(set(changes) & _PROTECTED)
        if protected:
            raise ValueError(f"cannot change RunState field(s): {', '.join(protected)}")
        changes.setdefault("updated_at", _now_iso())
        return replace(self, revision=self.revision + 1, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "observed_scope": _thaw(self.observed_scope),
            "source_attempts": _thaw(self.source_attempts),
            "capture_status": self.capture_status,
            "analysis_status": self.analysis_status,
            "check_status": self.check_status,
            "publication_status": self.publication_status,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunState:
        _check_version(data, "RunState")
        _require(data, "RunState", "run_id", "revision", "created_at", "updated_at")
        return cls(
            run_id=data["run_id"],
            revision=data["revision"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            observed_scope=data.get("observed_scope", {}),
            source_attempts=tuple(data.get("source_attempts", ())),
            capture_status=cast(RunStatus, data.get("capture_status", "pending")),
            analysis_status=cast(RunStatus, data.get("analysis_status", "pending")),
            check_status=cast(RunStatus, data.get("check_status", "pending")),
            publication_status=cast(
                RunStatus, data.get("publication_status", "pending")
            ),
            warnings=tuple(data.get("warnings", ())),
        )


# ---- IdentityCheck -----------------------------------------------------------


@dataclass(frozen=True)
class IdentityCheck:
    """Result of the identity-only customer-workspace check (``IdentityCheck v1``).

    Compares the provisional account's expected workspace with what the
    workspace itself proves (server workspace ID, host, principal). Nothing
    row-, log- or code-bearing is recorded, and the principal is an opaque ID
    (SCIM ``id``), never an email or user name.

    Attributes:
        run_id: The run's ID.
        provisional_account_key / provisional_account_name: The provisional
            account the operator (or a trusted source) named.
        provisional_source: ``operator``, ``mapping``, ``salesforce`` or ``ticket``.
        expected_workspace_id: From ``--workspace-id`` or a ``ws-<id>`` task
            name; empty when none was supplied (which is itself a mismatch).
        expected_host: Normalized expected host, when one was supplied.
        observed_workspace_id / observed_host: What the workspace proved.
        principal_id / principal_kind: Opaque principal ID and
            ``user``/``service_principal``.
        checked_at: ISO-8601 check time.
        status: ``verified`` or ``mismatch``.
        reasons: Mismatch reasons; empty exactly when ``verified``.
        workspace_profile: The ``--profile`` the check ran with (``None`` for
            ``--host``). Only recorded, never used to derive the expected workspace.
    """

    run_id: str
    provisional_account_key: str
    provisional_account_name: str
    provisional_source: ProvisionalSource
    expected_workspace_id: str
    expected_host: str | None
    observed_workspace_id: str
    observed_host: str
    principal_id: str
    principal_kind: PrincipalKind
    checked_at: str
    status: IdentityStatus
    reasons: tuple[str, ...] = ()
    workspace_profile: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"IdentityCheck.run_id is not a valid run ID: {self.run_id!r}"
            )
        for name in (
            "provisional_account_key",
            "provisional_account_name",
            "observed_workspace_id",
            "observed_host",
            "principal_id",
        ):
            _non_empty(getattr(self, name), f"IdentityCheck.{name}")
        if not isinstance(self.expected_workspace_id, str):
            raise ValueError("IdentityCheck.expected_workspace_id must be a string")
        if self.expected_host is not None:
            _non_empty(self.expected_host, "IdentityCheck.expected_host")
        if self.workspace_profile is not None:
            _non_empty(self.workspace_profile, "IdentityCheck.workspace_profile")
        if "@" in self.principal_id:
            raise ValueError(
                "IdentityCheck.principal_id must be an opaque ID, not an email address"
            )
        _one_of(
            self.provisional_source,
            _PROVISIONAL_SOURCES,
            "IdentityCheck.provisional_source",
        )
        _one_of(self.principal_kind, _PRINCIPAL_KINDS, "IdentityCheck.principal_kind")
        _one_of(self.status, _IDENTITY_STATUSES, "IdentityCheck.status")
        _check_timestamp(self.checked_at, "IdentityCheck.checked_at")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if self.status == "verified":
            if self.reasons:
                raise ValueError(
                    "a verified IdentityCheck cannot carry mismatch reasons"
                )
            if (
                not self.expected_workspace_id
                or self.expected_workspace_id != self.observed_workspace_id
            ):
                raise ValueError(
                    "a verified IdentityCheck needs equal expected and observed workspace IDs"
                )
            if (
                self.expected_host is not None
                and self.expected_host != self.observed_host
            ):
                raise ValueError(
                    "a verified IdentityCheck needs equal expected and observed hosts"
                )
        elif not self.reasons:
            raise ValueError("a mismatch IdentityCheck needs at least one reason")

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["reasons"] = list(self.reasons)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> IdentityCheck:
        _check_version(data, "IdentityCheck")
        _reject_credentials(data, "IdentityCheck")
        required = [
            f.name
            for f in fields(cls)
            if f.default is MISSING and f.default_factory is MISSING
        ]
        _require(data, "IdentityCheck", *required)
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
        values["reasons"] = tuple(data.get("reasons", ()))
        return cls(**values)


# ---- StorageRef --------------------------------------------------------------


@dataclass(frozen=True)
class StorageRef:
    """Typed reference to one stored object (``StorageRef v1``).

    ``path`` is the object's logical location relative to the run folder (for
    example ``analysis/report.json``); it is never a local filesystem path. The
    object ID is the authority.

    Attributes:
        path: Run-relative logical path.
        object_id: Provider object ID.
        revision: Content revision ID, when the provider reports one.
        md5: Provider MD5 hex digest, when available.
        size: Byte size, when available.
        mime_type: Content MIME type.
    """

    path: str
    object_id: str
    revision: str | None
    md5: str | None
    size: int | None
    mime_type: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _non_empty(self.path, "StorageRef.path")
        _non_empty(self.object_id, "StorageRef.object_id")
        _non_empty(self.mime_type, "StorageRef.mime_type")
        if (
            self.path.startswith(("/", "~"))
            or "\\" in self.path
            or _WINDOWS_DRIVE_RE.match(self.path)
            or ".." in self.path.split("/")
        ):
            raise ValueError(
                f"StorageRef.path must be a run-relative logical path, got {self.path!r}"
            )
        if self.revision is not None:
            _non_empty(self.revision, "StorageRef.revision")
        if self.md5 is not None and (
            not isinstance(self.md5, str) or not _MD5_RE.fullmatch(self.md5)
        ):
            raise ValueError(
                f"StorageRef.md5 must be a lowercase MD5 hex digest, got {self.md5!r}"
            )
        if self.size is not None and (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
        ):
            raise ValueError(f"StorageRef.size must be an int >= 0, got {self.size!r}")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StorageRef:
        _check_version(data, "StorageRef")
        _reject_credentials(data, "StorageRef")
        _require(data, "StorageRef", "path", "object_id", "mime_type")
        return cls(
            path=data["path"],
            object_id=data["object_id"],
            revision=data.get("revision"),
            md5=data.get("md5"),
            size=data.get("size"),
            mime_type=data["mime_type"],
        )


# ---- RunManifest -------------------------------------------------------------

_MANIFEST_PHASE3_REFS: tuple[str, ...] = (
    "health_ref",
    "plays_ref",
    "changes_ref",
    "cases_ref",
    "actions_ref",
)


@dataclass(frozen=True)
class RunManifest:
    """One immutable revision of a Drive-backed run's commit record (``RunManifest v1``).

    Revisions are append-only: each names its predecessor's object ID, so the
    chain is verifiable from storage alone. An object is citable only once a
    manifest revision lists its verified ``StorageRef``.

    Attributes:
        engagement_id / run_id: Engagement and run IDs.
        revision: Manifest revision number, starting at 1.
        previous_object_id: Object ID of revision ``revision - 1``; ``None``
            exactly when ``revision == 1``.
        task / task_name: The run's task and task name.
        source_mode / storage_policy: From the run authorization.
        descriptor_ref: The run descriptor (``run-authorization.json``).
        refs: Committed objects, one per run-relative path.
        states: ``capture``/``analysis``/``check``/``publication`` -> status
            (one of the ``RunState`` statuses); all four keys are required.
        committed_at: ISO-8601 commit time.
        input_scope: JSON-like scope the run actually ran over.
        workflow_profile: Workflow profile name (one of ``WORKFLOW_PROFILES``;
            gates ``run check``), if any.
        evidence_refs: ``EvidenceRef.evidence_id`` values cited by this revision.
        observation_refs: Committed observation-list objects
            (``analysis/observations.json``).
        findings_ref: The committed ``analysis/findings.json``, if any.
        reports: One ``{report_id, revision, audience, state}`` per report revision.
        approvals / receipts: ``Approval`` / ``DeliveryReceipt`` IDs.
        baseline_selection_ref: The committed ``analysis/baseline-selection.json``.
        health_ref / plays_ref / changes_ref / cases_ref / actions_ref: The
            committed ``analysis/{health,plays,changes,cases,actions}.json``
            (D3-1), each ``None`` until written.
    """

    engagement_id: str
    run_id: str
    revision: int
    previous_object_id: str | None
    task: str
    task_name: str
    source_mode: SourceMode
    storage_policy: StoragePolicy
    descriptor_ref: StorageRef
    refs: tuple[StorageRef, ...]
    states: Mapping[str, str]
    committed_at: str
    input_scope: Mapping[str, Any] = field(default_factory=dict)
    workflow_profile: str | None = None
    evidence_refs: tuple[str, ...] = ()
    observation_refs: tuple[StorageRef, ...] = ()
    findings_ref: StorageRef | None = None
    reports: tuple[Mapping[str, Any], ...] = ()
    approvals: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    baseline_selection_ref: StorageRef | None = None
    health_ref: StorageRef | None = None
    plays_ref: StorageRef | None = None
    changes_ref: StorageRef | None = None
    cases_ref: StorageRef | None = None
    actions_ref: StorageRef | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"RunManifest.run_id is not a valid run ID: {self.run_id!r}"
            )
        for name in ("engagement_id", "task", "task_name"):
            _non_empty(getattr(self, name), f"RunManifest.{name}")
        _positive_int(self.revision, "RunManifest.revision")
        if self.revision == 1:
            if self.previous_object_id is not None:
                raise ValueError("RunManifest revision 1 cannot name a previous object")
        else:
            if self.previous_object_id is None:
                raise ValueError(
                    f"RunManifest revision {self.revision} must name its predecessor"
                )
            _non_empty(self.previous_object_id, "RunManifest.previous_object_id")
        object.__setattr__(self, "source_mode", SourceMode(self.source_mode))
        object.__setattr__(self, "storage_policy", StoragePolicy(self.storage_policy))
        if not isinstance(self.descriptor_ref, StorageRef):
            raise TypeError("RunManifest.descriptor_ref must be a StorageRef")
        refs = tuple(self.refs)
        if not all(isinstance(r, StorageRef) for r in refs):
            raise TypeError("RunManifest.refs must contain StorageRef values")
        paths = [r.path for r in refs]
        if len(set(paths)) != len(paths):
            raise ValueError("RunManifest.refs must not repeat a path")
        object.__setattr__(self, "refs", refs)
        if set(self.states) != set(MANIFEST_STATE_KEYS):
            raise ValueError(
                f"RunManifest.states must have exactly the keys {MANIFEST_STATE_KEYS}, "
                f"got {sorted(self.states)}"
            )
        for key, value in self.states.items():
            _one_of(value, _STATUSES, f"RunManifest.states[{key!r}]")
        object.__setattr__(
            self, "states", _freeze({k: self.states[k] for k in MANIFEST_STATE_KEYS})
        )
        _check_timestamp(self.committed_at, "RunManifest.committed_at")
        object.__setattr__(self, "input_scope", _freeze(self.input_scope))
        _reject_credentials(self.input_scope, "RunManifest.input_scope")
        if self.workflow_profile is not None:
            _one_of(
                self.workflow_profile,
                WORKFLOW_PROFILES,
                "RunManifest.workflow_profile",
            )
        for name in ("evidence_refs", "approvals", "receipts"):
            object.__setattr__(
                self, name, _str_tuple(getattr(self, name), f"RunManifest.{name}")
            )
        observation_refs = tuple(self.observation_refs)
        if not all(isinstance(r, StorageRef) for r in observation_refs):
            raise TypeError(
                "RunManifest.observation_refs must contain StorageRef values"
            )
        object.__setattr__(self, "observation_refs", observation_refs)
        _storage_ref(self.findings_ref, "RunManifest.findings_ref", optional=True)
        for name in ("baseline_selection_ref", *_MANIFEST_PHASE3_REFS):
            _storage_ref(getattr(self, name), f"RunManifest.{name}", optional=True)
        reports = _freeze(tuple(self.reports))
        for entry in reports:
            if not isinstance(entry, Mapping) or set(entry) != {
                "report_id",
                "revision",
                "audience",
                "state",
            }:
                raise ValueError(
                    "RunManifest.reports entries need exactly report_id, revision, "
                    "audience and state"
                )
            _segment_id(entry["report_id"], "RunManifest.reports[].report_id")
            _positive_int(entry["revision"], "RunManifest.reports[].revision")
            _one_of(
                entry["audience"], _REPORT_AUDIENCES, "RunManifest.reports[].audience"
            )
            _one_of(entry["state"], _REPORT_STATES, "RunManifest.reports[].state")
        object.__setattr__(self, "reports", reports)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "engagement_id": self.engagement_id,
            "run_id": self.run_id,
            "revision": self.revision,
            "previous_object_id": self.previous_object_id,
            "task": self.task,
            "task_name": self.task_name,
            "source_mode": self.source_mode.value,
            "storage_policy": self.storage_policy.value,
            "descriptor_ref": self.descriptor_ref.to_dict(),
            "refs": [r.to_dict() for r in self.refs],
            "states": _thaw(self.states),
            "committed_at": self.committed_at,
            "input_scope": _thaw(self.input_scope),
            "workflow_profile": self.workflow_profile,
            "evidence_refs": list(self.evidence_refs),
            "observation_refs": [r.to_dict() for r in self.observation_refs],
            "findings_ref": None
            if self.findings_ref is None
            else self.findings_ref.to_dict(),
            "reports": _thaw(self.reports),
            "approvals": list(self.approvals),
            "receipts": list(self.receipts),
            "baseline_selection_ref": (
                None
                if self.baseline_selection_ref is None
                else self.baseline_selection_ref.to_dict()
            ),
            **{name: _plain(getattr(self, name)) for name in _MANIFEST_PHASE3_REFS},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RunManifest:
        _check_version(data, "RunManifest")
        _reject_credentials(data, "RunManifest")
        _require(
            data,
            "RunManifest",
            "engagement_id",
            "run_id",
            "revision",
            "previous_object_id",
            "task",
            "task_name",
            "source_mode",
            "storage_policy",
            "descriptor_ref",
            "refs",
            "states",
            "committed_at",
        )
        return cls(
            engagement_id=data["engagement_id"],
            run_id=data["run_id"],
            revision=data["revision"],
            previous_object_id=data["previous_object_id"],
            task=data["task"],
            task_name=data["task_name"],
            source_mode=SourceMode(data["source_mode"]),
            storage_policy=StoragePolicy(data["storage_policy"]),
            descriptor_ref=StorageRef.from_dict(data["descriptor_ref"]),
            refs=tuple(StorageRef.from_dict(r) for r in data["refs"]),
            states=data["states"],
            committed_at=data["committed_at"],
            input_scope=data.get("input_scope", {}),
            workflow_profile=data.get("workflow_profile"),
            evidence_refs=tuple(data.get("evidence_refs", ())),
            observation_refs=tuple(
                StorageRef.from_dict(r) for r in data.get("observation_refs", ())
            ),
            findings_ref=_ref_or_none(data.get("findings_ref")),
            reports=tuple(data.get("reports", ())),
            approvals=tuple(data.get("approvals", ())),
            receipts=tuple(data.get("receipts", ())),
            baseline_selection_ref=_ref_or_none(data.get("baseline_selection_ref")),
            health_ref=_ref_or_none(data.get("health_ref")),
            plays_ref=_ref_or_none(data.get("plays_ref")),
            changes_ref=_ref_or_none(data.get("changes_ref")),
            cases_ref=_ref_or_none(data.get("cases_ref")),
            actions_ref=_ref_or_none(data.get("actions_ref")),
        )


# ---- EvidenceRef -------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRef:
    """One committed evidence object of a run (``EvidenceRef v1``).

    Attributes:
        evidence_id: ``evidence_id(run_id, storage_ref.path, storage_ref.md5)``.
        run_id: The producing run.
        storage_ref: The stored object; its MD5 is required (read-back verified).
        source_kind: ``customer_workspace``, ``internal_mirror``,
            ``internal_telemetry``, ``drive_object`` or ``operator_input``.
        scope_workspace_ids: Workspaces the evidence covers.
        producer: Producing step (for example ``discovery:W-W01``, ``verify:qh``).
        row_count: Row count, when the evidence is tabular.
        truncated: True when rows were capped.
        acquired_at: ISO-8601 acquisition time.
        audience_class: ``internal_only`` or ``customer_shareable``; any
            ``internal_*`` source must be ``internal_only`` (D-14).
        method_version: Producing method version.
    """

    evidence_id: str
    run_id: str
    storage_ref: StorageRef
    source_kind: str
    scope_workspace_ids: tuple[str, ...]
    producer: str
    row_count: int | None
    truncated: bool
    acquired_at: str
    audience_class: str
    method_version: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"EvidenceRef.run_id is not a valid run ID: {self.run_id!r}"
            )
        _storage_ref(self.storage_ref, "EvidenceRef.storage_ref")
        if self.storage_ref.md5 is None:
            raise ValueError("EvidenceRef.storage_ref needs a verified md5")
        expected = evidence_id(self.run_id, self.storage_ref.path, self.storage_ref.md5)
        if self.evidence_id != expected:
            raise ValueError(
                f"EvidenceRef.evidence_id must be {expected!r} for this run/path/md5, "
                f"got {self.evidence_id!r}"
            )
        _check_audience(self.source_kind, self.audience_class, "EvidenceRef")
        object.__setattr__(
            self,
            "scope_workspace_ids",
            _str_tuple(self.scope_workspace_ids, "EvidenceRef.scope_workspace_ids"),
        )
        _non_empty(self.producer, "EvidenceRef.producer")
        _non_empty(self.method_version, "EvidenceRef.method_version")
        if self.row_count is not None and (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise ValueError(
                f"EvidenceRef.row_count must be an int >= 0, got {self.row_count!r}"
            )
        _check_bool(self.truncated, "EvidenceRef.truncated")
        _check_timestamp(self.acquired_at, "EvidenceRef.acquired_at")

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["storage_ref"] = self.storage_ref.to_dict()
        data["scope_workspace_ids"] = list(self.scope_workspace_ids)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EvidenceRef:
        _check_version(data, "EvidenceRef")
        _reject_credentials(data, "EvidenceRef")
        _require(data, "EvidenceRef", *_required_fields(cls))
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
        values["storage_ref"] = StorageRef.from_dict(data["storage_ref"])
        values["scope_workspace_ids"] = tuple(data["scope_workspace_ids"])
        return cls(**values)


# ---- Observation -------------------------------------------------------------

_OBSERVATION_KEY_FIELDS: tuple[str, ...] = (
    "account_key",
    "workspace_id",
    "family",
    "entity_kind",
    "entity_id",
    "metric",
    "interval_start",
    "interval_end",
    "method_version",
)


@dataclass(frozen=True)
class Observation:
    """One measured (or explicitly unknown) metric value (``Observation v1``).

    Attributes:
        observation_id: ``observation_id(self.key)``.
        run_id / account_key / workspace_id: Where it was observed.
        family: One of :data:`FAMILIES`, or ``unclassified`` for the flag of a
            finding whose rule carries no family tag (D3-17).
        entity_kind / entity_id / metric: What was measured.
        value: Measured value (``None`` exactly when ``state == "unknown"``).
        unit: One of :data:`UNITS` (D3-14).
        grain / method_version: Comparability attributes (with ``unit``).
        interval_start / interval_end: Measured window (ISO-8601, start <= end).
        as_of: ISO-8601 time the value was current.
        coverage: ``complete``, ``partial`` or ``unknown``.
        coverage_fraction: Optional 0..1 coverage fraction.
        state: ``measured`` or ``unknown``.
        unknown_reason: Why the value is unknown (required exactly when unknown).
        evidence_ids: Supporting ``EvidenceRef`` IDs.
        source_kind / audience_class: As on ``EvidenceRef`` (D-14).
        dedupe_key: Shared by mirrored copies of one event (counted once);
            identity for supersession only.
        uncertainty: Sorted, de-duplicated short codes qualifying a value
            (e.g. ``per_job_cap_25``, ``verify_limit_reached``); never free text.
    """

    observation_id: str
    run_id: str
    account_key: str
    workspace_id: str
    family: str
    entity_kind: str
    entity_id: str
    metric: str
    value: float | None
    unit: str
    grain: str
    method_version: str
    interval_start: str
    interval_end: str
    as_of: str
    coverage: str
    coverage_fraction: float | None
    state: str
    unknown_reason: str | None
    evidence_ids: tuple[str, ...]
    source_kind: str
    audience_class: str
    dedupe_key: str | None = None
    uncertainty: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    @property
    def key(self) -> tuple[str, ...]:
        """The identity tuple hashed into :attr:`observation_id`."""
        return tuple(getattr(self, name) for name in _OBSERVATION_KEY_FIELDS)

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"Observation.run_id is not a valid run ID: {self.run_id!r}"
            )
        for name in (*_OBSERVATION_KEY_FIELDS, "unit", "grain"):
            _non_empty(getattr(self, name), f"Observation.{name}")
        _one_of(self.family, _OBSERVATION_FAMILIES, "Observation.family")
        _one_of(self.unit, UNITS, "Observation.unit")
        _one_of(self.coverage, _COVERAGES, "Observation.coverage")
        _one_of(self.state, _OBSERVATION_STATES, "Observation.state")
        _check_audience(self.source_kind, self.audience_class, "Observation")
        for name in ("interval_start", "interval_end", "as_of"):
            _check_timestamp(getattr(self, name), f"Observation.{name}")
        if _parse_ts(self.interval_start) > _parse_ts(self.interval_end):
            raise ValueError(
                "Observation.interval_start must not be after interval_end"
            )
        if self.value is not None:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(
                    f"Observation.value must be a number, got {self.value!r}"
                )
            object.__setattr__(self, "value", float(self.value))
        if self.coverage_fraction is not None:
            if isinstance(self.coverage_fraction, bool) or not isinstance(
                self.coverage_fraction, (int, float)
            ):
                raise ValueError("Observation.coverage_fraction must be a number")
            if not 0.0 <= self.coverage_fraction <= 1.0:
                raise ValueError("Observation.coverage_fraction must be within 0..1")
            object.__setattr__(self, "coverage_fraction", float(self.coverage_fraction))
        if self.state == "measured":
            if self.value is None:
                raise ValueError("a measured Observation needs a value")
            if self.unknown_reason is not None:
                raise ValueError("a measured Observation cannot carry unknown_reason")
        else:
            if self.value is not None:
                raise ValueError("an unknown Observation cannot carry a value")
            _non_empty(self.unknown_reason or "", "Observation.unknown_reason")
        object.__setattr__(
            self,
            "evidence_ids",
            _str_tuple(self.evidence_ids, "Observation.evidence_ids"),
        )
        if self.dedupe_key is not None:
            _non_empty(self.dedupe_key, "Observation.dedupe_key")
        object.__setattr__(
            self,
            "uncertainty",
            tuple(
                sorted(set(_code_tuple(self.uncertainty, "Observation.uncertainty")))
            ),
        )
        expected = observation_id(self.key)
        if self.observation_id != expected:
            raise ValueError(
                f"Observation.observation_id must be {expected!r} for its key, "
                f"got {self.observation_id!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["evidence_ids"] = list(self.evidence_ids)
        data["uncertainty"] = list(self.uncertainty)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Observation:
        _check_version(data, "Observation")
        _reject_credentials(data, "Observation")
        _require(data, "Observation", *_required_fields(cls))
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
        values["evidence_ids"] = tuple(data["evidence_ids"])
        if "uncertainty" in values:
            values["uncertainty"] = tuple(values["uncertainty"])
        return cls(**values)


# ---- FindingRevision / FindingRecord ----------------------------------------


def _severity(value: Any, name: str, *, optional: bool = True) -> None:
    if value is None and optional:
        return
    _one_of(value, SEVERITIES, name)


@dataclass(frozen=True)
class FindingRevision:
    """One entry of a finding's revision chain (spec §B2, D3-4).

    Attributes:
        revision: 1-based position in the chain.
        run_id: Run that wrote this revision.
        reason: ``detected``, ``reassessed``, ``investigated``, ``recovered``,
            ``unknown_current`` or ``historical``.
        severity: One of :data:`SEVERITIES`, or ``None`` when unknown.
        symptom_confidence: ``confirmed``, ``probable`` or ``unverified``.
        cause_confidence: ``unassessed``, ``hypothesis`` or ``supported``.
        observation_ids / evidence_ids: Support for this revision.
        case_id: The case that produced it (reason ``investigated``), if any.
    """

    revision: int
    run_id: str
    reason: str
    severity: str | None
    symptom_confidence: str
    cause_confidence: str
    observation_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    case_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _positive_int(self.revision, "FindingRevision.revision")
        if not is_run_id(self.run_id):
            raise ValueError(
                f"FindingRevision.run_id is not a valid run ID: {self.run_id!r}"
            )
        _one_of(self.reason, _REVISION_REASONS, "FindingRevision.reason")
        _severity(self.severity, "FindingRevision.severity")
        _one_of(
            self.symptom_confidence,
            _SYMPTOM_CONFIDENCES,
            "FindingRevision.symptom_confidence",
        )
        _one_of(
            self.cause_confidence,
            _CAUSE_CONFIDENCES,
            "FindingRevision.cause_confidence",
        )
        object.__setattr__(
            self,
            "observation_ids",
            _id_tuple(
                self.observation_ids,
                _OBSERVATION_ID_RE,
                "FindingRevision.observation_ids",
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _id_tuple(
                self.evidence_ids, _EVIDENCE_ID_RE, "FindingRevision.evidence_ids"
            ),
        )
        _optional_id(self.case_id, _CASE_ID_RE, "FindingRevision.case_id")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FindingRevision:
        return cast(
            FindingRevision,
            _record_from_dict(
                cls,
                data,
                "FindingRevision",
                observation_ids=tuple,
                evidence_ids=tuple,
            ),
        )


_KEY_FIELDS: tuple[str, ...] = (
    "account_key",
    "workspace_id",
    "entity_kind",
    "entity_id",
    "concern_code",
)


@dataclass(frozen=True)
class FindingRecord:
    """Drive form of one finding plus its revision chain (``Finding v1``, spec §B2).

    Identity is the concern key: same ``finding_key`` means same finding
    (D3-4). The episode is kept while the concern continues and restarts only
    per :func:`starboard_core.engagement.history.finding_states`.

    Attributes:
        finding_id: ``finding_id(finding_key)``.
        finding_key: ``ck1|…`` concern key (:func:`concern_key`).
        concern_code / account_key / workspace_id / entity_kind / entity_id: The
            key's components (must agree with ``finding_key``).
        family: One of the six health families, or ``unclassified``; never ``other``.
        episode_id: ``episode_id(finding_id, episode_started_run_id)``.
        episode_started_run_id: Run that started the episode.
        state: ``active``, ``watch``, ``recovered``, ``historical`` or
            ``unknown_current``.
        severity: One of :data:`SEVERITIES`, or ``None`` when unknown (never
            ``None`` while ``active`` / ``watch``).
        last_confirmed_severity: Last severity confirmed by a measurement.
        symptom_confidence / cause_confidence: As on :class:`FindingRevision`.
        rule_id / rule_version: Producing rule (``rule_version >= 1``).
        revision: Latest revision number; ``revisions`` holds 1..revision.
        revisions: The chain, oldest first.
        observation_ids / evidence_ids: Support for the current state.
        run_id: Run that wrote this record.
        possible_links: Related finding IDs (advisory only, never merged).
        case_ids / action_ids: Cases and actions on this finding.
    """

    finding_id: str
    finding_key: str
    concern_code: str
    family: str
    account_key: str
    workspace_id: str
    entity_kind: str
    entity_id: str
    episode_id: str
    episode_started_run_id: str
    state: str
    severity: str | None
    last_confirmed_severity: str | None
    symptom_confidence: str
    cause_confidence: str
    rule_id: str
    rule_version: int
    revision: int
    revisions: tuple[FindingRevision, ...]
    observation_ids: tuple[str, ...]
    run_id: str
    evidence_ids: tuple[str, ...] = ()
    possible_links: tuple[str, ...] = ()
    case_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"FindingRecord.run_id is not a valid run ID: {self.run_id!r}"
            )
        parts = _split_concern_key(self.finding_key)
        for name, value in zip(_KEY_FIELDS, parts, strict=False):
            if getattr(self, name) != value:
                raise ValueError(
                    f"FindingRecord.{name} {getattr(self, name)!r} disagrees with "
                    f"finding_key ({value!r})"
                )
        expected = finding_id(self.finding_key)
        if self.finding_id != expected:
            raise ValueError(
                f"FindingRecord.finding_id must be {expected!r} for its key, "
                f"got {self.finding_id!r}"
            )
        _one_of(self.family, _FINDING_FAMILIES, "FindingRecord.family")
        if not is_run_id(self.episode_started_run_id):
            raise ValueError(
                "FindingRecord.episode_started_run_id is not a valid run ID: "
                f"{self.episode_started_run_id!r}"
            )
        expected_episode = episode_id(self.finding_id, self.episode_started_run_id)
        if self.episode_id != expected_episode:
            raise ValueError(
                f"FindingRecord.episode_id must be {expected_episode!r}, "
                f"got {self.episode_id!r}"
            )
        _one_of(self.state, _FINDING_STATES, "FindingRecord.state")
        _severity(self.severity, "FindingRecord.severity")
        _severity(self.last_confirmed_severity, "FindingRecord.last_confirmed_severity")
        if self.state in ("active", "watch") and self.severity is None:
            raise ValueError(f"an {self.state} FindingRecord needs a severity")
        _one_of(
            self.symptom_confidence,
            _SYMPTOM_CONFIDENCES,
            "FindingRecord.symptom_confidence",
        )
        _one_of(
            self.cause_confidence, _CAUSE_CONFIDENCES, "FindingRecord.cause_confidence"
        )
        _non_empty(self.rule_id, "FindingRecord.rule_id")
        _positive_int(self.rule_version, "FindingRecord.rule_version")
        _positive_int(self.revision, "FindingRecord.revision")
        revisions = tuple(self.revisions)
        if not all(isinstance(r, FindingRevision) for r in revisions):
            raise TypeError(
                "FindingRecord.revisions must contain FindingRevision values"
            )
        if [r.revision for r in revisions] != list(range(1, self.revision + 1)):
            raise ValueError(
                "FindingRecord.revisions must be numbered 1..revision consecutively"
            )
        object.__setattr__(self, "revisions", revisions)
        for name, regex in (
            ("observation_ids", _OBSERVATION_ID_RE),
            ("evidence_ids", _EVIDENCE_ID_RE),
            ("possible_links", _FINDING_ID_RE),
            ("case_ids", _CASE_ID_RE),
            ("action_ids", _ACTION_ID_RE),
        ):
            object.__setattr__(
                self,
                name,
                _id_tuple(getattr(self, name), regex, f"FindingRecord.{name}"),
            )

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FindingRecord:
        return cast(
            FindingRecord,
            _record_from_dict(
                cls,
                data,
                "FindingRecord",
                revisions=lambda v: tuple(FindingRevision.from_dict(r) for r in v),
                observation_ids=tuple,
                evidence_ids=tuple,
                possible_links=tuple,
                case_ids=tuple,
                action_ids=tuple,
            ),
        )


# ---- Registration ------------------------------------------------------------

_PROVENANCE_ORIGIN = {"run": "drive_run", "imported_local": "local_reference"}


@dataclass(frozen=True)
class Registration:
    """Immutable account-registry entry for one run (``Registration v1``).

    Attributes:
        registration_id: ``reg_<run_id>`` (kind ``run``) or ``reg_imp_<hex>``
            (kind ``imported_local``).
        kind: ``run`` or ``imported_local``.
        run_id / engagement_id / account_key / task / task_name: The run.
        route: ``account``, ``ticket`` or ``override``.
        source_mode / storage_policy: From the run authorization.
        run_folder_id: The Drive run folder (``None`` exactly for imports).
        descriptor_ref: The run descriptor, when Drive-backed.
        observation_summary_ref: Optional observation summary object.
        acl_classification: ACL class of the run folder at registration.
        principal_id: Opaque ID of the registering operator.
        registered_at: ISO-8601 registration time.
        provenance: ``{"origin": "drive_run"|"local_reference", "local_run_id",
            "approved_by"}``; imports need ``local_run_id`` and ``approved_by``.
    """

    registration_id: str
    kind: str
    run_id: str
    engagement_id: str
    account_key: str
    task: str
    task_name: str
    route: str
    source_mode: SourceMode
    storage_policy: StoragePolicy
    run_folder_id: str | None
    descriptor_ref: StorageRef | None
    observation_summary_ref: StorageRef | None
    acl_classification: str
    principal_id: str
    registered_at: str
    provenance: Mapping[str, Any]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"Registration.run_id is not a valid run ID: {self.run_id!r}"
            )
        _one_of(self.kind, _REGISTRATION_KINDS, "Registration.kind")
        _one_of(self.route, _ROUTES, "Registration.route")
        for name in (
            "engagement_id",
            "account_key",
            "task",
            "task_name",
            "acl_classification",
            "principal_id",
        ):
            _non_empty(getattr(self, name), f"Registration.{name}")
        _not_email(self.principal_id, "Registration.principal_id")
        object.__setattr__(self, "source_mode", SourceMode(self.source_mode))
        object.__setattr__(self, "storage_policy", StoragePolicy(self.storage_policy))
        _storage_ref(self.descriptor_ref, "Registration.descriptor_ref", optional=True)
        _storage_ref(
            self.observation_summary_ref,
            "Registration.observation_summary_ref",
            optional=True,
        )
        _check_timestamp(self.registered_at, "Registration.registered_at")
        if self.kind == "run":
            if self.registration_id != registration_id(self.run_id):
                raise ValueError(
                    "a run Registration.registration_id must be reg_<run_id>"
                )
            _non_empty(self.run_folder_id or "", "Registration.run_folder_id")
        else:
            if not isinstance(
                self.registration_id, str
            ) or not _IMPORT_REG_ID_RE.fullmatch(self.registration_id):
                raise ValueError(
                    "an imported_local Registration.registration_id must be reg_imp_<hex>"
                )
            if self.run_folder_id is not None:
                raise ValueError("an imported_local Registration has no run_folder_id")
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        _reject_credentials(self.provenance, "Registration.provenance")
        origin = self.provenance.get("origin")
        if origin != _PROVENANCE_ORIGIN[self.kind]:
            raise ValueError(
                f"Registration.provenance.origin must be {_PROVENANCE_ORIGIN[self.kind]!r} "
                f"for kind {self.kind!r}, got {origin!r}"
            )
        if self.kind == "imported_local":
            _non_empty(
                self.provenance.get("local_run_id") or "",
                "Registration.provenance.local_run_id",
            )
            approved_by = self.provenance.get("approved_by") or ""
            _non_empty(approved_by, "Registration.provenance.approved_by")
            _not_email(approved_by, "Registration.provenance.approved_by")

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["source_mode"] = self.source_mode.value
        data["storage_policy"] = self.storage_policy.value
        for name in ("descriptor_ref", "observation_summary_ref"):
            ref = getattr(self, name)
            data[name] = None if ref is None else ref.to_dict()
        data["provenance"] = _thaw(self.provenance)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Registration:
        _check_version(data, "Registration")
        _reject_credentials(data, "Registration")
        _require(data, "Registration", *_required_fields(cls))
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
        values["source_mode"] = SourceMode(data["source_mode"])
        values["storage_policy"] = StoragePolicy(data["storage_policy"])
        values["descriptor_ref"] = _ref_or_none(data["descriptor_ref"])
        values["observation_summary_ref"] = _ref_or_none(
            data["observation_summary_ref"]
        )
        return cls(**values)


# ---- ReportRevision ----------------------------------------------------------


@dataclass(frozen=True)
class ReportRevision:
    """One exact, immutable revision of a report (``ReportRevision v1``).

    Attributes:
        report_id: Report ID (a Drive path segment).
        revision: Revision number, starting at 1.
        audience: ``internal`` or ``customer``.
        object_ref: The report object; its MD5 is required (approvals bind it).
        cited_evidence_ids / cited_observation_ids: Citations.
        derived_from: ``<report_id>@<revision>`` of the source report, if any.
        state: State at registration (``draft``, ``ready`` or
            ``blocked_audience``; later states are derived by
            :mod:`starboard_core.engagement.publication`).
        blocked_reasons: Non-empty exactly when ``state == "blocked_audience"``.
        created_at: ISO-8601 creation time.
    """

    report_id: str
    revision: int
    audience: str
    object_ref: StorageRef
    cited_evidence_ids: tuple[str, ...]
    cited_observation_ids: tuple[str, ...]
    derived_from: str | None
    state: str
    blocked_reasons: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    @property
    def requires_delivery(self) -> bool:
        """Customer reports need a verified receipt; the internal run folder is
        itself the internal delivery."""
        return self.audience == "customer"

    def __post_init__(self) -> None:
        _segment_id(self.report_id, "ReportRevision.report_id")
        _positive_int(self.revision, "ReportRevision.revision")
        _one_of(self.audience, _REPORT_AUDIENCES, "ReportRevision.audience")
        _storage_ref(self.object_ref, "ReportRevision.object_ref")
        if self.object_ref.md5 is None:
            raise ValueError("ReportRevision.object_ref needs a verified md5")
        for name in ("cited_evidence_ids", "cited_observation_ids", "blocked_reasons"):
            object.__setattr__(
                self, name, _str_tuple(getattr(self, name), f"ReportRevision.{name}")
            )
        if self.derived_from is not None and (
            not isinstance(self.derived_from, str)
            or not _DERIVED_FROM_RE.fullmatch(self.derived_from)
        ):
            raise ValueError(
                f"ReportRevision.derived_from must be <report_id>@<revision>, "
                f"got {self.derived_from!r}"
            )
        _one_of(self.state, _REPORT_STATES, "ReportRevision.state")
        if (self.state == "blocked_audience") != bool(self.blocked_reasons):
            raise ValueError(
                "ReportRevision.blocked_reasons must be non-empty exactly when "
                "state is blocked_audience"
            )
        _check_timestamp(self.created_at, "ReportRevision.created_at")

    def to_dict(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["object_ref"] = self.object_ref.to_dict()
        for name in ("cited_evidence_ids", "cited_observation_ids", "blocked_reasons"):
            data[name] = list(getattr(self, name))
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReportRevision:
        _check_version(data, "ReportRevision")
        _reject_credentials(data, "ReportRevision")
        _require(data, "ReportRevision", *_required_fields(cls))
        values = {f.name: data[f.name] for f in fields(cls) if f.name in data}
        values["object_ref"] = StorageRef.from_dict(data["object_ref"])
        for name in ("cited_evidence_ids", "cited_observation_ids", "blocked_reasons"):
            values[name] = tuple(data[name])
        return cls(**values)


# ---- Approval ----------------------------------------------------------------


@dataclass(frozen=True)
class Approval:
    """Approval bound to one exact report revision and its MD5 (``Approval v1``).

    The approver is recorded; approval authority is policy, not code (D-21).
    """

    approval_id: str
    report_id: str
    revision: int
    object_md5: str
    approver_principal_id: str
    approved_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _segment_id(self.approval_id, "Approval.approval_id")
        _segment_id(self.report_id, "Approval.report_id")
        _positive_int(self.revision, "Approval.revision")
        _check_md5(self.object_md5, "Approval.object_md5")
        _non_empty(self.approver_principal_id, "Approval.approver_principal_id")
        _not_email(self.approver_principal_id, "Approval.approver_principal_id")
        _check_timestamp(self.approved_at, "Approval.approved_at")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Approval:
        _check_version(data, "Approval")
        _reject_credentials(data, "Approval")
        _require(data, "Approval", *_required_fields(cls))
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


# ---- DeliveryReceipt ---------------------------------------------------------


@dataclass(frozen=True)
class DeliveryReceipt:
    """Record of one delivery of an exact report revision (``DeliveryReceipt v1``).

    Drive kinds (``drive``, ``google_doc``, ``slides``) are verified by a
    ``get``; Slack cannot be read back, so a Slack receipt is never verified
    (D-22).
    """

    receipt_id: str
    report_id: str
    revision: int
    object_md5: str
    channel: str
    destination_id: str
    delivered_object_id: str
    delivered_revision: str | None
    verified: bool
    delivered_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _segment_id(self.receipt_id, "DeliveryReceipt.receipt_id")
        _segment_id(self.report_id, "DeliveryReceipt.report_id")
        _positive_int(self.revision, "DeliveryReceipt.revision")
        _check_md5(self.object_md5, "DeliveryReceipt.object_md5")
        _one_of(self.channel, _CHANNELS, "DeliveryReceipt.channel")
        _non_empty(self.destination_id, "DeliveryReceipt.destination_id")
        _non_empty(self.delivered_object_id, "DeliveryReceipt.delivered_object_id")
        if self.delivered_revision is not None:
            _non_empty(self.delivered_revision, "DeliveryReceipt.delivered_revision")
        _check_bool(self.verified, "DeliveryReceipt.verified")
        if self.channel == "slack" and self.verified:
            raise ValueError("a slack DeliveryReceipt cannot be verified (D-22)")
        _check_timestamp(self.delivered_at, "DeliveryReceipt.delivered_at")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DeliveryReceipt:
        _check_version(data, "DeliveryReceipt")
        _reject_credentials(data, "DeliveryReceipt")
        _require(data, "DeliveryReceipt", *_required_fields(cls))
        return cls(**{f.name: data[f.name] for f in fields(cls) if f.name in data})


# ---- BaselineSelection -------------------------------------------------------

_SELECTED_KEYS = frozenset(
    {"key", "current_observation_id", "baseline_observation_id", "comparison"}
)
_REJECTED_KEYS = frozenset(
    {"key", "candidate_observation_id", "candidate_run_id", "interval", "reason"}
)
_UNAVAILABLE_KEYS = frozenset({"registration_id", "reason"})


def _check_entries(entries: tuple[Any, ...], keys: frozenset[str], name: str) -> None:
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != keys:
            raise ValueError(f"{name} entries need exactly the keys {sorted(keys)}")
        if "key" in entry:
            key = entry["key"]
            if not isinstance(key, tuple) or not key:
                raise ValueError(
                    f"{name}[].key must be a non-empty sequence of strings"
                )
            for part in key:
                if not isinstance(part, str):
                    raise ValueError(f"{name}[].key must contain strings")


@dataclass(frozen=True)
class BaselineSelection:
    """Per-observation baseline selection of a run (``BaselineSelection v1``).

    Attributes:
        run_id: The current run.
        selected: ``{key, current_observation_id, baseline_observation_id,
            comparison}`` per comparison key (IDs may be ``None``).
        rejected: ``{key, candidate_observation_id, candidate_run_id, interval,
            reason}`` per ineligible candidate (``interval`` is the candidate's
            ``{start, end}``).
        unavailable: ``{registration_id, reason}`` per unreadable registration
            (never treated as a baseline, D-19).
        reporting_interval: ``(start, end)`` of the current run.
        computed_at: ISO-8601 computation time.
    """

    run_id: str
    selected: tuple[Mapping[str, Any], ...]
    rejected: tuple[Mapping[str, Any], ...]
    unavailable: tuple[Mapping[str, Any], ...]
    reporting_interval: tuple[str, str]
    computed_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"BaselineSelection.run_id is not a valid run ID: {self.run_id!r}"
            )
        for name, keys in (
            ("selected", _SELECTED_KEYS),
            ("rejected", _REJECTED_KEYS),
            ("unavailable", _UNAVAILABLE_KEYS),
        ):
            entries = _freeze(tuple(getattr(self, name)))
            _check_entries(entries, keys, f"BaselineSelection.{name}")
            _reject_credentials(entries, f"BaselineSelection.{name}")
            object.__setattr__(self, name, entries)
        for entry in self.selected:
            _one_of(
                entry["comparison"],
                _COMPARISONS,
                "BaselineSelection.selected[].comparison",
            )
        for entry in self.unavailable:
            _non_empty(
                entry["registration_id"],
                "BaselineSelection.unavailable[].registration_id",
            )
        interval = tuple(self.reporting_interval)
        if len(interval) != 2:
            raise ValueError(
                "BaselineSelection.reporting_interval must be (start, end)"
            )
        for value in interval:
            _check_timestamp(value, "BaselineSelection.reporting_interval")
        object.__setattr__(self, "reporting_interval", interval)
        _check_timestamp(self.computed_at, "BaselineSelection.computed_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "selected": _thaw(self.selected),
            "rejected": _thaw(self.rejected),
            "unavailable": _thaw(self.unavailable),
            "reporting_interval": list(self.reporting_interval),
            "computed_at": self.computed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BaselineSelection:
        _check_version(data, "BaselineSelection")
        _require(data, "BaselineSelection", *_required_fields(cls))
        return cls(
            run_id=data["run_id"],
            selected=tuple(data["selected"]),
            rejected=tuple(data["rejected"]),
            unavailable=tuple(data["unavailable"]),
            reporting_interval=cast(tuple[str, str], tuple(data["reporting_interval"])),
            computed_at=data["computed_at"],
        )


# ---- FamilyRead / HealthRead -------------------------------------------------

_ACQUISITION_REQUEST_KEYS = frozenset({"owner_role", "missing", "command", "placeholders"})
#: The only placeholder a printed command may hold (``<warehouse_id>``: the run
#: does not know the SQL warehouse of a public command).
_COMMAND_PLACEHOLDERS = frozenset({"warehouse_id"})
_PLACEHOLDER_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_-]*)>")


def _placeholders(value: Any, commands: Sequence[str], name: str) -> tuple[str, ...]:
    """``value``: exactly the placeholders ``commands`` print (``warehouse_id`` only)."""
    names = _code_tuple(value, name)
    printed = {m for c in commands for m in _PLACEHOLDER_RE.findall(c)}
    unknown = printed - _COMMAND_PLACEHOLDERS
    if unknown:
        raise ValueError(f"{name}: commands print unsupported placeholders {sorted(unknown)}")
    if set(names) != printed or len(names) != len(set(names)):
        raise ValueError(
            f"{name} must list exactly the printed placeholders {sorted(printed)}, got {names!r}"
        )
    return names


def _acquisition_request(value: Any, name: str) -> Mapping[str, Any]:
    request = _exact_keys(value, _ACQUISITION_REQUEST_KEYS, name)
    if request["owner_role"] != "operator":
        raise ValueError(
            f"{name}.owner_role must be 'operator', got {request['owner_role']!r}"
        )
    missing = _code_tuple(request["missing"], f"{name}.missing")
    if not missing:
        raise ValueError(f"{name}.missing must name at least one query or template ID")
    _check_command(request["command"], f"{name}.command")
    _placeholders(request["placeholders"], [request["command"]], f"{name}.placeholders")
    return cast(Mapping[str, Any], _freeze(request))


@dataclass(frozen=True)
class FamilyRead:
    """One health family's read for a run (spec §B3, D3-6).

    Attributes:
        family: One of the six health families, or ``unclassified``.
        assessment: ``assessed`` or ``unknown``; ``unknown`` iff coverage is ``unknown``.
        coverage: ``complete``, ``partial`` or ``unknown``.
        severity: Max active/watch finding severity, ``none``; ``None`` iff unknown.
        observation_ids / finding_ids / change_ids: Support for the read.
        uncertainty: Short codes (``per_job_cap_25``, ``verify_limit_reached`` ...).
        unknown_reason: A code, required iff unknown.
        acquisition_request: ``{owner_role: "operator", missing, command}``,
            required iff unknown or partial (optional for ``unclassified``, and
            for a read no command recovers: every ``uncertainty`` code is
            ``suppressed:*`` or ``evidence_capped``, and an unknown read's
            ``unknown_reason`` is ``suppressed:*``).
    """

    family: str
    assessment: str
    coverage: str
    severity: str | None
    observation_ids: tuple[str, ...]
    finding_ids: tuple[str, ...]
    change_ids: tuple[str, ...]
    uncertainty: tuple[str, ...]
    unknown_reason: str | None
    acquisition_request: Mapping[str, Any] | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _one_of(self.family, _FINDING_FAMILIES, "FamilyRead.family")
        _one_of(self.assessment, _ASSESSMENTS, "FamilyRead.assessment")
        _one_of(self.coverage, _COVERAGES, "FamilyRead.coverage")
        unknown = self.assessment == "unknown"
        if unknown != (self.coverage == "unknown"):
            raise ValueError(
                "FamilyRead.assessment is 'unknown' iff coverage is 'unknown', got "
                f"{self.assessment!r} / {self.coverage!r}"
            )
        if unknown:
            if self.severity is not None:
                raise ValueError("an unknown FamilyRead has no severity")
            _code(self.unknown_reason, "FamilyRead.unknown_reason")
        else:
            _severity(self.severity, "FamilyRead.severity", optional=False)
            if self.unknown_reason is not None:
                raise ValueError("an assessed FamilyRead has no unknown_reason")
        needs_request = self.coverage in ("unknown", "partial")
        # A read whose every gap no command recovers (a suppressed rule, capped
        # evidence) has nothing to acquire: no request.
        nothing_to_acquire = (
            bool(self.uncertainty)
            and all(unrecoverable_gap(c) for c in self.uncertainty)
            and (not unknown or str(self.unknown_reason).startswith("suppressed:"))
        )
        if self.acquisition_request is None:
            if needs_request and self.family != UNCLASSIFIED and not nothing_to_acquire:
                raise ValueError(
                    f"FamilyRead {self.family!r} with coverage {self.coverage!r} needs an "
                    "acquisition_request"
                )
        else:
            if not needs_request:
                raise ValueError("a complete FamilyRead has no acquisition_request")
            object.__setattr__(
                self,
                "acquisition_request",
                _acquisition_request(
                    self.acquisition_request, "FamilyRead.acquisition_request"
                ),
            )
        for name, regex in (
            ("observation_ids", _OBSERVATION_ID_RE),
            ("finding_ids", _FINDING_ID_RE),
            ("change_ids", _CHANGE_ID_RE),
        ):
            object.__setattr__(
                self, name, _id_tuple(getattr(self, name), regex, f"FamilyRead.{name}")
            )
        object.__setattr__(
            self, "uncertainty", _code_tuple(self.uncertainty, "FamilyRead.uncertainty")
        )

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FamilyRead:
        return cast(
            FamilyRead,
            _record_from_dict(
                cls,
                data,
                "FamilyRead",
                observation_ids=tuple,
                finding_ids=tuple,
                change_ids=tuple,
                uncertainty=tuple,
            ),
        )


@dataclass(frozen=True)
class HealthRead:
    """Per-run health read over the six families (``HealthRead v1``, spec §B3).

    There is no aggregate score and no "healthy" label (D3-6). ``verdict`` is
    ``insufficient_evidence`` iff no family is assessed (D3-7).

    Attributes:
        run_id / account_key / workspace_id: Scope.
        reporting_interval_start / reporting_interval_end: The run's interval.
        families: Exactly the six health families, in :data:`FAMILIES` order.
        verdict: ``health_read`` or ``insufficient_evidence``.
        assessed_count: Number of assessed families.
        top_concern_finding_ids: Finding IDs, most severe first.
        material_unknowns: The unknown families, in family order.
        unclassified: Findings of unmapped rules; always unknown, never counted.
        method_version: ``health_read_v1``.
    """

    run_id: str
    account_key: str
    workspace_id: str
    reporting_interval_start: str
    reporting_interval_end: str
    families: tuple[FamilyRead, ...]
    verdict: str
    assessed_count: int
    top_concern_finding_ids: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    unclassified: FamilyRead | None = None
    method_version: str = HEALTH_METHOD_VERSION
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not is_run_id(self.run_id):
            raise ValueError(
                f"HealthRead.run_id is not a valid run ID: {self.run_id!r}"
            )
        _non_empty(self.account_key, "HealthRead.account_key")
        _non_empty(self.workspace_id, "HealthRead.workspace_id")
        _interval(
            self.reporting_interval_start,
            self.reporting_interval_end,
            "HealthRead.reporting_interval",
        )
        if self.method_version != HEALTH_METHOD_VERSION:
            raise ValueError(
                f"HealthRead.method_version must be {HEALTH_METHOD_VERSION!r}, "
                f"got {self.method_version!r}"
            )
        families = tuple(self.families)
        if not all(isinstance(f, FamilyRead) for f in families):
            raise TypeError("HealthRead.families must contain FamilyRead values")
        if tuple(f.family for f in families) != _HEALTH_FAMILIES:
            raise ValueError(
                f"HealthRead.families must be exactly {_HEALTH_FAMILIES} in order, got "
                f"{tuple(f.family for f in families)}"
            )
        object.__setattr__(self, "families", families)
        _one_of(self.verdict, _VERDICTS, "HealthRead.verdict")
        _non_negative_int(self.assessed_count, "HealthRead.assessed_count")
        assessed = sum(f.assessment == "assessed" for f in families)
        if self.assessed_count != assessed:
            raise ValueError(
                f"HealthRead.assessed_count must be {assessed}, got {self.assessed_count}"
            )
        expected_verdict = "insufficient_evidence" if assessed == 0 else "health_read"
        if self.verdict != expected_verdict:
            raise ValueError(
                f"HealthRead.verdict must be {expected_verdict!r} with {assessed} "
                "assessed families"
            )
        unknowns = tuple(f.family for f in families if f.assessment == "unknown")
        if tuple(self.material_unknowns) != unknowns:
            raise ValueError(
                f"HealthRead.material_unknowns must be {unknowns}, got "
                f"{tuple(self.material_unknowns)}"
            )
        object.__setattr__(self, "material_unknowns", unknowns)
        object.__setattr__(
            self,
            "top_concern_finding_ids",
            _id_tuple(
                self.top_concern_finding_ids,
                _FINDING_ID_RE,
                "HealthRead.top_concern_finding_ids",
            ),
        )
        unc = self.unclassified
        if unc is not None:
            if not isinstance(unc, FamilyRead):
                raise TypeError("HealthRead.unclassified must be a FamilyRead or None")
            if (
                unc.family != UNCLASSIFIED
                or unc.assessment != "unknown"
                or unc.unknown_reason != "rule_family_unclassified"
            ):
                raise ValueError(
                    "HealthRead.unclassified must be family 'unclassified', assessment "
                    "'unknown', unknown_reason 'rule_family_unclassified'"
                )

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> HealthRead:
        return cast(
            HealthRead,
            _record_from_dict(
                cls,
                data,
                "HealthRead",
                families=lambda v: tuple(FamilyRead.from_dict(f) for f in v),
                unclassified=lambda v: None if v is None else FamilyRead.from_dict(v),
                top_concern_finding_ids=tuple,
                material_unknowns=tuple,
            ),
        )


# ---- Play --------------------------------------------------------------------

#: ``failed_runs`` / ``failed_run_dbus``: job-failure plays only, both set or both
#: ``None``; ``exposure_dbus``: the list-price DBU estimate of the finding's
#: evidence over the window; ``exposure_dbus_per_day``: a run-rate (DBU/day, e.g.
#: a spend step change) — never summed with window totals; at most one of the two.
_EXPOSURE_KEYS = frozenset(
    {"failed_runs", "failed_run_dbus", "exposure_dbus", "exposure_dbus_per_day"}
)
_FOLLOW_UP_KEYS = frozenset({"template", "params", "success_criterion"})
_ACQUIRE_PLAY = "acquire_family_evidence"


def _exposure(value: Any, name: str) -> Mapping[str, Any]:
    exposure = _exact_keys(value, _EXPOSURE_KEYS, name)
    if exposure["failed_runs"] is not None:
        _non_negative_int(exposure["failed_runs"], f"{name}.failed_runs")
    for key in ("failed_run_dbus", "exposure_dbus", "exposure_dbus_per_day"):
        dbus = _number(exposure[key], f"{name}.{key}", optional=True)
        if dbus is not None and dbus < 0:
            raise ValueError(f"{name}.{key} must be >= 0, got {dbus!r}")
    if exposure["failed_run_dbus"] is not None and exposure["failed_runs"] is None:
        raise ValueError(f"{name}.failed_run_dbus needs failed_runs")
    if exposure["exposure_dbus"] is not None and exposure["exposure_dbus_per_day"] is not None:
        raise ValueError(f"{name}: exposure_dbus and exposure_dbus_per_day are exclusive")
    return cast(Mapping[str, Any], _freeze(exposure))


def _follow_up_check(value: Any, name: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    check = _exact_keys(value, _FOLLOW_UP_KEYS, name)
    _non_empty(check["template"], f"{name}.template")
    if not isinstance(check["params"], Mapping):
        raise ValueError(f"{name}.params must be a mapping")
    _reject_credentials(check["params"], f"{name}.params")
    _non_empty(check["success_criterion"], f"{name}.success_criterion")
    _check_no_email_or_credential(
        check["success_criterion"], f"{name}.success_criterion"
    )
    return cast(Mapping[str, Any], _freeze(check))


@dataclass(frozen=True)
class Play:
    """A candidate next interaction for a finding (``Play v1``, spec §B4, D3-9).

    The host may only set ``host_rank`` / ``host_reorder_reason`` (together) and
    the host-set labels; ``reason``, ``exposure`` and ``evidence_strength`` come
    from ``play_rules_v1``. ``acquire_family_evidence`` plays cite no finding.
    ``placeholders`` lists exactly the placeholders ``next_commands`` print (only
    ``warehouse_id``: the run does not know the SQL warehouse); every other
    command runs as printed.
    """

    play_id: str
    play_code: str
    finding_ids: tuple[str, ...]
    interaction_type: str
    owner_role: str
    audience_class: str
    target_entity_kind: str
    target_entity_id: str
    reason: str
    urgency: str
    exposure: Mapping[str, Any]
    evidence_strength: str
    missing_evidence: tuple[str, ...]
    next_step_kind: str
    next_commands: tuple[str, ...]
    follow_up_check: Mapping[str, Any] | None
    run_id: str
    owner_label: str | None = None
    criticality: str = "unknown"
    reversibility: str = "unknown"
    owner_availability: str = "unknown"
    rule_id: str = PLAY_RULE_ID
    host_rank: int | None = None
    host_reorder_reason: str | None = None
    placeholders: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _id(self.play_id, _PLAY_ID_RE, "Play.play_id")
        _one_of(self.play_code, _PLAY_CODES, "Play.play_code")
        ids = _id_tuple(self.finding_ids, _FINDING_ID_RE, "Play.finding_ids")
        if not ids and self.play_code != _ACQUIRE_PLAY:
            raise ValueError("Play.finding_ids must cite at least one finding")
        object.__setattr__(self, "finding_ids", ids)
        _one_of(self.interaction_type, _INTERACTION_TYPES, "Play.interaction_type")
        _one_of(self.owner_role, _OWNER_ROLES, "Play.owner_role")
        _one_of(self.audience_class, _AUDIENCE_CLASSES, "Play.audience_class")
        _one_of(self.target_entity_kind, ENTITY_KINDS, "Play.target_entity_kind")
        _non_empty(self.target_entity_id, "Play.target_entity_id")
        _check_free_text(self.reason, "Play.reason")
        _one_of(self.urgency, _URGENCIES, "Play.urgency")
        object.__setattr__(self, "exposure", _exposure(self.exposure, "Play.exposure"))
        _one_of(self.evidence_strength, _EVIDENCE_STRENGTHS, "Play.evidence_strength")
        object.__setattr__(
            self,
            "missing_evidence",
            _code_tuple(self.missing_evidence, "Play.missing_evidence"),
        )
        _one_of(self.next_step_kind, _NEXT_STEP_KINDS, "Play.next_step_kind")
        commands = _str_tuple(self.next_commands, "Play.next_commands")
        if not commands:
            raise ValueError("Play.next_commands must hold at least one command")
        for command in commands:
            _check_command(command, "Play.next_commands[]")
        object.__setattr__(self, "next_commands", commands)
        object.__setattr__(
            self,
            "placeholders",
            _placeholders(self.placeholders, commands, "Play.placeholders"),
        )
        object.__setattr__(
            self,
            "follow_up_check",
            _follow_up_check(self.follow_up_check, "Play.follow_up_check"),
        )
        if not is_run_id(self.run_id):
            raise ValueError(f"Play.run_id is not a valid run ID: {self.run_id!r}")
        _check_optional_free_text(self.owner_label, "Play.owner_label")
        _one_of(self.criticality, _CRITICALITIES, "Play.criticality")
        _code(self.reversibility, "Play.reversibility")
        _code(self.owner_availability, "Play.owner_availability")
        if self.rule_id != PLAY_RULE_ID:
            raise ValueError(
                f"Play.rule_id must be {PLAY_RULE_ID!r}, got {self.rule_id!r}"
            )
        if (self.host_rank is None) != (self.host_reorder_reason is None):
            raise ValueError("Play.host_rank and host_reorder_reason are set together")
        if self.host_rank is not None:
            _positive_int(self.host_rank, "Play.host_rank")
            _check_free_text(self.host_reorder_reason, "Play.host_reorder_reason")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Play:
        return cast(
            Play,
            _record_from_dict(
                cls,
                data,
                "Play",
                finding_ids=tuple,
                missing_evidence=tuple,
                next_commands=tuple,
                placeholders=tuple,
            ),
        )


# ---- ChangeInput -------------------------------------------------------------

_CO_MOVEMENT_KEYS = frozenset({"observation_id", "metric", "delta", "unit"})
_CONTEXT_EVENT_KEYS = frozenset({"kind", "ref", "at"})


def _co_movement(value: Any, name: str) -> Any:
    if (
        not isinstance(value, Mapping)
        or not {"metric", "unit"} <= set(value)
        or (set(value) - _CO_MOVEMENT_KEYS)
    ):
        raise ValueError(
            f"{name} needs metric and unit (and optionally observation_id, delta), "
            f"got {value!r}"
        )
    _non_empty(value["metric"], f"{name}.metric")
    _one_of(value["unit"], UNITS, f"{name}.unit")
    if "observation_id" in value:
        _optional_id(
            value["observation_id"], _OBSERVATION_ID_RE, f"{name}.observation_id"
        )
    if "delta" in value:
        _number(value["delta"], f"{name}.delta", optional=True)
    return _freeze(value)


def _context_event(value: Any, name: str) -> Any:
    event = _exact_keys(value, _CONTEXT_EVENT_KEYS, name)
    _one_of(event["kind"], _CONTEXT_EVENT_KINDS, f"{name}.kind")
    _non_empty(event["ref"], f"{name}.ref")
    _check_no_email_or_credential(event["ref"], f"{name}.ref")
    _check_timestamp(event["at"], f"{name}.at")
    return _freeze(event)


def _source_window(value: Any, name: str) -> tuple[str, str, str]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, (list, tuple))
        or len(value) != 3
    ):
        raise ValueError(f"{name} must be (start, end, source_kind), got {value!r}")
    start, end, kind = value
    _interval(start, end, name)
    _one_of(kind, _SOURCE_KINDS, f"{name} source_kind")
    return (start, end, kind)


@dataclass(frozen=True)
class ChangeInput:
    """Measured inputs for explaining a change (``ChangeInput v1``, spec §B5, D3-11).

    Emitted only for a ``continuing`` / ``new`` / ``recovered`` pair whose baseline
    was selected. It never carries prose, and ``causality`` is the constant
    ``not_assessed``.
    """

    change_id: str
    observation_id: str
    baseline_observation_id: str
    family: str
    metric: str
    unit: str
    entity_kind: str
    entity_id: str
    baseline_value: float
    baseline_interval_start: str
    baseline_interval_end: str
    current_value: float
    current_interval_start: str
    current_interval_end: str
    delta: float
    delta_unit: str
    relative_pct: float | None
    comparison: str
    co_movements: tuple[Mapping[str, Any], ...]
    context_events: tuple[Mapping[str, Any], ...]
    source_windows: tuple[tuple[str, str, str], ...]
    evidence_ids: tuple[str, ...]
    method_version: str = CHANGE_METHOD_VERSION
    causality: str = "not_assessed"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _id(self.observation_id, _OBSERVATION_ID_RE, "ChangeInput.observation_id")
        _id(
            self.baseline_observation_id,
            _OBSERVATION_ID_RE,
            "ChangeInput.baseline_observation_id",
        )
        expected = change_id(self.observation_id, self.baseline_observation_id)
        if self.change_id != expected:
            raise ValueError(
                f"ChangeInput.change_id must be {expected!r}, got {self.change_id!r}"
            )
        _one_of(self.family, _FINDING_FAMILIES, "ChangeInput.family")
        _non_empty(self.metric, "ChangeInput.metric")
        _one_of(self.unit, UNITS, "ChangeInput.unit")
        _one_of(self.entity_kind, ENTITY_KINDS, "ChangeInput.entity_kind")
        _non_empty(self.entity_id, "ChangeInput.entity_id")
        for name in ("baseline_value", "current_value", "delta"):
            object.__setattr__(
                self, name, _number(getattr(self, name), f"ChangeInput.{name}")
            )
        object.__setattr__(
            self,
            "relative_pct",
            _number(self.relative_pct, "ChangeInput.relative_pct", optional=True),
        )
        if not math.isclose(
            self.delta,
            self.current_value - self.baseline_value,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "ChangeInput.delta must equal current_value - baseline_value"
            )
        expected_unit = "pp" if self.unit == "pct" else self.unit
        if self.delta_unit != expected_unit:
            raise ValueError(
                f"ChangeInput.delta_unit must be {expected_unit!r} for unit "
                f"{self.unit!r}, got {self.delta_unit!r}"
            )
        _interval(
            self.baseline_interval_start,
            self.baseline_interval_end,
            "ChangeInput.baseline_interval",
        )
        _interval(
            self.current_interval_start,
            self.current_interval_end,
            "ChangeInput.current_interval",
        )
        _one_of(self.comparison, _CHANGE_COMPARISONS, "ChangeInput.comparison")
        object.__setattr__(
            self,
            "co_movements",
            tuple(
                _co_movement(m, "ChangeInput.co_movements[]")
                for m in _sequence(self.co_movements, "ChangeInput.co_movements")
            ),
        )
        object.__setattr__(
            self,
            "context_events",
            tuple(
                _context_event(e, "ChangeInput.context_events[]")
                for e in _sequence(self.context_events, "ChangeInput.context_events")
            ),
        )
        object.__setattr__(
            self,
            "source_windows",
            tuple(
                _source_window(w, "ChangeInput.source_windows[]")
                for w in _sequence(self.source_windows, "ChangeInput.source_windows")
            ),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _id_tuple(self.evidence_ids, _EVIDENCE_ID_RE, "ChangeInput.evidence_ids"),
        )
        if self.method_version != CHANGE_METHOD_VERSION:
            raise ValueError(
                f"ChangeInput.method_version must be {CHANGE_METHOD_VERSION!r}, "
                f"got {self.method_version!r}"
            )
        if self.causality != "not_assessed":
            raise ValueError("ChangeInput.causality is the constant 'not_assessed'")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChangeInput:
        return cast(
            ChangeInput,
            _record_from_dict(cls, data, "ChangeInput", evidence_ids=tuple),
        )


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, (list, tuple)):
        raise TypeError(f"{name} must be a sequence, got {value!r}")
    return tuple(value)


# ---- Case --------------------------------------------------------------------

_HYPOTHESIS_KEYS = frozenset({"hypothesis_id", "statement", "status", "evidence_ids"})
_CASE_REVISION_KEYS = frozenset(
    {"revision", "run_id", "evidence_ids", "observation_ids", "gaps"}
)


def _hypothesis(value: Any, name: str) -> Any:
    h = _exact_keys(value, _HYPOTHESIS_KEYS, name)
    _segment_id(h["hypothesis_id"], f"{name}.hypothesis_id")
    _check_free_text(h["statement"], f"{name}.statement")
    _one_of(h["status"], _HYPOTHESIS_STATUSES, f"{name}.status")
    _id_tuple(h["evidence_ids"], _EVIDENCE_ID_RE, f"{name}.evidence_ids")
    return _freeze(h)


def _case_revision(value: Any, name: str) -> Any:
    r = _exact_keys(value, _CASE_REVISION_KEYS, name)
    _positive_int(r["revision"], f"{name}.revision")
    if not is_run_id(r["run_id"]):
        raise ValueError(f"{name}.run_id is not a valid run ID: {r['run_id']!r}")
    _id_tuple(r["evidence_ids"], _EVIDENCE_ID_RE, f"{name}.evidence_ids")
    _id_tuple(r["observation_ids"], _OBSERVATION_ID_RE, f"{name}.observation_ids")
    _code_tuple(r["gaps"], f"{name}.gaps")
    return _freeze(r)


@dataclass(frozen=True)
class Case:
    """An investigation opened from a finding, a clue or a Drive object (spec §B6).

    ``question`` and hypothesis statements are host free text: at most
    :data:`FREE_TEXT_MAX` characters, emails and credential-like strings rejected
    (D3-24).
    """

    case_id: str
    account_key: str
    workspace_id: str
    origin: str
    origin_ref: str
    finding_id: str
    target_entity_kind: str
    target_entity_id: str
    question: str
    hypotheses: tuple[Mapping[str, Any], ...]
    evidence_revisions: tuple[Mapping[str, Any], ...]
    state: str
    opened_run_id: str
    run_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _non_empty(self.account_key, "Case.account_key")
        _non_empty(self.workspace_id, "Case.workspace_id")
        _one_of(self.origin, _CASE_ORIGINS, "Case.origin")
        _id(self.finding_id, _FINDING_ID_RE, "Case.finding_id")
        if self.origin == "finding":
            _id(self.origin_ref, _FINDING_ID_RE, "Case.origin_ref")
            if self.origin_ref != self.finding_id:
                raise ValueError(
                    "a finding-origin Case must cite its finding as origin_ref"
                )
        elif self.origin == "clue":
            _id(self.origin_ref, _CLUE_REF_RE, "Case.origin_ref")
        else:
            _id(self.origin_ref, _DRIVE_REF_RE, "Case.origin_ref")
        for name in ("opened_run_id", "run_id"):
            if not is_run_id(getattr(self, name)):
                raise ValueError(
                    f"Case.{name} is not a valid run ID: {getattr(self, name)!r}"
                )
        _check_free_text(self.question, "Case.question")
        expected = case_id(
            self.account_key, self.origin_ref, self.opened_run_id, self.question
        )
        if self.case_id != expected:
            raise ValueError(f"Case.case_id must be {expected!r}, got {self.case_id!r}")
        _one_of(self.target_entity_kind, _CASE_TARGET_KINDS, "Case.target_entity_kind")
        _non_empty(self.target_entity_id, "Case.target_entity_id")
        hypotheses = tuple(
            _hypothesis(h, "Case.hypotheses[]")
            for h in _sequence(self.hypotheses, "Case.hypotheses")
        )
        hids = [h["hypothesis_id"] for h in hypotheses]
        if len(hids) != len(set(hids)):
            raise ValueError("Case.hypotheses must have unique hypothesis_id values")
        object.__setattr__(self, "hypotheses", hypotheses)
        revisions = tuple(
            _case_revision(r, "Case.evidence_revisions[]")
            for r in _sequence(self.evidence_revisions, "Case.evidence_revisions")
        )
        if [r["revision"] for r in revisions] != list(range(1, len(revisions) + 1)):
            raise ValueError(
                "Case.evidence_revisions must be numbered 1..n consecutively"
            )
        object.__setattr__(self, "evidence_revisions", revisions)
        _one_of(self.state, _CASE_STATES, "Case.state")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Case:
        return cast(Case, _record_from_dict(cls, data, "Case"))


# ---- ActionEvent / Action ----------------------------------------------------


@dataclass(frozen=True)
class ActionEvent:
    """One append-only event on an :class:`Action` (spec §B7)."""

    seq: int
    kind: str
    run_id: str
    at: str
    recorded_by: str
    evidence_ids: tuple[str, ...] = ()
    note: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _positive_int(self.seq, "ActionEvent.seq")
        _one_of(self.kind, _EVENT_KINDS, "ActionEvent.kind")
        if not is_run_id(self.run_id):
            raise ValueError(
                f"ActionEvent.run_id is not a valid run ID: {self.run_id!r}"
            )
        _check_timestamp(self.at, "ActionEvent.at")
        _one_of(self.recorded_by, _RECORDED_BY, "ActionEvent.recorded_by")
        object.__setattr__(
            self,
            "evidence_ids",
            _id_tuple(self.evidence_ids, _EVIDENCE_ID_RE, "ActionEvent.evidence_ids"),
        )
        _check_optional_free_text(self.note, "ActionEvent.note")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActionEvent:
        return cast(
            ActionEvent,
            _record_from_dict(cls, data, "ActionEvent", evidence_ids=tuple),
        )


@dataclass(frozen=True)
class Action:
    """A proposed next step and its lifecycle (``Action v1``, spec §B7, D3-13).

    An action originates from exactly one of a play (``play_id``, proposed by
    ``rule``) or a case (``case_id``, proposed by the host after the case's
    cause; ``verify_method`` says how its outcome will be checked).
    ``executed`` requires ``accepted``. Attribution is ``consistent_with_action``
    only when executed before the verification window and the measured outcome
    is ``improved``; no field says "caused".
    """

    action_id: str
    finding_id: str
    play_id: str | None
    case_id: str | None
    owner_role: str
    owner_label: str | None
    next_step: str
    proposal_state: str
    acceptance_state: str
    execution_state: str
    executed_at: str | None
    verification_window_start: str | None
    verification_window_end: str | None
    outcome_state: str
    outcome_observation_ids: tuple[str, ...]
    attribution: str
    events: tuple[ActionEvent, ...]
    run_id: str
    verify_method: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _id(self.action_id, _ACTION_ID_RE, "Action.action_id")
        _id(self.finding_id, _FINDING_ID_RE, "Action.finding_id")
        _optional_id(self.play_id, _PLAY_ID_RE, "Action.play_id")
        _optional_id(self.case_id, _CASE_ID_RE, "Action.case_id")
        if (self.play_id is None) == (self.case_id is None):
            raise ValueError("an Action originates from exactly one of play_id or case_id")
        _check_optional_free_text(self.verify_method, "Action.verify_method")
        _one_of(self.owner_role, _OWNER_ROLES, "Action.owner_role")
        _check_optional_free_text(self.owner_label, "Action.owner_label")
        _check_free_text(self.next_step, "Action.next_step")
        _one_of(self.proposal_state, _PROPOSAL_STATES, "Action.proposal_state")
        _one_of(self.acceptance_state, _ACCEPTANCE_STATES, "Action.acceptance_state")
        _one_of(self.execution_state, _EXECUTION_STATES, "Action.execution_state")
        _one_of(self.outcome_state, _OUTCOME_STATES, "Action.outcome_state")
        _one_of(self.attribution, _ATTRIBUTIONS, "Action.attribution")
        executed = self.execution_state == "executed"
        if executed and self.acceptance_state != "accepted":
            raise ValueError("an executed Action must be accepted first")
        if self.executed_at is not None:
            if not executed:
                raise ValueError("Action.executed_at is set only when executed")
            _check_timestamp(self.executed_at, "Action.executed_at")
        for name in ("verification_window_start", "verification_window_end"):
            if getattr(self, name) is not None:
                _check_timestamp(getattr(self, name), f"Action.{name}")
        if (
            self.verification_window_start is not None
            and self.verification_window_end is not None
        ):
            _interval(
                self.verification_window_start,
                self.verification_window_end,
                "Action.verification_window",
            )
        if self.attribution == "consistent_with_action" and not (
            executed
            and self.executed_at is not None
            and self.verification_window_start is not None
            and _parse_ts(self.executed_at) < _parse_ts(self.verification_window_start)
            and self.outcome_state == "improved"
        ):
            raise ValueError(
                "Action.attribution 'consistent_with_action' needs execution before the "
                "verification window and an improved outcome"
            )
        object.__setattr__(
            self,
            "outcome_observation_ids",
            _id_tuple(
                self.outcome_observation_ids,
                _OBSERVATION_ID_RE,
                "Action.outcome_observation_ids",
            ),
        )
        events = _sequence(self.events, "Action.events")
        if not all(isinstance(e, ActionEvent) for e in events):
            raise TypeError("Action.events must contain ActionEvent values")
        if not events:
            raise ValueError("Action.events must hold at least the proposed event")
        if [e.seq for e in events] != list(range(1, len(events) + 1)):
            raise ValueError("Action.events must be numbered 1..n consecutively")
        if events[0].kind != "proposed":
            raise ValueError("Action.events must start with a 'proposed' event")
        object.__setattr__(self, "events", events)
        if not is_run_id(self.run_id):
            raise ValueError(f"Action.run_id is not a valid run ID: {self.run_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return _record_to_dict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Action:
        return cast(
            Action,
            _record_from_dict(
                cls,
                data,
                "Action",
                outcome_observation_ids=tuple,
                events=lambda v: tuple(ActionEvent.from_dict(e) for e in v),
            ),
        )
