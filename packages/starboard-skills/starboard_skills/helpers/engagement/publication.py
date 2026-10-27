"""Publication on a run folder: ``report``, ``approve``, ``deliver`` and ``receipt``."""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ArgError,
    NotFoundError,
)
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    _ANCESTOR_LIMIT,
    _APPROVAL_RE,
    _RECEIPT_RE,
    _REPORT_REFUSED_TOPS,
    _REV_RE,
    ARTIFACT_PROPERTY,
    AUDIENCES,
    DELIVERY_PROPERTY,
    RECEIPT_CHANNELS,
    STAGED_PREFLIGHT,
    Refusal,
)
from starboard_skills.helpers.engagement._runs import (
    _append,
    _artifacts,
    _committed,
    _digest,
    _evidence_map,
    _json,
    _latest,
    _md5,
    _put_record,
    _read_ref,
    _read_staged,
    _run_command,
    _run_observations,
    _storage_ref,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.records import RunAuthorization
    from starboard_core.engagement.sink import DriveRunSink
    from starboard_core.ports.engagement_storage import EngagementStoragePort


# --------------------------------------------------------------------------- #
# Publication records
# --------------------------------------------------------------------------- #
def _publication_records(
    storage: EngagementStoragePort, objs: Mapping[str, Any]
) -> tuple[list[Any], list[Any], list[Any]]:
    """The run's report revisions, approvals and receipts, each read verified."""
    from starboard_core.engagement.records import (  # lazy – kernel dep
        Approval,
        DeliveryReceipt,
        ReportRevision,
    )
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    revs: list[Any] = []
    approvals: list[Any] = []
    receipts: list[Any] = []
    for rel in sorted(objs):
        kind: Any = None
        bucket: list[Any] = []
        if _REV_RE.fullmatch(rel):
            kind, bucket = ReportRevision, revs
        elif _APPROVAL_RE.fullmatch(rel):
            kind, bucket = Approval, approvals
        elif _RECEIPT_RE.fullmatch(rel):
            kind, bucket = DeliveryReceipt, receipts
        if kind is None:
            continue
        raw = _json(_envelope._read_verified(storage, objs[rel]), rel)
        try:
            bucket.append(kind.from_dict(raw))
        except (ValueError, TypeError, KeyError) as exc:
            raise StorageIntegrityError(f"{rel} is not a valid record ({exc})") from exc
    return revs, approvals, receipts


def _commit_publication(
    storage: EngagementStoragePort, run_folder_id: str, run_id: str
) -> tuple[Any, list[Any], list[Any], list[Any]]:
    """Recompute reports / approvals / receipts / publication into a new manifest revision."""
    from starboard_core.engagement.publication import (  # lazy – kernel dep
        publication_state,
        revision_state,
    )

    objs = _artifacts(storage, run_folder_id, run_id)
    revs, approvals, receipts = _publication_records(storage, objs)
    prev, _ = _latest(storage, run_folder_id, run_id)
    states = dict(prev.states)
    if revs:
        states["publication"] = publication_state(revs, approvals, receipts)
    changes = {
        "reports": tuple(
            {
                "report_id": r.report_id,
                "revision": r.revision,
                "audience": r.audience,
                "state": revision_state(r, approvals, receipts),
            }
            for r in sorted(revs, key=lambda r: (r.report_id, r.revision))
        ),
        "approvals": tuple(sorted(a.approval_id for a in approvals)),
        "receipts": tuple(sorted(r.receipt_id for r in receipts)),
        "states": states,
    }
    manifest, _, _ = _append(storage, run_folder_id, prev, changes)
    return manifest, revs, approvals, receipts


def _find_revision(revs: Sequence[Any], report_id: str, revision: int) -> Any:
    for r in revs:
        if r.report_id == report_id and r.revision == revision:
            return r
    raise NotFoundError(
        f"report {report_id} has no revision {revision}; register it with "
        "`engagement report` first"
    )


# --------------------------------------------------------------------------- #
# report / approve / deliver / receipt
# --------------------------------------------------------------------------- #
def cmd_report(args: argparse.Namespace) -> dict[str, Any]:
    if args.audience not in AUDIENCES:
        raise ArgError(
            f"--audience must be one of {', '.join(AUDIENCES)}; got {args.audience!r}"
        )

    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        from starboard_core.engagement.publication import (  # lazy – kernel dep
            audience_gate,
        )
        from starboard_core.engagement.records import ReportRevision
        from starboard_core.engagement.sink import validate_relpath

        rf = sink.run_folder_id
        rel = validate_relpath(args.path)
        if rel.split("/", 1)[0].casefold() in _REPORT_REFUSED_TOPS:
            raise Refusal(
                "REPORT_REFUSED",
                f"{rel!r} is under raw/ or evidence/; a report body must be a "
                "deliverable, not captured data",
            )
        cited_ev = tuple(dict.fromkeys(args.cite_evidence or ()))
        cited_obs = tuple(dict.fromkeys(args.cite_observation or ()))
        if args.audience == "customer" and not (cited_ev or cited_obs):
            raise Refusal(
                "REPORT_REFUSED",
                "a customer report needs at least one citation "
                "(--cite-evidence or --cite-observation)",
            )
        objs = _artifacts(storage, rf, auth.run_id)
        obj = objs.get(rel)
        if obj is None:
            raise NotFoundError(
                f"{rel!r} is not an artifact of run {auth.run_id}; write the report "
                "through the run sink first"
            )
        evidence = _evidence_map(storage, objs)
        if args.audience == "customer" and any(
            ref.storage_ref.path == rel and ref.audience_class != "customer_shareable"
            for ref in evidence.values()
        ):
            raise Refusal(
                "REPORT_REFUSED",
                f"{rel!r} is recorded as internal-sourced evidence; it cannot be "
                "the body of a customer report",
            )
        _envelope._read_verified(storage, obj)
        if not _committed(storage, rf, rel, obj.md5):
            raise Refusal(
                "UNCOMMITTED_ARTIFACT",
                f"{rel!r} (md5 {obj.md5}) is not bound by the "
                "latest committed manifest; commit its stage first",
            )
        object_ref = _storage_ref(rel, obj)
        revs, _, _ = _publication_records(storage, objs)
        source = _resolve_derived_from(revs, args.report_id, args.derived_from)
        mine = [r for r in revs if r.report_id == args.report_id]
        for r in mine:
            if (
                r.object_ref.path == rel
                and r.object_ref.md5 == object_ref.md5
                and r.audience == args.audience
                and r.cited_evidence_ids == cited_ev
                and r.cited_observation_ids == cited_obs
                and r.derived_from == args.derived_from
            ):
                manifest, _, _, _ = _commit_publication(storage, rf, auth.run_id)
                return _report_data(auth, rf, r, manifest, source, unchanged=True)
        try:
            draft = ReportRevision(
                report_id=args.report_id,
                revision=max((r.revision for r in mine), default=0) + 1,
                audience=args.audience,
                object_ref=object_ref,
                cited_evidence_ids=cited_ev,
                cited_observation_ids=cited_obs,
                derived_from=args.derived_from,
                state="ready",
                blocked_reasons=(),
                created_at=_envelope._now(),
            )
        except ValueError as exc:
            raise ArgError(str(exc)) from exc
        observations = {o.observation_id: o for o in _run_observations(storage, objs)}
        state, reasons = audience_gate(
            draft,
            evidence,
            observations,
            source_mode=auth.source_mode,
            source_revision=source,
        )
        rev = dataclasses.replace(draft, state=state, blocked_reasons=reasons)
        _put_record(
            sink, f"reports/{rev.report_id}/rev-{rev.revision:06d}.json", rev.to_dict()
        )
        manifest, _, _, _ = _commit_publication(storage, rf, auth.run_id)
        return _report_data(auth, rf, rev, manifest, source, unchanged=False)

    return _run_command(args, body, stage="publication")


def _resolve_derived_from(
    revs: Sequence[Any], report_id: str, derived_from: str | None
) -> Any:
    """The exact source revision ``derived_from`` names in this run, or ``None``.

    A self-reference or a ``<report_id>@<rev>`` with no such revision in the
    run is ``REPORT_REFUSED`` (D4-6). A malformed value is left to
    ``ReportRevision`` validation (``USAGE``).
    """
    if derived_from is None:
        return None
    src_id, sep, src_rev = derived_from.rpartition("@")
    if not sep or not src_rev.isdigit():
        return None
    if src_id == report_id:
        raise Refusal(
            "REPORT_REFUSED",
            f"--derived-from {derived_from!r} names this report; a derivative is "
            "its own report_id derived from another report's revision",
        )
    for r in revs:
        if r.report_id == src_id and r.revision == int(src_rev):
            return r
    raise Refusal(
        "REPORT_REFUSED",
        f"--derived-from {derived_from!r} is not a report revision of this run; "
        "register the source with `engagement report` first",
    )


def _report_data(
    auth: RunAuthorization,
    rf: str,
    rev: Any,
    manifest: Any,
    source: Any,
    *,
    unchanged: bool,
) -> dict[str, Any]:
    from starboard_core.engagement.publication import (  # lazy – kernel dep
        allowed_audiences,
    )

    allowed = allowed_audiences(auth.source_mode)
    return {
        "run_id": auth.run_id,
        "run_folder_id": rf,
        "report_id": rev.report_id,
        "revision": rev.revision,
        "audience": rev.audience,
        "state": rev.state,
        "blocked_reasons": list(rev.blocked_reasons),
        "object_ref": rev.object_ref.to_dict(),
        "unchanged": unchanged,
        "manifest_revision": manifest.revision,
        "publication": manifest.states.get("publication"),
        "allowed_audiences": list(allowed),
        "derived_from_revision": None
        if source is None
        else {
            "report_id": source.report_id,
            "revision": source.revision,
            "audience": source.audience,
            "state": source.state,
            "object_md5": source.object_ref.md5,
        },
    }


def _run_unattended(storage: EngagementStoragePort, auth: RunAuthorization) -> bool:
    """Whether the run is unattended, from its staged preflight. Fails closed (True)."""
    from starboard_core.ports.engagement_storage import (  # lazy – kernel dep
        StorageAuthError,
        StorageError,
    )

    staging_id = None if auth.drive is None else auth.drive.preflight_folder_id
    if not staging_id:
        return True
    try:
        pre = _read_staged(
            storage, staging_id, STAGED_PREFLIGHT, f"preflight:{auth.run_id}"
        )
    except StorageAuthError:
        raise
    except (StorageError, ValueError):  # an unreadable record counts as unattended
        return True
    if not isinstance(pre, dict):
        return True
    return bool(pre.get("unattended", True))


def _existing_record(
    storage: EngagementStoragePort, objs: Mapping[str, Any], rel: str, kind: Any
) -> Any:
    from starboard_core.ports.engagement_storage import (  # lazy – kernel dep
        StorageIntegrityError,
    )

    obj = objs.get(rel)
    if obj is None:
        return None
    raw = _json(_envelope._read_verified(storage, obj), rel)
    try:
        return kind.from_dict(raw)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise StorageIntegrityError(f"{rel} is not a valid record ({exc})") from exc


def cmd_approve(args: argparse.Namespace) -> dict[str, Any]:
    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        from starboard_core.engagement.publication import (  # lazy – kernel dep
            approval_matches,
            can_approve,
            revision_state,
        )
        from starboard_core.engagement.records import Approval

        rf = sink.run_folder_id
        objs = _artifacts(storage, rf, auth.run_id)
        revs, approvals, receipts = _publication_records(storage, objs)
        rev = _find_revision(revs, args.report_id, args.revision)
        held = next((a for a in approvals if approval_matches(rev, a)), None)
        if held is None:
            unattended = _run_unattended(storage, auth)
            if not can_approve(rev, unattended=unattended):
                why = (
                    "an unattended run cannot approve; an attended operator must approve"
                    if unattended
                    else f"revision {rev.revision} of {rev.report_id} is {rev.state}, not ready"
                )
                raise Refusal("APPROVAL_REFUSED", f"approval refused: {why}")
            approval_id = "apr_" + _digest(
                rev.report_id, str(rev.revision), rev.object_ref.md5
            )
            held = Approval(
                approval_id=approval_id,
                report_id=rev.report_id,
                revision=rev.revision,
                object_md5=rev.object_ref.md5,
                approver_principal_id=storage.principal_id(),
                approved_at=_envelope._now(),
            )
            _put_record(
                sink,
                f"reports/{rev.report_id}/approvals/{approval_id}.json",
                held.to_dict(),
            )
            approvals.append(held)
        manifest, _, _, _ = _commit_publication(storage, rf, auth.run_id)
        return {
            "run_id": auth.run_id,
            "run_folder_id": rf,
            "report_id": rev.report_id,
            "revision": rev.revision,
            "approval_id": held.approval_id,
            "state": revision_state(rev, approvals, receipts),
            "manifest_revision": manifest.revision,
            "publication": manifest.states.get("publication"),
        }

    return _run_command(args, body, stage="publication")


def _record_receipt(
    storage: EngagementStoragePort,
    sink: DriveRunSink,
    auth: RunAuthorization,
    rev: Any,
    receipt: Any,
) -> tuple[Any, Any]:
    """Write the receipt once, then commit the publication state."""
    from starboard_core.engagement.records import DeliveryReceipt  # lazy – kernel dep

    rf = sink.run_folder_id
    rel = f"reports/{rev.report_id}/receipts/{receipt.receipt_id}.json"
    objs = _artifacts(storage, rf, auth.run_id)
    held = _existing_record(storage, objs, rel, DeliveryReceipt)
    if held is None:
        _put_record(sink, rel, receipt.to_dict())
        held = receipt
    manifest, _, _, _ = _commit_publication(storage, rf, auth.run_id)
    return held, manifest


def _deliverable(
    storage: EngagementStoragePort,
    auth: RunAuthorization,
    sink: DriveRunSink,
    args: argparse.Namespace,
) -> tuple[Any, list[Any], list[Any]]:
    from starboard_core.engagement.publication import can_deliver  # lazy – kernel dep

    objs = _artifacts(storage, sink.run_folder_id, auth.run_id)
    revs, approvals, receipts = _publication_records(storage, objs)
    rev = _find_revision(revs, args.report_id, args.revision)
    if not can_deliver(rev, approvals):
        why = (
            f"it is {rev.state}"
            if rev.state in ("draft", "blocked_audience")
            else "a customer report needs an approval of this exact revision first "
            "(`engagement approve`)"
        )
        raise Refusal(
            "DELIVERY_REFUSED",
            f"revision {rev.revision} of {rev.report_id} cannot be delivered: {why}",
        )
    return rev, approvals, receipts


def cmd_deliver(args: argparse.Namespace) -> dict[str, Any]:
    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        from starboard_core.engagement.folders import (  # lazy – kernel dep
            PINNED_INTERNAL_DOMAINS,
            classify_access,
        )
        from starboard_core.engagement.publication import revision_state
        from starboard_core.engagement.records import DeliveryReceipt
        from starboard_core.engagement.staging import verify_bytes
        from starboard_core.ports.engagement_storage import StorageIntegrityError

        dest = (args.destination_folder_id or "").strip()
        if not dest:
            raise ArgError("--destination-folder-id is required")
        rev, approvals, _ = _deliverable(storage, auth, sink, args)
        access = classify_access(storage.inspect_access(dest), PINNED_INTERNAL_DOMAINS)
        if access != "internal_only":
            raise Refusal(
                "DELIVERY_REFUSED",
                f"destination {dest} is {access}, not internal-only; the helper only "
                "delivers into internal folders (share from there deliberately)",
            )
        content = _read_ref(storage, rev.object_ref)
        name = PurePosixPath(rev.object_ref.path).name
        key = f"delivery:{auth.run_id}:{rev.report_id}@{rev.revision}"
        existing = [
            o
            for o in storage.list_children(dest, name=name)
            if not o.is_folder and o.properties.get(DELIVERY_PROPERTY) == key
        ]
        if len(existing) > 1:
            raise StorageIntegrityError(
                f"{len(existing)} deliveries of {key} in {dest}; reconcile in Drive"
            )
        if (
            existing
            and existing[0].md5 == _md5(content)
            and existing[0].size == len(content)
        ):
            delivered = existing[0]
        elif existing:
            delivered = storage.update_stream(
                existing[0].id, rev.object_ref.mime_type, [content]
            )
        else:
            delivered = storage.put_stream(
                dest,
                name,
                rev.object_ref.mime_type,
                [content],
                properties={DELIVERY_PROPERTY: key},
            )
        verify_bytes(storage, delivered, content)
        receipt = DeliveryReceipt(
            receipt_id="rcp_"
            + _digest(
                rev.report_id,
                str(rev.revision),
                rev.object_ref.md5,
                "drive",
                delivered.id,
            ),
            report_id=rev.report_id,
            revision=rev.revision,
            object_md5=rev.object_ref.md5,
            channel="drive",
            destination_id=dest,
            delivered_object_id=delivered.id,
            delivered_revision=delivered.revision,
            verified=True,
            delivered_at=_envelope._now(),
        )
        held, manifest = _record_receipt(storage, sink, auth, rev, receipt)
        return {
            "run_id": auth.run_id,
            "run_folder_id": sink.run_folder_id,
            "report_id": rev.report_id,
            "revision": rev.revision,
            "receipt_id": held.receipt_id,
            "delivered_object_id": delivered.id,
            "delivered_link": delivered.web_link,
            "state": revision_state(rev, approvals, [held]),
            "manifest_revision": manifest.revision,
            "publication": manifest.states.get("publication"),
        }

    return _run_command(args, body, stage="publication")


def cmd_receipt(args: argparse.Namespace) -> dict[str, Any]:
    if args.channel not in RECEIPT_CHANNELS:
        raise ArgError(
            f"--channel must be one of {', '.join(RECEIPT_CHANNELS)}; got {args.channel!r}"
        )

    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        from starboard_core.engagement.publication import (
            revision_state,  # lazy – kernel dep
        )
        from starboard_core.engagement.records import DeliveryReceipt

        external = (args.external_object_id or "").strip()
        if not external:
            raise ArgError("--external-object-id is required")
        rev, approvals, receipts = _deliverable(storage, auth, sink, args)
        warnings: list[str] = []
        if args.channel == "slack":
            dest = (args.destination_id or "").strip()
            if not dest:
                raise ArgError(
                    "--destination-id (the Slack channel ID) is required for slack"
                )
            verified, revision = False, None
        else:
            obj = storage.get(external)
            expected = (args.destination_id or "").strip() or next(
                (
                    r.destination_id
                    for r in receipts
                    if r.channel == "drive"
                    and r.verified
                    and r.report_id == rev.report_id
                    and r.revision == rev.revision
                ),
                "",
            )
            warnings = _receipt_problems(
                storage, auth, sink.run_folder_id, rev, approvals, obj, expected
            )
            dest = expected or (obj.parent_ids[0] if obj.parent_ids else obj.id)
            verified, revision = not warnings, obj.revision
        receipt = DeliveryReceipt(
            receipt_id="rcp_"
            + _digest(
                rev.report_id,
                str(rev.revision),
                rev.object_ref.md5,
                args.channel,
                external,
            ),
            report_id=rev.report_id,
            revision=rev.revision,
            object_md5=rev.object_ref.md5,
            channel=args.channel,
            destination_id=dest,
            delivered_object_id=external,
            delivered_revision=revision,
            verified=verified,
            delivered_at=_envelope._now(),
        )
        held, manifest = _record_receipt(storage, sink, auth, rev, receipt)
        return {
            "run_id": auth.run_id,
            "run_folder_id": sink.run_folder_id,
            "report_id": rev.report_id,
            "revision": rev.revision,
            "receipt_id": held.receipt_id,
            "channel": held.channel,
            "verified": held.verified,
            "state": revision_state(rev, approvals, [held]),
            "manifest_revision": manifest.revision,
            "publication": manifest.states.get("publication"),
            "warnings": warnings,
        }

    return _run_command(args, body, stage="publication")


def _receipt_problems(
    storage: EngagementStoragePort,
    auth: RunAuthorization,
    rf: str,
    rev: Any,
    approvals: list[Any],
    obj: Any,
    expected: str,
) -> list[str]:
    """Why an external object cannot verify a delivery (empty when it can).

    The object must sit directly in the expected destination, outside the run
    folder and staging, match the revision's MD5 when Drive reports one, and be
    created after the revision was approved (or created, when no approval is
    needed). ``created_time`` stands in for a modification time the port lacks.
    """
    from starboard_core.engagement.publication import (
        approval_matches,  # lazy – kernel dep
    )
    from starboard_core.ports.engagement_storage import StorageNotFoundError

    problems: list[str] = []
    if not expected:
        problems.append(
            "no destination to check: pass --destination-id or `engagement deliver` first"
        )
    elif not obj.parent_ids or obj.parent_ids[0] != expected:
        problems.append(f"{obj.id} is not in destination {expected}")
    blocked = {rf} | (
        {auth.drive.preflight_folder_id}
        if auth.drive is not None and auth.drive.preflight_folder_id
        else set()
    )
    seen: set[str] = set()
    frontier = list(obj.parent_ids)
    while frontier and len(seen) < _ANCESTOR_LIMIT:
        pid = frontier.pop()
        if pid in seen:
            continue
        seen.add(pid)
        if pid in blocked:
            problems.append(f"{obj.id} is inside the run folder or staging")
            break
        try:
            frontier.extend(storage.get(pid).parent_ids)
        except StorageNotFoundError:
            continue
    if ARTIFACT_PROPERTY in obj.properties:
        problems.append(f"{obj.id} is a run artifact, not a delivered copy")
    if obj.md5 and obj.md5 != rev.object_ref.md5:
        problems.append(
            f"{obj.id} content (md5 {obj.md5}) is not revision {rev.revision}"
        )
    since = next(
        (a.approved_at for a in approvals if approval_matches(rev, a)), rev.created_at
    )
    try:
        fresh = obj.created_time is not None and datetime.fromisoformat(
            obj.created_time
        ) >= datetime.fromisoformat(since)
    except (TypeError, ValueError):
        fresh = False
    if not fresh:
        problems.append(f"{obj.id} was not created after {since}")
    return problems
