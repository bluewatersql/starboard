"""Run lifecycle on a run folder: ``status``, ``commit``, ``put``, ``read`` and ``history``."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ArgError,
    NotFoundError,
)
from starboard_skills.helpers.engagement import _envelope
from starboard_skills.helpers.engagement._envelope import (
    _ENVELOPE_RESERVE,
    _PUT_MIME,
    AUTHORIZATION_RECORD,
    BASELINE_PATH,
    DEFAULT_PUT_BYTES,
    FINDINGS_MANIFEST_PATH,
    FINDINGS_PATH,
    IDENTITY_RECORD,
    OBSERVATIONS_PATH,
    RECORD_PATHS,
    RUN_FOLDER_PROPERTY,
    SHARED_REGISTRY_ENV,
    STAGE_STATES,
    STAGED_IDENTITY,
    STAGED_PREFLIGHT,
    STAGES,
    Refusal,
    _account_key,
    _ctx,
    _storage_errors,
)
from starboard_skills.helpers.engagement._runs import (
    _append,
    _artifacts,
    _check_run_id,
    _close,
    _committed,
    _drive_storage,
    _evidence_map,
    _fingerprint,
    _internal_domains,
    _json,
    _latest,
    _local_run_dir,
    _locate_staging,
    _put_record,
    _quarantine_reason,
    _read_staged,
    _run_command,
    _run_observations,
    _storage_ref,
)
from starboard_skills.helpers.engagement.analysis_cmds import FACTS_PATH
from starboard_skills.helpers.engagement.setup import _load_local_preflight

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.records import RunAuthorization
    from starboard_core.engagement.sink import DriveRunSink
    from starboard_core.ports.engagement_storage import EngagementStoragePort


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def _status_data(st: Any) -> dict[str, Any]:
    return {
        "run_status": st.status,
        "states": dict(st.states),
        "pending": list(st.pending),
        "resume": None if st.resume is None else dict(st.resume),
        "checkpoint_revision": st.checkpoint_revision,
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.access import recheck_access  # lazy – kernel dep
    from starboard_core.engagement.commit import latest_manifest, read_descriptor
    from starboard_core.engagement.staging import QUARANTINE_PROPERTY
    from starboard_core.engagement.status import derive_status

    ctx = _ctx(args)
    if args.run_dir and args.run_folder:
        raise ArgError(
            "--run-dir names a local run and --run-folder a Drive run; pass one "
            "(optionally with the run's --run-id)"
        )
    if not (args.run_id or args.run_dir or args.run_folder):
        raise ArgError("pass --run-id, --run-dir or --run-folder")
    # --run-id with the run's folder or dir is a consistency check, not a selector.
    expected = (
        _check_run_id(args.run_id)
        if args.run_id and (args.run_dir or args.run_folder)
        else None
    )
    if not args.run_folder:
        if args.run_id and not args.run_dir:
            ctx["run_id"] = _check_run_id(args.run_id)
        local = _local_run_dir(args)
        if local:
            return _check_status_run_id(
                _local_status(local, ctx), expected, "--run-dir"
            )
        storage = _drive_storage(ctx["run_id"])
    else:
        storage = _envelope._make_storage()
    try:
        with _storage_errors(False, args.run_id):
            rf = (args.run_folder or "").strip() or None
            if rf is None:
                run_id = ctx["run_id"]
                state, folder = _locate_staging(storage, run_id)
                if state == "missing":
                    raise ArgError(
                        f"unknown run {run_id}: there is no Drive staging folder for it"
                    )
                if state == "quarantined":
                    data = _status_data(derive_status(None, [], None, True))
                    reason = folder.properties.get(QUARANTINE_PROPERTY)
                    return {
                        **data,
                        "run_id": run_id,
                        "run_folder_id": None,
                        "reason": reason,
                        "refs_count": 0,
                        "report_revisions": [],
                    }
                rf = folder.properties.get(RUN_FOLDER_PROPERTY)
                if not rf:
                    pre = _read_staged(
                        storage, folder.id, STAGED_PREFLIGHT, f"preflight:{run_id}"
                    )
                    ident = _read_staged(
                        storage, folder.id, STAGED_IDENTITY, f"identity:{run_id}"
                    )
                    if pre is None:
                        stage = "preflight"
                    elif pre.get("source_mode") != "internal_only" and ident is None:
                        stage = "verify-identity"
                    else:
                        stage = "route"
                    data = _status_data(derive_status(None, [], None, False))
                    return {
                        **data,
                        "resume": {
                            "run_id": run_id,
                            "run_folder_id": None,
                            "stage": stage,
                        },
                        "run_id": run_id,
                        "run_folder_id": None,
                        "refs_count": 0,
                        "report_revisions": [],
                    }
            ctx["run_folder_id"] = rf
            auth, _ = read_descriptor(storage, rf)
            ctx["run_id"] = auth.run_id
            _check_status_run_id({"run_id": auth.run_id}, expected, "--run-folder")
            verdict = recheck_access(_fingerprint(auth, rf), storage.inspect_access(rf))
            latest = latest_manifest(storage, rf)
            manifests = [] if latest is None else [latest[0]]
            st = derive_status(
                auth, manifests, verdict, _quarantine_reason(storage, auth) is not None
            )
            manifest = None if latest is None else latest[0]
            drift = _drift(storage, rf, auth.run_id, manifest)
            return {
                **_status_data(st),
                "run_id": auth.run_id,
                "run_folder_id": rf,
                "access": verdict.reason,
                "refs_count": 0 if manifest is None else len(manifest.refs),
                "report_revisions": []
                if manifest is None
                else [dict(r) for r in manifest.reports],
                # Artifacts rewritten after the commit that bound them: run_status
                # does not change, but the next `engagement commit` must re-bind
                # them (a README or recur-result.json edited after its commit).
                "drift": drift,
                "warnings": [
                    f"drift: {d['path']} was rewritten after its commit; re-run "
                    "`engagement commit` to bind the current bytes"
                    for d in drift
                ],
            }
    finally:
        _close(storage)


def _check_status_run_id(
    data: dict[str, Any], expected: str | None, flag: str
) -> dict[str, Any]:
    """``data`` unchanged; ``RUN_ID_MISMATCH`` when ``--run-id`` names another run
    than the one ``flag`` resolved."""
    if expected is not None and data["run_id"] != expected:
        raise Refusal(
            "RUN_ID_MISMATCH",
            f"--run-id {expected} does not match {flag}, which holds run "
            f"{data['run_id']}; pass the run's own ID, or {flag} alone",
        )
    return data


def _drift(
    storage: EngagementStoragePort, rf: str, run_id: str, manifest: Any
) -> list[dict[str, Any]]:
    """Committed artifacts whose current bytes differ from the latest manifest's ref."""
    if manifest is None or not manifest.refs:
        return []
    current = _artifacts(storage, rf, run_id)
    return [
        {"path": r.path, "committed_md5": r.md5, "current_md5": current[r.path].md5}
        for r in manifest.refs
        if r.path in current
        and r.md5
        and current[r.path].md5
        and current[r.path].md5 != r.md5
    ]


def _local_status(local: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """A local run's status from its run-dir records; it never loads the Drive adapter.

    Local runs keep no stage manifest, so a routed local run reports ``routed``
    with nothing pending; its later stages live in the run dir itself.
    """
    pre, run_dir = _load_local_preflight(local)
    run_id = pre["run_id"]
    ctx["run_id"] = run_id
    common = {
        "checkpoint_revision": None,
        "run_id": run_id,
        "run_folder_id": None,
        "run_dir": run_dir.as_posix(),
        "destination": "local",
        "refs_count": 0,
        "report_revisions": [],
    }
    if (run_dir / AUTHORIZATION_RECORD).exists():
        return {
            "run_status": "routed",
            "states": {},
            "pending": [],
            "resume": None,
            **common,
        }
    stage = "route"
    if pre.get("source_mode") != "internal_only":
        try:
            ident = json.loads((run_dir / IDENTITY_RECORD).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ident = None
        if not isinstance(ident, dict) or ident.get("status") != "verified":
            stage = "verify-identity"
    return {
        "run_status": "staged",
        "states": {},
        "pending": ["route"],
        "resume": {"run_id": run_id, "run_folder_id": None, "stage": stage},
        **common,
    }


# --------------------------------------------------------------------------- #
# commit
# --------------------------------------------------------------------------- #
def cmd_commit(args: argparse.Namespace) -> dict[str, Any]:
    if args.stage not in STAGES:
        raise ArgError(
            f"--stage must be one of {', '.join(STAGES)}; got {args.stage!r}"
        )
    state = args.state or "complete"
    if state not in STAGE_STATES:
        raise ArgError(
            f"--state must be one of {', '.join(STAGE_STATES)}; got {state!r}"
        )

    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        rf = sink.run_folder_id
        prev, prev_obj = _latest(storage, rf, auth.run_id)
        objs = _artifacts(storage, rf, auth.run_id)
        refs = []
        for rel in sorted(objs):
            _envelope._read_verified(storage, objs[rel])
            refs.append(_storage_ref(rel, objs[rel]))
        by_path = {r.path: r for r in refs}
        states = dict(prev.states)
        states[args.stage] = state
        changes = {
            "refs": tuple(refs),
            "states": states,
            "evidence_refs": tuple(_evidence_map(storage, objs)),
            "observation_refs": tuple(
                r for r in (by_path.get(OBSERVATIONS_PATH),) if r is not None
            ),
            "findings_ref": by_path.get(FINDINGS_PATH)
            or by_path.get(FINDINGS_MANIFEST_PATH),
            "baseline_selection_ref": by_path.get(BASELINE_PATH),
            **{f"{name}_ref": by_path.get(path) for name, path in RECORD_PATHS.items()},
        }
        manifest, obj, appended = _append(storage, rf, prev, changes)
        return {
            "run_id": auth.run_id,
            "run_folder_id": rf,
            "stage": args.stage,
            "state": state,
            "revision": manifest.revision,
            "manifest_object_id": (obj or prev_obj).id,
            "unchanged": not appended,
            "refs_added": sorted(r.path for r in refs if r not in prev.refs),
            "refs_count": len(refs),
            "states": dict(manifest.states),
        }

    return _run_command(args, body, stage=args.stage)


# --------------------------------------------------------------------------- #
# put
# --------------------------------------------------------------------------- #
def _put_path(path: str) -> str:
    """Validate a host ``put`` path: run-relative and not a control record.

    Refused: every kernel record (:func:`~starboard_core.engagement.sink.reserved_record`,
    case-insensitive) and every ``_``-prefixed top-level folder.
    """
    from starboard_core.engagement.sink import (  # lazy – kernel dep
        reserved_record,
        validate_relpath,
    )

    try:
        rel = validate_relpath(path)
    except ValueError as exc:
        raise ArgError(f"--path: {exc}") from exc
    if reserved_record(rel) is not None or rel.startswith("_"):
        raise ArgError(
            f"--path {rel!r} is a control record written by the helper; put only "
            "host-authored artifacts (README.md, plan.json, domains/, deliverables/, "
            "reports/, raw/, discovery/); kernel records are written by the helper"
        )
    return rel


def _read_stdin(limit: int) -> bytes:
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        raise ArgError(
            "put reads the artifact bytes from stdin; stdin is not available"
        )
    data = stream.read(limit + 1)
    if not data:
        raise ArgError("put needs the artifact bytes on stdin; stdin was empty")
    if len(data) > limit:
        raise ArgError(
            f"stdin is over the --max-bytes cap of {limit} bytes (hard cap "
            f"{DEFAULT_PUT_BYTES}); split the artifact"
        )
    return bytes(data)


def cmd_put(args: argparse.Namespace) -> dict[str, Any]:
    """Write one host-authored artifact (bytes from stdin) through the run sink."""
    limit = DEFAULT_PUT_BYTES if args.max_bytes is None else int(args.max_bytes)
    if limit < 1:
        raise ArgError("--max-bytes must be positive")
    if limit > DEFAULT_PUT_BYTES:
        raise ArgError(
            f"--max-bytes {limit} is over the hard cap of {DEFAULT_PUT_BYTES} bytes; "
            "split the artifact"
        )
    rel = _put_path(args.path)
    data = _read_stdin(limit)
    mime = _PUT_MIME.get(PurePosixPath(rel).suffix.lower(), "application/octet-stream")

    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        before = _artifacts(storage, sink.run_folder_id, auth.run_id).get(rel)
        ref = sink.put_bytes(rel, data, mime)
        unchanged = (
            before is not None
            and before.id == ref.object_id
            and before.md5 == ref.md5
            and before.size == ref.size
        )
        return {
            "path": ref.path,
            "object_id": ref.object_id,
            "md5": ref.md5,
            "size": ref.size,
            "unchanged": unchanged,
        }

    return _run_command(args, body)


# --------------------------------------------------------------------------- #
# read
# --------------------------------------------------------------------------- #
#: Smallest ``read --max-bytes``: a JSON-quoted excerpt of one ASCII character plus
#: the quotes always fits; below it nothing useful (and no JSON string) can be shown.
_MIN_READ_BYTES = 8

#: Largest artifact ``read --jsonpath`` parses (the whole document is loaded).
_JSONPATH_MAX_BYTES = 32 * 1024 * 1024

#: Most ``--jsonpath`` expressions per read (the envelope's list cap).
_MAX_JSONPATHS = 50

#: Bytes kept for the read envelope's own keys when sizing a ``--jsonpath``
#: excerpt, on top of the measured echo of the expressions and warnings.
_JSONPATH_ENVELOPE_SLACK = 768


def _cap_lists(value: Any, cap: int) -> tuple[Any, bool]:
    """``value`` with every list cut to ``cap`` items, and whether any was cut."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        cut = False
        for k, v in value.items():
            out[k], c = _cap_lists(v, cap)
            cut = cut or c
        return out, cut
    if isinstance(value, list):
        items = [_cap_lists(v, cap) for v in value[:cap]]
        return [v for v, _ in items], len(value) > cap or any(c for _, c in items)
    return value, False


def _prefix_within(value: Any, budget: int) -> Any:
    """The longest non-empty prefix of ``value`` (list items, object keys or
    string characters, each whole) whose JSON fits ``budget`` bytes, else ``None``."""
    from starboard_core.engagement.stdout_budget import encoded_size  # lazy – kernel

    if isinstance(value, (list, dict, str)):

        def cut(n: int) -> Any:
            if isinstance(value, dict):
                return dict(list(value.items())[:n])
            return value[:n]

        lo, hi = 0, len(value)
        if not value or encoded_size(cut(1)) > budget:
            return None
        while lo < hi:  # the largest n with cut(n) in budget
            mid = (lo + hi + 1) // 2
            if encoded_size(cut(mid)) <= budget:
                lo = mid
            else:
                hi = mid - 1
        return cut(lo)
    return None


def _fit_excerpt(
    slices: dict[str, Any], budget: int
) -> tuple[dict[str, Any], list[str]]:
    """``(excerpt, truncated_paths)``: ``slices`` fitting ``budget`` bytes, still an
    object keyed by expression.

    Lists are first capped at the envelope's list cap; then, largest slice first,
    a slice is cut to the prefix that fits, or dropped (its key absent) when no
    prefix does. Every cut or dropped expression is named, in expression order.
    Never cuts inside a JSON value.
    """
    from starboard_core.engagement.stdout_budget import (  # lazy – kernel
        MAX_LIST_ITEMS,
        encoded_size,
    )

    excerpt: dict[str, Any] = {}
    cut: set[str] = set()
    for expr, value in slices.items():
        excerpt[expr], capped = _cap_lists(value, MAX_LIST_ITEMS)
        if capped:
            cut.add(expr)
    while excerpt and (over := encoded_size(excerpt) - budget) > 0:
        expr = max(excerpt, key=lambda e: encoded_size(excerpt[e]))
        keep = _prefix_within(excerpt[expr], encoded_size(excerpt[expr]) - over)
        if keep is None:
            del excerpt[expr]
        else:
            excerpt[expr] = keep
        cut.add(expr)
    return excerpt, [e for e in slices if e in cut]


def _read_head(
    storage: EngagementStoragePort, obj: Any, keep: int, *, start: int = 0
) -> tuple[bytes, int]:
    """``(bytes [start, start + keep), total size)`` of the listed file ``obj``, all verified.

    Streams the file once, hashing every chunk but retaining only the window, so
    a bounded excerpt costs ``keep`` bytes of memory; the size and md5 are still
    checked against ``obj`` (capped at the largest artifact the run sink accepts).
    """
    import hashlib

    from starboard_core.engagement.sink import (  # lazy – kernel dep
        DEFAULT_MAX_BYTES as SINK_MAX_BYTES,
    )
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    if obj.is_folder:
        raise StorageIntegrityError(f"{obj.id} is a folder, not a file")
    too_big = f"{obj.id} is larger than {SINK_MAX_BYTES} bytes"
    if obj.size is not None and obj.size > SINK_MAX_BYTES:
        raise StorageIntegrityError(too_big)
    digest = hashlib.md5(usedforsecurity=False)
    window = bytearray()
    total = 0
    for chunk in storage.get_stream(obj.id):
        lo, hi = max(start - total, 0), min(start + keep - total, len(chunk))
        if lo < hi:
            window += chunk[lo:hi]
        total += len(chunk)
        if total > SINK_MAX_BYTES:
            raise StorageIntegrityError(too_big)
        digest.update(chunk)
    md5 = digest.hexdigest()
    if (obj.size is not None and obj.size != total) or (obj.md5 and obj.md5 != md5):
        raise StorageIntegrityError(
            f"{obj.id} downloaded {total} bytes md5 {md5}; Drive records "
            f"{obj.size} bytes md5 {obj.md5}"
        )
    return bytes(window), total


def _text_excerpt(window: bytes, limit: int, *, at_end: bool) -> tuple[str, int]:
    """``(text, bytes consumed)``: the longest UTF-8 prefix of ``window`` whose JSON
    form fits ``limit``, never ending inside a multi-byte character (a partial
    trailing character is left for the next page, unless the file ends there)."""
    import codecs

    n = len(window)
    while True:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text = decoder.decode(window[:n], final=at_end and n == len(window))
        over = len(json.dumps(text)) - limit
        if over <= 0 or n <= 0:
            return text, n - len(decoder.getstate()[0])
        n = max(n - max(over // 6, 1), 0)  # one byte is at most 6 JSON characters


#: One ``--jsonpath`` step: ``name`` (after an optional ``.``), ``[n]``, ``[*]`` or a
#: ``[a:b]`` slice (either bound optional, Python semantics).
_JSONPATH_STEP = re.compile(r"\.?([^.\[\]]+)|\[(\*|-?\d+)\]|\[(-?\d*):(-?\d*)\]")

#: One ``--jsonpath`` step: a key or index (``str``), ``"*"``, or a slice.
_Step = str | slice


def _jsonpath_steps(expr: str) -> list[_Step]:
    """The steps of ``expr`` (``a.b[0].c``, ``runs[*].state``, ``$[50:100].id``; a
    leading ``$`` is optional)."""
    expr = expr.strip()
    if expr.startswith("$"):
        expr = expr[1:]
    steps: list[_Step] = []
    pos = 0
    while pos < len(expr):
        m = _JSONPATH_STEP.match(expr, pos)
        if m is None or m.end() == pos:
            hint = ""
            if "[?" in expr:
                hint = (
                    "; filters [?(...)] are not supported - read '$[*].finding_id' "
                    "(or the field you filter on), page past 50 items with the "
                    "'next_paths' slice ('$[50:100].finding_id'), then read "
                    "'[<n>].<field>' at the item's position"
                )
            raise ArgError(
                f"--jsonpath: cannot parse {expr[pos:]!r} (use a.b, a[0], a.0, a[*] "
                f"or a[50:100]){hint}"
            )
        if m.group(1) is not None:
            steps.append(m.group(1))
        elif m.group(2) is not None:
            steps.append(m.group(2))
        else:
            lo, hi = m.group(3), m.group(4)
            steps.append(slice(int(lo) if lo else None, int(hi) if hi else None))
        pos = m.end()
    return steps


def _jsonpath_text(steps: Sequence[_Step]) -> str:
    """``steps`` written back as an expression (``$[50:100].play_id``)."""
    out = "$"
    for step in steps:
        if isinstance(step, slice):
            lo = "" if step.start is None else step.start
            hi = "" if step.stop is None else step.stop
            out += f"[{lo}:{hi}]"
        elif step == "*" or step.lstrip("-").isdigit():
            out += f"[{step}]"
        else:
            out += f".{step}"
    return out


def _next_path(doc: Any, steps: Sequence[_Step], kept: int | None) -> str | None:
    """The slice expression that reads the list items after those this read
    returned, or ``None`` when no item follows.

    The list is the first ``[*]`` / ``[a:b]`` step of ``steps``; ``kept`` is how many
    of its items the excerpt holds (``None``: all it selected). A slice read whole
    pages on past its end. ``None`` too when nothing fits (paging would not move).
    A page is the envelope's list cap of items."""
    from starboard_core.engagement.stdout_budget import MAX_LIST_ITEMS  # lazy – kernel

    at = next(
        (i for i, s in enumerate(steps) if s == "*" or isinstance(s, slice)), None
    )
    if at is None or kept == 0:
        return None
    try:
        items = _follow(doc, steps[:at])
    except _PathMissing:
        return None
    if not isinstance(items, list):
        return None
    step = steps[at]
    positions = range(len(items))[step if isinstance(step, slice) else slice(None)]
    if kept is not None and kept < len(positions):
        start = positions[kept]
    elif positions and positions[-1] + 1 < len(items):
        start = positions[-1] + 1
    else:
        return None
    page = slice(start, start + MAX_LIST_ITEMS)
    return _jsonpath_text([*steps[:at], page, *steps[at + 1 :]])


class _PathMissing(Exception):
    """A well-formed ``--jsonpath`` names something the document does not hold."""


def _follow(value: Any, steps: Sequence[_Step]) -> Any:
    """Follow parsed steps: dotted names, ``[n]`` / ``.n`` indexes, ``[*]`` (every
    item) and ``[a:b]`` (the items of a slice).

    Raises :class:`_PathMissing` when a step is absent; under ``[*]`` or a slice an
    item that lacks the rest of the path is ``None`` (the caller still reports the
    path).
    """
    for i, part in enumerate(steps):
        if part == "*" or isinstance(part, slice):
            if not isinstance(value, list):
                raise _PathMissing("[*] and [a:b] need a list")
            items: list[Any] = []
            partial = False
            for v in value[part] if isinstance(part, slice) else value:
                try:
                    items.append(_follow(v, steps[i + 1 :]))
                except _PartialPath as nested:
                    items.append(nested.items)
                    partial = True
                except _PathMissing:
                    items.append(None)
                    partial = True
            if partial:
                raise _PartialPath(items)
            return items
        if isinstance(value, list) and part.lstrip("-").isdigit():
            try:
                value = value[int(part)]
            except IndexError as exc:
                raise _PathMissing(f"index {part} is out of range") from exc
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise _PathMissing(f"{part!r} is not present")
    return value


class _PartialPath(_PathMissing):
    """A ``[*]`` path where some items lack the rest: ``items`` has ``None`` for them."""

    def __init__(self, items: list[Any]) -> None:
        super().__init__("some items lack the path")
        self.items = items


def cmd_read(args: argparse.Namespace) -> dict[str, Any]:
    from starboard_core.engagement.reads import (  # lazy – kernel
        ReadRefusedError,
        read_object,
    )
    from starboard_core.engagement.sink import validate_relpath
    from starboard_core.engagement.stdout_budget import (
        DEFAULT_MAX_BYTES as STDOUT_MAX_BYTES,
    )
    from starboard_core.engagement.stdout_budget import encoded_size
    from starboard_core.ports.engagement_storage import StorageIntegrityError

    cap = STDOUT_MAX_BYTES - _ENVELOPE_RESERVE
    warnings: list[str] = []
    limit = cap if args.max_bytes is None else int(args.max_bytes)
    if limit < _MIN_READ_BYTES:
        raise ArgError(
            f"--max-bytes must be at least {_MIN_READ_BYTES} (the smallest useful excerpt)"
        )
    if limit > cap:
        # The envelope fits the stdout budget: a larger excerpt is never printed.
        warnings.append(
            f"--max-bytes {limit} is above the read cap of {cap} bytes; the excerpt is "
            "at most that (page with --offset, or slice JSON with --jsonpath)"
        )
        limit = cap
    offset = int(args.offset or 0)
    if offset < 0:
        raise ArgError("--offset must be zero or positive")
    # Repeated expressions are read once; every one is parsed before the download.
    exprs = list(dict.fromkeys(args.jsonpath or ()))
    if len(exprs) > _MAX_JSONPATHS:
        raise ArgError(
            f"{len(exprs)} --jsonpath expressions; at most {_MAX_JSONPATHS} per read "
            "(split them over several reads)"
        )
    steps = {expr: _jsonpath_steps(expr) for expr in exprs}
    if exprs and offset:
        raise ArgError(
            "--offset pages a plain text read; it cannot combine with --jsonpath "
            "(narrow the --jsonpath instead)"
        )
    try:
        rel = validate_relpath(args.path)
    except ValueError as exc:
        raise ArgError(f"--path: {exc}") from exc

    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        _state: dict[str, Any],
    ) -> dict[str, Any]:
        obj = _artifacts(storage, sink.run_folder_id, auth.run_id).get(rel)
        if obj is None:
            raise NotFoundError(f"{rel!r} is not an artifact of run {auth.run_id}")
        truncated = False
        next_offset: int | None = None
        missing_paths: list[str] = []
        truncated_paths: list[str] = []
        next_paths: dict[str, str] = {}
        excerpt: str | dict[str, Any]
        if exprs:
            # The cap holds on the listed size *and* while streaming (a listing
            # without a size cannot slip past it); the bytes are still verified.
            try:
                data = read_object(storage, obj, max_bytes=_JSONPATH_MAX_BYTES)
            except ReadRefusedError as exc:
                if obj.is_folder:
                    raise StorageIntegrityError(str(exc)) from exc
                raise Refusal(
                    "READ_TOO_LARGE",
                    f"{rel} is larger than {_JSONPATH_MAX_BYTES} bytes; --jsonpath parses "
                    "at most that. Read it without --jsonpath.",
                ) from exc
            try:
                doc = json.loads(data)
            except ValueError as exc:
                raise ArgError(
                    f"--jsonpath needs a JSON artifact; {rel} is not JSON. Read it "
                    "without --jsonpath."
                ) from exc
            slices: dict[str, Any] = {}
            for expr in exprs:
                try:
                    slices[expr] = _follow(doc, steps[expr])
                except _PartialPath as part:
                    slices[expr] = part.items
                    missing_paths.append(expr)
                except _PathMissing:
                    slices[expr] = None
                    missing_paths.append(expr)
            if missing_paths:
                warnings.append(
                    "jsonpath not (fully) present, returned as null: "
                    + ", ".join(repr(m) for m in missing_paths)
                )
            # One shape always: an object keyed by expression, in order. The
            # budget leaves room for the envelope's echo of the expressions and
            # warnings, so the envelope is never re-bounded (which would cut it).
            echo = encoded_size([exprs, missing_paths, warnings, warnings])
            room = STDOUT_MAX_BYTES - _JSONPATH_ENVELOPE_SLACK - echo
            excerpt, truncated_paths = _fit_excerpt(slices, min(limit, room))
            truncated = bool(truncated_paths)
            for expr in exprs:
                kept = excerpt.get(expr)
                count = None  # every selected item is in the excerpt
                if expr in truncated_paths:
                    count = len(kept) if isinstance(kept, list) else 0
                follow = _next_path(doc, steps[expr], count)
                if follow is not None:
                    next_paths[expr] = follow
        else:
            # The JSON-escaped excerpt is never shorter than its raw bytes, so the
            # ``limit`` bytes from ``offset`` always cover it.
            window, total = _read_head(storage, obj, limit, start=offset)
            if offset and offset >= total:
                raise ArgError(
                    f"--offset {offset} is at or past the end of {rel} ({total} bytes)"
                )
            text, used = _text_excerpt(
                window, limit, at_end=offset + len(window) >= total
            )
            excerpt = text
            if used == 0 and offset + len(window) < total:
                raise ArgError(f"--max-bytes {limit} is too small for one character")
            if offset + used < total:
                next_offset = offset + used
                truncated = True
        return {
            "run_id": auth.run_id,
            "run_folder_id": sink.run_folder_id,
            "path": rel,
            "jsonpaths": exprs or None,
            # Expressions the document does not (fully) hold; their value is null.
            "missing_paths": missing_paths,
            "offset": offset,
            # Text for a plain read; for --jsonpath an object keyed by expression.
            "excerpt": excerpt,
            "truncated": truncated,
            # --jsonpath expressions whose value was cut to fit: a valid prefix,
            # or the key dropped when none fits. Always empty for a plain read.
            "truncated_paths": truncated_paths,
            # Per cut list expression, the ``[a:b]`` slice that reads its next items
            # (item k of ``[a:b]`` is position a + k). Always empty for a plain read.
            "next_paths": next_paths,
            # Pass as --offset to read the next page; null once the file is read.
            "next_offset": next_offset,
            "object_id": obj.id,
            "md5": obj.md5,
            "size": obj.size,
            # True only when the latest committed manifest binds these exact bytes.
            "committed": _committed(storage, sink.run_folder_id, rel, obj.md5),
            "warnings": warnings,
        }

    return _run_command(args, body)


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #
def cmd_history(args: argparse.Namespace) -> dict[str, Any]:
    def body(
        storage: EngagementStoragePort,
        auth: RunAuthorization,
        sink: DriveRunSink,
        ctx: dict[str, Any],
    ) -> dict[str, Any]:
        from starboard_core.engagement.history import select_baselines
        from starboard_core.engagement.prior import load_prior

        families = frozenset(args.families or ())

        def wanted(o: Any) -> bool:
            return not families or o.family in families

        warnings: list[str] = []
        ctx["warnings"] = warnings
        prior = load_prior(
            storage,
            account_key=_account_key(auth),
            workspace_id=None,
            exclude_run_id=auth.run_id,
            shared_root_id=os.environ.get(SHARED_REGISTRY_ENV, "").strip() or None,
            internal_domains=_internal_domains(args),
            warnings=warnings,
            kinds=("observations",),
        )
        candidates = [c for c in prior.observations if wanted(c.observation)]
        unavailable = [u for u in prior.unavailable if "observations" in u.records]
        objs = _artifacts(storage, sink.run_folder_id, auth.run_id)
        current = [o for o in _run_observations(storage, objs) if wanted(o)]
        start = args.interval_start or min(
            (o.interval_start for o in current), default=None
        )
        end = args.interval_end or max((o.interval_end for o in current), default=None)
        source = (
            "flags" if args.interval_start and args.interval_end else "observations"
        )
        if (not start or not end) and FACTS_PATH in objs:
            # Before ``analyze`` there are no observations: the captured facts window
            # is the one ``analyze`` will give them, so the interval is the same.
            facts = _json(
                _envelope._read_verified(storage, objs[FACTS_PATH]), FACTS_PATH
            )
            window = facts.get("window") if isinstance(facts, dict) else None
            if isinstance(window, dict) and window.get("start") and window.get("end"):
                start = args.interval_start or str(window["start"])
                end = args.interval_end or str(window["end"])
                source = "facts"
        if not start or not end:
            raise ArgError(
                "no current observations and no captured discovery/facts.json window "
                "to take the reporting interval from; capture discovery first (commit "
                "--stage capture), or pass --interval-start and --interval-end"
            )
        selection = select_baselines(
            current,
            candidates,
            reporting_interval=(start, end),
            unavailable=unavailable,
            overlap_adjusted=bool(args.overlap_adjusted),
            run_id=auth.run_id,
        )
        payload = selection.to_dict()
        ref = _put_record(sink, BASELINE_PATH, payload)
        return {
            "run_id": auth.run_id,
            "run_folder_id": sink.run_folder_id,
            "selected": payload.get("selected", []),
            "rejected": payload.get("rejected", []),
            "unavailable": payload.get("unavailable", []),
            "reporting_interval": [start, end],
            # Where the interval came from: ``flags``, ``observations`` or ``facts``.
            "reporting_interval_source": source,
            "candidates": len(candidates),
            "current_observations": len(current),
            "baseline_selection_ref": ref.to_dict(),
            "warnings": warnings,
        }

    return _run_command(args, body, stage="analysis")
