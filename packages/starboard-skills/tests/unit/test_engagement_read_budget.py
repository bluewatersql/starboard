"""Read budget of the Drive analysis verbs: every object is downloaded once per command.

``engagement analyze`` and ``run recur`` read each run artifact once, and each prior
run's descriptor once (the registry check); the prior run is read through its
committed refs, never by walking its tree.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from .conftest import run_main
from .test_run_recur_drive import _current, _registered_prior

_DESCRIPTOR = "run-authorization.json"


def _count_downloads(store: Any) -> Counter[tuple[str, str]]:
    """``(object id, name) -> downloads`` from now on."""
    calls: Counter[tuple[str, str]] = Counter()
    get_stream = store.get_stream

    def counted(object_id: str, *args: Any, **kwargs: Any) -> Any:
        calls[(object_id, store.get(object_id).name)] += 1
        return get_stream(object_id, *args, **kwargs)

    store.get_stream = counted
    return calls


@pytest.mark.unit
@pytest.mark.parametrize(
    "argv",
    [["engagement", "analyze"], ["run", "recur"]],
    ids=["analyze", "recur"],
)
def test_each_object_is_downloaded_once(covered_env, drive_run, capsys, argv):
    _registered_prior(drive_run, capsys)
    _current(drive_run)
    calls = _count_downloads(drive_run.store)
    code, out = run_main([*argv, "--run-folder", drive_run.folder_id], capsys)
    assert code == 0, out
    again = {key: n for key, n in calls.items() if n > 1 and key[1] != _DESCRIPTOR}
    assert again == {}, again
    # One descriptor download per run folder, plus the sink's open of the current
    # run (the prior run's is the registry check; it is not read again).
    descriptors = sum(n for (_, name), n in calls.items() if name == _DESCRIPTOR)
    assert descriptors <= 3, calls
    folders = {oid for (oid, name) in calls if name == _DESCRIPTOR}
    assert len(folders) == 2


@pytest.mark.unit
def test_recur_reads_the_prior_run_through_its_refs_only(
    covered_env, drive_run, capsys
):
    prior = _registered_prior(drive_run, capsys)
    _current(drive_run)
    calls = _count_downloads(drive_run.store)
    code, out = run_main(["run", "recur", "--run-folder", drive_run.folder_id], capsys)
    assert code == 0, out
    below_prior = {
        o.id for o in drive_run.store.list_children(prior.folder_id)
    } | _descendants(drive_run.store, prior.folder_id)
    read = sorted(name for (oid, name) in calls if oid in below_prior)
    assert read == sorted(
        [
            _DESCRIPTOR,
            "rev-000001.json",
            "observations.json",
            "findings.json",
            "findings-manifest.json",
        ]
    ), read


def _descendants(store: Any, folder_id: str) -> set[str]:
    out: set[str] = set()
    pending = [folder_id]
    while pending:
        for child in store.list_children(pending.pop()):
            out.add(child.id)
            if child.is_folder:
                pending.append(child.id)
    return out


@pytest.mark.unit
def test_a_put_drops_the_held_bytes() -> None:
    from types import SimpleNamespace

    from starboard_skills.helpers.engagement.analysis_cmds import OpenRun

    class Sink:
        def __init__(self) -> None:
            self.data = {"analysis/plays.json": b"[1]"}
            self.gets = 0

        def get_bytes(self, rel: str) -> bytes:
            self.gets += 1
            return self.data[rel]

        def put_record(self, rel: str, data: bytes, mime_type: str) -> Any:
            self.data[rel] = data
            return rel

    sink = Sink()
    run = OpenRun(SimpleNamespace(sink=sink), None, "acme", None, None)  # type: ignore[arg-type]
    assert run.read_json("analysis/plays.json") == [1]
    assert run.read_json("analysis/plays.json") == [1]
    assert sink.gets == 1
    run.put("analysis/plays.json", [2])
    assert run.read_json("analysis/plays.json") == [2]
    assert sink.gets == 2

