# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live customer run 2026-10-22: a just-created folder may not be listed yet.

``engagement route`` into a shared-drive ticket folder failed STORAGE_ERROR
"created folder … is not listed under … on read-back"; a second route worked. The
read-back re-lists with a short bounded backoff until the created folder shows.
"""

from __future__ import annotations

import pytest
from starboard_core.engagement import folders
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.sink import DriveRunSink  # noqa: F401  (import check)
from starboard_core.ports.engagement_storage import StorageIntegrityError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(folders, "_sleep", slept.append)
    return slept


def test_create_and_converge_waits_for_a_lagging_listing(no_sleep) -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.list_lag = 2
    created = folders.create_and_converge(store, root, "acme", "account:acme")
    assert created.name == "acme"
    assert len(no_sleep) == 2  # two re-lists missed it, the third saw it


def test_a_folder_that_never_lists_still_fails(no_sleep) -> None:
    store = InMemoryEngagementStorage()
    root = store.root_folder_id()
    store.list_lag = 99
    with pytest.raises(StorageIntegrityError, match="not listed"):
        folders.create_and_converge(store, root, "acme", "account:acme")
    assert len(no_sleep) == len(folders.RELIST_DELAYS)


def test_drive_sink_waits_for_its_new_artifact_folders(no_sleep) -> None:
    from starboard_core.engagement.folders import IDENTITY_PROPERTY

    store = InMemoryEngagementStorage()
    run = store.create_folder(
        store.root_folder_id(), "r1", {IDENTITY_PROPERTY: "run:r1"}
    )
    fp = store.inspect_access(run.id).fingerprint
    sink = DriveRunSink(
        store,
        run.id,
        run_id="20261022_12345678-1234-4234-8234-123456789abc",
        access_fingerprint=fp,
    )
    store.list_lag = 1
    sink.put_bytes("discovery/domains/x.md", b"# x\n", "text/markdown")
    assert no_sleep  # the new folders were re-listed after a lagging listing
    (disc,) = store.list_children(run.id, name="discovery", folders_only=True)
    (doms,) = store.list_children(disc.id, name="domains", folders_only=True)
    assert [o.name for o in store.list_children(doms.id)] == ["x.md"]
