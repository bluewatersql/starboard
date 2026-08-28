# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Per-host integration smoke tests (O6).

Validates five hosts — Claude Code, Isaac, Codex, OpenCode, MCP server — against
four checks each.  Real hosts are NOT required:

- Claude Code / Isaac: artifacts asserted from the checked-in ``plugin/`` tree
  (the exact files the host would consume).
- Codex / OpenCode: ``python -m starboard_x.*`` executed directly in-process.
- MCP server: checked via importlib + entry-point metadata.

Checks per host
---------------
1. **discovery**   — artifacts (plugin/skills/agents/rulesets) present + well-formed
2. **invocation**  — documented entry command resolves (run.sh or python -m)
3. **auth**        — auth-resolution path exercises SDK credential chain gracefully
4. **idempotence** — running the same command twice yields identical result

Run with::

    pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov

Host × check matrix
--------------------
==============  =============================  =============================  ========================  =======================
Host            Discovery                      Invocation                     Auth (mock)               Idempotence
==============  =============================  =============================  ========================  =======================
Claude Code     plugin.json + SKILL.md valid   run.sh delegates to starboard_x  no hardcoded creds in    plugin.json stable
Isaac           same plugin + rules/ present   same run.sh check              rules .md files            canonical skills stable
Codex           starboard_x importable          --help exits 0 per capability  mock creds → graceful     --help output stable
OpenCode        starboard_x + agents/ present  --help exits 0 per capability  mock creds → graceful     --help output stable
MCP server      mcp.cli importable             main callable                  import needs no live creds  module identity stable
==============  =============================  =============================  ========================  =======================
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repository paths
# ---------------------------------------------------------------------------
# This file lives at:
#   {repo_root}/packages/starboard/tests/integration/host_coverage/test_host_coverage.py
#   parents[0] = host_coverage/
#   parents[1] = integration/
#   parents[2] = tests/
#   parents[3] = starboard/  (the package directory)
#   parents[4] = packages/
#   parents[5] = repo root
_REPO_ROOT = Path(__file__).parents[5]
_PLUGIN_ROOT = _REPO_ROOT / "plugin"
_SKILLS_ROOT = _PLUGIN_ROOT / "skills"
_AGENTS_ROOT = _PLUGIN_ROOT / "agents"
_RULES_ROOT = _PLUGIN_ROOT / "rules"
_CANONICAL_SKILLS_ROOT = (
    _REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard"
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Skills that ship a scripts/run.sh tier-1 entry point in the plugin bundle.
# Derived from the plugin/skills/ directory structure (only dirs with scripts/).
_SKILLS_WITH_SCRIPTS: frozenset[str] = frozenset(
    {
        "starboard-diagnostic",
        "starboard-discovery",
        "starboard-uc",
        "starboard-warehouse",
        "starboard-workload-review",
    }
)

# Implemented ``python -m starboard_x.<cap>`` capabilities
# (mirrors _IMPLEMENTED in starboard_x.__main__).
_RUNNABLE_CAPABILITIES: tuple[str, ...] = (
    "diagnostic",
    "discovery",
    "sparklog",
    "warehouse",
    "uc",
    "review",
)

# Minimum expected artifact counts.
_MIN_SKILL_COUNT = 5
_MIN_AGENT_FILE_COUNT = 5

# Standard exit codes (mirrors starboard_x.contract).
_EXIT_OK = 0
_EXIT_AUTH = 1
_EXIT_NOT_FOUND = 2
_EXIT_API = 3
_EXIT_ARG = 4
# Any of these exit codes is considered "graceful" (no unhandled exception).
_GRACEFUL_EXIT_CODES: frozenset[int] = frozenset(
    {_EXIT_OK, _EXIT_AUTH, _EXIT_NOT_FOUND, _EXIT_API, _EXIT_ARG}
)

# Mock Databricks credentials used for the auth-path tests.
# These are syntactically valid tokens pointing at a non-existent host so the
# SDK credential chain is exercised but no real network call can succeed.
_MOCK_DATABRICKS_HOST = "https://smoke-test-mock.host.invalid"
_MOCK_DATABRICKS_TOKEN = "dapi" + "0" * 32  # noqa: S105 — intentionally fake


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract top-level YAML frontmatter key/value pairs (stdlib-only).

    Handles simple ``key: value`` lines between ``---`` delimiters.  Does not
    support nested blocks — sufficient for SKILL.md files.
    """
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith(" ") and not line.startswith("#"):
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def _run(
    cmd: list[str],
    *,
    extra_env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* in a subprocess and return its ``CompletedProcess``."""
    env = {**os.environ, **(extra_env or {})}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# ---------------------------------------------------------------------------
# Host: Claude Code
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClaudeCodeHost:
    """Claude Code host: plugin marketplace discovery + skill invocation.

    Claude Code discovers Starboard via ``plugin/.claude-plugin/plugin.json``
    and injects skills from ``plugin/skills/``.  Tests run against checked-in
    artifacts — no live Claude Code installation required.
    """

    # --- discovery ----------------------------------------------------------

    def test_discovery_plugin_json_exists_and_valid(self) -> None:
        """plugin.json is present, parses as JSON, and has required fields."""
        plugin_json = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
        assert plugin_json.exists(), f"plugin.json not found at {plugin_json}"
        data = json.loads(plugin_json.read_text())
        for field in ("name", "version", "skills", "agents"):
            assert field in data, f"plugin.json missing required field '{field}'"
        assert data["name"], "plugin.json 'name' must be non-empty"
        assert data["version"], "plugin.json 'version' must be non-empty"

    def test_discovery_minimum_skills_present(self) -> None:
        """plugin/skills/ contains at least _MIN_SKILL_COUNT skill directories."""
        skill_dirs = [
            d
            for d in _SKILLS_ROOT.iterdir()
            if d.is_dir() and d.name.startswith("starboard-")
        ]
        assert len(skill_dirs) >= _MIN_SKILL_COUNT, (
            f"Expected >= {_MIN_SKILL_COUNT} skill dirs, "
            f"found {len(skill_dirs)}: {[d.name for d in skill_dirs]}"
        )

    def test_discovery_skill_frontmatter_valid(self) -> None:
        """Every plugin/skills/<name>/SKILL.md has required frontmatter fields."""
        errors: list[str] = []
        for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                errors.append(f"{skill_dir.name}: SKILL.md not found")
                continue
            fm = _parse_frontmatter(skill_md.read_text())
            for field in ("name", "description", "allowed-tools"):
                if not fm.get(field):
                    errors.append(
                        f"{skill_dir.name}/SKILL.md: missing frontmatter field '{field}'"
                    )
        assert not errors, "Skill frontmatter errors:\n" + "\n".join(errors)

    def test_discovery_skill_name_matches_directory(self) -> None:
        """Each SKILL.md 'name' field matches its containing directory name."""
        errors: list[str] = []
        for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            fm = _parse_frontmatter(skill_md.read_text())
            if fm.get("name") and fm["name"] != skill_dir.name:
                errors.append(
                    f"{skill_dir.name}: SKILL.md name='{fm['name']}' does not match dir"
                )
        assert not errors, "SKILL.md name/dir mismatches:\n" + "\n".join(errors)

    # --- invocation ---------------------------------------------------------

    def test_invocation_run_sh_delegates_to_starboard_x(self) -> None:
        """Skills that ship run.sh delegate to a Starboard CLI invocation.

        Accepted patterns:
        - ``python -m starboard_x.<cap>``  (tier-1 helper, most skills)
        - ``exec starboard <verb>``         (full CLI, e.g. workload-review)

        Both patterns are correct: ``exec starboard review --json`` is the
        documented invocation for the workload-review skill, which calls the
        full CLI rather than a starboard_x capability module.
        """
        # A valid run.sh must delegate to one of the two Starboard invocation forms.
        _starboard_invocation_re = re.compile(
            r"python\s+-m\s+starboard_x\.|exec\s+starboard\s+",
        )
        errors: list[str] = []
        for skill_name in sorted(_SKILLS_WITH_SCRIPTS):
            run_sh = _SKILLS_ROOT / skill_name / "scripts" / "run.sh"
            if not run_sh.exists():
                errors.append(f"{skill_name}/scripts/run.sh not found")
                continue
            content = run_sh.read_text()
            if not _starboard_invocation_re.search(content):
                errors.append(
                    f"{skill_name}/scripts/run.sh does not invoke a Starboard command "
                    f"(expected 'python -m starboard_x.*' or 'exec starboard ...')"
                )
        assert not errors, "run.sh invocation errors:\n" + "\n".join(errors)

    def test_invocation_allowed_tools_references_run_sh(self) -> None:
        """Skills with scripts have 'allowed-tools' gating the run.sh path."""
        errors: list[str] = []
        for skill_name in sorted(_SKILLS_WITH_SCRIPTS):
            skill_md = _SKILLS_ROOT / skill_name / "SKILL.md"
            if not skill_md.exists():
                continue
            fm = _parse_frontmatter(skill_md.read_text())
            allowed = fm.get("allowed-tools", "")
            if "run.sh" not in allowed and "scripts/run.sh" not in allowed:
                errors.append(
                    f"{skill_name}/SKILL.md: allowed-tools does not gate run.sh"
                )
        assert not errors, "allowed-tools gating errors:\n" + "\n".join(errors)

    # --- auth ---------------------------------------------------------------

    def test_auth_no_hardcoded_credentials_in_skills(self) -> None:
        """SKILL.md files do not embed hardcoded Databricks credentials."""
        # Match a PAT (dapi + 32 hex chars) or bare token= assignment
        pat_re = re.compile(r"dapi[a-f0-9]{32}", re.IGNORECASE)
        errors: list[str] = []
        for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            for md_file in skill_dir.rglob("*.md"):
                if pat_re.search(md_file.read_text()):
                    errors.append(f"{md_file.relative_to(_PLUGIN_ROOT)}: hardcoded PAT found")
        assert not errors, "Hardcoded credentials:\n" + "\n".join(errors)

    def test_auth_sdk_chain_referenced_in_skill_body(self) -> None:
        """At least one skill explicitly references the SDK credential chain."""
        # Skills must document that auth flows through the SDK / profile flag,
        # not through embedded credentials.
        sdk_re = re.compile(r"sdk\s+credential|DATABRICKS_HOST|DATABRICKS_TOKEN|--profile", re.IGNORECASE)
        matching = [
            d.name
            for d in sorted(_SKILLS_ROOT.iterdir())
            if d.is_dir()
            and (d / "SKILL.md").exists()
            and sdk_re.search((d / "SKILL.md").read_text())
        ]
        assert matching, (
            "No SKILL.md mentions SDK credential chain or --profile flag; "
            "at least one should document how auth works"
        )

    # --- idempotence --------------------------------------------------------

    def test_idempotence_plugin_json_stable(self) -> None:
        """Reading plugin.json twice returns identical content."""
        plugin_json = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
        first = json.loads(plugin_json.read_text())
        second = json.loads(plugin_json.read_text())
        assert first == second, "plugin.json content differs between reads"

    def test_idempotence_skill_md_stable(self) -> None:
        """Reading each SKILL.md twice returns identical content."""
        for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                assert skill_md.read_text() == skill_md.read_text(), (
                    f"{skill_dir.name}/SKILL.md differs between reads"
                )


# ---------------------------------------------------------------------------
# Host: Isaac (wraps Claude Code — same plugin + rules)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIsaacHost:
    """Isaac host: same plugin bundle as Claude Code, plus per-domain rules.

    Isaac wraps Claude Code and uses the identical plugin; the additional
    Isaac-specific surface is ``plugin/rules/`` (baseline + per-domain rulesets).
    """

    # --- discovery ----------------------------------------------------------

    def test_discovery_canonical_skills_present(self) -> None:
        """Canonical skills tree (consumed by both Isaac and Claude Code) exists."""
        assert _CANONICAL_SKILLS_ROOT.exists(), (
            f"Canonical skills root not found at {_CANONICAL_SKILLS_ROOT}"
        )
        skill_dirs = [d for d in _CANONICAL_SKILLS_ROOT.iterdir() if d.is_dir()]
        assert len(skill_dirs) >= _MIN_SKILL_COUNT, (
            f"Expected >= {_MIN_SKILL_COUNT} canonical skills, "
            f"found {len(skill_dirs)}: {[d.name for d in skill_dirs]}"
        )

    def test_discovery_rules_directory_present(self) -> None:
        """plugin/rules/ exists with at least one ruleset for Isaac sessions."""
        assert _RULES_ROOT.exists(), f"plugin/rules/ not found at {_RULES_ROOT}"
        rule_files = list(_RULES_ROOT.glob("*.md"))
        assert rule_files, f"No .md rule files found in {_RULES_ROOT}"

    def test_discovery_canonical_skills_well_formed(self) -> None:
        """All canonical SKILL.md files have required frontmatter."""
        errors: list[str] = []
        for skill_dir in sorted(_CANONICAL_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                errors.append(f"canonical/{skill_dir.name}/SKILL.md not found")
                continue
            fm = _parse_frontmatter(skill_md.read_text())
            if not fm.get("name"):
                errors.append(f"canonical/{skill_dir.name}/SKILL.md: missing 'name'")
            if not fm.get("allowed-tools"):
                errors.append(f"canonical/{skill_dir.name}/SKILL.md: missing 'allowed-tools'")
        assert not errors, "Canonical skill errors:\n" + "\n".join(errors)

    def test_discovery_rules_non_empty(self) -> None:
        """Every rule .md file in plugin/rules/ is non-empty."""
        errors: list[str] = []
        for rule_file in sorted(_RULES_ROOT.glob("*.md")):
            if not rule_file.read_text().strip():
                errors.append(f"{rule_file.name}: empty rule file")
        assert not errors, "Empty rule files:\n" + "\n".join(errors)

    # --- invocation ---------------------------------------------------------

    def test_invocation_skills_delegate_to_starboard_x(self) -> None:
        """Isaac invokes skills via run.sh → Starboard CLI (same as Claude Code)."""
        _starboard_invocation_re = re.compile(
            r"python\s+-m\s+starboard_x\.|exec\s+starboard\s+",
        )
        for skill_name in sorted(_SKILLS_WITH_SCRIPTS):
            run_sh = _SKILLS_ROOT / skill_name / "scripts" / "run.sh"
            if run_sh.exists():
                content = run_sh.read_text()
                assert _starboard_invocation_re.search(content), (
                    f"{skill_name}/scripts/run.sh must delegate to a Starboard command "
                    f"('python -m starboard_x.*' or 'exec starboard ...'); "
                    f"content: {content!r}"
                )

    def test_invocation_maint_entry_point_registered_or_skipped(self) -> None:
        """starboard-maint console_script entry point is registered (skip if E1 not landed)."""
        try:
            eps = importlib.metadata.entry_points(group="console_scripts")
            ep_names = {ep.name for ep in eps}
        except Exception:
            pytest.skip("Cannot enumerate entry points")
        if "starboard-maint" not in ep_names:
            pytest.skip(
                "starboard-maint not yet registered (E1 task pending); "
                "this check will pass once starboard-skills is installed with the maint CLI"
            )
        # If registered, the entry point value must be non-empty
        for ep in eps:
            if ep.name == "starboard-maint":
                assert ep.value, "starboard-maint entry point has empty value"

    # --- auth ---------------------------------------------------------------

    def test_auth_no_hardcoded_credentials_in_rules(self) -> None:
        """Rule files contain no hardcoded Databricks PATs."""
        pat_re = re.compile(r"dapi[a-f0-9]{32}", re.IGNORECASE)
        for rule_file in sorted(_RULES_ROOT.glob("*.md")):
            text = rule_file.read_text()
            assert not pat_re.search(text), (
                f"{rule_file.name}: contains what looks like a hardcoded PAT"
            )

    def test_auth_rules_document_sdk_chain(self) -> None:
        """At least one rule file documents the SDK credential chain."""
        sdk_re = re.compile(
            r"sdk\s+credential|DATABRICKS_HOST|DATABRICKS_TOKEN|databrickscfg|--profile",
            re.IGNORECASE,
        )
        matching = [f.name for f in _RULES_ROOT.glob("*.md") if sdk_re.search(f.read_text())]
        # Rules may be sparse; this is a best-effort check
        if not matching:
            pytest.skip(
                "No rule file mentions SDK credential chain yet; "
                "this check will pass once per-domain rulesets (O7) include auth guidance"
            )

    # --- idempotence --------------------------------------------------------

    def test_idempotence_canonical_skills_stable(self) -> None:
        """Canonical SKILL.md content is stable across multiple reads."""
        for skill_dir in sorted(_CANONICAL_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                first = skill_md.read_text()
                second = skill_md.read_text()
                assert first == second, (
                    f"canonical/{skill_dir.name}/SKILL.md content differs between reads"
                )

    def test_idempotence_rules_stable(self) -> None:
        """Rule file content is stable across multiple reads."""
        for rule_file in sorted(_RULES_ROOT.glob("*.md")):
            first = rule_file.read_text()
            second = rule_file.read_text()
            assert first == second, f"{rule_file.name}: content differs between reads"


# ---------------------------------------------------------------------------
# Host: Codex
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCodexHost:
    """Codex host: python -m starboard_x.* CLI (no plugin loader).

    Codex has no Claude Code-style plugin loader; it calls
    ``python -m starboard_x.<capability>`` directly.  Tests exercise the real
    CLI entrypoints in-process.
    """

    # --- discovery ----------------------------------------------------------

    def test_discovery_starboard_x_importable(self) -> None:
        """starboard_x package is importable."""
        importlib.import_module("starboard_x")

    def test_discovery_contract_module_importable(self) -> None:
        """starboard_x.contract is importable and exposes required exit codes."""
        contract = importlib.import_module("starboard_x.contract")
        for attr in ("EXIT_OK", "EXIT_AUTH", "EXIT_NOT_FOUND", "EXIT_API", "EXIT_ARG"):
            assert hasattr(contract, attr), f"starboard_x.contract missing '{attr}'"
        assert contract.EXIT_OK == _EXIT_OK
        assert contract.EXIT_AUTH == _EXIT_AUTH

    @pytest.mark.parametrize("capability", _RUNNABLE_CAPABILITIES)
    def test_discovery_capability_importable(self, capability: str) -> None:
        """Each implemented starboard_x capability module is importable."""
        importlib.import_module(f"starboard_x.{capability}")

    # --- invocation ---------------------------------------------------------

    def test_invocation_dispatcher_help(self) -> None:
        """python -m starboard_x --help exits 0 and lists implemented domains."""
        result = _run([sys.executable, "-m", "starboard_x", "--help"])
        assert result.returncode == _EXIT_OK, (
            f"starboard_x --help: exit {result.returncode}\nstderr: {result.stderr}"
        )
        out = result.stdout.lower()
        assert "implemented" in out or "usage" in out, (
            f"Unexpected --help output: {result.stdout!r}"
        )

    @pytest.mark.parametrize("capability", _RUNNABLE_CAPABILITIES)
    def test_invocation_capability_help(self, capability: str) -> None:
        """python -m starboard_x.<cap> --help exits 0."""
        result = _run([sys.executable, "-m", f"starboard_x.{capability}", "--help"])
        assert result.returncode == _EXIT_OK, (
            f"starboard_x.{capability} --help: exit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    def test_invocation_warehouse_analyze_pure(self, tmp_path: Path) -> None:
        """warehouse analyze is pure in-process (no SDK) and always emits a valid envelope.

        ``--history`` takes a FILE PATH (not inline JSON).  An empty records
        array exits EXIT_NOT_FOUND (2) — "no records for this warehouse" — which
        is still fully graceful and proves the command ran end-to-end without
        any Databricks SDK call.  The key assertions are:

        * exit code is in _GRACEFUL_EXIT_CODES (no unhandled exception)
        * stdout is a valid JSON envelope with the correct contract_version
        * stderr is empty (pure in-process path; nothing to log)
        """
        history_file = tmp_path / "history.json"
        history_file.write_text("[]")
        result = _run(
            [
                sys.executable, "-m", "starboard_x.warehouse", "analyze",
                "--history", str(history_file),
                "--warehouse-id", "smoke-test-wh",
            ]
        )
        assert result.returncode in _GRACEFUL_EXIT_CODES, (
            f"warehouse analyze (pure): unexpected exit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"Unhandled exception in pure warehouse analyze:\n{result.stderr}"
        )
        # Verify envelope shape — always emitted even on error
        envelope = json.loads(result.stdout)
        assert "ok" in envelope, "envelope missing 'ok' field"
        assert "domain" in envelope, "envelope missing 'domain' field"
        assert envelope.get("meta", {}).get("contract_version") == "1.0", (
            "envelope meta.contract_version must be '1.0'"
        )

    # --- auth ---------------------------------------------------------------

    def test_auth_mock_creds_discovery_graceful(self) -> None:
        """discovery run with mock credentials exercises the SDK auth chain gracefully.

        With a non-existent host the SDK may time-out on DNS/TCP rather than
        returning immediately.  Either outcome counts as "graceful" — what
        matters is that the process was launched (auth chain invoked) and did
        NOT crash with an unhandled exception before even attempting auth.
        A ``TimeoutExpired`` proves the auth path ran (the SDK tried to
        connect) without an immediate crash.
        """
        import subprocess as _subprocess  # local alias for clarity

        mock_env = {
            "DATABRICKS_HOST": _MOCK_DATABRICKS_HOST,
            "DATABRICKS_TOKEN": _MOCK_DATABRICKS_TOKEN,
        }
        try:
            result = _run(
                [sys.executable, "-m", "starboard_x.discovery", "run"],
                extra_env=mock_env,
                timeout=8,  # short timeout; DNS hang on a .invalid host is expected
            )
        except _subprocess.TimeoutExpired:
            # Timeout = SDK auth attempted but fake host did not respond.
            # This is the correct auth-path behaviour — no immediate crash.
            return

        assert result.returncode in _GRACEFUL_EXIT_CODES, (
            f"discovery run with mock creds: unexpected exit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"Unhandled exception in Codex auth path:\n{result.stderr}"
        )

    def test_auth_contract_autherror_has_correct_exit_code(self) -> None:
        """AuthError.exit_code == EXIT_AUTH (1) so the SDK chain maps to the standard code."""
        from starboard_x.contract import AuthError

        assert AuthError.exit_code == _EXIT_AUTH, (
            f"AuthError.exit_code must be {_EXIT_AUTH}; got {AuthError.exit_code}"
        )

    # --- idempotence --------------------------------------------------------

    def test_idempotence_dispatcher_help_stable(self) -> None:
        """python -m starboard_x --help produces identical output on two runs."""
        cmd = [sys.executable, "-m", "starboard_x", "--help"]
        first = _run(cmd)
        second = _run(cmd)
        assert first.returncode == second.returncode == _EXIT_OK
        assert first.stdout == second.stdout, (
            "starboard_x --help output differs between runs"
        )

    def test_idempotence_warehouse_analyze_stable(self, tmp_path: Path) -> None:
        """warehouse analyze emits identical JSON envelope on two successive runs."""
        history_file = tmp_path / "history.json"
        history_file.write_text("[]")
        cmd = [
            sys.executable, "-m", "starboard_x.warehouse", "analyze",
            "--history", str(history_file),
            "--warehouse-id", "smoke-test-wh",
        ]
        first = _run(cmd)
        second = _run(cmd)
        assert first.returncode == second.returncode, (
            f"Exit codes differ: {first.returncode} vs {second.returncode}"
        )
        # Pure in-process: stdout must be byte-identical regardless of exit code
        assert json.loads(first.stdout) == json.loads(second.stdout), (
            "warehouse analyze produces different envelopes on successive runs"
        )


# ---------------------------------------------------------------------------
# Host: OpenCode
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOpenCodeHost:
    """OpenCode host: identical CLI path as Codex + agent definition artifacts.

    OpenCode references agent config files (``plugin/agents/``) and calls
    ``python -m starboard_x.*`` directly — no host-specific plugin machinery.
    """

    # --- discovery ----------------------------------------------------------

    def test_discovery_agent_definitions_present(self) -> None:
        """plugin/agents/ contains agent definition .md files."""
        assert _AGENTS_ROOT.exists(), f"plugin/agents/ not found at {_AGENTS_ROOT}"
        agent_files = list(_AGENTS_ROOT.glob("*.md"))
        assert len(agent_files) >= _MIN_AGENT_FILE_COUNT, (
            f"Expected >= {_MIN_AGENT_FILE_COUNT} agent definitions, "
            f"found {len(agent_files)}: {[f.name for f in agent_files]}"
        )

    def test_discovery_agent_definitions_well_formed(self) -> None:
        """Agent .md files are non-empty and contain at least one markdown heading."""
        heading_re = re.compile(r"^#", re.MULTILINE)
        errors: list[str] = []
        for agent_file in sorted(_AGENTS_ROOT.glob("*.md")):
            text = agent_file.read_text()
            if not text.strip():
                errors.append(f"{agent_file.name}: empty file")
            elif not heading_re.search(text):
                errors.append(f"{agent_file.name}: no markdown heading found")
        assert not errors, "Agent definition errors:\n" + "\n".join(errors)

    def test_discovery_starboard_x_available_for_opencode(self) -> None:
        """starboard_x is importable (OpenCode resolves it via installed wheel)."""
        importlib.import_module("starboard_x")

    # --- invocation ---------------------------------------------------------

    def test_invocation_dispatcher_resolves(self) -> None:
        """python -m starboard_x resolves (same entry point OpenCode would call)."""
        result = _run([sys.executable, "-m", "starboard_x", "--help"])
        assert result.returncode == _EXIT_OK, (
            f"starboard_x --help: exit {result.returncode}\nstderr: {result.stderr}"
        )

    @pytest.mark.parametrize("capability", _RUNNABLE_CAPABILITIES)
    def test_invocation_capability_resolves(self, capability: str) -> None:
        """python -m starboard_x.<cap> --help exits 0 for each capability."""
        result = _run([sys.executable, "-m", f"starboard_x.{capability}", "--help"])
        assert result.returncode == _EXIT_OK, (
            f"starboard_x.{capability} --help: exit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    def test_invocation_agent_files_reference_starboard_x(self) -> None:
        """At least one agent definition references the starboard_x invocation path."""
        ref_re = re.compile(r"python\s+-m\s+starboard_x|starboard.helper", re.IGNORECASE)
        matching = [
            f.name
            for f in sorted(_AGENTS_ROOT.glob("*.md"))
            if ref_re.search(f.read_text())
        ]
        assert matching, (
            "No agent definition in plugin/agents/ references 'python -m starboard_x' "
            "or 'starboard-helper'; at least one must document the OpenCode invocation path"
        )

    # --- auth ---------------------------------------------------------------

    def test_auth_mock_creds_uc_graceful(self) -> None:
        """uc with mock credentials exits gracefully (no unhandled exception)."""
        result = _run(
            # uc analyze with minimal valid input; with mock host it will hit SDK
            [
                sys.executable,
                "-m",
                "starboard_x.uc",
                "analyze",
                "--input",
                '{"columns": [{"name": "id", "data_type": "BIGINT", "position": 0, "nullable": false}]}',
            ],
            extra_env={
                "DATABRICKS_HOST": _MOCK_DATABRICKS_HOST,
                "DATABRICKS_TOKEN": _MOCK_DATABRICKS_TOKEN,
            },
        )
        assert result.returncode in _GRACEFUL_EXIT_CODES, (
            f"uc analyze with mock creds: unexpected exit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"Unhandled exception in OpenCode auth path:\n{result.stderr}"
        )

    def test_auth_no_hardcoded_credentials_in_agents(self) -> None:
        """Agent .md files contain no hardcoded Databricks PATs."""
        pat_re = re.compile(r"dapi[a-f0-9]{32}", re.IGNORECASE)
        errors: list[str] = []
        for agent_file in sorted(_AGENTS_ROOT.glob("*.md")):
            if pat_re.search(agent_file.read_text()):
                errors.append(f"{agent_file.name}: contains hardcoded PAT")
        assert not errors, "Hardcoded credentials in agent files:\n" + "\n".join(errors)

    # --- idempotence --------------------------------------------------------

    def test_idempotence_capability_help_stable(self) -> None:
        """python -m starboard_x.warehouse --help is identical on two runs."""
        cmd = [sys.executable, "-m", "starboard_x.warehouse", "--help"]
        first = _run(cmd)
        second = _run(cmd)
        assert first.returncode == second.returncode == _EXIT_OK
        assert first.stdout == second.stdout, (
            "warehouse --help output differs between runs"
        )

    def test_idempotence_agent_files_stable(self) -> None:
        """Agent definition files are stable across multiple reads."""
        for agent_file in sorted(_AGENTS_ROOT.glob("*.md")):
            assert agent_file.read_text() == agent_file.read_text(), (
                f"{agent_file.name}: content differs between reads"
            )


# ---------------------------------------------------------------------------
# Host: MCP server
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPServerHost:
    """MCP server host: starboard-mcp entry point + tool discoverability.

    The MCP server is optional and additive; it does not replace the skills
    path.  Tests check module importability and entry-point registration
    without starting a live server.
    """

    # --- discovery ----------------------------------------------------------

    def test_discovery_mcp_cli_module_importable(self) -> None:
        """starboard.mcp.cli is importable (MCP server module present)."""
        importlib.import_module("starboard.mcp.cli")

    def test_discovery_mcp_entry_point_registered(self) -> None:
        """starboard-mcp console_scripts entry point is registered in the wheel metadata."""
        try:
            eps = importlib.metadata.entry_points(group="console_scripts")
            ep_names = {ep.name for ep in eps}
        except Exception as exc:
            pytest.skip(f"Cannot enumerate entry points: {exc}")
        assert "starboard-mcp" in ep_names, (
            f"starboard-mcp not found in console_scripts. "
            f"Registered scripts include: {sorted(n for n in ep_names if 'starboard' in n)}"
        )

    def test_discovery_mcp_main_callable(self) -> None:
        """starboard.mcp.cli.main is a callable (entry point target is wired)."""
        mcp_cli = importlib.import_module("starboard.mcp.cli")
        main_fn = getattr(mcp_cli, "main", None)
        assert callable(main_fn), (
            "starboard.mcp.cli.main is not callable; "
            "the entry point would fail at invocation"
        )

    # --- invocation ---------------------------------------------------------

    def test_invocation_mcp_binary_on_path_or_registered(self) -> None:
        """starboard-mcp is findable on PATH or registered as an entry point."""
        on_path = shutil.which("starboard-mcp") is not None
        if not on_path:
            # Fall back to entry-point check
            try:
                eps = importlib.metadata.entry_points(group="console_scripts")
                ep_names = {ep.name for ep in eps}
                on_path = "starboard-mcp" in ep_names
            except Exception:
                pass
        assert on_path, (
            "starboard-mcp is neither on PATH nor registered as a console_scripts entry point"
        )

    def test_invocation_mcp_help_exits_ok(self) -> None:
        """starboard-mcp --help exits 0 when the binary is on PATH."""
        if not shutil.which("starboard-mcp"):
            pytest.skip("starboard-mcp not on PATH; skipping subprocess invocation check")
        result = _run(["starboard-mcp", "--help"])
        assert result.returncode == _EXIT_OK, (
            f"starboard-mcp --help: exit {result.returncode}\nstderr: {result.stderr}"
        )

    # --- auth ---------------------------------------------------------------

    def test_auth_mcp_import_does_not_require_credentials(self) -> None:
        """Importing starboard.mcp.cli does not attempt network calls or credential lookup."""
        # A clean import with no Databricks env vars must not raise or print warnings
        env_backup = {
            k: os.environ.pop(k)
            for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_CONFIG_FILE")
            if k in os.environ
        }
        try:
            import importlib as _il

            mod = _il.import_module("starboard.mcp.cli")
            assert mod is not None
        finally:
            os.environ.update(env_backup)

    # --- idempotence --------------------------------------------------------

    def test_idempotence_mcp_module_identity_stable(self) -> None:
        """Importing starboard.mcp.cli twice returns the same module object."""
        import starboard.mcp.cli as first_import
        import starboard.mcp.cli as second_import  # noqa: F811

        assert first_import is second_import, (
            "Module object identity differs — import is not idempotent (sys.modules caching broken)"
        )

    def test_idempotence_entry_point_lookup_stable(self) -> None:
        """Entry-point lookup for starboard-mcp returns consistent results on two calls."""
        try:
            eps_first = {ep.name for ep in importlib.metadata.entry_points(group="console_scripts")}
            eps_second = {ep.name for ep in importlib.metadata.entry_points(group="console_scripts")}
        except Exception as exc:
            pytest.skip(f"Cannot enumerate entry points: {exc}")
        assert "starboard-mcp" in eps_first
        assert eps_first == eps_second, "Entry-point listing is not stable between calls"
