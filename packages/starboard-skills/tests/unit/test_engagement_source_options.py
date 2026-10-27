"""``engagement source-options``: the read-only source/storage menu (phase-4 B5, D4-8).

No run, no storage call, no file and no Databricks profile is touched. A public
install offers one option and needs no choice; an overlay install offers three
and requires one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.write_guard import sandbox_diff, sandbox_snapshot
from starboard_skills.helpers.__main__ import main
from starboard_skills.helpers.engagement import _envelope

OVERLAY_ON = OverlaySignal(enabled=True, reasons=("internal_package",))
OVERLAY_OFF = OverlaySignal(enabled=False)
OPTION_KEYS = {
    "source_mode",
    "storage_policy",
    "storage_choices",
    "default_storage",
    "needs_workspace_auth",
}


class _Boom:
    """A storage or workspace fake that fails on any use."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"source-options must not touch {name}")


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("home", "cwd", "tmp"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.chdir(tmp_path / "cwd")

    def boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("source-options must not build storage or a client")

    monkeypatch.setattr(_envelope, "_make_storage", boom)
    monkeypatch.setattr(_envelope, "_make_workspace_client", boom)
    return tmp_path


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, dict[str, Any], str]:
    with pytest.raises(SystemExit) as exc:
        main(["engagement", "source-options", *argv])
    raw = capsys.readouterr().out
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    env = json.loads(lines[-1]) if lines else {}
    return int(exc.value.code or 0), env, raw


def options(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, *argv: str
) -> dict[str, Any]:
    roots = [tmp_path / n for n in ("home", "cwd", "tmp")]
    before = sandbox_snapshot(roots)
    code, env, raw = run(capsys, *argv)
    assert code == 0, raw
    assert env["ok"] is True
    assert env["domain"] == "engagement"
    assert env["command"] == "source-options"
    assert sandbox_diff(before, sandbox_snapshot(roots)) == []
    return env["data"]


def test_public_install_offers_one_option_without_a_choice(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
    data = options(capsys, isolated)
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


def test_overlay_install_offers_three_options_and_requires_a_choice(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    data = options(capsys, isolated)
    assert data["overlay_enabled"] is True
    assert data["choice_required"] is True
    got = data["options"]
    assert [o["source_mode"] for o in got] == [
        "internal_only",
        "customer_workspace",
        "hybrid",
    ]
    assert all(set(o) == OPTION_KEYS for o in got)
    assert [o["storage_policy"] for o in got] == [
        "drive_default",
        "drive_required",
        "drive_required",
    ]
    assert [o["storage_choices"] for o in got] == [
        ["drive", "local"],
        ["drive"],
        ["drive"],
    ]
    assert [o["default_storage"] for o in got] == ["drive", "drive", "drive"]
    assert [o["needs_workspace_auth"] for o in got] == [False, True, True]


@pytest.mark.parametrize("overlay", [OVERLAY_ON, OVERLAY_OFF])
def test_default_storage_is_always_a_choice_and_unknown_is_never_offered(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    overlay: OverlaySignal,
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: overlay)
    data = options(capsys, isolated)
    for option in data["options"]:
        assert option["default_storage"] in option["storage_choices"]
        assert option["source_mode"] != "unknown"


@pytest.mark.parametrize(
    "task", ["health_check", "troubleshooting", "discovery", "action_plan", "review"]
)
def test_every_task_is_accepted(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    task: str,
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    data = options(capsys, isolated, "--task", task)
    assert len(data["options"]) == 3


def test_a_bad_task_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    code, _env, raw = run(capsys, "--task", "bogus")
    assert code == 2, raw


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["engagement", "source-options", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--task" in out
    assert "--run-dir" not in out and "--out" not in out


def test_a_required_choice_comes_with_a_ready_question(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Run 7 (opus P01): the host asked "which source?" without each option's
    # storage and workspace-auth need. The helper now writes the question.
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    data = options(capsys, isolated, "--task", "health_check")
    question = data["question"]
    lines = question.splitlines()
    assert lines[0] == "Which source should this run use?"
    assert lines[1:] == [
        "- internal_only: internal telemetry only. Storage: drive_default "
        "(drive or local). No workspace sign-in.",
        "- customer_workspace: the customer workspace. Storage: drive_required "
        "(drive). Needs a workspace profile.",
        "- hybrid: internal telemetry and the customer workspace. Storage: "
        "drive_required (drive). Needs a workspace profile.",
    ]


def test_no_question_when_no_choice_is_needed(
    capsys: pytest.CaptureFixture[str],
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
    assert options(capsys, isolated)["question"] is None
