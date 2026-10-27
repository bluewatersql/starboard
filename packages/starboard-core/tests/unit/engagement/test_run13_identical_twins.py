# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Live runs 11/13: identical staged twins (a retried upload) do not wedge a run."""

from __future__ import annotations

import pytest
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.staging import StagingError, encode_json, put_json

pytestmark = pytest.mark.unit

_PROPS = {"starboard_artifact": "preflight:r1"}


def _twins(store: InMemoryEngagementStorage, payload: dict) -> str:
    root = store.root_folder_id()
    for _ in range(2):
        store.put_stream(
            root,
            "storage-preflight.json",
            "application/json",
            [encode_json(payload)],
            properties=_PROPS,
        )
    return root


def test_equal_write_over_identical_twins_reuses_one() -> None:
    store = InMemoryEngagementStorage()
    root = _twins(store, {"run_id": "r1"})
    obj = put_json(
        store, root, "storage-preflight.json", {"run_id": "r1"}, properties=_PROPS
    )
    assert obj.id in {
        o.id for o in store.list_children(root, name="storage-preflight.json")
    }


def test_changing_identical_twins_collapses_then_updates() -> None:
    # A preflight resume can change the record (e.g. unattended=True): the twins are
    # collapsed to the earliest copy, which is then updated in place.
    store = InMemoryEngagementStorage()
    root = _twins(store, {"run_id": "r1"})
    obj = put_json(
        store,
        root,
        "storage-preflight.json",
        {"run_id": "r1", "unattended": True},
        properties=_PROPS,
    )
    (left,) = store.list_children(root, name="storage-preflight.json")
    assert left.id == obj.id
    assert b"".join(store.get_stream(obj.id)) == encode_json(
        {"run_id": "r1", "unattended": True}
    )


def test_differing_twins_still_stop() -> None:
    store = InMemoryEngagementStorage()
    root = _twins(store, {"run_id": "r1"})
    store.put_stream(
        root,
        "storage-preflight.json",
        "application/json",
        [encode_json({"run_id": "x"})],
        properties=_PROPS,
    )
    with pytest.raises(StagingError, match="3 files"):
        put_json(
            store, root, "storage-preflight.json", {"run_id": "r1"}, properties=_PROPS
        )


def test_untrashable_identical_twins_stop() -> None:
    store = InMemoryEngagementStorage()
    root = _twins(store, {"run_id": "r1"})
    store.deny_writes_under.add(root)
    with pytest.raises(StagingError, match="could not trash"):
        put_json(
            store, root, "storage-preflight.json", {"run_id": "r2"}, properties=_PROPS
        )
    assert len(store.list_children(root, name="storage-preflight.json")) == 2
