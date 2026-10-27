# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-5 Group B fix B6: the overlay skill the host loaded wins over plugin caches.

Order: ``STARBOARD_OVERLAY_DIR``, then ``$CLAUDE_PLUGIN_ROOT/skills/<skill>``, then the
enabled dev-mode plugin paths of ``~/.config/llm-cli/plugin-dev-mode.json`` (read
only), then the direct skill roots, then the plugin caches (``.claude`` before
``.codex``). Every test uses a tmp home and an explicit ``env`` -- never the real files.
"""

from __future__ import annotations

import json
from pathlib import Path

from starboard_core.engagement.overlay import (
    OVERLAY_DIR_ENV,
    OVERLAY_SKILL_NAME,
    detect_overlay,
    find_overlay_skill,
)


def _no_pkg() -> bool:
    return False


def _skill(base: Path) -> Path:
    skill = base / "skills" / OVERLAY_SKILL_NAME
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: starboard-internal-overlay\n---\n")
    return skill


def _stale_codex_cache(home: Path) -> Path:
    return _skill(home / ".codex/plugins/cache/dev/starboard-internal/0.1.0")


def _dev_mode(home: Path, plugins: object) -> None:
    cfg = home / ".config/llm-cli/plugin-dev-mode.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"plugins": plugins}))


def test_dev_mode_path_beats_another_hosts_cache(tmp_path: Path) -> None:
    _stale_codex_cache(tmp_path)
    loaded = _skill(tmp_path / "repo/plugin-internal")
    _dev_mode(
        tmp_path,
        {
            "starboard": {"path": str(tmp_path / "repo/plugin"), "enabled": True},
            "starboard-internal": {
                "path": str(tmp_path / "repo/plugin-internal"),
                "enabled": True,
            },
        },
    )
    assert find_overlay_skill(tmp_path, env={}) == loaded
    signal = detect_overlay(home=tmp_path, env={}, package_installed=_no_pkg)
    assert signal.reasons == (
        f"overlay_skill:~/repo/plugin-internal/skills/{OVERLAY_SKILL_NAME}",
    )


def test_disabled_dev_mode_plugin_is_ignored(tmp_path: Path) -> None:
    stale = _stale_codex_cache(tmp_path)
    _skill(tmp_path / "repo/plugin-internal")
    _dev_mode(
        tmp_path,
        {
            "starboard-internal": {
                "path": str(tmp_path / "repo/plugin-internal"),
                "enabled": False,
            }
        },
    )
    assert find_overlay_skill(tmp_path, env={}) == stale


def test_malformed_dev_mode_file_falls_back(tmp_path: Path) -> None:
    stale = _stale_codex_cache(tmp_path)
    cfg = tmp_path / ".config/llm-cli/plugin-dev-mode.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{not json")
    assert find_overlay_skill(tmp_path, env={}) == stale
    _dev_mode(tmp_path, ["not", "a", "mapping"])
    assert find_overlay_skill(tmp_path, env={}) == stale


def test_claude_plugin_root_beats_dev_mode_and_caches(tmp_path: Path) -> None:
    _stale_codex_cache(tmp_path)
    loaded = _skill(tmp_path / "host-plugin")
    env = {"CLAUDE_PLUGIN_ROOT": str(tmp_path / "host-plugin")}
    assert find_overlay_skill(tmp_path, env=env) == loaded


def test_explicit_overlay_dir_wins(tmp_path: Path) -> None:
    _skill(tmp_path / "host-plugin")
    explicit = _skill(tmp_path / "pinned")
    env = {
        OVERLAY_DIR_ENV: str(explicit),
        "CLAUDE_PLUGIN_ROOT": str(tmp_path / "host-plugin"),
    }
    assert find_overlay_skill(tmp_path, env=env) == explicit


def test_env_dir_without_skill_md_is_skipped(tmp_path: Path) -> None:
    stale = _stale_codex_cache(tmp_path)
    (tmp_path / "empty").mkdir()
    env = {OVERLAY_DIR_ENV: str(tmp_path / "empty"), "CLAUDE_PLUGIN_ROOT": "relative"}
    assert find_overlay_skill(tmp_path, env=env) == stale


def test_claude_cache_beats_codex_cache(tmp_path: Path) -> None:
    _stale_codex_cache(tmp_path)
    claude = _skill(tmp_path / ".claude/plugins/cache/dev/starboard-internal/0.1.0")
    assert find_overlay_skill(tmp_path, env={}) == claude
