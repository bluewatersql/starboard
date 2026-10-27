"""Unit tests for starboard-maint (E1).

Coverage matrix per spec:
- OS detection (darwin / linux / wsl)
- Scope detection (auto user, auto project, explicit override)
- Idempotent re-install is a no-op (hash/state compare)
- Remove reverses install (state entry gone, files removed)
- Verify reports drift (installed file modified -> drift detected)
- Missing prerequisite -> actionable PrereqError
- maint.json round-trip (save -> load -> equal)
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skills_tree(root: Path) -> Path:
    """Create a minimal canonical skills tree under *root* and return it."""
    skills = root / "skills" / "starboard"
    for skill in ("starboard-warehouse", "starboard-query"):
        d = skills / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: test\n---\n\nBody.\n"
        )
    return skills


# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

class TestDetectOS:
    def test_darwin(self):
        from starboard_skills.maint.detect import detect_os
        with patch("sys.platform", "darwin"):
            assert detect_os() == "darwin"

    def test_linux_plain(self, tmp_path):
        from starboard_skills.maint.detect import detect_os
        proc_content = "Linux version 5.15.0"
        with patch("sys.platform", "linux"), \
             patch("starboard_skills.maint.detect._PROC_VERSION", str(tmp_path / "version")):
            (tmp_path / "version").write_text(proc_content)
            assert detect_os() == "linux"

    def test_linux_proc_missing(self):
        from starboard_skills.maint.detect import detect_os
        with patch("sys.platform", "linux"), \
             patch("starboard_skills.maint.detect._PROC_VERSION", "/nonexistent/proc/version"):
            assert detect_os() == "linux"

    def test_wsl(self, tmp_path):
        from starboard_skills.maint.detect import detect_os
        proc = tmp_path / "proc_version"
        proc.write_text("Linux version 5.15 (Microsoft WSL2)")
        with patch("sys.platform", "linux"), \
             patch("starboard_skills.maint.detect._PROC_VERSION", str(proc)):
            assert detect_os() == "wsl"

    def test_wsl_microsoft_keyword(self, tmp_path):
        from starboard_skills.maint.detect import detect_os
        proc = tmp_path / "proc_version"
        proc.write_text("Linux version 5.15 (microsoft)")
        with patch("sys.platform", "linux"), \
             patch("starboard_skills.maint.detect._PROC_VERSION", str(proc)):
            assert detect_os() == "wsl"


# ---------------------------------------------------------------------------
# Scope detection
# ---------------------------------------------------------------------------

class TestDetectScope:
    def test_explicit_user(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        assert detect_scope("user", cwd=tmp_path) == "user"

    def test_explicit_project(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        assert detect_scope("project", cwd=tmp_path) == "project"

    def test_invalid_explicit_raises(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        with pytest.raises(ValueError, match="scope must be"):
            detect_scope("global", cwd=tmp_path)

    def test_auto_user_when_no_dotclaude(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        # tmp_path has no .claude or .isaac
        assert detect_scope(None, cwd=tmp_path) == "user"

    def test_auto_project_when_dotclaude_exists(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        (tmp_path / ".claude").mkdir()
        assert detect_scope(None, cwd=tmp_path) == "project"

    def test_auto_project_when_dotisaac_exists(self, tmp_path):
        from starboard_skills.maint.detect import detect_scope
        (tmp_path / ".isaac").mkdir()
        assert detect_scope(None, cwd=tmp_path) == "project"


# ---------------------------------------------------------------------------
# install_paths
# ---------------------------------------------------------------------------

class TestInstallPaths:
    def test_project_paths_are_cwd_relative(self, tmp_path):
        from starboard_skills.maint.detect import install_paths
        paths = install_paths("project", os_name="linux", cwd=tmp_path)
        assert paths["maint_json"] == tmp_path / ".starboard" / "maint.json"
        assert paths["claude_skills"] == tmp_path / ".claude" / "skills" / "starboard"
        assert paths["isaac_rules"] == tmp_path / ".isaac" / "rules"

    def test_user_paths_are_home_relative(self, tmp_path):
        from starboard_skills.maint.detect import install_paths
        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = install_paths("user", os_name="linux")
        assert paths["maint_json"] == tmp_path / ".starboard" / "maint.json"
        assert paths["claude_skills"] == tmp_path / ".claude" / "skills" / "starboard"

    def test_darwin_user_paths(self, tmp_path):
        from starboard_skills.maint.detect import install_paths
        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = install_paths("user", os_name="darwin")
        # For user scope, Claude skills always go to ~/.claude/skills/starboard
        assert paths["claude_skills"] == tmp_path / ".claude" / "skills" / "starboard"


# ---------------------------------------------------------------------------
# maint.json round-trip
# ---------------------------------------------------------------------------

class TestStateRoundTrip:
    def test_save_and_load(self, tmp_path):
        from starboard_skills.maint.state import load, save
        maint_json = tmp_path / ".starboard" / "maint.json"
        state = {
            "schema_version": "1.0",
            "scope": "user",
            "platforms": {"claude-code": {"status": "installed"}},
        }
        save(state, maint_json)
        loaded = load(maint_json)
        assert loaded["schema_version"] == "1.0"
        assert loaded["platforms"]["claude-code"]["status"] == "installed"

    def test_load_missing_returns_skeleton(self, tmp_path):
        from starboard_skills.maint.state import load
        state = load(tmp_path / "nonexistent.json")
        assert state["schema_version"] == "1.0"
        assert state["platforms"] == {}
        assert state["installed_at"] is None

    def test_load_corrupt_returns_skeleton(self, tmp_path):
        from starboard_skills.maint.state import load
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{")
        state = load(bad)
        assert state["platforms"] == {}

    def test_mark_installed_and_removed(self, tmp_path):
        from starboard_skills.maint.state import (
            load,
            mark_installed,
            mark_removed,
        )
        maint_json = tmp_path / "maint.json"
        state = load(maint_json)
        mark_installed(state, platform="claude-code", scope="user",
                       skills_hash="sha256:abc", extra={"skills_path": "/tmp/s"})
        assert state["platforms"]["claude-code"]["status"] == "installed"
        assert state["skills_hash"] == "sha256:abc"

        mark_removed(state, platform="claude-code")
        assert "claude-code" not in state["platforms"]

    def test_compute_skills_hash_stable(self, tmp_path):
        from starboard_skills.maint.state import compute_skills_hash
        skills = _make_skills_tree(tmp_path)
        h1 = compute_skills_hash(skills)
        h2 = compute_skills_hash(skills)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_compute_skills_hash_empty(self, tmp_path):
        from starboard_skills.maint.state import compute_skills_hash
        assert compute_skills_hash(tmp_path / "nonexistent") == "sha256:empty"

    def test_compute_skills_hash_detects_change(self, tmp_path):
        from starboard_skills.maint.state import compute_skills_hash
        skills = _make_skills_tree(tmp_path)
        h1 = compute_skills_hash(skills)
        # Modify one file.
        (skills / "starboard-warehouse" / "SKILL.md").write_text("changed")
        h2 = compute_skills_hash(skills)
        assert h1 != h2


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

class TestPrereqs:
    def test_missing_starboard_helper_raises(self):
        from starboard_skills.maint.prereqs import PrereqError, check
        with patch("shutil.which", return_value=None), pytest.raises(PrereqError) as exc_info:
            check("claude-code")
        msg = str(exc_info.value)
        assert "starboard-helper" in msg
        assert "pip install" in msg or "uv pip install" in msg

    def test_missing_isaac_cli_raises(self):
        from starboard_skills.maint.prereqs import PrereqError, check

        def which_side_effect(name: str) -> str | None:
            return "/usr/bin/starboard-helper" if name == "starboard-helper" else None

        with patch("shutil.which", side_effect=which_side_effect), pytest.raises(PrereqError) as exc_info:
            check("isaac")
        msg = str(exc_info.value)
        assert "isaac" in msg.lower()

    def test_all_present_does_not_raise(self):
        from starboard_skills.maint.prereqs import check
        with patch("shutil.which", return_value="/usr/bin/something"):
            check("claude-code")  # should not raise

    def test_unknown_host_is_no_op(self):
        from starboard_skills.maint.prereqs import check
        check("unknown-host")  # no checks registered → no error


# ---------------------------------------------------------------------------
# Claude Code backend
# ---------------------------------------------------------------------------

class TestClaudeCodeBackend:
    def test_install_copies_tree(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import install
        skills_src = _make_skills_tree(tmp_path / "src")
        skills_dest = tmp_path / "dest" / ".claude" / "skills" / "starboard"

        extra = install(skills_src, skills_dest)
        assert extra["skills_path"] == str(skills_dest)
        assert (skills_dest / "starboard-warehouse" / "SKILL.md").is_file()

    def test_install_missing_src_raises(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import install
        with pytest.raises(FileNotFoundError):
            install(tmp_path / "nonexistent", tmp_path / "dest")

    def test_verify_ok_after_install(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import install, verify
        skills_src = _make_skills_tree(tmp_path / "src")
        skills_dest = tmp_path / "dest"
        install(skills_src, skills_dest)
        ok, msg = verify(skills_src, skills_dest)
        assert ok, msg

    def test_verify_not_installed(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import verify
        skills_src = _make_skills_tree(tmp_path / "src")
        ok, msg = verify(skills_src, tmp_path / "nonexistent")
        assert not ok
        assert "Not installed" in msg

    def test_verify_detects_drift(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import install, verify
        skills_src = _make_skills_tree(tmp_path / "src")
        skills_dest = tmp_path / "dest"
        install(skills_src, skills_dest)
        # Modify an installed file to create drift.
        (skills_dest / "starboard-warehouse" / "SKILL.md").write_text("tampered")
        ok, msg = verify(skills_src, skills_dest)
        assert not ok
        assert "Drift" in msg or "differs" in msg.lower()

    def test_remove_cleans_up(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import install, remove
        skills_src = _make_skills_tree(tmp_path / "src")
        skills_dest = tmp_path / "dest"
        install(skills_src, skills_dest)
        assert skills_dest.is_dir()
        remove(skills_dest)
        assert not skills_dest.exists()

    def test_remove_nonexistent_is_safe(self, tmp_path):
        from starboard_skills.maint.backends.claude_code import remove
        remove(tmp_path / "nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# Canonical skills-tree resolution (dev checkout vs. built wheel)
# ---------------------------------------------------------------------------

class TestCanonicalSkillsResolution:
    def test_prefers_dev_tree_sibling(self, tmp_path):
        """Editable checkout: skills live beside the package dir."""
        from starboard_skills.maint.__main__ import _resolve_canonical_skills
        pkg = tmp_path / "pkgroot" / "starboard_skills"
        pkg.mkdir(parents=True)
        dev = tmp_path / "pkgroot" / "skills" / "starboard"
        dev.mkdir(parents=True)
        assert _resolve_canonical_skills(pkg) == dev

    def test_falls_back_to_vendored(self, tmp_path):
        """Built wheel: skills are force-included inside the package dir."""
        from starboard_skills.maint.__main__ import _resolve_canonical_skills
        pkg = tmp_path / "pkgroot" / "starboard_skills"
        vendored = pkg / "skills" / "starboard"
        vendored.mkdir(parents=True)
        assert _resolve_canonical_skills(pkg) == vendored

    def test_module_constant_points_at_real_tree(self):
        """The resolved constant must exist in this (editable) install."""
        from starboard_skills.maint import __main__ as m
        assert m._CANONICAL_SKILLS.is_dir()
        assert (m._CANONICAL_SKILLS / "starboard-diagnostic" / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# Idempotent re-install
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_second_install_is_noop(self, tmp_path, capsys):
        """Install twice; second call prints 'already up to date' and state unchanged."""
        from starboard_skills.maint.__main__ import _cmd_install
        from starboard_skills.maint.detect import install_paths
        from starboard_skills.maint.state import load

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)

        # Patch canonical skills + prereqs.
        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.check_prereqs"):

            args1 = _make_args(host="claude-code", scope="project")
            with patch("starboard_skills.maint.__main__.install_paths",
                       return_value=paths):
                rc1 = _cmd_install(args1)

            assert rc1 == 0
            state_after_first = load(paths["maint_json"])

            args2 = _make_args(host="claude-code", scope="project")
            with patch("starboard_skills.maint.__main__.install_paths",
                       return_value=paths):
                rc2 = _cmd_install(args2)

        assert rc2 == 0
        captured = capsys.readouterr().out
        assert "already up to date" in captured.lower()

        # State should be identical (no updated_at change since no write).
        state_after_second = load(paths["maint_json"])
        assert (
            state_after_first["platforms"]["claude-code"]["installed_at"]
            == state_after_second["platforms"]["claude-code"]["installed_at"]
        )


# ---------------------------------------------------------------------------
# update refreshes every recorded platform
# ---------------------------------------------------------------------------

class TestUpdateRefreshesAllPlatforms:
    def test_update_reinstalls_every_recorded_host(self, tmp_path):
        """`update` must force-refresh ALL recorded hosts, not just the first.

        Regression guard: mark_installed rewrites the global skills_hash after
        the first host, so a non-forced update would trip the idempotency guard
        for every subsequent host and silently skip it.
        """
        from starboard_skills.maint.__main__ import _cmd_install, _cmd_update
        from starboard_skills.maint.detect import install_paths
        from starboard_skills.maint.state import load

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)

        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.check_prereqs"), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths), \
             patch("starboard_skills.maint.__main__.claude_code") as cc, \
             patch("starboard_skills.maint.__main__.codex") as cx:
            cc.install.return_value = {}
            cx.install.return_value = {}

            assert _cmd_install(_make_args(host="claude-code", scope="project")) == 0
            assert _cmd_install(_make_args(host="codex", scope="project")) == 0
            state = load(paths["maint_json"])
            assert set(state["platforms"]) == {"claude-code", "codex"}

            cc.install.reset_mock()
            cx.install.reset_mock()

            assert _cmd_update(_make_args(scope="project")) == 0

            assert cc.install.call_count == 1, "claude-code was not refreshed by update"
            assert cx.install.call_count == 1, "codex was not refreshed by update (finding 1)"

    def test_update_empty_state_is_noop(self, tmp_path, capsys):
        from starboard_skills.maint.__main__ import _cmd_update
        from starboard_skills.maint.detect import install_paths

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)
        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths):
            assert _cmd_update(_make_args(scope="project")) == 0
        assert "nothing installed" in capsys.readouterr().out.lower()

    def test_update_redeploys_rules(self, tmp_path):
        """`update` must actually re-deploy rulesets (finding 2).

        Previously the 'rules' pseudo-platform hit the host install chain, which
        has no 'rules' branch: nothing was copied yet a successful install was
        recorded. This proves changed ruleset content lands on update.
        """
        from starboard_skills.maint.__main__ import _cmd_rules_install, _cmd_update
        from starboard_skills.maint.detect import install_paths

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)
        rules_src = tmp_path / "rules_src"
        rules_src.mkdir()
        (rules_src / "starboard.md").write_text("# router\n")
        (rules_src / "starboard-jobs.md").write_text("# jobs v1\n")

        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths), \
             patch("starboard_skills.maint.__main__._rules_src", return_value=rules_src):
            assert _cmd_rules_install(
                _make_args(scope="project", domains="baseline,jobs")
            ) == 0
            dest = paths["isaac_rules"]
            assert (dest / "starboard-jobs.md").read_text() == "# jobs v1\n"

            # Change the source, then update.
            (rules_src / "starboard-jobs.md").write_text("# jobs v2\n")
            assert _cmd_update(_make_args(scope="project")) == 0

            assert (dest / "starboard-jobs.md").read_text() == "# jobs v2\n", (
                "update did not re-deploy the changed ruleset (finding 2)"
            )


# ---------------------------------------------------------------------------
# Remove reverses install
# ---------------------------------------------------------------------------

class TestRemoveReversesInstall:
    def test_install_then_remove_clears_state(self, tmp_path):
        from starboard_skills.maint.__main__ import _cmd_install, _cmd_remove
        from starboard_skills.maint.detect import install_paths
        from starboard_skills.maint.state import load

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)

        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.check_prereqs"), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths):

            rc = _cmd_install(_make_args(host="claude-code", scope="project"))
            assert rc == 0

            state = load(paths["maint_json"])
            assert "claude-code" in state["platforms"]

            rc = _cmd_remove(_make_args(host="claude-code", scope="project"))
            assert rc == 0

        state_after = load(paths["maint_json"])
        assert "claude-code" not in state_after.get("platforms", {})
        # Skills directory should be gone.
        assert not paths["claude_skills"].exists()


# ---------------------------------------------------------------------------
# Verify reports drift
# ---------------------------------------------------------------------------

class TestVerifyReportsDrift:
    def test_verify_after_tamper_returns_nonzero(self, tmp_path):
        from starboard_skills.maint.__main__ import _cmd_install, _cmd_verify
        from starboard_skills.maint.detect import install_paths

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)

        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.check_prereqs"), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths):

            _cmd_install(_make_args(host="claude-code", scope="project"))
            # Tamper with an installed file.
            (paths["claude_skills"] / "starboard-warehouse" / "SKILL.md").write_text("tampered")

            rc = _cmd_verify(_make_args(host="claude-code"))

        assert rc == 1  # drift detected

    def test_verify_after_clean_install_returns_zero(self, tmp_path, capsys):
        from starboard_skills.maint.__main__ import _cmd_install, _cmd_verify
        from starboard_skills.maint.detect import install_paths

        skills_src = _make_skills_tree(tmp_path / "canonical")
        paths = install_paths("project", os_name="linux", cwd=tmp_path)

        with patch("starboard_skills.maint.__main__._CANONICAL_SKILLS", skills_src), \
             patch("starboard_skills.maint.__main__.check_prereqs"), \
             patch("starboard_skills.maint.__main__.install_paths", return_value=paths):

            _cmd_install(_make_args(host="claude-code", scope="project"))
            rc = _cmd_verify(_make_args(host="claude-code"))

        assert rc == 0


# ---------------------------------------------------------------------------
# Codex backend
# ---------------------------------------------------------------------------

class TestCodexBackend:
    def test_install_creates_agents_md(self, tmp_path):
        from starboard_skills.maint.backends.codex import install, verify
        skills_src = _make_skills_tree(tmp_path / "skills")
        agents_md = tmp_path / "AGENTS.md"
        install(agents_md, skills_src)
        ok, msg = verify(agents_md)
        assert ok, msg

    def test_install_idempotent(self, tmp_path):
        from starboard_skills.maint.backends.codex import install, verify
        skills_src = _make_skills_tree(tmp_path / "skills")
        agents_md = tmp_path / "AGENTS.md"
        install(agents_md, skills_src)
        install(agents_md, skills_src)  # second call
        content = agents_md.read_text()
        # Only one starboard section.
        assert content.count("starboard-maint:start") == 1
        ok, msg = verify(agents_md)
        assert ok, msg

    def test_remove_strips_section(self, tmp_path):
        from starboard_skills.maint.backends.codex import install, remove, verify
        skills_src = _make_skills_tree(tmp_path / "skills")
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Existing content\n\nSome notes.\n")
        install(agents_md, skills_src)
        remove(agents_md)
        ok, _ = verify(agents_md)
        assert not ok
        # Original content preserved.
        assert "Existing content" in agents_md.read_text()

    def test_verify_missing_file(self, tmp_path):
        from starboard_skills.maint.backends.codex import verify
        ok, msg = verify(tmp_path / "AGENTS.md")
        assert not ok
        assert "Not installed" in msg


# ---------------------------------------------------------------------------
# OpenCode backend
# ---------------------------------------------------------------------------

class TestOpenCodeBackend:
    def test_instructions_contain_pip_install(self):
        from starboard_skills.maint.backends.opencode import install_instructions
        text = install_instructions("user")
        assert "pip install" in text
        assert "starboard-helper" in text

    def test_instructions_mention_scope(self):
        from starboard_skills.maint.backends.opencode import install_instructions
        user_text = install_instructions("user")
        project_text = install_instructions("project")
        assert "user" in user_text.lower()
        assert "project" in project_text.lower()

    def test_verify_helper_present(self):
        from starboard_skills.maint.backends.opencode import verify
        with patch("shutil.which", return_value="/usr/bin/starboard-helper"):
            ok, msg = verify()
        assert ok

    def test_verify_helper_missing(self):
        from starboard_skills.maint.backends.opencode import verify
        with patch("shutil.which", return_value=None):
            ok, msg = verify()
        assert not ok
        assert "pip install" in msg


# ---------------------------------------------------------------------------
# Rules backend
# ---------------------------------------------------------------------------

class TestRulesBackend:
    def _make_rules(self, rules_dir: Path, domains: list[str]) -> None:
        rules_dir.mkdir(parents=True, exist_ok=True)
        for domain in domains:
            (rules_dir / f"starboard-{domain}.md").write_text(f"# {domain} rules\n")

    def test_install_copies_rules(self, tmp_path):
        from starboard_skills.maint.backends.rules import install, verify
        rules_src = tmp_path / "rules_src"
        self._make_rules(rules_src, ["jobs", "sql"])
        rules_dest = tmp_path / "rules_dest"

        extra = install(rules_src, rules_dest, domains=["jobs", "sql"])
        assert "jobs" in extra["deployed_domains"]
        assert "sql" in extra["deployed_domains"]
        ok, msg = verify(rules_src, rules_dest, domains=["jobs", "sql"])
        assert ok, msg

    def test_install_missing_src_raises(self, tmp_path):
        from starboard_skills.maint.backends.rules import install
        with pytest.raises(FileNotFoundError):
            install(tmp_path / "nonexistent", tmp_path / "dest")

    def test_missing_domain_files_are_skipped(self, tmp_path):
        from starboard_skills.maint.backends.rules import install
        rules_src = tmp_path / "rules_src"
        self._make_rules(rules_src, ["jobs"])  # no sql file
        rules_dest = tmp_path / "rules_dest"

        extra = install(rules_src, rules_dest, domains=["jobs", "sql"])
        assert "jobs" in extra["deployed_domains"]
        assert "sql" in extra["missing_domains"]

    def test_remove_deletes_files(self, tmp_path):
        from starboard_skills.maint.backends.rules import install, remove
        rules_src = tmp_path / "rules_src"
        self._make_rules(rules_src, ["jobs", "sql"])
        rules_dest = tmp_path / "rules_dest"
        install(rules_src, rules_dest, domains=["jobs", "sql"])
        remove(rules_dest, domains=["jobs", "sql"])
        assert not (rules_dest / "starboard-jobs.md").exists()
        assert not (rules_dest / "starboard-sql.md").exists()

    def test_verify_detects_drift(self, tmp_path):
        from starboard_skills.maint.backends.rules import install, verify
        rules_src = tmp_path / "rules_src"
        self._make_rules(rules_src, ["jobs"])
        rules_dest = tmp_path / "rules_dest"
        install(rules_src, rules_dest, domains=["jobs"])
        # Tamper.
        (rules_dest / "starboard-jobs.md").write_text("tampered")
        ok, msg = verify(rules_src, rules_dest, domains=["jobs"])
        assert not ok
        assert "drift" in msg.lower()


# ---------------------------------------------------------------------------
# CLI parser wiring
# ---------------------------------------------------------------------------

class TestCLIParser:
    def test_install_parses(self):
        from starboard_skills.maint.__main__ import _build_parser
        args = _build_parser().parse_args(["install", "--host", "claude-code", "--scope", "user"])
        assert args.command == "install"
        assert args.host == "claude-code"
        assert args.scope == "user"

    def test_rules_install_parses(self):
        from starboard_skills.maint.__main__ import _build_parser
        args = _build_parser().parse_args(
            ["rules", "install", "--scope", "project", "--domains", "jobs,sql"]
        )
        assert args.command == "rules"
        assert args.rules_command == "install"
        assert args.domains == "jobs,sql"

    def test_verify_parses(self):
        from starboard_skills.maint.__main__ import _build_parser
        args = _build_parser().parse_args(["verify", "--host", "codex"])
        assert args.command == "verify"
        assert args.host == "codex"

    def test_missing_command_exits(self):
        from starboard_skills.maint.__main__ import _build_parser
        with pytest.raises(SystemExit):
            _build_parser().parse_args([])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_args(**kwargs: object) -> object:
    """Build a SimpleNamespace with defaults for argparse args."""
    defaults = {"host": "claude-code", "scope": None, "domains": None, "rules_command": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)
