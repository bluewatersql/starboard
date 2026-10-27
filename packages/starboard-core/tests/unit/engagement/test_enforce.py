# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for writer storage enforcement (phase-2 spec P2-G1/P2-G3, D-11)."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from starboard_core.engagement import enforce, sink
from starboard_core.engagement.commit import write_descriptor
from starboard_core.engagement.enforce import (
    LocalStorageRefused,
    WriterContext,
    covered,
    decide_for_writer,
    guarded_run,
    raise_if_refused,
    refuse_local,
    writer_context,
)
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import (
    SourceMode,
    StorageDecision,
    StoragePolicy,
)
from starboard_core.engagement.records import AccountRef, DriveContext, RunAuthorization
from starboard_core.engagement.sink import DriveRunSink, LocalDirSink, MemorySink
from starboard_core.engagement.write_guard import (
    LocalWriteRefused,
    active,
    default_policy,
)
from starboard_core.ports.engagement_storage import Grant

RID = "20261008_12345678-1234-4234-8234-123456789abc"
ON = OverlaySignal(enabled=True, reasons=("forced_by_env",))
OFF = OverlaySignal(enabled=False)
REQUIRED = StorageDecision(StoragePolicy.DRIVE_REQUIRED, True, "overlay")
LOCAL = StorageDecision(StoragePolicy.LOCAL, False, "public")


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Iterator[None]:
    assert not active()
    yield
    assert not active()


def _auth(
    *,
    source_mode: SourceMode,
    storage_policy: StoragePolicy,
    drive: DriveContext | None = None,
) -> RunAuthorization:
    return RunAuthorization(
        engagement_id="acme/workspace/ws-123",
        run_id=RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=source_mode,
        storage_policy=storage_policy,
        audience="internal",
        methodology_version="m1",
        drive=drive,
    )


def _local_run(
    tmp_path: Path, auth: RunAuthorization | None, raw: str | None = None
) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "analysis").mkdir(parents=True)
    target = run_dir / "analysis" / "run-authorization.json"
    if raw is not None:
        target.write_text(raw)
    elif auth is not None:
        target.write_text(json.dumps(auth.to_dict()))
    return run_dir


INTERNAL_LOCAL_AUTH = _auth(
    source_mode=SourceMode.INTERNAL_ONLY,
    storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
)


# --- module surface -------------------------------------------------------------------


def test_local_storage_refused_is_the_sink_class() -> None:
    assert LocalStorageRefused is sink.LocalStorageRefused
    assert LocalStorageRefused.code == "LOCAL_STORAGE_REFUSED"


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (StoragePolicy.DRIVE_REQUIRED, True),
        (StoragePolicy.DRIVE_DEFAULT, False),
        (StoragePolicy.DRIVE_OPTIONAL, False),
        (StoragePolicy.LOCAL, False),
        (StoragePolicy.INTERNAL_ONLY_LOCAL, False),
    ],
)
def test_covered(policy: StoragePolicy, expected: bool) -> None:
    assert (
        covered(StorageDecision(policy, policy is StoragePolicy.DRIVE_REQUIRED, "r"))
        is expected
    )


# --- decide_for_writer (D-11 / D-12) --------------------------------------------------


def test_public_without_run_folder_is_local() -> None:
    decision = decide_for_writer(
        run_folder_id=None, local_run_dir=None, acquires_customer_data=True, overlay=OFF
    )
    assert decision.policy is StoragePolicy.LOCAL
    assert not covered(decision)


def test_public_with_run_folder_is_drive_optional() -> None:
    decision = decide_for_writer(
        run_folder_id="f1", local_run_dir=None, acquires_customer_data=True, overlay=OFF
    )
    assert decision.policy is StoragePolicy.DRIVE_OPTIONAL
    assert not covered(decision)


@pytest.mark.parametrize("acquires", [True, False])
def test_overlay_with_run_folder_is_covered(acquires: bool) -> None:
    decision = decide_for_writer(
        run_folder_id="f1",
        local_run_dir=None,
        acquires_customer_data=acquires,
        overlay=ON,
    )
    assert decision.policy is StoragePolicy.DRIVE_REQUIRED
    assert covered(decision)
    assert decision.refusal is None


def test_overlay_local_with_internal_only_descriptor_is_allowed(tmp_path: Path) -> None:
    run_dir = _local_run(tmp_path, INTERNAL_LOCAL_AUTH)
    decision = decide_for_writer(
        run_folder_id=None,
        local_run_dir=str(run_dir),
        acquires_customer_data=False,
        overlay=ON,
    )
    assert decision.policy is StoragePolicy.INTERNAL_ONLY_LOCAL
    assert not covered(decision)


def test_overlay_local_customer_acquiring_is_refused_even_with_descriptor(
    tmp_path: Path,
) -> None:
    run_dir = _local_run(tmp_path, INTERNAL_LOCAL_AUTH)
    decision = decide_for_writer(
        run_folder_id=None,
        local_run_dir=str(run_dir),
        acquires_customer_data=True,
        overlay=ON,
    )
    assert decision.policy is StoragePolicy.DRIVE_REQUIRED
    assert decision.refusal


@pytest.mark.parametrize(
    "case",
    [
        "no_dir",
        "no_descriptor",
        "bad_json",
        "not_object",
        "invalid_record",
        "customer_source",
        "drive_policy",
    ],
)
def test_overlay_local_fails_closed(tmp_path: Path, case: str) -> None:
    run_dir: Path | None
    if case == "no_dir":
        run_dir = None
    elif case == "no_descriptor":
        run_dir = _local_run(tmp_path, None)
    elif case == "bad_json":
        run_dir = _local_run(tmp_path, None, raw="{not json")
    elif case == "not_object":
        run_dir = _local_run(tmp_path, None, raw="[]")
    elif case == "invalid_record":
        run_dir = _local_run(
            tmp_path, None, raw=json.dumps({"storage_policy": "internal_only_local"})
        )
    elif case == "customer_source":
        run_dir = _local_run(
            tmp_path,
            _auth(
                source_mode=SourceMode.CUSTOMER_WORKSPACE,
                storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
            ),
        )
    else:
        run_dir = _local_run(
            tmp_path,
            _auth(
                source_mode=SourceMode.INTERNAL_ONLY,
                storage_policy=StoragePolicy.DRIVE_DEFAULT,
            ),
        )
    decision = decide_for_writer(
        run_folder_id=None,
        local_run_dir=None if run_dir is None else str(run_dir),
        acquires_customer_data=False,
        overlay=ON,
    )
    assert decision.policy is StoragePolicy.DRIVE_REQUIRED
    assert decision.refusal


def test_overlay_detected_when_not_given(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enforce, "detect_overlay", lambda: ON)
    decision = decide_for_writer(
        run_folder_id="f1", local_run_dir=None, acquires_customer_data=False
    )
    assert decision.policy is StoragePolicy.DRIVE_REQUIRED


# --- refuse_local ---------------------------------------------------------------------


def test_refuse_local_raises_on_a_truthy_flag_when_covered() -> None:
    with pytest.raises(LocalStorageRefused) as info:
        refuse_local(REQUIRED, stdout=False, log_file="/tmp/x.log", session=None)
    assert info.value.flag == "--log-file"
    assert "--log-file" in str(info.value)


def test_refuse_local_allows_falsy_flags_when_covered() -> None:
    refuse_local(REQUIRED, stdout=False, log_file=None, out="")


def test_refuse_local_is_a_no_op_when_not_covered() -> None:
    refuse_local(LOCAL, stdout=True, log_file="/tmp/x.log")


# --- writer_context -------------------------------------------------------------------


def _drive_run() -> tuple[InMemoryEngagementStorage, str]:
    store = InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), "run", {})
    store.set_access(
        folder.id,
        can_add_children=True,
        grants=(Grant(kind="user", role="owner"),),
        complete=True,
    )
    fp = store.inspect_access(folder.id).fingerprint
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=folder.id,
        registry_folder_id="reg",
        account_key="acme",
        acl_classification="restricted",
        permission_fingerprints={folder.id: fp},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
    )
    write_descriptor(
        store,
        folder.id,
        _auth(
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            drive=drive,
        ),
    )
    return store, folder.id


def test_writer_context_covered_arms_the_guard() -> None:
    store, folder_id = _drive_run()
    with writer_context(
        run_folder_id=folder_id,
        local_root=None,
        acquires_customer_data=True,
        storage_factory=lambda: store,
        overlay=ON,
    ) as ctx:
        assert isinstance(ctx, WriterContext)
        assert active()
        assert ctx.guard == default_policy()
        assert isinstance(ctx.sink, DriveRunSink)
        assert ctx.sink.run_id == RID
        ref = ctx.sink.put_json("raw/w-w01.json", {"rows": []})
        assert ref.path == "raw/w-w01.json"
        assert ctx.raise_if_refused() is None
    assert not active()


def test_writer_context_covered_refuses_a_local_write(tmp_path: Path) -> None:
    store, folder_id = _drive_run()
    with (
        pytest.raises(LocalWriteRefused),
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ),
    ):
        (tmp_path / "leak.json").write_text("[]")
    assert not active()
    assert not (tmp_path / "leak.json").exists()


def test_writer_context_covered_acquiring_runs_under_the_armed_guard(
    tmp_path: Path,
) -> None:
    store, folder_id = _drive_run()
    with (
        pytest.raises(LocalWriteRefused),
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=True,
            storage_factory=lambda: store,
            overlay=ON,
        ) as ctx,
    ):
        assert active()
        assert ctx.guard == default_policy()
        (tmp_path / "leak.json").write_text("[]")
    assert not active()
    assert not (tmp_path / "leak.json").exists()


def test_writer_context_covered_non_acquiring_writer() -> None:
    store, folder_id = _drive_run()
    with writer_context(
        run_folder_id=folder_id,
        local_root=None,
        acquires_customer_data=False,
        storage_factory=lambda: store,
        overlay=ON,
    ) as ctx:
        assert active()
        assert covered(ctx.decision)


def test_writer_context_covered_without_run_folder_is_refused(tmp_path: Path) -> None:
    with (
        pytest.raises(LocalStorageRefused),
        writer_context(
            run_folder_id=None,
            local_root=str(tmp_path),
            acquires_customer_data=False,
            storage_factory=InMemoryEngagementStorage,
            overlay=ON,
        ),
    ):
        pass
    assert list(tmp_path.iterdir()) == []


def test_writer_context_guard_released_on_error() -> None:
    store, folder_id = _drive_run()
    with (
        pytest.raises(RuntimeError),
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ),
    ):
        assert active()
        raise RuntimeError("boom")


def test_writer_context_public_local(tmp_path: Path) -> None:
    with writer_context(
        run_folder_id=None,
        local_root=str(tmp_path),
        acquires_customer_data=True,
        storage_factory=InMemoryEngagementStorage,
        overlay=OFF,
    ) as ctx:
        assert not active()
        assert ctx.guard is None
        assert isinstance(ctx.sink, LocalDirSink)
        ctx.sink.put_text("analysis/review.md", "# ok")
    assert (tmp_path / "analysis" / "review.md").read_text() == "# ok"


def test_writer_context_public_without_root_is_memory() -> None:
    with writer_context(
        run_folder_id=None,
        local_root=None,
        acquires_customer_data=False,
        storage_factory=InMemoryEngagementStorage,
        overlay=OFF,
    ) as ctx:
        assert isinstance(ctx.sink, MemorySink)


def test_writer_context_internal_only_local(tmp_path: Path) -> None:
    run_dir = _local_run(tmp_path, INTERNAL_LOCAL_AUTH)
    with writer_context(
        run_folder_id=None,
        local_root=str(run_dir),
        acquires_customer_data=False,
        storage_factory=InMemoryEngagementStorage,
        overlay=ON,
    ) as ctx:
        assert ctx.decision.policy is StoragePolicy.INTERNAL_ONLY_LOCAL
        assert ctx.guard is None
        ctx.sink.put_json("analysis/backlog.json", {"items": []})
    assert (run_dir / "analysis" / "backlog.json").is_file()


def test_writer_context_public_drive_optional_is_not_guarded() -> None:
    store, folder_id = _drive_run()
    with writer_context(
        run_folder_id=folder_id,
        local_root=None,
        acquires_customer_data=True,
        storage_factory=lambda: store,
        overlay=OFF,
    ) as ctx:
        assert ctx.decision.policy is StoragePolicy.DRIVE_OPTIONAL
        assert ctx.guard is None
        assert not active()
        assert isinstance(ctx.sink, DriveRunSink)


# --- swallowed refusals (P2-G1) -------------------------------------------------------


def _swallowed_write(path: Path) -> None:
    """A library that catches the guard's refusal and carries on."""
    with contextlib.suppress(OSError):
        path.write_text("[]")


def test_writer_context_fails_when_a_refused_write_was_swallowed(
    tmp_path: Path,
) -> None:
    store, folder_id = _drive_run()
    with (
        pytest.raises(LocalWriteRefused) as exc,
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ) as ctx,
    ):
        ctx.raise_if_refused()
        _swallowed_write(tmp_path / "leak.json")
    assert exc.value.path.endswith("leak.json")
    assert not (tmp_path / "leak.json").exists()


def test_writer_context_raise_if_refused_reports_before_exit(tmp_path: Path) -> None:
    store, folder_id = _drive_run()
    seen: list[str] = []
    with (
        pytest.raises(LocalWriteRefused),
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ) as ctx,
    ):
        _swallowed_write(tmp_path / "leak.json")
        try:
            ctx.raise_if_refused()
        except LocalWriteRefused as refused:
            seen.append(refused.code)
            raise
    assert seen == ["LOCAL_STORAGE_REFUSED"]


def test_writer_context_clean_exit_with_a_zero_system_exit_is_checked(
    tmp_path: Path,
) -> None:
    store, folder_id = _drive_run()
    with (
        pytest.raises(LocalWriteRefused),
        writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ),
    ):
        _swallowed_write(tmp_path / "leak.json")
        raise SystemExit(0)


def test_writer_context_refusals_before_entry_do_not_count(tmp_path: Path) -> None:
    """Only refusals recorded inside this writer's block fail it (nested guards)."""
    store, folder_id = _drive_run()
    with pytest.raises(LocalWriteRefused) as outer, guarded_run():
        _swallowed_write(tmp_path / "outer.json")
        with writer_context(
            run_folder_id=folder_id,
            local_root=None,
            acquires_customer_data=False,
            storage_factory=lambda: store,
            overlay=ON,
        ) as ctx:
            ctx.raise_if_refused()
        with pytest.raises(LocalWriteRefused):
            raise_if_refused()
    assert outer.value.path.endswith("outer.json")


def test_guarded_run_is_clean_without_refusals(tmp_path: Path) -> None:
    with guarded_run() as check:
        assert active()
        check()
    assert not active()


def test_guarded_run_fails_on_a_swallowed_refusal(tmp_path: Path) -> None:
    with pytest.raises(LocalWriteRefused), guarded_run():
        _swallowed_write(tmp_path / "leak.json")
    assert not active()


def test_guarded_run_keeps_the_original_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), guarded_run():
        _swallowed_write(tmp_path / "leak.json")
        raise RuntimeError("boom")


def _concurrent_entries(tmp_path: Path, *, a_in_worker: bool) -> dict[str, BaseException | None]:
    """Two overlapping guarded_run entries on two threads; only ``a`` writes locally."""
    import threading

    b_entered = threading.Event()
    refused = threading.Event()
    a_done = threading.Event()
    outcome: dict[str, BaseException | None] = {}

    def a() -> None:
        try:
            with guarded_run():
                b_entered.wait(5)
                if a_in_worker:
                    worker = threading.Thread(
                        target=_swallowed_write, args=(tmp_path / "a-worker.json",)
                    )
                    worker.start()
                    worker.join()
                else:
                    _swallowed_write(tmp_path / "a.json")
                refused.set()
                a_done.wait(5)
            outcome["a"] = None
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            outcome["a"] = exc

    def b() -> None:
        try:
            with guarded_run():
                b_entered.set()
                refused.wait(5)
            outcome["b"] = None
        except BaseException as exc:  # noqa: BLE001 - recorded for the assertion
            outcome["b"] = exc
        finally:
            a_done.set()

    threads = [threading.Thread(target=a), threading.Thread(target=b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return outcome


def test_concurrent_guarded_runs_only_fail_the_entry_that_was_refused(
    tmp_path: Path,
) -> None:
    """One MCP call's refused write must not fail a concurrent, clean call."""
    outcome = _concurrent_entries(tmp_path, a_in_worker=False)
    assert isinstance(outcome["a"], LocalWriteRefused)
    assert outcome["a"].path.endswith("a.json")
    assert outcome["b"] is None
    assert not active()


def test_refusal_without_an_entry_in_scope_fails_every_entry(tmp_path: Path) -> None:
    """A refusal on a thread outside any entry's scope fails closed: every entry fails."""
    outcome = _concurrent_entries(tmp_path, a_in_worker=True)
    assert isinstance(outcome["a"], LocalWriteRefused)
    assert isinstance(outcome["b"], LocalWriteRefused)
    assert not active()


def test_concurrent_async_guarded_runs_are_scoped_per_task(tmp_path: Path) -> None:
    """The MCP server runs each tool call as its own asyncio task."""
    import asyncio

    async def main() -> list[BaseException | None]:
        b_entered = asyncio.Event()
        refused = asyncio.Event()

        async def a() -> None:
            with guarded_run():
                await b_entered.wait()
                _swallowed_write(tmp_path / "async-a.json")
                refused.set()
                await asyncio.sleep(0)

        async def b() -> None:
            with guarded_run():
                b_entered.set()
                await refused.wait()

        results = await asyncio.gather(a(), b(), return_exceptions=True)
        return [r if isinstance(r, BaseException) else None for r in results]

    a_out, b_out = asyncio.run(main())
    assert isinstance(a_out, LocalWriteRefused)
    assert b_out is None
    assert not active()
