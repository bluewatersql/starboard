"""Run-6 fix: two first runs at once left two ``My Drive/starboard`` roots.

Live run 6 started with no ``starboard`` folder. Concurrent preflights each created
one before Drive listed the other, and 16 of 18 sessions then stopped at
``verify-identity`` / ``route`` / ``status`` with ``STORAGE_ERROR`` "2 folder(s)
named 'starboard' … Reconcile in Drive". Same-identity roots now converge: run and
account lookups search every root, new folders go under the earliest-created one,
and ``route`` carries a ``duplicate_starboard_roots:`` warning instead of failing.
"""

from __future__ import annotations

from pathlib import Path

from starboard_core.engagement.folders import IDENTITY_PROPERTY
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.staging import ensure_staging, quarantine_staging

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import PREFLIGHT, ok, run

store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox

EARLIER = "2000-01-01T00:00:00Z"


def _other_sessions_root(store: InMemoryEngagementStorage) -> str:
    """Seed the ``starboard`` root a concurrent first run created before ours."""
    return store.add_folder(
        store.root_folder_id(),
        "starboard",
        properties={IDENTITY_PROPERTY: "segment:starboard"},
        created_time=EARLIER,
    ).id


def _roots(store: InMemoryEngagementStorage) -> list[str]:
    found = store.list_children(
        store.root_folder_id(), name="starboard", folders_only=True
    )
    return [f.id for f in found]


def _warnings(env: dict) -> list[str]:
    return [*env.get("warnings", []), *env["data"].get("warnings", [])]


def test_run_staged_under_the_later_root_still_verifies_routes_and_reports(
    capsys, store
):
    pre = ok(capsys, *PREFLIGHT)
    winner = _other_sessions_root(store)

    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
    code, env, raw = run(capsys, "route", "--run-id", pre["run_id"])
    assert code == 0, raw
    status = ok(capsys, "status", "--run-id", pre["run_id"])

    assert status["run_id"] == pre["run_id"]
    assert any(w.startswith("duplicate_starboard_roots:") for w in _warnings(env))
    account = store.get(env["data"]["account_folder_id"])
    assert account.parent_ids == (winner,)  # new account folders go to the winner
    assert len(_roots(store)) == 2  # the helper never trashes or merges


def test_preflight_with_two_roots_does_not_stop(capsys, store):
    store.add_folder(
        store.root_folder_id(),
        "starboard",
        properties={IDENTITY_PROPERTY: "segment:starboard"},
    )
    _other_sessions_root(store)

    pre = ok(capsys, *PREFLIGHT)
    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
    ok(capsys, "route", "--run-id", pre["run_id"])

    assert len(_roots(store)) == 2


def test_second_run_reuses_the_account_folder_under_the_later_root(capsys, store):
    first = ok(capsys, *PREFLIGHT)
    ok(capsys, "verify-identity", "--run-id", first["run_id"], "--profile", "acme")
    first_route = ok(capsys, "route", "--run-id", first["run_id"])
    _other_sessions_root(store)

    second = ok(capsys, *PREFLIGHT)
    ok(capsys, "verify-identity", "--run-id", second["run_id"], "--profile", "acme")
    second_route = ok(capsys, "route", "--run-id", second["run_id"])

    assert second_route["account_folder_id"] == first_route["account_folder_id"]
    code, env, raw = run(
        capsys,
        "history",
        "--run-folder",
        second_route["run_folder_id"],
        "--interval-start",
        "2026-09-01T00:00:00Z",
        "--interval-end",
        "2026-10-01T00:00:00Z",
    )
    assert code == 0, raw  # the registry is found across both roots
    assert any(w.startswith("duplicate_starboard_roots:") for w in _warnings(env))


def test_quarantined_run_under_the_later_root_is_still_refused(capsys, store):
    pre = ok(capsys, *PREFLIGHT)
    quarantine_staging(store, ensure_staging(store, pre["run_id"]), "identity_mismatch")
    _other_sessions_root(store)

    status = ok(capsys, "status", "--run-id", pre["run_id"])
    assert status["run_status"] == "quarantined" and status["resume"] is None
    code, env, _ = run(capsys, "route", "--run-id", pre["run_id"])
    assert code == 5 and env["errors"][0]["code"] == "RUN_QUARANTINED"


def test_engagement_skill_says_duplicate_roots_are_a_warning():
    skill = (
        Path(__file__).parents[2]
        / "skills"
        / "starboard"
        / "starboard-engagement"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    text = " ".join(skill.split())
    assert "`duplicate_starboard_roots`" in text
    assert (
        "Two `My Drive/starboard` folders (two first runs at once) are not an error"
        in text
    )
