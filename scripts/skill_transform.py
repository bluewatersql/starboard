#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Shared host-portability transform for generated non-Claude skill bundles.

The canonical skills lead with the portable ``python -m starboard_x.<cap>``
invocation and document ``${CLAUDE_SKILL_DIR}/scripts/run.sh`` as the *Claude
Code convenience* wrapper (it runs the identical command with no permission
prompt because it matches the skill's ``allowed-tools`` prefix).

``${CLAUDE_SKILL_DIR}`` is set **only** by Claude Code. On Codex / OpenCode /
``databricks aitools`` it is empty, so ``${CLAUDE_SKILL_DIR}/scripts/run.sh``
resolves to ``/scripts/run.sh`` and breaks. This module rewrites that token to
the portable command the wrapper *execs* (``python -m starboard_x.<cap>`` or
``starboard <verb>``), so the generated aitools / opencode bundles are
host-neutral. The Claude-Code plugin mirror (``plugin/``) is deliberately left
verbatim — Claude Code sets ``CLAUDE_SKILL_DIR`` and the wrapper is the correct,
pre-approved path there.

Two deterministic steps (no parsing of the skill prose), so the output stays
reproducible under the ``--check`` drift guards:

1. **Strip** the ``<!-- claude-only -->…<!-- /claude-only -->`` fenced note (the
   Claude-Code convenience-wrapper guidance) — the non-Claude bundles must not
   carry it, and stripping it avoids the circular "use X in place of X" prose a
   blind substitution would leave behind.
2. **Substitute** any remaining ``${CLAUDE_SKILL_DIR}/scripts/run.sh`` token
   (e.g. in ``allowed-tools`` or an agent body) with the portable command.
"""

from __future__ import annotations

import re
from pathlib import Path

#: The Claude-Code-only invocation token that must not ship to other hosts.
RUN_SH_TOKEN = "${CLAUDE_SKILL_DIR}/scripts/run.sh"

#: Canonical bodies fence the Claude-Code "convenience wrapper" note (the
#: sentence that presents ``${CLAUDE_SKILL_DIR}/scripts/run.sh`` as the
#: pre-approved, no-permission-prompt path) between these HTML-comment markers.
#: The Claude plugin mirror keeps the fenced note verbatim (Claude Code needs
#: it); the non-Claude bundles strip the whole block so they carry neither the
#: Claude-only guidance nor the circular "use X in place of X" prose that a
#: blind token substitution would otherwise produce.
CLAUDE_ONLY_OPEN = "<!-- claude-only -->"
CLAUDE_ONLY_CLOSE = "<!-- /claude-only -->"
_CLAUDE_ONLY_RE = re.compile(
    r"\n?[ \t]*<!-- claude-only -->\n.*?\n[ \t]*<!-- /claude-only -->[ \t]*\n",
    re.DOTALL,
)

#: Text file extensions whose bodies carry the token and get rewritten.
TRANSFORMABLE_SUFFIXES = frozenset({".md", ".sh"})

#: Autonomous/scheduled agents wrap a base skill; their run.sh reference points
#: at the base skill's wrapper. Strip these suffixes to resolve the command.
_AGENT_SUFFIXES = ("-auto", "-monitor")


def resolve_run_sh_command(run_sh_text: str) -> str:
    """Return the portable command a ``scripts/run.sh`` wrapper execs.

    Reads the ``exec <command> "$@"`` line and returns ``<command>`` with the
    ``"$@"`` / ``$@`` argument-forwarding token stripped. Raises ``ValueError``
    when no ``exec`` line is present.
    """
    for raw in run_sh_text.splitlines():
        line = raw.strip()
        if line.startswith("exec "):
            cmd = line[len("exec ") :]
            cmd = cmd.replace('"$@"', "").replace("$@", "")
            return cmd.strip()
    raise ValueError("run.sh has no 'exec <command>' line")


def build_command_map(skills_root: Path) -> dict[str, str]:
    """Map each skill dir name to the portable command its run.sh execs.

    Skills without a ``scripts/run.sh`` are absent from the map (they carry no
    ``${CLAUDE_SKILL_DIR}`` token and need no transform).
    """
    command_map: dict[str, str] = {}
    for run_sh in sorted(skills_root.glob("*/scripts/run.sh")):
        skill_name = run_sh.parent.parent.name
        command_map[skill_name] = resolve_run_sh_command(
            run_sh.read_text(encoding="utf-8")
        )
    return command_map


def command_for(name: str, command_map: dict[str, str]) -> str | None:
    """Resolve the portable command for a skill or agent *name*.

    Exact skill-name matches win; autonomous agent names (``*-auto`` /
    ``*-monitor``) fall back to their base skill's command.
    """
    if name in command_map:
        return command_map[name]
    for suffix in _AGENT_SUFFIXES:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            if base in command_map:
                return command_map[base]
    return None


def strip_claude_only_blocks(text: str) -> str:
    """Remove ``<!-- claude-only -->…<!-- /claude-only -->`` fenced blocks."""
    return _CLAUDE_ONLY_RE.sub("", text)


def transform_text(text: str, command: str) -> str:
    """Make body *text* host-neutral.

    Strips the Claude-only convenience-wrapper note, then rewrites any remaining
    Claude-Code run.sh token (e.g. in ``allowed-tools`` or an agent body) to the
    portable *command*.
    """
    text = strip_claude_only_blocks(text)
    return text.replace(RUN_SH_TOKEN, command)


def transform_file_bytes(path: Path, raw: bytes, command: str | None) -> bytes:
    """Return the host-neutral bytes for *path*.

    Text files (``.md`` / ``.sh``) with a resolved *command* are rewritten;
    everything else (and files for skills without a wrapper) is returned
    unchanged.
    """
    if command is None or path.suffix not in TRANSFORMABLE_SUFFIXES:
        return raw
    return transform_text(raw.decode("utf-8"), command).encode("utf-8")
