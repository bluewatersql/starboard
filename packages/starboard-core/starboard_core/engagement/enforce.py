# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Writer storage enforcement: one entry point for every artifact writer.

:func:`writer_context` decides the storage policy for a writer (D-11 / D-12),
arms the local write guard on covered runs and opens the artifact sink::

    with writer_context(
        run_folder_id=args.run_folder,
        local_root=args.out_dir,
        acquires_customer_data=True,
    ) as ctx:
        refuse_local(ctx.decision, stdout=args.stdout, log_file=args.log_file)
        ctx.sink.put_json("raw/w-w01.json", rows)

A run is *covered* when its policy is ``drive_required``. On a covered run the
guard is armed **before** the sink (and so the Drive adapter) is created, and stays
armed until the block exits.

Stdlib + port only.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from starboard_core.engagement.overlay import OverlaySignal, detect_overlay
from starboard_core.engagement.policy import SourceMode, StorageDecision, StoragePolicy
from starboard_core.engagement.records import RunAuthorization
from starboard_core.engagement.sink import (
    ArtifactSink,
    LocalStorageRefused,
    load_engagement_storage,
    open_sink,
)
from starboard_core.engagement.write_guard import (
    GuardPolicy,
    LocalWriteRefused,
    default_policy,
    guarded,
    refused_events,
    refused_in_scope,
)
from starboard_core.ports.engagement_storage import EngagementStoragePort

__all__ = [
    "LOCAL_DESCRIPTOR_RELPATH",
    "LocalStorageRefused",
    "WriterContext",
    "covered",
    "decide_for_writer",
    "guarded_run",
    "raise_if_refused",
    "refuse_local",
    "writer_context",
]

#: Where a local run directory keeps its run descriptor (D-11).
LOCAL_DESCRIPTOR_RELPATH = "analysis/run-authorization.json"

_NEEDS_DRIVE = (
    "this install has the internal overlay enabled, so outputs must go to the run's "
    "Drive folder: pass --run-folder"
)


def covered(decision: StorageDecision) -> bool:
    """Whether the run is covered: Drive is mandatory and local writes are refused."""
    return decision.policy is StoragePolicy.DRIVE_REQUIRED


def _covered_decision(reason: str) -> StorageDecision:
    return StorageDecision(
        StoragePolicy.DRIVE_REQUIRED, True, reason, refusal=_NEEDS_DRIVE
    )


def _local_descriptor_problem(local_run_dir: str | None) -> str | None:
    """``None`` when the run dir holds an internal-only local descriptor, else why not."""
    if not local_run_dir:
        return "no run directory was given"
    path = Path(local_run_dir) / LOCAL_DESCRIPTOR_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("not a JSON object")
        auth = RunAuthorization.from_dict(data)
    except FileNotFoundError:
        return f"{path} does not exist"
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return f"{path} is not a valid run descriptor ({exc})"
    if auth.storage_policy is not StoragePolicy.INTERNAL_ONLY_LOCAL:
        return f"{path} records storage policy {auth.storage_policy.value}"
    if auth.source_mode is not SourceMode.INTERNAL_ONLY:
        return f"{path} records source mode {auth.source_mode.value}"
    return None


def decide_for_writer(
    *,
    run_folder_id: str | None,
    local_run_dir: str | None,
    acquires_customer_data: bool,
    overlay: OverlaySignal | None = None,
) -> StorageDecision:
    """The storage decision for one writer invocation (D-11, D-12).

    * Public install (no overlay): ``drive_optional`` with a run folder, else
      ``local`` (unchanged public behaviour).
    * Overlay install with a run folder: ``drive_required`` (covered).
    * Overlay install without a run folder: ``internal_only_local`` only when the
      writer does not acquire customer data **and** ``local_run_dir`` holds an
      ``analysis/run-authorization.json`` recording ``internal_only`` /
      ``internal_only_local``. Anything else, including an unreadable descriptor,
      fails closed to ``drive_required`` with a refusal.

    Args:
        overlay: Overlay detection result; detected when omitted.
    """
    signal = detect_overlay() if overlay is None else overlay
    if not signal.enabled:
        if run_folder_id:
            return StorageDecision(
                StoragePolicy.DRIVE_OPTIONAL, False, "public run; run folder given"
            )
        return StorageDecision(
            StoragePolicy.LOCAL, False, "public run; local store is the default"
        )
    if run_folder_id:
        return StorageDecision(
            StoragePolicy.DRIVE_REQUIRED,
            True,
            "overlay enabled and a run folder was given: outputs go to Drive",
        )
    if acquires_customer_data:
        return _covered_decision(
            "overlay enabled and this writer acquires customer data: local storage is "
            "refused regardless of any local descriptor"
        )
    problem = _local_descriptor_problem(local_run_dir)
    if problem is not None:
        return _covered_decision(
            f"overlay enabled and no internal-only local descriptor: {problem}"
        )
    return StorageDecision(
        StoragePolicy.INTERNAL_ONLY_LOCAL,
        False,
        "overlay enabled; the local run directory is an internal-only local run",
    )


def refuse_local(decision: StorageDecision, **flags: object) -> None:
    """On a covered run, refuse any truthy local-output flag.

    Keyword names map to CLI flags (``log_file`` -> ``--log-file``). Not covered:
    no-op.

    Raises:
        LocalStorageRefused: The first truthy flag, in argument order.
    """
    if not covered(decision):
        return
    for name, value in flags.items():
        if value:
            flag = "--" + name.replace("_", "-")
            raise LocalStorageRefused(
                f"{flag} writes to local disk, which a covered run refuses "
                f"({decision.reason})",
                flag=flag,
            )


def raise_if_refused(since: int = 0, *, token: object | None = None) -> None:
    """Raise the first local write the armed guard refused after ``since``.

    A refusal a library caught and swallowed still fails the run: call this before
    reporting success. ``since`` is a :func:`refused_events` count taken earlier.
    With ``token`` (a :func:`guarded` entry), only refusals counting against that
    entry are considered (see :func:`refused_in_scope`); without it, every refusal.

    Raises:
        LocalWriteRefused: A write or spawn was refused after ``since``.
    """
    refused = (
        refused_events()[since:]
        if token is None
        else refused_in_scope(token, since)
    )
    if refused:
        raise LocalWriteRefused(*refused[0])


@contextmanager
def guarded_run(policy: GuardPolicy | None = None) -> Iterator[Callable[[], None]]:
    """Arm the write guard; a refused write inside the block fails it, even if swallowed.

    Yields a check (:func:`raise_if_refused` from this block's start) to call before
    reporting success. Only this entry's refusals count, so a concurrent entry's
    refusal (another MCP call) does not fail it; a refusal made with no entry in scope
    counts against every entry. The block's own exception wins; a clean exit (or a
    zero ``SystemExit``) after a refusal raises :class:`LocalWriteRefused`.
    """
    with guarded(default_policy() if policy is None else policy) as token:
        since = len(refused_events())

        def check() -> None:
            raise_if_refused(since, token=token)

        try:
            yield check
        except SystemExit as exc:
            if not exc.code:
                check()
            raise
        check()


@dataclass(frozen=True)
class WriterContext:
    """What a writer works with: the decision, its sink, and the armed guard policy.

    ``guard`` is ``None`` when the run is not covered (nothing is armed).
    ``raise_if_refused`` raises the first local write refused in this block (a
    no-op when nothing is armed); call it before reporting success.
    """

    decision: StorageDecision
    sink: ArtifactSink
    guard: GuardPolicy | None
    raise_if_refused: Callable[[], None] = lambda: None


@contextmanager
def writer_context(
    *,
    run_folder_id: str | None,
    local_root: str | None,
    acquires_customer_data: bool,
    storage_factory: Callable[[], EngagementStoragePort] = load_engagement_storage,
    overlay: OverlaySignal | None = None,
) -> Iterator[WriterContext]:
    """Decide, guard and open the sink for one writer.

    On a covered run the write guard (:func:`default_policy`) is armed, and only then
    is the sink opened. The guard is released when the block exits, also on error; a
    clean exit after a refused local write (even one a library swallowed) raises
    :class:`LocalWriteRefused`.

    Args:
        local_root: The writer's local run directory (public / internal-only local).
        overlay: Overlay detection result; detected when omitted.

    Raises:
        LocalStorageRefused: Covered without a run folder.
        LocalWriteRefused: Covered, and a local write was refused in the block.
        StorageUnavailableError / CommitError / StoragePermissionError: From
            :func:`~starboard_core.engagement.sink.open_sink`.
    """
    decision = decide_for_writer(
        run_folder_id=run_folder_id,
        local_run_dir=local_root,
        acquires_customer_data=acquires_customer_data,
        overlay=overlay,
    )
    if not covered(decision):
        yield WriterContext(
            decision,
            open_sink(
                decision=decision,
                run_folder_id=run_folder_id,
                local_root=local_root,
                storage_factory=storage_factory,
            ),
            None,
        )
        return
    policy = default_policy()
    with guarded_run(policy) as check:
        sink = open_sink(
            decision=decision,
            run_folder_id=run_folder_id,
            local_root=local_root,
            storage_factory=storage_factory,
        )
        yield WriterContext(decision, sink, policy, check)
