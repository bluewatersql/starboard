# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Drive folder resolver for engagement runs (engagement-drive spec §3).

Maps a verified account (or a validated ``AR-`` ticket) to remote folder IDs over
:class:`~starboard_core.ports.engagement_storage.EngagementStoragePort`. Names are
presentation, IDs are authority: every folder carries a ``starboard_identity``
property, and each level is resolved by listing only the children of a known
parent ID.

Routes:

* account: ``My Drive -> starboard -> <ACCOUNT> -> <TASK> -> <TASK NAME> -> <RUN ID>``
* ticket: ``<shared root> -> <ACCOUNT> -> AR-NNNNNNNNN: <TITLE> -> starboard ->
  <TASK> -> <TASK NAME> -> <RUN ID>``
* override: ``<override folder> -> starboard -> <TASK> -> <TASK NAME> -> <RUN ID>``
  (an operator-named folder; D-8)

Drive has no compare-and-set (phase-0 fact F5), so a create is followed by a
re-list. Folders that carry the *same* identity (a concurrent double-create)
converge on one deterministic winner: the earliest ``created_time``, ties broken
by the smallest ID. Nothing is ever trashed or deleted; the losers stay for
operator reconciliation. A same-named folder with a *different* or missing
identity still stops for reconciliation.

Account folders resolve by identity first (:func:`ensure_account_folder`): the
folder tagged ``account:<key>`` is reused whatever its display name, so a run
routed under one name and analyzed under another sees the same folder.

Owner decision D6 (no test writes): the ticket route reads ``can_add_children``
on the shared root before writing; when it is false, or a create under the
ticket route is refused, the run falls back to the ``My Drive`` account route
with a visible warning. Authentication errors are never a fallback.

Owner ACL rule (fact F3): the ticket folder must be internal-staff-only. A
widened or unverifiable ACL raises :class:`FolderAccessError` instead of
silently falling back, so the operator sees that the ticket folder's sharing is
not what the route assumes.

The override route is preflighted like the ticket route: not writable (or not
accessible) falls back to My Drive with a warning; a widened or unverifiable ACL
raises :class:`OverrideNotRestrictedError`, with no fallback.

The resolver never accepts or returns local filesystem paths.
"""

from __future__ import annotations

import dataclasses
import re
import time
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from starboard_core.ports.engagement_storage import (
    AccessInfo,
    EngagementStoragePort,
    StorageIntegrityError,
    StorageNotFoundError,
    StorageObject,
    StoragePermissionError,
)

IDENTITY_PROPERTY = "starboard_identity"
STARBOARD_SEGMENT = "starboard"
MY_DRIVE_LABEL = "My Drive"
DEFAULT_MAX_NAME_LEN = 120

AR_KEY_PATTERN = re.compile(r"^AR-[0-9]{9}$")


def ticket_folder_title(ar_key: str, title: str) -> str:
    """``AR-NNNNNNNNN: <title>``, the ASQ folder naming (a space after the colon), so
    a run lands in the hand-made ticket folder instead of beside it."""
    return f"{ar_key}: {title}"


_SEPARATORS = ("/", "\\")

Route = Literal["account", "ticket", "override"]
AccessClass = Literal["internal_only", "widened", "unknown"]


class FolderResolutionError(Exception):
    """Base class for folder-resolution failures that need operator action."""


class FolderConflictError(FolderResolutionError):
    """Same-named folders under one parent could not be resolved to one identity.

    Attributes:
        parent_id: The parent folder that was listed.
        name: The sanitized folder name.
        identity_key: The identity being resolved.
        object_ids: IDs of the same-named folders found.
        existing_identities: Each found folder's identity (``None`` when it has
            none), aligned with ``object_ids``; empty when the caller did not say.
    """

    def __init__(
        self,
        message: str,
        *,
        parent_id: str,
        name: str,
        identity_key: str,
        object_ids: Iterable[str],
        existing_identities: Iterable[str | None] = (),
    ) -> None:
        super().__init__(message)
        self.parent_id = parent_id
        self.name = name
        self.identity_key = identity_key
        self.object_ids = tuple(object_ids)
        self.existing_identities = tuple(existing_identities)

    @property
    def other_account_key(self) -> str | None:
        """The account key owning the name, when that is the whole conflict.

        Set only when an account folder is being resolved and exactly one
        same-named folder exists, tagged as a *different* account: the name is
        simply another account's, so no Drive reconciliation applies.
        """
        return _other_account_key(self.identity_key, self.existing_identities)


class FolderAccessError(FolderResolutionError):
    """A route folder's effective ACL is not internal-only (widened or unknown).

    Attributes:
        object_id: The folder whose access was classified.
        classification: ``widened`` or ``unknown``.
        fingerprint: The provider ACL fingerprint that was classified.
    """

    def __init__(
        self,
        message: str,
        *,
        object_id: str,
        classification: AccessClass,
        fingerprint: str,
    ) -> None:
        super().__init__(message)
        self.object_id = object_id
        self.classification = classification
        self.fingerprint = fingerprint


class OverrideNotRestrictedError(FolderAccessError):
    """The override folder (or its run folder) is not internal-staff-only (D-8)."""


@dataclass(frozen=True)
class FolderResolution:
    """Resolved folder IDs for one run.

    Attributes:
        route: ``account`` (My Drive), ``ticket`` (shared root) or ``override``
            (operator-named folder). A ticket or override request that fell back
            reports ``account``.
        base_id: My Drive root ID, the shared root ID or the override folder ID.
        account_folder_id: The verified account folder. On the override route it
            is the override folder itself (there is no account level).
        ticket_folder_id: The ``AR-...: <title>`` folder, ticket route only.
        run_folder_id: The ``<RUN ID>`` folder that holds the run's objects.
        path_names: Display names from the base down to the run folder.
        access: Effective access of the run folder.
        links: Provider links keyed by role (``base``, ``account``,
            ``ticket``, ``run``) when the provider returns them.
        fallback_warning: Human message when a requested ticket or override
            destination was not writable and results went to My Drive instead.
        warnings: Folder warnings: ``duplicate_starboard_roots:`` from
            :func:`ensure_starboard_root` (account route), then
            ``account_name_differs:`` / ``duplicate_account_folders:`` from
            :func:`ensure_account_folder`.
    """

    route: Route
    base_id: str
    account_folder_id: str
    ticket_folder_id: str | None
    run_folder_id: str
    path_names: tuple[str, ...]
    access: AccessInfo
    links: Mapping[str, str] = field(default_factory=dict)
    fallback_warning: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccountFolder:
    """The account folder an identity resolves to.

    Attributes:
        folder: The folder reads and writes use (the winner).
        duplicates: Other folders that carry the same identity, oldest first.
            Reads merge their registrations; nothing is written to them.
        warnings: ``account_name_differs:`` when the reused folder's name is not
            the requested one; ``duplicate_account_folders:`` when ``duplicates``
            is non-empty.
    """

    folder: StorageObject
    duplicates: tuple[StorageObject, ...] = ()
    warnings: tuple[str, ...] = ()


def sanitize_folder_name(name: str, max_len: int = DEFAULT_MAX_NAME_LEN) -> str:
    """Return a Drive-safe display name.

    NFC-normalizes, turns whitespace control characters into spaces, drops other
    control/format characters, replaces ``/`` and ``\\`` with ``-``, collapses
    whitespace and caps the length. Readable punctuation, including the ``:``
    ticket separator, is kept.

    Raises:
        ValueError: If ``max_len`` is not positive or nothing printable remains.
    """
    if max_len < 1:
        raise ValueError("max_len must be positive")
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", name):
        if ch.isspace():
            out.append(" ")
        elif ch in _SEPARATORS:
            out.append("-")
        elif unicodedata.category(ch).startswith("C"):
            continue
        else:
            out.append(ch)
    cleaned = " ".join(unicodedata.normalize("NFC", "".join(out)).split())
    cleaned = cleaned[:max_len].rstrip()
    if not cleaned:
        raise ValueError(f"folder name {name!r} is empty after sanitization")
    return cleaned


def classify_access(
    access: AccessInfo, internal_domains: frozenset[str]
) -> AccessClass:
    """Classify an ACL as ``internal_only``, ``widened`` or ``unknown``.

    ``widened`` wins whenever a visible grant proves exposure: any ``anyone``
    grant, or a ``domain``/``user``/``group`` grant whose domain is outside
    ``internal_domains`` (exact, case-insensitive match; subdomains are not
    implied). Otherwise the ACL is ``unknown`` when the listing is incomplete or
    a grant has no domain to check, else ``internal_only``.
    """
    allowed = {d.lower() for d in internal_domains}
    unknown = not access.complete
    for grant in access.grants:
        if grant.kind == "anyone":
            return "widened"
        if grant.domain is None:
            unknown = True
        elif grant.domain.lower() not in allowed:
            return "widened"
    return "unknown" if unknown else "internal_only"


#: Email domains that may ever count as internal staff (decisions F3: every
#: principal on the ASQs root is ``@databricks.com``). A caller's
#: ``--internal-domain`` list can only narrow this set, never widen it.
PINNED_INTERNAL_DOMAINS: frozenset[str] = frozenset({"databricks.com"})


def effective_internal_domains(
    requested: Iterable[str], *, pinned: frozenset[str] = PINNED_INTERNAL_DOMAINS
) -> frozenset[str]:
    """Return the internal-domain set: ``pinned`` narrowed by ``requested``.

    An empty ``requested`` means the whole pinned set. A requested domain that is
    not pinned raises :class:`ValueError` rather than being dropped quietly, so a
    typo or an attempt to count an outside domain as internal fails closed.
    """
    allowed = frozenset(d.lower() for d in pinned)
    wanted = frozenset(d.strip().lower() for d in requested)
    unpinned = sorted(wanted - allowed)
    if unpinned:
        raise ValueError(
            f"{', '.join(unpinned)} is not a pinned internal domain "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    return wanted or allowed


def creation_order(obj: StorageObject) -> tuple[str, str]:
    """Sort key that puts the convergence winner first.

    Earliest ``created_time`` (RFC 3339, so it sorts as text) wins; a tie or a
    missing time falls back to the smallest ID. Every caller that must agree on
    one of several same-identity folders uses this key.
    """
    return (obj.created_time or "\uffff", obj.id)


def identity_children(
    storage: EngagementStoragePort, parent_id: str, identity_key: str
) -> list[StorageObject]:
    """Folders under ``parent_id`` tagged exactly ``identity_key``, winner first."""
    return sorted(
        (
            c
            for c in storage.list_children(parent_id, folders_only=True)
            if c.properties.get(IDENTITY_PROPERTY) == identity_key
        ),
        key=creation_order,
    )


def identity_children_under(
    storage: EngagementStoragePort, parent_ids: Iterable[str], identity_key: str
) -> list[StorageObject]:
    """:func:`identity_children` across several parents, winner first."""
    return sorted(
        (c for p in parent_ids for c in identity_children(storage, p, identity_key)),
        key=creation_order,
    )


def account_folder_from(
    matches: list[StorageObject],
    *,
    parent_id: str,
    account_key: str,
    account_name: str | None = None,
) -> AccountFolder:
    """Pick the winner of exact-identity ``matches`` and describe the outcome.

    Raises:
        ValueError: ``matches`` is empty.
    """
    if not matches:
        raise ValueError("account_folder_from needs at least one match")
    ordered = sorted(matches, key=creation_order)
    winner, rest = ordered[0], tuple(ordered[1:])
    warnings: list[str] = []
    if rest:
        ids = ", ".join(o.id for o in ordered)
        parents = dict.fromkeys(p for o in ordered for p in o.parent_ids)
        where = ", ".join(parents) if len(parents) > 1 else parent_id
        warnings.append(
            f"duplicate_account_folders: {len(ordered)} folders under {where} "
            f"carry identity 'account:{account_key}' (ids: {ids}); writes go to the "
            f"earliest-created {winner.id} ({winner.name!r}) and reads merge all of "
            "them. Reconcile in Drive: move the contents into one folder, trash the "
            "others, then run `engagement rebuild-index`."
        )
    if account_name:
        wanted = sanitize_folder_name(account_name)
        if winner.name != wanted:
            warnings.append(
                f"account_name_differs: account key {account_key!r} already has "
                f"folder {winner.id} named {winner.name!r}; reusing it (requested "
                f"name {wanted!r}). Rename the folder in Drive if the name is wrong."
            )
    return AccountFolder(folder=winner, duplicates=rest, warnings=tuple(warnings))


def ensure_account_folder(
    storage: EngagementStoragePort,
    parent_id: str,
    account_name: str,
    account_key: str,
    *,
    also_under: Sequence[str] = (),
) -> AccountFolder:
    """Find or create the account folder by identity first, then by name.

    Lists the children of ``parent_id`` (and of each ``also_under`` parent: the
    duplicate ``starboard`` roots) for the exact ``account:<account_key>`` tag.
    One match is reused whatever its display name (``account_name_differs:``
    warning when the name differs); several converge on the
    :func:`creation_order` winner with a ``duplicate_account_folders:`` warning.
    With no match the folder is found or created by name under ``parent_id``
    (:func:`ensure_folder`, which still adopts a single untagged same-named
    folder), then re-listed by identity so a concurrent create under another
    name converges too.

    Raises:
        FolderConflictError: No identity match and the name is taken by a folder
            with a different identity.
        StorageIntegrityError: The created folder is not listed on read-back.
    """
    identity = f"account:{account_key}"
    parents = (parent_id, *also_under)
    matches = identity_children_under(storage, parents, identity)
    if not matches:
        found = ensure_folder(storage, parent_id, account_name, identity)
        if found.properties.get(IDENTITY_PROPERTY) != identity:
            return AccountFolder(folder=found)  # an adopted untagged folder
        matches = identity_children_under(storage, parents, identity)
        if found.id not in {m.id for m in matches}:
            raise StorageIntegrityError(
                f"account folder {found.id} is not listed under {parent_id} with "
                f"identity {identity!r} on read-back"
            )
    return account_folder_from(
        matches, parent_id=parent_id, account_key=account_key, account_name=account_name
    )


def ensure_folder(
    storage: EngagementStoragePort,
    parent_id: str,
    name: str,
    identity_key: str,
    *,
    adopt_untagged: bool = True,
) -> StorageObject:
    """Find or create the folder ``name`` with ``identity_key`` under ``parent_id``.

    Reuses the same-named child carrying the identity; creates one when no
    same-named child exists, then re-lists to detect a concurrent duplicate.
    Several same-named children that all carry the identity (before or after the
    create) converge on the :func:`creation_order` winner; none is deleted.
    When ``adopt_untagged`` is True, a single same-named child with no identity
    tag is adopted as-is (not re-tagged): hand-made ASQ account/ticket folders
    and earlier Starboard deliveries predate the tag. Run folders pass False.

    Raises:
        FolderConflictError: A same-named child with a different identity, or
            (without adoption) a missing identity, or several untagged ones
            (before or after the create).
        StorageIntegrityError: The created folder does not read back with the
            expected parent and identity.
    """
    clean = sanitize_folder_name(name)
    existing = existing_folders(
        storage, parent_id, clean, identity_key, adopt_untagged=adopt_untagged
    )
    if existing:
        return existing[0]
    return create_and_converge(storage, parent_id, clean, identity_key)


#: Backoff (seconds) between re-lists of a just-created folder: Drive's listing can lag
#: a create (live customer run 2026-10-22: route failed "not listed on read-back").
RELIST_DELAYS = (0.5, 1.0, 2.0, 4.0)
_sleep = time.sleep


def list_after_create(
    storage: EngagementStoragePort, parent_id: str, name: str, created_id: str
) -> list[StorageObject]:
    """List ``parent_id``'s ``name`` folders until ``created_id`` shows (bounded backoff).

    Returns the last listing; the caller decides what a listing without it means.
    """
    listed = storage.list_children(parent_id, name=name, folders_only=True)
    for delay in RELIST_DELAYS:
        if any(c.id == created_id for c in listed):
            break
        _sleep(delay)
        listed = storage.list_children(parent_id, name=name, folders_only=True)
    return listed


def create_and_converge(
    storage: EngagementStoragePort, parent_id: str, name: str, identity_key: str
) -> StorageObject:
    """Create ``name`` under ``parent_id``, then re-list and converge on the winner.

    For a caller that has just listed ``parent_id`` and found no such child (the
    second half of :func:`ensure_folder`), so the Drive list call isn't repeated.

    Raises:
        FolderConflictError: A same-named child with another identity appeared.
        StorageIntegrityError: The created folder does not read back with the
            expected parent and identity.
    """
    clean = sanitize_folder_name(name)
    created = storage.create_folder(parent_id, clean, {IDENTITY_PROPERTY: identity_key})
    after = list_after_create(storage, parent_id, clean, created.id)
    if not after:
        raise StorageIntegrityError(
            f"created folder {created.id} is not listed under {parent_id} on read-back"
        )
    match = _single_match(after, parent_id, clean, identity_key, after_create=True)
    mine = next((c for c in after if c.id == created.id), None)
    if (
        mine is None
        or parent_id not in mine.parent_ids
        or mine.properties.get(IDENTITY_PROPERTY) != identity_key
    ):
        raise StorageIntegrityError(
            f"created folder {created.id} did not read back under {parent_id} "
            f"with identity {identity_key!r}"
        )
    return match


def existing_folders(
    storage: EngagementStoragePort,
    parent_id: str,
    name: str,
    identity_key: str,
    *,
    adopt_untagged: bool = True,
) -> list[StorageObject]:
    """The existing folders :func:`ensure_folder` would reuse, winner first. Never creates.

    Empty when no same-named child exists. A single untagged same-named child is
    adopted (when ``adopt_untagged``). Several same-named children that all carry
    ``identity_key`` (a concurrent double-create) are all returned in
    :func:`creation_order`, so a lookup by run ID or account can search every one.

    Raises:
        FolderConflictError: A same-named child with a different identity, or
            (without adoption) a missing identity.
    """
    clean = sanitize_folder_name(name)
    found = storage.list_children(parent_id, name=clean, folders_only=True)
    if not found:
        return []
    if (
        adopt_untagged
        and len(found) == 1
        and IDENTITY_PROPERTY not in found[0].properties
    ):
        return [found[0]]
    # Raises on any foreign or missing identity; every match converges.
    _single_match(found, parent_id, clean, identity_key)
    return sorted(found, key=creation_order)


@dataclass(frozen=True)
class StarboardRoot:
    """The ``My Drive/starboard`` folder and any same-identity duplicates.

    Attributes:
        folder: The :func:`creation_order` winner; writes go here.
        duplicates: The other ``segment:starboard`` folders (two first runs at
            once); lookups by run ID or account search them too.
        warnings: A ``duplicate_starboard_roots:`` warning when there are duplicates.
    """

    folder: StorageObject
    duplicates: tuple[StorageObject, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def all_ids(self) -> tuple[str, ...]:
        """Winner first, then the duplicates."""
        return (self.folder.id, *(d.id for d in self.duplicates))


def starboard_roots(storage: EngagementStoragePort) -> list[StorageObject]:
    """Every existing ``My Drive/starboard`` folder, winner first. Never creates."""
    return existing_folders(
        storage,
        storage.root_folder_id(),
        STARBOARD_SEGMENT,
        _segment_key(STARBOARD_SEGMENT),
    )


def ensure_starboard_root(
    storage: EngagementStoragePort, roots: Sequence[StorageObject] | None = None
) -> StarboardRoot:
    """Find or create ``My Drive/starboard``; duplicates converge on the winner.

    Two first runs at once can each create the folder before either sees the
    other's (Drive lists are eventually consistent), so the losers are reported,
    never treated as a conflict, and nothing is trashed.

    Args:
        storage: The Drive port.
        roots: The caller's fresh :func:`starboard_roots` result, so My Drive
            isn't listed twice.
    """
    roots = list(starboard_roots(storage) if roots is None else roots)
    if not roots:
        roots = [
            create_and_converge(
                storage,
                storage.root_folder_id(),
                STARBOARD_SEGMENT,
                _segment_key(STARBOARD_SEGMENT),
            )
        ]
    winner, rest = roots[0], tuple(roots[1:])
    warnings: tuple[str, ...] = ()
    if rest:
        ids = ", ".join(r.id for r in roots)
        warnings = (
            f"duplicate_starboard_roots: {len(roots)} folders named "
            f"{STARBOARD_SEGMENT!r} in {MY_DRIVE_LABEL} carry identity "
            f"'segment:{STARBOARD_SEGMENT}' (ids: {ids}), most likely two first runs "
            f"at once; writes go to the earliest-created {winner.id} and run and "
            "account lookups search all of them. Reconcile in Drive when convenient: "
            "move the contents into one folder, trash the others, then run "
            "`engagement rebuild-index`.",
        )
    return StarboardRoot(folder=winner, duplicates=rest, warnings=warnings)


def _single_match(
    candidates: list[StorageObject],
    parent_id: str,
    name: str,
    identity_key: str,
    *,
    after_create: bool = False,
) -> StorageObject:
    matches = [
        c for c in candidates if c.properties.get(IDENTITY_PROPERTY) == identity_key
    ]
    ids = [c.id for c in candidates]
    if matches and len(matches) == len(candidates):
        # One match, or a concurrent double-create of the same identity: every
        # caller converges on the same winner; the others stay for reconciliation.
        return min(matches, key=creation_order)
    identities = [c.properties.get(IDENTITY_PROPERTY) for c in candidates]
    other = _other_account_key(identity_key, identities)
    if other is not None:
        raise FolderConflictError(
            f"folder {name!r} under parent {parent_id} belongs to account key "
            f"{other!r} (id {ids[0]}); if this is the same account re-run preflight "
            f"with --account-key {other}, else choose a different --account-name",
            parent_id=parent_id,
            name=name,
            identity_key=identity_key,
            object_ids=ids,
            existing_identities=identities,
        )
    reason = (
        f"folder name {name!r} is already used by {len(candidates) - len(matches)} "
        f"folder(s) with a different or missing identity"
    )
    if after_create:
        reason += " after create"
    raise FolderConflictError(
        f"{reason.strip()} under parent {parent_id}; reconcile in Drive (ids: {', '.join(ids)})",
        parent_id=parent_id,
        name=name,
        identity_key=identity_key,
        object_ids=ids,
        existing_identities=identities,
    )


def _other_account_key(
    identity_key: str, identities: Sequence[str | None]
) -> str | None:
    """``<other>`` when resolving ``account:<key>`` met exactly one ``account:<other>``."""
    prefix = "account:"
    if not identity_key.startswith(prefix) or len(identities) != 1:
        return None
    found = identities[0]
    if not found or not found.startswith(prefix) or found == identity_key:
        return None
    return found[len(prefix) :] or None


def _segment_key(name: str) -> str:
    return f"segment:{sanitize_folder_name(name)}"


def _require_text(value: str, label: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value.strip()


def _build_tail(
    storage: EngagementStoragePort,
    parent_id: str,
    task: str,
    task_name: str,
    run_id: str,
) -> tuple[StorageObject, StorageObject, StorageObject]:
    task_obj = ensure_folder(storage, parent_id, task, _segment_key(task))
    name_obj = ensure_folder(storage, task_obj.id, task_name, _segment_key(task_name))
    run_obj = ensure_folder(
        storage, name_obj.id, run_id, f"run:{run_id}", adopt_untagged=False
    )
    return task_obj, name_obj, run_obj


def _links(**objs: StorageObject | None) -> dict[str, str]:
    return {
        role: o.web_link for role, o in objs.items() if o is not None and o.web_link
    }


def resolve_account_route(
    storage: EngagementStoragePort,
    *,
    account_key: str,
    account_name: str,
    task: str,
    task_name: str,
    run_id: str,
) -> FolderResolution:
    """Resolve ``My Drive/starboard/<ACCOUNT>/<TASK>/<TASK NAME>/<RUN ID>``.

    Permission and auth errors propagate: there is no further fallback.
    """
    account_key = _require_text(account_key, "account_key")
    run_id = _require_text(run_id, "run_id")
    root_id = storage.root_folder_id()
    base = storage.get(root_id)
    root = ensure_starboard_root(storage)
    starboard = root.folder
    resolved = ensure_account_folder(
        storage,
        starboard.id,
        account_name,
        account_key,
        also_under=root.all_ids[1:],
    )
    account = resolved.folder
    task_obj, name_obj, run_obj = _build_tail(
        storage, account.id, task, task_name, run_id
    )
    return FolderResolution(
        route="account",
        base_id=root_id,
        account_folder_id=account.id,
        ticket_folder_id=None,
        run_folder_id=run_obj.id,
        path_names=(
            MY_DRIVE_LABEL,
            starboard.name,
            account.name,
            task_obj.name,
            name_obj.name,
            run_obj.name,
        ),
        links=_links(base=base, account=account, run=run_obj),
        access=storage.inspect_access(run_obj.id),
        warnings=(*root.warnings, *resolved.warnings),
    )


def _ensure_ticket_folder(
    storage: EngagementStoragePort, account_id: str, ar_key: str, title: str
) -> StorageObject:
    """The ticket folder: the one named ``AR-NNNNNNNNN: <title>`` (a hand-made ASQ
    folder included), else the one tagged ``ticket:<AR>`` under any name (an earlier
    unspaced name, or a ticket title that changed), else a new one."""
    name = sanitize_folder_name(ticket_folder_title(ar_key, title))
    identity = f"ticket:{ar_key}"
    named = existing_folders(storage, account_id, name, identity)
    if named:
        return named[0]
    tagged = identity_children(storage, account_id, identity)
    if tagged:
        return tagged[0]
    return create_and_converge(storage, account_id, name, identity)


def resolve_ticket_route(
    storage: EngagementStoragePort,
    *,
    shared_root_id: str,
    account_key: str,
    account_name: str,
    ar_key: str,
    ticket_title: str,
    task: str,
    task_name: str,
    run_id: str,
    internal_domains: frozenset[str],
) -> FolderResolution:
    """Resolve the ticket route, falling back to My Drive when it is not writable.

    Args:
        internal_domains: Email domains whose users/groups/domain grants count
            as internal staff. Required and non-empty; the kernel hard-codes none.

    Raises:
        ValueError: Invalid ``ar_key`` (must match ``AR-NNNNNNNNN``), empty title
            or empty ``internal_domains``.
        FolderAccessError: The ticket or run folder ACL is widened or unknown.
        FolderConflictError: A level could not be resolved to one folder.
        StorageAuthError: Not authenticated; the caller prompts for auth.
    """
    if not AR_KEY_PATTERN.match(ar_key):
        raise ValueError(f"ticket key {ar_key!r} must match AR-NNNNNNNNN")
    if not internal_domains:
        raise ValueError(
            "internal_domains must name at least one internal email domain"
        )
    account_key = _require_text(account_key, "account_key")
    run_id = _require_text(run_id, "run_id")
    title = sanitize_folder_name(ticket_title)
    account_kw = {
        "account_key": account_key,
        "account_name": account_name,
        "task": task,
        "task_name": task_name,
        "run_id": run_id,
    }

    def fall_back(reason: str) -> FolderResolution:
        result = resolve_account_route(storage, **account_kw)
        warning = (
            f"The requested ticket destination for {ar_key} under shared folder "
            f"{shared_root_id} is not writable ({reason}). Results are in "
            f"{'/'.join(result.path_names)} instead."
        )
        return dataclasses.replace(result, fallback_warning=warning)

    try:
        root_access = storage.inspect_access(shared_root_id)
    except (StoragePermissionError, StorageNotFoundError) as exc:
        return fall_back(f"shared folder not accessible: {exc}")
    if not root_access.can_add_children:
        return fall_back("no permission to add folders to the shared folder")

    try:
        base = storage.get(shared_root_id)
        resolved = ensure_account_folder(
            storage, shared_root_id, account_name, account_key
        )
        account = resolved.folder
        ticket = _ensure_ticket_folder(storage, account.id, ar_key, title)
        _require_internal(storage.inspect_access(ticket.id), internal_domains)
        starboard = ensure_folder(
            storage, ticket.id, STARBOARD_SEGMENT, _segment_key(STARBOARD_SEGMENT)
        )
        task_obj, name_obj, run_obj = _build_tail(
            storage, starboard.id, task, task_name, run_id
        )
    except StoragePermissionError as exc:
        return fall_back(f"permission denied while creating folders: {exc}")

    run_access = storage.inspect_access(run_obj.id)
    _require_internal(run_access, internal_domains)
    return FolderResolution(
        route="ticket",
        base_id=shared_root_id,
        account_folder_id=account.id,
        ticket_folder_id=ticket.id,
        run_folder_id=run_obj.id,
        path_names=(
            base.name,
            account.name,
            ticket.name,
            starboard.name,
            task_obj.name,
            name_obj.name,
            run_obj.name,
        ),
        links=_links(base=base, account=account, ticket=ticket, run=run_obj),
        access=run_access,
        warnings=resolved.warnings,
    )


def resolve_override_route(
    storage: EngagementStoragePort,
    *,
    override_folder_id: str,
    account_key: str,
    account_name: str,
    task: str,
    task_name: str,
    run_id: str,
    internal_domains: frozenset[str],
) -> FolderResolution:
    """Resolve ``<override folder>/starboard/<TASK>/<TASK NAME>/<RUN ID>`` (D-8).

    ``account_key`` / ``account_name`` are used only for the My Drive fallback.

    Raises:
        ValueError: Empty ``override_folder_id``, ``account_key``, ``run_id`` or
            ``internal_domains``.
        OverrideNotRestrictedError: The override or run folder ACL is widened or
            unknown. Nothing falls back.
        FolderConflictError: A level could not be resolved to one folder.
        StorageAuthError: Not authenticated; the caller prompts for auth.
    """
    override_folder_id = _require_text(override_folder_id, "override_folder_id")
    if not internal_domains:
        raise ValueError(
            "internal_domains must name at least one internal email domain"
        )
    account_kw = {
        "account_key": _require_text(account_key, "account_key"),
        "account_name": account_name,
        "task": task,
        "task_name": task_name,
        "run_id": _require_text(run_id, "run_id"),
    }

    def fall_back(reason: str) -> FolderResolution:
        result = resolve_account_route(storage, **account_kw)
        warning = (
            f"The override folder {override_folder_id} is not writable ({reason}). "
            f"Results are in {'/'.join(result.path_names)} instead."
        )
        return dataclasses.replace(result, fallback_warning=warning)

    try:
        root_access = storage.inspect_access(override_folder_id)
    except (StoragePermissionError, StorageNotFoundError) as exc:
        return fall_back(f"folder not accessible: {exc}")
    if not root_access.can_add_children:
        return fall_back("no permission to add folders to it")
    _require_internal(root_access, internal_domains, error=OverrideNotRestrictedError)

    try:
        base = storage.get(override_folder_id)
        starboard = ensure_folder(
            storage,
            override_folder_id,
            STARBOARD_SEGMENT,
            _segment_key(STARBOARD_SEGMENT),
        )
        task_obj, name_obj, run_obj = _build_tail(
            storage, starboard.id, task, task_name, account_kw["run_id"]
        )
    except StoragePermissionError as exc:
        return fall_back(f"permission denied while creating folders: {exc}")

    run_access = storage.inspect_access(run_obj.id)
    _require_internal(run_access, internal_domains, error=OverrideNotRestrictedError)
    return FolderResolution(
        route="override",
        base_id=override_folder_id,
        account_folder_id=override_folder_id,
        ticket_folder_id=None,
        run_folder_id=run_obj.id,
        path_names=(
            base.name,
            starboard.name,
            task_obj.name,
            name_obj.name,
            run_obj.name,
        ),
        links=_links(base=base, run=run_obj),
        access=run_access,
    )


def _require_internal(
    access: AccessInfo,
    internal_domains: frozenset[str],
    *,
    error: type[FolderAccessError] = FolderAccessError,
) -> None:
    classification = classify_access(access, internal_domains)
    if classification != "internal_only":
        route = "override" if error is OverrideNotRestrictedError else "ticket"
        raise error(
            f"folder {access.object_id} access is {classification}, not internal-only; "
            f"the {route} route requires an internal-staff-only folder",
            object_id=access.object_id,
            classification=classification,
            fingerprint=access.fingerprint,
        )


__all__ = [
    "AR_KEY_PATTERN",
    "IDENTITY_PROPERTY",
    "AccessClass",
    "AccountFolder",
    "FolderAccessError",
    "FolderConflictError",
    "FolderResolution",
    "FolderResolutionError",
    "PINNED_INTERNAL_DOMAINS",
    "OverrideNotRestrictedError",
    "Route",
    "StarboardRoot",
    "account_folder_from",
    "classify_access",
    "creation_order",
    "effective_internal_domains",
    "create_and_converge",
    "ensure_account_folder",
    "ensure_folder",
    "ensure_starboard_root",
    "existing_folders",
    "identity_children",
    "identity_children_under",
    "resolve_account_route",
    "resolve_override_route",
    "resolve_ticket_route",
    "sanitize_folder_name",
    "ticket_folder_title",
    "starboard_roots",
]
