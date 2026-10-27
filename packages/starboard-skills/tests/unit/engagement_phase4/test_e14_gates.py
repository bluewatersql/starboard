"""E14 Gates (spec §H.14).

* ``lint-imports`` keeps all five contracts.
* AST scan: no ``httpx`` under ``starboard_core/engagement`` or
  ``starboard_x/diagnostic``; no ``starboard_internal`` import in a public
  package.
* The governance grep over the new skill text and the phase-4 test tree is
  clean (red-line names built by concatenation).
* Only the synthetic AR keys ``AR-000000001`` .. ``AR-000000003`` appear.
* No email-shaped string in any record an E1-E7 test wrote (collected by the
  ``_email_collector`` fixture in this directory's ``conftest.py``).

Copied from the phase-3 gate pattern; nothing here imports from
``engagement_phase3``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from ._support import EMAIL_SCAN

HERE = Path(__file__).resolve().parent
PKG = HERE.parents[2]
REPO = PKG.parents[1]
BIN = REPO / ".venv" / "bin"
CORE = REPO / "packages" / "starboard-core"
NO_HTTPX = (CORE / "starboard_core" / "engagement", CORE / "starboard_x" / "diagnostic")
PUBLIC_PACKAGES = tuple(
    REPO / "packages" / name
    for name in (
        "starboard-core",
        "starboard",
        "starboard-skills",
        "starboard-capability",
        "starboard-core-alias",
        "starboard-plugin-sample",
    )
)
NEW_SKILLS = ("starboard-health-review", "starboard-troubleshoot")
SKILL_ROOTS = (
    PKG / "skills" / "starboard",
    REPO / "plugin" / "skills",
    REPO / "packages" / "starboard-distribution" / "aitools",
    REPO / "packages" / "starboard-distribution" / "opencode" / "skills",
)
SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
INTERNAL = "starboard" + "_internal"

#: Built by concatenation so this file never carries a red-line name literally.
_NAMES = (
    "centralized_" + "system_tables",
    "fin_live" + "_gold",
    "log" + "food",
    "dbr" + "-doctor",
    "logs" + "-summariser",
    "gtm" + "_",
    "eng" + "_",
    "Click" + "House",
    "hmr_stack" + "_hash",
)
NAMESPACES = re.compile("|".join(re.escape(n) for n in _NAMES))
AR_KEY = re.compile("AR" + r"-\d+")
AR_ALLOWED = frozenset("AR" + "-00000000" + d for d in "123")


def _imports(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text("utf-8"), str(path))):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            out.append((node.lineno, node.module or ""))
    return out


def _sources(root: Path, *, skip_tests: bool = False) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*.py"))
        if not SKIP_DIRS.intersection(p.parts)
        and not (skip_tests and "tests" in p.relative_to(root).parts)
    ]


def _imported(roots: tuple[Path, ...], top: str, *, skip_tests: bool) -> list[str]:
    return [
        f"{path.relative_to(REPO)}:{line}"
        for root in roots
        for path in _sources(root, skip_tests=skip_tests)
        for line, name in _imports(path)
        if name == top or name.startswith(top + ".")
    ]


def _text_files(root: Path) -> list[Path]:
    return [
        p
        for p in sorted(root.rglob("*"))
        if p.is_file() and not SKIP_DIRS.intersection(p.parts)
    ]


def _grep(paths: list[Path], pattern: re.Pattern[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        try:
            text = path.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:160]}")
    return hits


# --------------------------------------------------------------------------- #
# Import gates
# --------------------------------------------------------------------------- #
def test_lint_imports_keeps_five_contracts() -> None:
    proc = subprocess.run(
        [str(BIN / "lint-imports"), "--no-cache"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    out = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout + proc.stderr)
    assert proc.returncode == 0, out
    assert "Contracts: 5 kept, 0 broken." in out


def test_no_httpx_under_engagement_or_diagnostic() -> None:
    for root in NO_HTTPX:
        assert root.is_dir(), root
    assert _imported(NO_HTTPX, "httpx", skip_tests=False) == []


def test_no_public_package_imports_the_internal_package() -> None:
    for root in PUBLIC_PACKAGES:
        assert root.is_dir(), root
    assert _imported(PUBLIC_PACKAGES, INTERNAL, skip_tests=True) == []


# --------------------------------------------------------------------------- #
# Governance grep
# --------------------------------------------------------------------------- #
def test_the_repo_governance_grep_is_clean() -> None:
    from ..engagement_phase2 import test_exit_11_contracts as phase2

    assert phase2._hits() == []


@pytest.mark.parametrize("skill", NEW_SKILLS)
def test_the_new_skill_text_is_governance_clean(skill: str) -> None:
    roots = [root / skill for root in SKILL_ROOTS]
    assert (roots[0] / "SKILL.md").is_file(), f"{skill}/SKILL.md does not exist"
    paths = [p for root in roots if root.is_dir() for p in _text_files(root)]
    assert _grep(paths, NAMESPACES) == []


def test_the_phase4_test_tree_is_governance_clean() -> None:
    assert _grep(_text_files(HERE), NAMESPACES) == []


def test_only_the_synthetic_ar_keys_appear() -> None:
    keys = {
        f"{p.relative_to(REPO)}: {m}"
        for p in _text_files(HERE)
        if p.suffix == ".py"
        for m in AR_KEY.findall(p.read_text("utf-8"))
        if m not in AR_ALLOWED
    }
    assert sorted(keys) == []


# --------------------------------------------------------------------------- #
# Written records
# --------------------------------------------------------------------------- #
def test_no_email_in_any_record_e1_to_e7_wrote() -> None:
    if not EMAIL_SCAN:
        pytest.skip("no E1-E7 test ran in this session (run the whole phase-4 suite)")
    hits = {node: found for node, found in sorted(EMAIL_SCAN.items()) if found}
    assert hits == {}
