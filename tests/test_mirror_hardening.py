"""Verify that scripts/mirror-public.sh --dry-run produces a correctly filtered tree.

These tests run the mirror script in --dry-run mode and assert that:
  - The script exits 0.
  - Internal paths (packages/starboard-internal, plugin-internal) are absent
    from the filtered commit tree.
  - The "starboard-internal" marketplace.json entry is absent from the filtered
    tree.
  - The public plugin directory is still present.

Tests are skipped automatically when the working tree has uncommitted changes
(the mirror script pre-flight rejects a dirty tree).

These tests are NOT part of ``make test-unit`` or ``make test-architecture``
(those targets run specific package subdirectories).  Run them directly:

    pytest tests/test_mirror_hardening.py -v
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
MIRROR_SCRIPT = REPO_ROOT / "scripts" / "mirror-public.sh"

# Paths that must be absent from the public mirror tree.
INTERNAL_PATHS = ["packages/starboard-internal", "plugin-internal"]

# Marketplace plugin names that must be stripped.
INTERNAL_PLUGIN_NAMES = ["starboard-internal"]


def _working_tree_is_clean() -> bool:
    """Return True when git reports no staged or unstaged changes."""
    for extra in ([], ["--cached"]):
        result = subprocess.run(
            ["git", "diff", "--quiet", *extra],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            return False
    return True


def _run_dry_run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(MIRROR_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def dry_run_result() -> subprocess.CompletedProcess[str]:
    """Run --dry-run once and share the result across tests in this module.

    Skips the entire module when the working tree is dirty: the mirror script's
    pre-flight rejects uncommitted changes, and running it would just produce a
    predictable failure rather than a useful test result.
    """
    if not _working_tree_is_clean():
        pytest.skip(
            "Working tree is dirty — mirror-hardening tests require a clean tree"
        )
    return _run_dry_run()


class TestMirrorHardening:
    """Integration tests for the filtered-mirror mechanism."""

    def test_dry_run_exits_zero(
        self, dry_run_result: subprocess.CompletedProcess[str]
    ) -> None:
        """--dry-run must exit 0 when the filtered tree passes all checks."""
        assert dry_run_result.returncode == 0, (
            f"mirror-public.sh --dry-run failed (rc={dry_run_result.returncode}):\n"
            f"stdout:\n{dry_run_result.stdout}\n"
            f"stderr:\n{dry_run_result.stderr}"
        )

    @pytest.mark.parametrize("path", INTERNAL_PATHS)
    def test_internal_path_is_absent(
        self,
        path: str,
        dry_run_result: subprocess.CompletedProcess[str],
    ) -> None:
        """Each internal path must be reported absent from the filtered tree."""
        combined = dry_run_result.stdout + dry_run_result.stderr
        expected = f"OK: '{path}' is absent from filtered tree"
        assert expected in combined, (
            f"Expected '{path}' to be absent from filtered tree.\n"
            f"Full output:\n{combined}"
        )

    @pytest.mark.parametrize("name", INTERNAL_PLUGIN_NAMES)
    def test_internal_marketplace_entry_is_absent(
        self,
        name: str,
        dry_run_result: subprocess.CompletedProcess[str],
    ) -> None:
        """Internal plugin names must be stripped from the filtered marketplace.json."""
        combined = dry_run_result.stdout + dry_run_result.stderr
        expected = f"OK: '{name}' absent from filtered marketplace.json"
        assert expected in combined, (
            f"Expected marketplace entry '{name}' to be absent.\n"
            f"Full output:\n{combined}"
        )

    def test_public_plugin_dir_is_present(
        self, dry_run_result: subprocess.CompletedProcess[str]
    ) -> None:
        """The public plugin/ directory must survive the filter."""
        combined = dry_run_result.stdout + dry_run_result.stderr
        assert "OK: public path 'plugin' present in filtered tree" in combined, (
            f"Expected public 'plugin' dir to remain in filtered tree.\n"
            f"Full output:\n{combined}"
        )

    def test_public_marketplace_json_is_present(
        self, dry_run_result: subprocess.CompletedProcess[str]
    ) -> None:
        """The rewritten marketplace.json must survive the filter.

        Regression guard for the SIGPIPE-under-``pipefail`` bug: piping
        ``git ls-tree`` into ``grep -q`` made this present path read as absent
        (grep short-circuits, git dies with SIGPIPE, pipefail propagates 141),
        so the survival spot-check false-warned even though the file was there.
        """
        combined = dry_run_result.stdout + dry_run_result.stderr
        expected = (
            "OK: public path '.claude-plugin/marketplace.json' present in filtered tree"
        )
        assert expected in combined, (
            "Expected public '.claude-plugin/marketplace.json' to remain in "
            f"filtered tree.\nFull output:\n{combined}"
        )

    def test_no_public_survival_warning(
        self, dry_run_result: subprocess.CompletedProcess[str]
    ) -> None:
        """No public path may be reported missing from the filtered tree.

        A "Public path '...' not found" warning means the survival check is
        misreporting a present path (the SIGPIPE race), which silently weakens
        every survival guarantee — treat it as a hard failure.
        """
        combined = dry_run_result.stdout + dry_run_result.stderr
        assert "Warning: Public path" not in combined, (
            "A public survival check warned that a present path was missing.\n"
            f"Full output:\n{combined}"
        )

    def test_verification_passes(
        self, dry_run_result: subprocess.CompletedProcess[str]
    ) -> None:
        """The script's own verification step must report 'Verification passed'."""
        combined = dry_run_result.stdout + dry_run_result.stderr
        assert "Verification passed." in combined, (
            f"Expected 'Verification passed.' in output.\nFull output:\n{combined}"
        )

    def test_filtered_commit_is_orphan(
        self,
        dry_run_result: subprocess.CompletedProcess[str],
    ) -> None:
        """The filtered commit must be an orphan — zero parents.

        ``git rev-list --parents -n1 <sha>`` returns ``<sha>`` with no
        trailing tokens when the commit has no parents.  Two or more tokens
        means one or more parents are present, which leaks internal history.
        """
        combined = dry_run_result.stdout + dry_run_result.stderr
        sha: str | None = None
        for line in combined.splitlines():
            if "Filtered commit SHA:" in line:
                sha = line.split("Filtered commit SHA:")[-1].strip()
                break
        assert sha is not None, (
            "Could not find 'Filtered commit SHA:' in dry-run output.\n"
            f"Full output:\n{combined}"
        )
        result = subprocess.run(
            ["git", "rev-list", "--parents", "-n1", sha],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"git rev-list failed for {sha}: {result.stderr}"
        )
        tokens = result.stdout.strip().split()
        assert len(tokens) == 1, (
            f"Filtered commit {sha} has {len(tokens) - 1} parent(s); "
            f"expected 0 (orphan). git rev-list output: {result.stdout.strip()}"
        )
        assert tokens[0] == sha, (
            f"rev-list returned unexpected SHA: {tokens[0]} (expected {sha})"
        )
