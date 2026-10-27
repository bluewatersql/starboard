"""Run assessment: ``engagement analyze`` and the shared pipeline ``run recur`` reuses.

One run is opened with exactly one of ``--run-folder`` (a Drive run; prior runs
come from the account registry) or ``--run-dir`` + ``--workspace-root`` (a local
run: internal-only, or public with a local run authorization; prior runs are every
run dir of its account root, D4-16).
:func:`assess` reads the run's discovery facts, findings manifest and
``vt-job-run-states`` slices, loads the prior records, calls the kernel
:func:`~starboard_core.engagement.assess.assess_run` and writes the seven
record sets (``analysis/{observations,findings,health,plays,changes,cases,actions}.json``)
plus ``analysis/baseline-selection.json`` through the run sink. Case and action
records this run already holds (``engagement case`` / ``engagement action``) are
kept.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starboard_skills.helpers.contract import (
    ArgError,
    HelperError,
    HelperRun,
    NotFoundError,
    StorageRefusedError,
    helper_writer,
)
from starboard_skills.helpers.engagement._envelope import (
    ACTIONS_PATH,
    AUTHORIZATION_RECORD,
    BASELINE_PATH,
    CASES_PATH,
    CHANGES_PATH,
    EVIDENCE_PATH,
    FINDINGS_MANIFEST_PATH,
    FINDINGS_PATH,
    HEALTH_PATH,
    OBSERVATIONS_PATH,
    PLAYS_PATH,
    PREFLIGHT_RECORD,
    SHARED_REGISTRY_ENV,
    TASKS,
    Refusal,
    _account_key,
    _ctx,
)

if TYPE_CHECKING:  # kernel types only; imported lazily at runtime
    from starboard_core.engagement.prior import PriorRecords
    from starboard_core.engagement.records import RunAuthorization

FACTS_PATH = "discovery/facts.json"
DISCOVERY_RAW_PREFIX = "discovery/raw/"
BACKLOG_PATH = "analysis/backlog.json"
VERIFY_PREFIX = "analysis/verify/"
RUN_STATES_TEMPLATE = "vt-job-run-states"
_TOP_PLAYS = 10
#: ``plays_by_code[<code>].play_ids`` lists at most this many plays (effective order).
_PLAYS_BY_CODE_IDS = 25
#: ``plays_by_code[<code>].samples`` digests at most this many plays (effective order).
_PLAYS_BY_CODE_SAMPLES = 3
#: Derived digest keys ``plays.json`` items carry beside the ``Play`` record fields
#: (recomputed on every write; the kernel ignores them on read).
PLAY_DIGEST_KEYS = (
    "target",
    "effective_rank",
    "action_id",
    "severity",
    "review_rule_id",
)
#: The overlay's internal verify templates (``verify run --templates`` of an
#: internal-only run), and the characters a printed ``~/`` path may hold unquoted.
MIRROR_TEMPLATES_NAME = "mirror-verify.md"
_SAFE_PATH_RE = re.compile(r"[\w./-]+")
#: ``read_authorization``'s hint for a local run dir without a run authorization.
PREFLIGHT_HINT = "run engagement preflight --storage local and route first"
#: ``load_prior_local`` scans only run-ID-named run dirs of the account root.
RUN_DIR_NAME_WARNING = (
    "run dir name is not its run id; later runs will not find these records"
)
#: D4-16: the run dir is not ``<account-root>/<task>/<task-name>/<run_id>`` as its
#: run authorization (and the preflight's reports root) names it.
OUTSIDE_LAYOUT_WARNING = (
    "run dir is outside the preflight layout; prior read from the case root only"
)


def _dump(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode()


# --------------------------------------------------------------------------- #
# The open run
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PriorRoot:
    """Where a local run reads its prior records (D4-16).

    Attributes:
        path: The account root, or the case root when the run dir is outside the
            authorized layout.
        case_roots: Every ``<task>/<task-name>`` case root under ``path``.
        account: ``path`` is the account root.
        warnings: Task or case dirs that could not be listed (skipped).
    """

    path: Path
    case_roots: tuple[Path, ...]
    account: bool
    warnings: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"the {'account' if self.account else 'case'} root {self.path}"


def local_prior_root(run_dir: Path, auth: RunAuthorization) -> PriorRoot:
    """The account root ``run_dir.parents[2]`` when the run's immutable authorization
    names the layout, else the case root alone (D4-16).

    ``run_dir`` is resolved. The layout holds when the authorization's ``intent`` is a
    task naming ``run_dir.parents[1]``, its ``task`` (the task name) names the case
    root, the slug of its account display name names the account root, and the case
    root is the one the preflight recorded under its reports root. Symlinked task or
    case dirs are not followed; one that cannot be listed is skipped with a warning.
    """
    from starboard_skills.helpers.engagement.setup import local_segment

    case_root = run_dir.parent
    fallback = PriorRoot(case_root, (case_root,), False)
    if len(run_dir.parents) < 3:
        return fallback
    task_dir, root = run_dir.parents[1], run_dir.parents[2]
    try:
        segment = local_segment(auth.account.display_name)
    except ArgError:
        return fallback
    if not (
        auth.intent in TASKS
        and auth.intent == task_dir.name
        and auth.task == case_root.name
        and segment == root.name
        and _recorded_case_root(run_dir, case_root)
    ):
        return fallback
    notes: list[str] = []
    cases = {case_root}
    for task in _real_dirs(root, notes):
        cases.update(_real_dirs(task, notes))
    return PriorRoot(root, tuple(sorted(cases)), True, tuple(notes))


def _recorded_case_root(run_dir: Path, case_root: Path) -> bool:
    """The preflight recorded ``case_root`` (``<reports-root>/<account>/<task>/<name>``):
    an absolute record must resolve to it; a relative one (resolved against the
    preflight's working dir) must be its trailing path."""
    try:
        raw = json.loads((run_dir / PREFLIGHT_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    pre = raw.get("data", raw) if isinstance(raw, dict) else None
    recorded = pre.get("case_root") if isinstance(pre, dict) else None
    if not isinstance(recorded, str) or not recorded:
        return False
    path = Path(recorded).expanduser()
    if path.is_absolute():
        return Path(os.path.realpath(path)) == case_root
    parts = path.parts
    return ".." not in parts and case_root.parts[-len(parts) :] == parts


def _real_dirs(parent: Path, notes: list[str]) -> list[Path]:
    """The subdirectories of ``parent`` that are not symlinks; a dir that cannot be
    listed is a note and none."""
    try:
        with os.scandir(parent) as entries:
            return [Path(e.path) for e in entries if e.is_dir(follow_symlinks=False)]
    except OSError as exc:
        notes.append(
            f"prior dir {parent} is not readable ({exc.strerror or exc}); skipped"
        )
        return []


@dataclass
class OpenRun:
    """One analysis-side run: its sink, descriptor, account and prior-history source."""

    helper: HelperRun
    auth: RunAuthorization
    account_key: str
    prior_root: PriorRoot | None
    args: argparse.Namespace
    warnings: list[str] = field(default_factory=list)
    _prior: dict[tuple[str | None, str | None], PriorRecords] = field(
        default_factory=dict, repr=False
    )
    #: Bytes this command already read, by run-relative path: each artifact is
    #: downloaded once per command. Process memory only (never written anywhere);
    #: a :meth:`put` of the path drops its entry.
    _read: dict[str, bytes] = field(default_factory=dict, repr=False)

    @property
    def run_id(self) -> str:
        return self.auth.run_id

    @property
    def internal(self) -> bool:
        return self.auth.source_mode.value == "internal_only"

    @property
    def _sink(self) -> Any:
        assert self.helper.sink is not None
        return self.helper.sink

    def has(self, rel: str) -> bool:
        return bool(self._sink.exists(rel))

    def read(self, rel: str) -> bytes:
        from starboard_core.engagement.sink import ReadRefusedError  # lazy – kernel dep
        from starboard_core.ports.engagement_storage import StorageNotFoundError

        held = self._read.get(rel)
        if held is not None:
            return held
        try:
            data = bytes(self._sink.get_bytes(rel))
        except StorageNotFoundError as exc:
            raise ArgError(f"{rel} is not in the run") from exc
        except ReadRefusedError as exc:
            raise ArgError(f"{rel}: {exc}") from exc
        self._read[rel] = data
        return data

    def read_json(self, rel: str) -> Any:
        try:
            return json.loads(self.read(rel))
        except ValueError as exc:
            raise ArgError(f"{rel} is not valid JSON ({exc})") from exc

    def listing(self, prefix: str) -> tuple[str, ...]:
        return tuple(self._sink.list(prefix))

    def put(
        self, rel: str, payload: Any, *, action_of: Mapping[str, str] | None = None
    ) -> Any:
        """Write one kernel record through the run sink; returns its ref.

        ``plays.json`` items also carry the digest's derived ``target``
        (``kind:id``), ``effective_rank``, ``action_id`` (``action_of``, else
        this run's ``actions.json``), ``severity`` and ``review_rule_id`` (of the
        play's first finding in this run's ``findings.json``), so a host reading
        the file need not recompute them; the kernel ignores them on read.
        """
        if (
            rel == PLAYS_PATH
            and isinstance(payload, list)
            and payload
            and all(isinstance(item, dict) for item in payload)
        ):
            payload = self._ranked_plays(payload, action_of)
        self._read.pop(rel, None)
        return self._sink.put_record(rel, _dump(payload), "application/json")

    def _ranked_plays(
        self, items: list[Any], action_of: Mapping[str, str] | None
    ) -> list[dict[str, Any]]:
        from starboard_core.engagement.prior import parse_records  # lazy – kernel dep

        if action_of is None:
            action_of = action_index(self.records("actions", ACTIONS_PATH), self.run_id)
        rank_of = {
            p.play_id: r for r, p in effective_order(parse_records(items, "plays"))
        }
        finding_of = {f.finding_id: f for f in self.records("findings", FINDINGS_PATH)}

        def first(item: Mapping[str, Any]) -> Any:
            ids = item.get("finding_ids") or ()
            return finding_of.get(ids[0]) if ids else None

        return [
            {
                **item,
                "target": f"{item['target_entity_kind']}:{item['target_entity_id']}",
                "effective_rank": rank_of[item["play_id"]],
                "action_id": action_of.get(item["play_id"]),
                "severity": getattr(first(item), "severity", None),
                "review_rule_id": review_rule_of(first(item)),
            }
            for item in items
        ]

    def records(self, kind: str, rel: str) -> list[Any]:
        """This run's own copy of one record set (empty when not written yet)."""
        from starboard_core.engagement.prior import parse_records  # lazy – kernel dep

        if not self.has(rel):
            return []
        raw = self.read_json(rel)
        if not isinstance(raw, list):
            raise ArgError(f"{rel} is not a JSON list")
        return parse_records(raw, kind)

    def evidence(self) -> dict[str, Any]:
        """This run's evidence index by run-relative path (Drive runs)."""
        from starboard_core.engagement.records import EvidenceRef  # lazy – kernel dep

        if not self.has(EVIDENCE_PATH):
            return {}
        raw = self.read_json(EVIDENCE_PATH)
        out: dict[str, Any] = {}
        for item in raw if isinstance(raw, list) else ():
            ref = EvidenceRef.from_dict(item)
            out[ref.storage_ref.path] = ref
        return out

    def evidence_id(self, rel: str, data: bytes, index: Mapping[str, Any]) -> str:
        """The evidence ID of one run artifact: its index entry, else the deterministic ID."""
        import hashlib

        from starboard_core.engagement.records import evidence_id  # lazy – kernel dep

        if rel in index:
            return str(index[rel].evidence_id)
        return evidence_id(self.run_id, rel, hashlib.md5(data).hexdigest())  # noqa: S324

    def prior(
        self, workspace_id: str | None, *, only_folder: str | None = None
    ) -> PriorRecords:
        """Every prior record of the account (workspace) from the registry / account root.

        Loaded once per command (per ``workspace_id`` / ``only_folder``); later calls
        return the same records.
        """
        key = (workspace_id, only_folder)
        if key not in self._prior:
            self._prior[key] = self._load_prior(workspace_id, only_folder)
        return self._prior[key]

    def _load_prior(
        self, workspace_id: str | None, only_folder: str | None
    ) -> PriorRecords:
        from starboard_core.engagement.prior import (  # lazy – kernel dep
            load_prior,
            load_prior_local,
        )

        if self.prior_root is not None:
            return load_prior_local(
                self.prior_root.case_roots,
                account_key=self.account_key,
                workspace_id=workspace_id,
                exclude_run_id=self.run_id,
                warnings=self.warnings,
            )
        from starboard_skills.helpers.engagement._runs import _internal_domains

        return load_prior(
            self.helper.storage(),
            account_key=self.account_key,
            workspace_id=workspace_id,
            exclude_run_id=self.run_id,
            only_folder=only_folder,
            shared_root_id=os.environ.get(SHARED_REGISTRY_ENV, "").strip() or None,
            internal_domains=_internal_domains(self.args),
            warnings=self.warnings,
        )

    def workspace(self, *docs: Any) -> str:
        """The one workspace this run measures: the scope, else the inputs' ``workspace_id``."""
        scope = tuple(
            str(w) for w in self.auth.authorized_scope.get("workspace_ids") or ()
        )
        if len(scope) == 1:
            return scope[0]
        named = [
            str(d.get("workspace_id"))
            for d in docs
            if isinstance(d, Mapping) and d.get("workspace_id")
        ]
        for ws in named:
            if not scope or ws in scope:
                return ws
        hint = (
            "; an internal_only run declares its workspace at preflight: start a new "
            "run with engagement preflight --internal-workspace-id <id>"
            if self.internal
            else ""
        )
        raise ArgError(
            f"the run needs one workspace: its scope has {len(scope)} "
            f"({', '.join(scope) or 'none'}) and the inputs name "
            f"{', '.join(named) or 'none'}{hint}"
        )

    def result(self, data: dict[str, Any]) -> dict[str, Any]:
        out = {
            "run_id": self.run_id,
            "run_folder_id": self.helper.run_folder,
            **data,
        }
        out["warnings"] = [*self.warnings, *data.get("warnings", ())]
        return out


def add_run_args(p: argparse.ArgumentParser) -> None:
    """``--run-folder`` | ``--run-dir`` + ``--workspace-root`` (+ ``--internal-domain``)."""
    p.add_argument(
        "--run-folder", default=None, help="Drive run folder ID (a Drive-backed run)"
    )
    p.add_argument(
        "--run-dir",
        default=None,
        help=(
            "Local run directory (internal-only, or public with a local run "
            "authorization)"
        ),
    )
    p.add_argument(
        "--workspace-root",
        default=None,
        help="Case root of --run-dir (its parent): where prior local runs live",
    )
    p.add_argument(
        "--internal-domain",
        action="append",
        default=None,
        help="Internal Workspace domain of the shared registry (repeatable)",
    )


def read_authorization(run_dir: Path) -> RunAuthorization:
    """The run authorization of a local run dir.

    Raises:
        ArgError: The record is missing (the message names the preflight step) or
            not a valid run authorization.
    """
    from starboard_core.engagement.records import (  # lazy – kernel dep
        RunAuthorization,
    )

    path = run_dir / AUTHORIZATION_RECORD
    try:
        return RunAuthorization.from_dict(json.loads(path.read_text("utf-8")))
    except FileNotFoundError as exc:
        raise ArgError(
            f"--run-dir: no run authorization at {path}; {PREFLIGHT_HINT}"
        ) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise ArgError(
            f"--run-dir: {path} is not a valid run authorization ({exc})"
        ) from exc


def _refusal(exc: StorageRefusedError) -> Refusal:
    """A helper storage refusal as an engagement refusal (exit 2, its ``CODE``)."""
    text = str(exc)
    head = text.split(":", 1)[0]
    code = head if head.replace("_", "").isalpha() and head.isupper() else "REFUSED"
    return Refusal(code, text)


def _writer(stack: ExitStack, **kwargs: Any) -> HelperRun:
    """Enter :func:`helper_writer`; a storage-policy refusal becomes a :class:`Refusal`."""
    try:
        return stack.enter_context(helper_writer(acquires=False, **kwargs))
    except StorageRefusedError as exc:
        raise _refusal(exc) from exc


@contextmanager
def open_run(args: argparse.Namespace) -> Iterator[OpenRun]:
    """Open the run named by ``--run-folder`` or ``--run-dir`` (exactly one).

    A ``--run-dir`` run keeps kernel records only where
    :meth:`~starboard_skills.helpers.contract.HelperRun.records_root` allows it:
    an internal-only local run, or a public local run with a LOCAL run
    authorization. A run dir not named by its run ID gets
    :data:`RUN_DIR_NAME_WARNING`; one outside the preflight layout reads its prior
    from the case root only and gets :data:`OUTSIDE_LAYOUT_WARNING` (D4-16).

    Raises:
        ArgError: Neither or both run flags, or a bad ``--run-dir`` (exit 2).
        NotFoundError: A public local run dir without a run authorization; the
            message names ``engagement preflight --storage local`` (exit 4).
        HelperError: A public local run dir whose run authorization is
            unreadable (exit 4).
        Refusal: ``LOCAL_STORAGE_REFUSED`` for ``--run-dir`` on any other run
            (covered, or a copied non-LOCAL descriptor), or ``OUTSIDE_RUN_DIR``
            for a ``--workspace-root`` other than its case root (both exit 2,
            nothing written).
    """
    ctx = _ctx(args)
    folder = getattr(args, "run_folder", None)
    run_dir_arg = getattr(args, "run_dir", None)
    root = getattr(args, "workspace_root", None)
    if bool(folder) == bool(run_dir_arg):
        raise ArgError(
            "pass exactly one of --run-folder (a Drive run) or --run-dir (a local "
            "run: internal-only, or public with a local run authorization)"
        )
    if folder:
        if root:
            raise ArgError(
                "--workspace-root goes with --run-dir; a --run-folder run finds its "
                "prior runs through the account registry"
            )
        with ExitStack() as stack:
            hr = _writer(stack, run_folder=folder, local_root=None)
            auth = hr.descriptor()
            ctx.update(run_id=auth.run_id, run_folder_id=folder)
            yield OpenRun(hr, auth, _account_key(auth), None, args)
        return
    if not root:
        raise ArgError("--run-dir needs --workspace-root (the run's case root)")
    run_dir = Path(str(run_dir_arg)).expanduser().resolve()
    if not run_dir.is_dir():
        raise ArgError(f"--run-dir not found or not a directory: {run_dir}")
    with ExitStack() as stack:
        hr = _writer(stack, run_folder=None, local_root=str(run_dir))
        if hr.records_root(run_dir) is None:
            from starboard_core.engagement.policy import StoragePolicy  # lazy – kernel

            if hr.decision is not None and hr.decision.policy == StoragePolicy.LOCAL:
                try:  # a public run dir: a missing / unreadable descriptor is exit 4
                    read_authorization(run_dir)
                except ArgError as exc:  # (the envelope maps ArgError to usage, 2)
                    missing = not (run_dir / AUTHORIZATION_RECORD).exists()
                    raise (NotFoundError if missing else HelperError)(
                        exc.message
                    ) from exc
            raise Refusal(
                "LOCAL_STORAGE_REFUSED",
                "LOCAL_STORAGE_REFUSED: --run-dir is for local runs (internal-only, "
                "or public with a local run authorization); this run keeps its "
                "records in its Drive run folder (--run-folder)",
            )
        case_root = os.path.realpath(run_dir.parent)
        if os.path.realpath(Path(root).expanduser()) != case_root:
            raise Refusal(
                "OUTSIDE_RUN_DIR",
                f"OUTSIDE_RUN_DIR: --workspace-root {root!r} must be the run dir's "
                f"case root {case_root}",
            )
        auth = read_authorization(run_dir)
        ctx["run_id"] = auth.run_id
        prior_root = local_prior_root(run_dir, auth)
        view = OpenRun(hr, auth, _account_key(auth), prior_root, args)
        if run_dir.name != auth.run_id:
            view.warnings.append(RUN_DIR_NAME_WARNING)
        if not prior_root.account:
            view.warnings.append(OUTSIDE_LAYOUT_WARNING)
        view.warnings.extend(prior_root.warnings)
        yield view


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Inputs:
    """Run-relative inputs of one assessment."""

    manifest: str | None = FINDINGS_MANIFEST_PATH
    facts: str | None = None
    verify: tuple[str, ...] = ()
    interval: tuple[str | None, str | None] = (None, None)


def discover_inputs(run: OpenRun) -> Inputs:
    """The inputs a run already holds: facts, manifest and its run-states slices."""
    verify = tuple(
        rel
        for rel in sorted(run.listing(VERIFY_PREFIX))
        if rel.startswith(f"{VERIFY_PREFIX}{RUN_STATES_TEMPLATE}")
        and rel.endswith(".json")
    )
    return Inputs(
        manifest=FINDINGS_MANIFEST_PATH if run.has(FINDINGS_MANIFEST_PATH) else None,
        facts=FACTS_PATH if run.has(FACTS_PATH) else None,
        verify=verify,
    )


def _capture(run: OpenRun) -> tuple[int, int, tuple[str, ...]]:
    """``(queries, succeeded, unsuccessful query IDs)`` of the run's discovery capture.

    Read from ``discovery/raw/<pack>.json``; ``(0, 0, ())`` when the run holds none.
    """
    statuses: dict[str, str] = {}
    for rel in sorted(run.listing(DISCOVERY_RAW_PREFIX)):
        if not (rel.startswith(DISCOVERY_RAW_PREFIX) and rel.endswith(".json")):
            continue
        doc = run.read_json(rel)
        results = doc.get("results") if isinstance(doc, Mapping) else None
        for r in results if isinstance(results, list) else ():
            qid = r.get("query_id") if isinstance(r, Mapping) else None
            if not isinstance(qid, str) or qid in statuses:
                continue
            status = r.get("status")
            if not isinstance(status, str) or not status:
                status = "succeeded" if r.get("succeeded") else "failed"
            statuses[qid] = status
    unsuccessful = tuple(sorted(q for q, s in statuses.items() if s != "succeeded"))
    return len(statuses), len(statuses) - len(unsuccessful), unsuccessful


def _window(doc: Any, key: str) -> tuple[str, str] | None:
    w = doc.get(key) if isinstance(doc, Mapping) else None
    if (
        isinstance(w, Mapping)
        and isinstance(w.get("start"), str)
        and isinstance(w.get("end"), str)
    ):
        return str(w["start"])[:10], str(w["end"])[:10]
    return None


def _interval(
    run: OpenRun, flags: tuple[str | None, str | None], facts: Any, manifest: Any
) -> tuple[str, str]:
    """Flags, else the facts window, else the manifest / backlog ``facts_window``,
    else ``P<n>D`` ending the day before the run."""
    start, end = flags
    if bool(start) != bool(end):
        raise ArgError("pass both --interval-start and --interval-end, or neither")
    if start and end:
        return start, end
    for found in (_window(facts, "window"), _window(manifest, "facts_window")):
        if found:
            return found
    if run.has(BACKLOG_PATH):
        try:
            found = _window(run.read_json(BACKLOG_PATH), "facts_window")
        except ArgError:
            found = None  # an unreadable backlog only loses this fallback
        if found:
            return found
    days = run.auth.reporting_interval
    if days.startswith("P") and days.endswith("D") and days[1:-1].isdigit():
        stamp = run.run_id.split("_", 1)[0]
        last = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])) - timedelta(
            days=1
        )
        return (
            last - timedelta(days=int(days[1:-1]) - 1)
        ).isoformat(), last.isoformat()
    raise ArgError(
        "no reporting interval: pass --interval-start/--interval-end, or capture "
        "discovery facts with a window"
    )


def _slices(run: OpenRun, rels: Sequence[str], index: Mapping[str, Any]) -> list[Any]:
    from starboard_core.engagement.jobruns import slice_from_verify  # lazy – kernel dep

    out = []
    for rel in rels:
        data = run.read(rel)
        try:
            payload = json.loads(data)
            source = index[rel].source_kind if rel in index else verify_source(payload)
            out.append(
                slice_from_verify(
                    payload,
                    source_kind=source,
                    evidence_id=run.evidence_id(rel, data, index),
                )
            )
        except ValueError as exc:
            raise ArgError(f"--verify {rel}: {exc}") from exc
    return out


def verify_source(payload: Mapping[str, Any]) -> str:
    """The source kind of a verify envelope (``internal`` mirror, else the workspace)."""
    meta = (payload.get("data") or {}).get("verify") or {}
    return (
        "internal_mirror" if meta.get("source") == "internal" else "customer_workspace"
    )


def _merge(base: Sequence[Any], kept: Sequence[Any], key: str) -> list[Any]:
    """``base`` with ``kept`` replacing (or joining) items of the same ``key``."""
    by_key = {getattr(k, key): k for k in kept}
    out = [by_key.pop(getattr(b, key), b) for b in base]
    return [*out, *by_key.values()]


def _investigated(finding: Any, run_id: str) -> int | None:
    """Index of the last ``investigated`` revision ``run_id`` recorded (else ``None``)."""
    for i in range(len(finding.revisions) - 1, -1, -1):
        rev = finding.revisions[i]
        if rev.run_id == run_id and rev.reason == "investigated":
            return i
    return None


def _kept_findings(run: OpenRun) -> list[Any]:
    """This run's case findings and investigated findings (``engagement case``)."""
    return [
        f
        for f in run.records("findings", FINDINGS_PATH)
        if f.run_id == run.run_id
        and (
            f.concern_code.startswith("case:")
            or _investigated(f, run.run_id) is not None
        )
    ]


def _union(*groups: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(x for g in groups for x in g))


def _on_investigation(assessed: Any, kept: Any, run_id: str) -> Any:
    """The fresh assessment chained on top of this run's investigated copy.

    Same ``finding_id`` / episode as ``assessed`` (so health, plays and actions
    agree); the chain keeps every revision up to the last ``investigated`` one and
    adds the assessed revision on top (revision + 1). Case / evidence / action IDs
    are unioned and the host-set cause confidence is kept.
    """
    last = _investigated(kept, run_id)
    if last is None:
        return kept
    base = kept.revisions[: last + 1]
    latest = replace(
        assessed.revisions[-1],
        revision=len(base) + 1,
        cause_confidence=kept.cause_confidence,
    )
    return replace(
        assessed,
        revision=latest.revision,
        revisions=(*base, latest),
        cause_confidence=kept.cause_confidence,
        evidence_ids=_union(kept.evidence_ids, assessed.evidence_ids),
        case_ids=_union(kept.case_ids, assessed.case_ids),
        action_ids=_union(kept.action_ids, assessed.action_ids),
    )


def _merge_findings(
    assessed: Sequence[Any], kept: Sequence[Any], run_id: str
) -> list[Any]:
    """``assessed`` with this run's case work kept (:func:`_on_investigation`)."""
    by_id = {f.finding_id: f for f in assessed}
    chained = [
        _on_investigation(by_id[k.finding_id], k, run_id)
        if k.finding_id in by_id and not k.concern_code.startswith("case:")
        else k
        for k in kept
    ]
    return _merge(assessed, chained, "finding_id")


def _with_host_ranks(plays: Sequence[Any], held: Sequence[Any]) -> list[Any]:
    """``plays`` keeping the host rank / reorder reason already recorded per play."""
    ranked = {p.play_id: p for p in held if p.host_rank is not None}
    return [
        replace(
            p,
            host_rank=ranked[p.play_id].host_rank,
            host_reorder_reason=ranked[p.play_id].host_reorder_reason,
        )
        if p.play_id in ranked
        else p
        for p in plays
    ]


def effective_order(plays: Sequence[Any]) -> list[tuple[int, Any]]:
    """``(effective_rank, play)`` pairs, 1 first: the host-ranked plays by
    ``host_rank``, then every other play in its computed (``play_rules_v1``) order.

    A total order: host-rank ties and unranked plays keep the computed order.
    """
    computed = {p.play_id: i for i, p in enumerate(plays)}
    ordered = sorted(
        plays,
        key=lambda p: (
            p.host_rank is None,
            p.host_rank or 0,
            computed[p.play_id],
        ),
    )
    return list(enumerate(ordered, 1))


def review_rule_of(finding: Any) -> str | None:
    """The review rule behind a rule finding (``rule:<id>``); ``None`` otherwise."""
    code = str(getattr(finding, "concern_code", "") or "")
    return code.removeprefix("rule:") if code.startswith("rule:") else None


def play_digest(
    rank: int,
    play: Any,
    severity: str | None,
    action_id: str | None = None,
    *,
    acceptance_state: str | None = None,
    review_rule_id: str | None = None,
) -> dict[str, Any]:
    """The compact envelope view of one play (no re-read of ``plays.json`` needed)."""
    return {
        "effective_rank": rank,
        "play_id": play.play_id,
        "action_id": action_id,
        "acceptance_state": acceptance_state,
        "review_rule_id": review_rule_id,
        "play_code": play.play_code,
        "interaction_type": play.interaction_type,
        "next_step_kind": play.next_step_kind,
        "target": f"{play.target_entity_kind}:{play.target_entity_id}",
        "finding_ids": list(play.finding_ids),
        "severity": severity,
        "urgency": play.urgency,
        "exposure": dict(play.exposure),
        "host_rank": play.host_rank,
        "reason": play.reason,
        "next_commands": list(play.next_commands),
        "placeholders": list(getattr(play, "placeholders", ())),
    }


def top_plays(
    plays: Sequence[Any],
    severity_of: Mapping[str, str | None],
    action_of: Mapping[str, str],
    limit: int = _TOP_PLAYS,
    *,
    acceptance_of: Mapping[str, str] | None = None,
    rule_of: Mapping[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """The first ``limit`` digest entries in effective order, one per entity target.

    Plays on the same job / warehouse / ... (e.g. a failure-rate rise and a
    failed-spend rule on one job) are one entry: the lead play's digest (its
    exposure only, so no exposure is counted twice) plus ``same_target_plays``
    (``play_id`` / ``play_code`` / ``action_id`` / ``acceptance_state`` /
    ``effective_rank`` of the others). Workspace-grain plays are distinct
    concerns: one entry each. ``acceptance_of`` maps ``action_id`` to its
    acceptance state and ``rule_of`` ``finding_id`` to its review rule.
    """
    states = acceptance_of or {}
    rules = rule_of or {}
    entries: dict[str, dict[str, Any]] = {}
    for rank, p in effective_order(plays):
        target = f"{p.target_entity_kind}:{p.target_entity_id}"
        key = p.play_id if p.target_entity_kind == "workspace" else target
        held = entries.get(key)
        if held is not None:
            action = action_of.get(p.play_id)
            held["same_target_plays"].append(
                {
                    "play_id": p.play_id,
                    "play_code": p.play_code,
                    "action_id": action,
                    "acceptance_state": states.get(action) if action else None,
                    "effective_rank": rank,
                }
            )
            continue
        if len(entries) >= limit:
            continue
        fid = p.finding_ids[0] if p.finding_ids else None
        action = action_of.get(p.play_id)
        entries[key] = {
            **play_digest(
                rank,
                p,
                severity_of.get(fid) if fid else None,
                action,
                acceptance_state=states.get(action) if action else None,
                review_rule_id=rules.get(fid) if fid else None,
            ),
            "same_target_plays": [],
        }
    return list(entries.values())


def action_index(actions: Sequence[Any], run_id: str) -> dict[str, str]:
    """``play_id -> action_id``: this run's action of a play first, else a prior's."""
    action_of: dict[str, str] = {}
    for a in sorted(actions, key=lambda a: a.run_id != run_id):
        if a.play_id:
            action_of.setdefault(a.play_id, a.action_id)
    return action_of


def plays_by_code(plays: Sequence[Any]) -> dict[str, dict[str, Any]]:
    """``{play_code: {"count", "play_ids", "samples"}}``: ``play_ids`` is the first
    :data:`_PLAYS_BY_CODE_IDS` plays of the code in effective order; ``samples``
    digests the first :data:`_PLAYS_BY_CODE_SAMPLES` of them (``play_id`` /
    ``effective_rank`` / ``target`` / ``reason`` / ``exposure``) so a host can
    rank a code's plays without reading ``plays.json``."""
    out: dict[str, dict[str, Any]] = {}
    for rank, p in effective_order(plays):
        entry = out.setdefault(p.play_code, {"count": 0, "play_ids": [], "samples": []})
        entry["count"] += 1
        if len(entry["play_ids"]) < _PLAYS_BY_CODE_IDS:
            entry["play_ids"].append(p.play_id)
        if len(entry["samples"]) < _PLAYS_BY_CODE_SAMPLES:
            entry["samples"].append(
                {
                    "play_id": p.play_id,
                    "effective_rank": rank,
                    "target": f"{p.target_entity_kind}:{p.target_entity_id}",
                    "reason": p.reason,
                    "exposure": dict(p.exposure),
                }
            )
    return out


def findings_by_rule(manifest: Any) -> dict[str, dict[str, int]]:
    """``{rule_id: {"findings", "dropped"}}`` from the findings manifest, most
    findings first: the findings each review rule lists and, for a rule at its
    finding cap, how many more entities matched (``rule_findings_dropped``)."""
    found = manifest.get("findings") if isinstance(manifest, Mapping) else None
    out: dict[str, dict[str, int]] = {}
    for f in found or []:
        if not isinstance(f, Mapping) or not f.get("rule_id"):
            continue
        entry = out.setdefault(str(f["rule_id"]), {"findings": 0, "dropped": 0})
        entry["findings"] += 1
        entry["dropped"] = max(
            entry["dropped"], int(f.get("rule_findings_dropped") or 0)
        )
    return dict(sorted(out.items(), key=lambda kv: (-kv[1]["findings"], kv[0])))


def mirror_templates(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> str | None:
    """``~/<overlay skill>/mirror-verify.md`` when the overlay skill is installed
    and holds it (an internal-only run's ``verify run --templates``), else ``None``.

    The skill is the copy the host loaded when one is known (``find_overlay_skill``:
    ``STARBOARD_OVERLAY_DIR``, the plugin root, the dev-mode plugin paths), before
    any plugin cache. ``~/``-relative so the printed command names no account;
    ``None`` outside ``home`` or when the path needs shell quoting (a quoted ``~``
    does not expand).
    """
    from starboard_core.engagement.overlay import (  # lazy – kernel dep
        find_overlay_skill,
    )

    home = home or Path.home()
    try:
        skill = find_overlay_skill(home, env)
    except OSError:
        return None
    if skill is None or not (skill / MIRROR_TEMPLATES_NAME).is_file():
        return None
    try:
        rel = (skill / MIRROR_TEMPLATES_NAME).relative_to(home).as_posix()
    except ValueError:
        return None
    return f"~/{rel}" if _SAFE_PATH_RE.fullmatch(rel) else None


def run_target(run: OpenRun) -> Any:
    """Where the run's printed commands read and write (:class:`RunTarget`)."""
    from starboard_core.engagement.health import RunTarget  # lazy – kernel dep

    folder = run.helper.run_folder
    run_dir = None if folder else getattr(run.args, "run_dir", None)
    return RunTarget(
        internal=run.internal,
        run_folder=folder,
        run_dir=str(Path(str(run_dir)).expanduser().resolve()) if run_dir else None,
        warehouse_id=None if run.internal else getattr(run.args, "warehouse_id", None),
        profile=None if run.internal else run.auth.workspace_profile,
        mirror_templates=mirror_templates() if run.internal else None,
    )


def _kept_actions(run: OpenRun) -> list[Any]:
    """This run's actions a host or operator already moved (``engagement action``)."""
    return [
        a
        for a in run.records("actions", ACTIONS_PATH)
        if a.run_id == run.run_id and any(e.recorded_by != "rule" for e in a.events)
    ]


def _with_records_only_runs(
    prior_runs: list[dict[str, Any]], prior: PriorRecords, run: OpenRun
) -> list[dict[str, Any]]:
    """``prior_runs`` plus every prior run that left records but no observation
    candidate (e.g. a troubleshooting run's case): ``interval`` null and
    ``skipped_reason`` ``other_task`` (its task is known and is not this run's)
    or ``no_observations``. They follow the observation entries, newest first."""
    seen = {str(r.get("run_id")) for r in prior_runs}
    tasks = {rid: m.task for rid, (_, m) in prior.run_manifests.items()}
    rids = set(tasks)
    for items in (prior.findings, prior.cases, prior.actions):
        rids.update(i.run_id for i in items)
    rids.update(c.opened_run_id for c in prior.cases)
    extra: list[dict[str, Any]] = []
    for rid in sorted(rids - seen - {run.run_id}, reverse=True):
        task = tasks.get(rid) or _local_task(run, rid)
        extra.append(
            {
                "run_id": rid,
                "interval": None,
                "task": task,
                "skipped_reason": "other_task"
                if task and task != run.auth.intent
                else "no_observations",
            }
        )
    return [*prior_runs, *extra]


def _local_task(run: OpenRun, run_id: str) -> str | None:
    """The task of a local prior run dir (its own run authorization), else ``None``."""
    from starboard_core.engagement.prior import _local_owner  # lazy – kernel dep

    if run.prior_root is None:
        return None
    for root in run.prior_root.case_roots:
        run_dir = root / run_id
        if run_dir.is_dir() and not run_dir.is_symlink():
            return _local_owner(run_dir)[1] or None
    return None


def assess(
    run: OpenRun,
    inputs: Inputs,
    *,
    only_folder: str | None = None,
    baseline: bool = False,
) -> dict[str, Any]:
    """Assess the run against its prior records and write its record sets.

    ``only_folder`` reads exactly one prior run folder (``run recur --prior``);
    ``baseline`` assesses against no prior records (``run recur --baseline``).

    Returns:
        The summary: interval, workspace, verdict, families, top plays, counts,
        prior coverage and the written outputs.

    Raises:
        ArgError: A missing / unreadable input, an input the kernel rejects, or
            an explicit ``--prior`` that is unreadable or of another account.
    """
    from starboard_core.engagement.assess import (  # lazy – kernel dep
        CurrentInputs,
        assess_run,
    )
    from starboard_core.engagement.health import (
        ACQUISITION_METHOD,
        no_evidence,
        targeted_requests,
    )

    for rel in (inputs.manifest, inputs.facts, *inputs.verify):
        if rel is not None and not run.has(rel):
            raise ArgError(f"{rel} is not in the run; capture it first")
    index = run.evidence()
    manifest = run.read_json(inputs.manifest) if inputs.manifest else None
    facts = run.read_json(inputs.facts) if inputs.facts else None
    for rel, doc in ((inputs.manifest, manifest), (inputs.facts, facts)):
        if rel is not None and not isinstance(doc, Mapping):
            raise ArgError(f"{rel} must be a JSON object")
    evidence_ids = [
        run.evidence_id(rel, run.read(rel), index)
        for rel in (inputs.manifest, inputs.facts)
        if rel is not None
    ]
    workspace_id = run.workspace(manifest, facts)
    interval = _interval(run, inputs.interval, facts, manifest)
    today = date.fromisoformat(interval[1]) + timedelta(days=1)
    slices = _slices(run, inputs.verify, index)

    from starboard_core.engagement.prior import PriorRecords

    prior = (
        PriorRecords() if baseline else run.prior(workspace_id, only_folder=only_folder)
    )
    if only_folder is not None:
        for gap in prior.unavailable:
            if gap.registration is None and gap.object_id == only_folder:
                raise ArgError(f"--prior drive:{only_folder}: {gap.reason}")
    case_obs = [
        o
        for o in run.records("observations", OBSERVATIONS_PATH)
        if o.run_id == run.run_id and o.method_version == ACQUISITION_METHOD
    ]
    target = run_target(run)
    current = CurrentInputs(
        facts=facts,
        manifest=manifest,
        verify_slices=tuple(slices),
        case_evidence=tuple(case_obs),
        evidence_ids=tuple(evidence_ids),
        source_kind="internal_mirror" if run.internal else "customer_workspace",
    )
    try:
        result = assess_run(
            prior,
            current,
            run_id=run.run_id,
            account_key=run.account_key,
            workspace_id=workspace_id,
            interval=interval,
            today=today,
            task=run.auth.intent,
            target=target,
        )
    except ValueError as exc:
        raise ArgError(f"the run's inputs do not assess: {exc}") from exc

    from starboard_core.engagement.history import window_comparison

    priors = [c for c in prior.observations if c.observation.run_id != run.run_id]
    windows = window_comparison(
        priors,
        interval,
        result.baseline_selection,
        task=run.auth.intent,
        pinned=only_folder is not None,
    )
    prior_runs = windows.pop("prior_runs")
    if windows["reason"] == "window_mismatch":
        run.warnings.append(
            f"window_mismatch: every prior run covers a different window (prior "
            f"{windows['prior_lookback_days']}-day vs current "
            f"{windows['current_lookback_days']}-day lookback); no prior observation "
            "is a baseline and window totals are not comparable"
        )
    elif not windows["comparable"]:
        run.warnings.append(
            f"{windows['reason']}: no prior observation is a baseline for any "
            "comparison key; this run is not comparable to its prior runs and no "
            "action outcome is observed"
        )
    prior_runs = _with_records_only_runs(prior_runs, prior, run)
    if not priors:
        # A baseline (forced, or no prior candidate) compares with nothing: the
        # same contract as ``run recur``'s baseline.
        windows["comparable"] = False
        windows["reason"] = "baseline"

    health = result.health
    queries, succeeded, unsuccessful = _capture(run)
    if queries and not succeeded:
        # Defence in depth: a capture that proved nothing assesses nothing.
        reason = f"no_evidence:discovery_0_of_{queries}_queries_succeeded"
        health = targeted_requests(no_evidence(health, reason, unsuccessful), target)
        run.warnings.append(
            f"discovery captured 0 of {queries} queries successfully — every family "
            "is unknown and the verdict is insufficient_evidence; fix access and "
            "re-run discovery"
        )

    findings = _merge_findings(result.findings, _kept_findings(run), run.run_id)
    plays = _with_host_ranks(result.plays, run.records("plays", PLAYS_PATH))
    cases = _merge(result.cases, run.records("cases", CASES_PATH), "case_id")
    kept_actions = _kept_actions(run)
    actions = _merge(result.actions, kept_actions, "action_id")
    linked: dict[str, list[str]] = {}
    for a in kept_actions:
        linked.setdefault(a.finding_id, []).append(a.action_id)
    # A host-proposed (case) action stays linked from its finding across re-runs.
    findings = [
        replace(f, action_ids=_union(f.action_ids, linked[f.finding_id]))
        if f.finding_id in linked
        else f
        for f in findings
    ]
    observations = _merge(result.observations, case_obs, "observation_id")
    selection = result.baseline_selection.to_dict()
    writes: dict[str, Any] = {
        OBSERVATIONS_PATH: [o.to_dict() for o in observations],
        FINDINGS_PATH: [f.to_dict() for f in findings],
        HEALTH_PATH: health.to_dict(),
        PLAYS_PATH: [p.to_dict() for p in plays],
        CHANGES_PATH: [c.to_dict() for c in result.changes],
        CASES_PATH: [c.to_dict() for c in cases],
        ACTIONS_PATH: [a.to_dict() for a in actions],
        BASELINE_PATH: selection,
    }
    action_of = action_index(actions, run.run_id)
    for rel, payload in writes.items():
        run.put(rel, payload, action_of=action_of if rel == PLAYS_PATH else None)

    comparisons: dict[str, int] = {}
    for row in selection.get("selected", []):
        name = str(row.get("comparison"))
        comparisons[name] = comparisons.get(name, 0) + 1
    states: dict[str, int] = {}
    for f in findings:
        states[f.state] = states.get(f.state, 0) + 1
    severity_of = {f.finding_id: f.severity for f in findings}
    coverage: dict[str, list[str]] = {"complete": [], "partial": [], "unknown": []}
    for f in health.families:
        coverage.setdefault(f.coverage, []).append(f.family)
    by_family: dict[str, int] = {}
    for o in observations:
        by_family[o.family] = by_family.get(o.family, 0) + 1
    if prior.unavailable:
        run.warnings.append(
            f"{len(prior.unavailable)} prior record set(s) unavailable — recorded as "
            "history_unavailable and never used as a baseline"
        )
    return {
        "interval": {"start": interval[0], "end": interval[1]},
        "workspace_id": workspace_id,
        "verdict": health.verdict,
        "families": [
            {
                "family": f.family,
                "assessment": f.assessment,
                "coverage": f.coverage,
                "severity": f.severity,
            }
            for f in health.families
        ],
        # The six families by coverage (each family's own coverage is in families[]).
        "coverage": coverage,
        # The digest: the first plays in effective order (host rank, then computed),
        # one entry per entity target, so a host need not re-read plays.json /
        # observations.json to act on them.
        "top_plays": top_plays(
            plays,
            severity_of,
            action_of,
            acceptance_of={a.action_id: a.acceptance_state for a in actions},
            rule_of={f.finding_id: review_rule_of(f) for f in findings},
        ),
        "plays_by_code": plays_by_code(plays),
        "observations_by_family": by_family,
        "findings_by_rule": findings_by_rule(manifest),
        # A baseline run had no prior candidate at all; a run whose priors were all
        # rejected (window_mismatch, ...) is a not-comparable recurrence instead.
        "baseline": not priors,
        "comparable": windows["comparable"],
        "not_comparable_reason": windows["reason"],
        "window": windows,
        "prior_runs": prior_runs,
        "comparisons": comparisons,
        "finding_states": states,
        "counts": {
            "observations": len(observations),
            "findings": len(findings),
            "plays": len(plays),
            "changes": len(result.changes),
            "cases": len(cases),
            "actions": len(actions),
            "prior_candidates": len(prior.observations),
            "prior_unavailable": len(prior.unavailable),
        },
        "inputs": {
            "manifest": inputs.manifest,
            "facts": inputs.facts,
            "verify": list(inputs.verify),
        },
        "outputs": list(writes),
    }


# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #
def cmd_analyze(args: argparse.Namespace) -> dict[str, Any]:
    with open_run(args) as run:
        _ctx(args)["stage"] = "analysis"
        found = discover_inputs(run)
        inputs = Inputs(
            manifest=args.manifest or found.manifest,
            facts=args.facts or found.facts,
            verify=tuple(args.verify) if args.verify else found.verify,
            interval=(args.interval_start, args.interval_end),
        )
        return run.result(
            assess(
                run,
                inputs,
                only_folder=_prior_folder(run, args),
                baseline=args.baseline,
            )
        )


def _prior_folder(run: OpenRun, args: argparse.Namespace) -> str | None:
    """The ``--prior drive:<id>`` folder, checked exactly as ``run recur`` checks it.

    A local run reads every prior run of its prior root, as local ``run recur``
    does, so ``--prior`` there only gets a warning.
    """
    from starboard_skills.helpers.run import DRIVE_PREFIX, _check_prior_folder

    prior = args.prior
    if not prior:
        return None
    if run.prior_root is not None:
        run.warnings.append(
            "--prior picks the trend delta only; the analysis reads every prior run "
            f"of {run.prior_root.label}"
        )
        return None
    if not prior.startswith(DRIVE_PREFIX):
        raise ArgError("--prior with --run-folder must be drive:<run_folder_id>")
    folder = prior[len(DRIVE_PREFIX) :]
    if folder == run.helper.run_folder:
        raise ArgError("--prior must be a different run folder than --run-folder")
    _check_prior_folder(run.helper, run.account_key, folder)
    return folder
