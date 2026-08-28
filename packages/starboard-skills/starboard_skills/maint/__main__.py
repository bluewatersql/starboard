#!/usr/bin/env python3
"""starboard-maint — unified maintenance CLI for Starboard hosts.

Usage::

    starboard-maint install   [--host HOST] [--scope user|project]
    starboard-maint update    [--scope user|project]
    starboard-maint remove    [--host HOST] [--scope user|project]
    starboard-maint verify    [--host HOST]
    starboard-maint rules install [--scope user|project] [--domains DOMAIN,...]

Hosts: claude-code | isaac | codex | opencode | mcp | all
Scope auto-detected from CWD (.claude/.isaac present → project, else user).
State persisted in ~/.starboard/maint.json (user) or .starboard/maint.json (project).
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import starboard_skills
from starboard_skills.maint.backends import claude_code, codex, isaac, opencode, rules
from starboard_skills.maint.detect import Scope, detect_os, detect_scope, install_paths
from starboard_skills.maint.prereqs import PrereqError
from starboard_skills.maint.prereqs import check as check_prereqs
from starboard_skills.maint.state import (
    compute_skills_hash,
    mark_installed,
    mark_removed,
)
from starboard_skills.maint.state import (
    load as load_state,
)
from starboard_skills.maint.state import (
    save as save_state,
)

_ALL_HOSTS = ["claude-code", "isaac", "codex", "opencode"]
_PACKAGE_DIR = Path(starboard_skills.__file__).parent
_CANONICAL_SKILLS = _PACKAGE_DIR / "skills" / "starboard"

# The plugin dir for Isaac (dev-mode path; falls back to package skills).
def _plugin_dir() -> Path:
    """Locate the plugin directory (repo dev tree or package fallback)."""
    # Walk up from the package to find repo root (dev install).
    for parent in _PACKAGE_DIR.parents:
        candidate = parent / "plugin"
        if candidate.is_dir() and (candidate / ".claude-plugin").is_dir():
            return candidate
    # Wheel install fallback — use the vendored skills dir as the plugin.
    return _PACKAGE_DIR / "skills"


def _rules_src() -> Path:
    """Locate the rules source directory (repo plugin/rules or package fallback)."""
    for parent in _PACKAGE_DIR.parents:
        candidate = parent / "plugin" / "rules"
        if candidate.is_dir():
            return candidate
    return _PACKAGE_DIR / "rules"  # future wheel-vendored location


# --------------------------------------------------------------------------- #
# Sub-command implementations
# --------------------------------------------------------------------------- #

def _cmd_install(args: argparse.Namespace) -> int:
    scope: Scope = detect_scope(args.scope)
    os_name = detect_os()
    paths = install_paths(scope, os_name)
    hosts = _ALL_HOSTS if args.host == "all" else [args.host]

    state = load_state(paths["maint_json"])
    current_hash = compute_skills_hash(_CANONICAL_SKILLS)

    installed_any = False
    for host in hosts:
        # Idempotency check: skip if already installed at same hash.
        platform_state = state.get("platforms", {}).get(host, {})
        if (
            platform_state.get("status") == "installed"
            and state.get("skills_hash") == current_hash
        ):
            print("[claude-code] already up to date — no changes needed" if host == "claude-code"
                  else f"[{host}] already up to date — no changes needed")
            continue

        try:
            check_prereqs(host)
        except PrereqError as exc:
            print(f"[{host}] prereq check failed:\n{exc}", file=sys.stderr)
            return 1

        extra: dict[str, Any] = {}
        try:
            if host == "claude-code":
                extra = claude_code.install(_CANONICAL_SKILLS, paths["claude_skills"])
                print(f"[claude-code] installed skills to {paths['claude_skills']}")

            elif host == "isaac":
                plugin = _plugin_dir()
                extra = isaac.install(plugin)
                print(f"[isaac] registered plugin at {plugin}")

            elif host == "codex":
                # user: ~/AGENTS.md; project: ./AGENTS.md
                if scope == "project":
                    agents_md = Path.cwd() / "AGENTS.md"
                else:
                    agents_md = Path.home() / "AGENTS.md"
                extra = codex.install(agents_md, _CANONICAL_SKILLS)
                print(f"[codex] updated {agents_md}")

            elif host == "opencode":
                instructions = opencode.install_instructions(scope)
                print(instructions)
                extra = {"status_note": "prompt-based install — see instructions above"}

        except Exception as exc:  # noqa: BLE001
            print(f"[{host}] install failed: {exc}", file=sys.stderr)
            return 1

        mark_installed(
            state,
            platform=host,
            scope=scope,
            skills_hash=current_hash,
            extra=extra,
        )
        installed_any = True

    if installed_any:
        save_state(state, paths["maint_json"])
        print(f"State saved to {paths['maint_json']}")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Re-install all platforms recorded in maint.json."""
    scope: Scope = detect_scope(args.scope)
    os_name = detect_os()
    paths = install_paths(scope, os_name)
    state = load_state(paths["maint_json"])

    installed_platforms = list(state.get("platforms", {}).keys())
    if not installed_platforms:
        print("Nothing installed yet — run 'starboard-maint install' first.")
        return 0

    # Force re-install by clearing skills_hash (will bypass idempotency check).
    state["skills_hash"] = None
    save_state(state, paths["maint_json"])

    # Re-invoke install for each recorded platform.
    for platform in installed_platforms:
        fake_args = argparse.Namespace(scope=scope, host=platform)
        rc = _cmd_install(fake_args)
        if rc != 0:
            return rc
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    scope: Scope = detect_scope(args.scope)
    os_name = detect_os()
    paths = install_paths(scope, os_name)
    hosts = _ALL_HOSTS if args.host == "all" else [args.host]

    state = load_state(paths["maint_json"])

    for host in hosts:
        if host not in state.get("platforms", {}):
            print(f"[{host}] not installed — nothing to remove")
            continue

        try:
            if host == "claude-code":
                claude_code.remove(paths["claude_skills"])
                print(f"[claude-code] removed skills from {paths['claude_skills']}")

            elif host == "isaac":
                isaac.remove()
                print("[isaac] removed plugin dev entry")

            elif host == "codex":
                if scope == "project":
                    agents_md = Path.cwd() / "AGENTS.md"
                else:
                    agents_md = Path.home() / "AGENTS.md"
                codex.remove(agents_md)
                print(f"[codex] removed section from {agents_md}")

            elif host == "opencode":
                print("[opencode] no artifacts to remove (prompt-based install only)")

        except Exception as exc:  # noqa: BLE001
            print(f"[{host}] remove failed: {exc}", file=sys.stderr)
            return 1

        mark_removed(state, platform=host)

    save_state(state, paths["maint_json"])
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    scope: Scope = detect_scope(getattr(args, "scope", None))
    os_name = detect_os()
    paths = install_paths(scope, os_name)
    hosts: list[str] = _ALL_HOSTS if args.host == "all" else [args.host]

    all_ok = True
    for host in hosts:
        if host == "claude-code":
            ok, msg = claude_code.verify(_CANONICAL_SKILLS, paths["claude_skills"])
        elif host == "isaac":
            ok, msg = isaac.verify()
        elif host == "codex":
            agents_md = (Path.cwd() if scope == "project" else Path.home()) / "AGENTS.md"
            ok, msg = codex.verify(agents_md)
        elif host == "opencode":
            ok, msg = opencode.verify()
        else:
            print(f"[{host}] unknown host", file=sys.stderr)
            continue

        status = "OK" if ok else "FAIL"
        print(f"[{host}] {status}: {msg}")
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


def _cmd_rules_install(args: argparse.Namespace) -> int:
    scope: Scope = detect_scope(args.scope)
    os_name = detect_os()
    paths = install_paths(scope, os_name)

    domains: list[str] | None = None
    if getattr(args, "domains", None):
        domains = [d.strip() for d in args.domains.split(",") if d.strip()]

    rules_src = _rules_src()
    rules_dest = paths["isaac_rules"]

    state = load_state(paths["maint_json"])

    try:
        extra = rules.install(rules_src, rules_dest, domains)
    except FileNotFoundError as exc:
        print(f"[rules] install failed: {exc}", file=sys.stderr)
        print(
            "Hint: per-domain rulesets are generated by 'scripts/gen_rulesets.py' (X7).\n"
            "Run that script first, then re-run 'starboard-maint rules install'.",
            file=sys.stderr,
        )
        return 1

    deployed = extra.get("deployed_domains", [])
    missing = extra.get("missing_domains", [])
    if deployed:
        print(f"[rules] deployed {deployed} to {rules_dest}")
    if missing:
        print(f"[rules] skipped (not yet generated): {missing}")

    mark_installed(
        state,
        platform="rules",
        scope=scope,
        skills_hash=compute_skills_hash(_CANONICAL_SKILLS),
        extra=extra,
    )
    save_state(state, paths["maint_json"])
    return 0


# --------------------------------------------------------------------------- #
# Argument parser
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="starboard-maint",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # -- install
    pi = sub.add_parser("install", help="Install Starboard on one or all hosts")
    pi.add_argument(
        "--host",
        default="claude-code",
        choices=_ALL_HOSTS + ["all"],
        help="Target host (default: claude-code)",
    )
    pi.add_argument(
        "--scope",
        choices=["user", "project"],
        default=None,
        help="Install scope (auto-detected from CWD if omitted)",
    )

    # -- update
    pu = sub.add_parser("update", help="Re-install all recorded platforms")
    pu.add_argument("--scope", choices=["user", "project"], default=None)

    # -- remove
    pr = sub.add_parser("remove", help="Remove Starboard from one or all hosts")
    pr.add_argument(
        "--host",
        default="all",
        choices=_ALL_HOSTS + ["all"],
    )
    pr.add_argument("--scope", choices=["user", "project"], default=None)

    # -- verify
    pv = sub.add_parser("verify", help="Check install health across hosts")
    pv.add_argument(
        "--host",
        default="all",
        choices=_ALL_HOSTS + ["all"],
    )

    # -- rules (sub-group)
    prules = sub.add_parser("rules", help="Manage .isaac/rules deployments")
    rules_sub = prules.add_subparsers(dest="rules_command", metavar="RULES_COMMAND")
    rules_sub.required = True

    pri = rules_sub.add_parser("install", help="Deploy per-domain rulesets")
    pri.add_argument("--scope", choices=["user", "project"], default=None)
    pri.add_argument(
        "--domains",
        default=None,
        metavar="DOMAIN,...",
        help="Comma-separated list of domains (default: all available)",
    )

    return p


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "install":
        return _cmd_install(args)
    elif args.command == "update":
        return _cmd_update(args)
    elif args.command == "remove":
        return _cmd_remove(args)
    elif args.command == "verify":
        return _cmd_verify(args)
    elif args.command == "rules" and args.rules_command == "install":
        return _cmd_rules_install(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
