"""Run-5 Group B fix B6: ``verify run --templates`` names the overlay copy the host
loaded (dev-mode plugin path), not another host's stale plugin cache.

Tmp home + explicit ``env`` only; the real dev-mode file is never read or written.
"""

from __future__ import annotations

import json
from pathlib import Path

from starboard_skills.helpers.engagement import analysis_cmds as ac

_SKILL = "starboard-internal-overlay"


def _overlay(base: Path) -> Path:
    skill = base / "skills" / _SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: x\n---\n")
    (skill / ac.MIRROR_TEMPLATES_NAME).write_text("templates\n")
    return skill


def test_templates_follow_the_dev_mode_copy(tmp_path: Path) -> None:
    _overlay(tmp_path / ".codex/plugins/cache/dev/starboard-internal/0.1.0")
    _overlay(tmp_path / "Work/repo/plugin-internal")
    cfg = tmp_path / ".config/llm-cli/plugin-dev-mode.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        json.dumps(
            {
                "plugins": {
                    "starboard-internal": {
                        "path": str(tmp_path / "Work/repo/plugin-internal"),
                        "enabled": True,
                    }
                }
            }
        )
    )
    assert ac.mirror_templates(tmp_path, env={}) == (
        f"~/Work/repo/plugin-internal/skills/{_SKILL}/{ac.MIRROR_TEMPLATES_NAME}"
    )


def test_templates_outside_home_are_not_printed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    pinned = _overlay(tmp_path / "elsewhere")
    assert ac.mirror_templates(home, env={"STARBOARD_OVERLAY_DIR": str(pinned)}) is None
