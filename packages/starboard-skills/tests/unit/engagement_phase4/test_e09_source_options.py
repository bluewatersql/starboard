"""E9 Source options (spec §H.9, B5, D4-8).

``engagement source-options`` is read-only: no run, no storage call, no file.
A public install offers one option and needs no choice; an overlay install
offers ``internal_only`` / ``customer_workspace`` / ``hybrid`` and requires a
choice. ``storage_choices`` are the requested stores whose decision has no
refusal. An unattended overlay preflight still needs ``--source-mode``.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement import overlay
from starboard_core.engagement.write_guard import sandbox_diff

from ._support import ACCOUNT, eng, ok

TASKS = ("health_check", "troubleshooting", "discovery", "action_plan", "review")
OPTION_KEYS = {
    "source_mode",
    "storage_policy",
    "storage_choices",
    "default_storage",
    "needs_workspace_auth",
}


def _options(capsys: Any, *argv: str) -> dict[str, Any]:
    return ok(capsys, "source-options", *argv)


def _expected_choices(source_mode: str) -> list[str]:
    """``requested`` values in ``("drive", "local")`` whose decision has no refusal."""
    from starboard_core.engagement.policy import SourceMode, classify_storage

    signal = overlay.detect_overlay()
    return [
        r
        for r in ("drive", "local")
        if classify_storage(SourceMode(source_mode), signal, requested=r).refusal
        is None
    ]


def _expected_policy(source_mode: str) -> str:
    from starboard_core.engagement.policy import SourceMode, classify_storage

    decision = classify_storage(
        SourceMode(source_mode), overlay.detect_overlay(), requested=None
    )
    return decision.policy.value


def test_a_public_install_offers_customer_workspace_without_a_choice(
    public: None,
    capsys: pytest.CaptureFixture[str],
    sandbox: Any,
    store: Any,
    drive_calls: list[str],
) -> None:
    before, objects = sandbox.snapshot(), store.object_count
    data = _options(capsys)
    assert data["overlay_enabled"] is False
    assert data["choice_required"] is False
    assert data["options"] == [
        {
            "source_mode": "customer_workspace",
            "storage_policy": "local",
            "storage_choices": ["local", "drive"],
            "default_storage": "local",
            "needs_workspace_auth": True,
        }
    ]
    assert sorted(_expected_choices("customer_workspace")) == ["drive", "local"]
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert store.object_count == objects
    assert drive_calls == []


def test_an_overlay_install_requires_a_choice_of_three(
    capsys: pytest.CaptureFixture[str], sandbox: Any, store: Any
) -> None:
    before, objects = sandbox.snapshot(), store.object_count
    data = _options(capsys)
    assert data["overlay_enabled"] is True
    assert data["choice_required"] is True
    options = data["options"]
    assert [o["source_mode"] for o in options] == [
        "internal_only",
        "customer_workspace",
        "hybrid",
    ]
    by_mode = {o["source_mode"]: o for o in options}
    assert [o["storage_policy"] for o in options] == [
        "drive_default",
        "drive_required",
        "drive_required",
    ]
    assert by_mode["internal_only"]["storage_choices"] == ["drive", "local"]
    assert by_mode["internal_only"]["default_storage"] == "drive"
    for mode in ("customer_workspace", "hybrid"):
        assert by_mode[mode]["storage_choices"] == ["drive"]
        assert by_mode[mode]["default_storage"] == "drive"
    assert by_mode["internal_only"]["needs_workspace_auth"] is False
    assert by_mode["customer_workspace"]["needs_workspace_auth"] is True
    assert by_mode["hybrid"]["needs_workspace_auth"] is True
    for option in options:
        assert set(option) == OPTION_KEYS
        mode = option["source_mode"]
        assert option["storage_policy"] == _expected_policy(mode)
        assert option["storage_choices"] == _expected_choices(mode)
        assert option["default_storage"] in option["storage_choices"]
    assert "unknown" not in by_mode
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert store.object_count == objects


@pytest.mark.parametrize("task", TASKS)
def test_every_task_is_accepted_and_writes_nothing(
    capsys: pytest.CaptureFixture[str], sandbox: Any, store: Any, task: str
) -> None:
    before, objects = sandbox.snapshot(), store.object_count
    data = _options(capsys, "--task", task)
    assert data["choice_required"] is True
    assert len(data["options"]) == 3
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert store.object_count == objects


def test_a_bad_task_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], sandbox: Any
) -> None:
    before = sandbox.snapshot()
    code, _env, raw = eng(capsys, "source-options", "--task", "bogus")
    assert code == 2, raw
    assert sandbox_diff(before, sandbox.snapshot()) == []


def test_an_overlay_preflight_without_source_mode_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], sandbox: Any, store: Any
) -> None:
    before, objects = sandbox.snapshot(), store.object_count
    code, _env, raw = eng(
        capsys,
        "preflight",
        "--task",
        "troubleshooting",
        "--task-name",
        "job-42",
        "--account-key",
        ACCOUNT,
        "--account-name",
        "Acme Corp",
    )
    assert code == 2, raw
    assert "--source-mode" in raw
    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert store.object_count == objects
