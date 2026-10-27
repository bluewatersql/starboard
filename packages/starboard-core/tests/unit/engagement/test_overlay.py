# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the fail-closed internal-overlay signal."""

from __future__ import annotations

from pathlib import Path

import pytest
from starboard_core.engagement import overlay
from starboard_core.engagement.overlay import OverlaySignal, detect_overlay


def _no_pkg() -> bool:
    return False


def _pkg() -> bool:
    return True


def _make_skill(base: Path, with_skill_md: bool = True) -> Path:
    base.mkdir(parents=True)
    if with_skill_md:
        (base / "SKILL.md").write_text("---\nname: starboard-internal-overlay\n---\n")
    return base


def test_nothing_installed_is_disabled(tmp_path: Path) -> None:
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert signal == OverlaySignal(enabled=False, reasons=())


def test_package_only_enables(tmp_path: Path) -> None:
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_pkg)
    assert signal.enabled
    assert signal.reasons == ("internal_package",)


def test_direct_skill_enables(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path / ".claude/skills/starboard-internal-overlay")
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert signal.enabled
    assert signal.reasons == (f"overlay_skill:~/{skill.relative_to(tmp_path)}",)


def test_nested_plugin_cache_skill_enables(tmp_path: Path) -> None:
    skill = _make_skill(
        tmp_path
        / ".claude/plugins/cache/mk/starboard/0.1.1/skills/starboard-internal-overlay"
    )
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert signal.enabled
    assert signal.reasons == (f"overlay_skill:~/{skill.relative_to(tmp_path)}",)


def test_directory_without_skill_md_does_not_count(tmp_path: Path) -> None:
    _make_skill(
        tmp_path / ".claude/skills/starboard-internal-overlay", with_skill_md=False
    )
    _make_skill(
        tmp_path
        / ".claude/plugins/cache/mk/starboard/0.1.1/skills/starboard-internal-overlay",
        with_skill_md=False,
    )
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert not signal.enabled


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_env_forces_on(tmp_path: Path, value: str) -> None:
    signal = detect_overlay(
        home=tmp_path, env={"STARBOARD_OVERLAY": value}, package_installed=_no_pkg
    )
    assert signal.enabled
    assert signal.reasons == ("forced_by_env",)


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_env_zero_does_not_force_off(tmp_path: Path, value: str) -> None:
    signal = detect_overlay(
        home=tmp_path, env={"STARBOARD_OVERLAY": value}, package_installed=_pkg
    )
    assert signal.enabled
    assert "internal_package" in signal.reasons


def test_env_zero_without_overlay_stays_disabled(tmp_path: Path) -> None:
    signal = detect_overlay(
        home=tmp_path, env={"STARBOARD_OVERLAY": "0"}, package_installed=_no_pkg
    )
    assert not signal.enabled


def test_scan_oserror_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(home: Path, env: object = None) -> Path | None:
        raise PermissionError("denied")

    monkeypatch.setattr(overlay, "find_overlay_skill", boom)
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert signal.enabled
    assert signal.reasons == ("skill_scan_error:PermissionError",)


def test_multiple_reasons_accumulate(tmp_path: Path) -> None:
    _make_skill(tmp_path / ".codex/skills/starboard-internal-overlay")
    signal = detect_overlay(
        home=tmp_path, env={"STARBOARD_OVERLAY": "1"}, package_installed=_pkg
    )
    assert signal.enabled
    assert len(signal.reasons) == 3
    assert signal.reasons[:2] == ("forced_by_env", "internal_package")


def test_default_scan_ignores_a_redirected_home_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``HOME`` pointing at an empty dir must not hide the account's real skill."""
    account_home = tmp_path / "account"
    _make_skill(account_home / ".claude/skills/starboard-internal-overlay")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("HOME", str(empty))
    monkeypatch.setattr(overlay, "_account_home", lambda: account_home)

    signal = detect_overlay(env={}, package_installed=_no_pkg)

    assert signal.enabled
    assert signal.reasons == (
        "overlay_skill:~/.claude/skills/starboard-internal-overlay",
    )


def test_default_scan_also_reads_home_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_home = tmp_path / "env"
    _make_skill(env_home / ".claude/skills/starboard-internal-overlay")
    account_home = tmp_path / "account"
    account_home.mkdir()
    monkeypatch.setenv("HOME", str(env_home))
    monkeypatch.setattr(overlay, "_account_home", lambda: account_home)

    assert detect_overlay(env={}, package_installed=_no_pkg).enabled
