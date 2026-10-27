"""P2-G14 exit test 11 - contracts.

Spec item 11: "``lint-imports`` 5 contracts KEPT. ``tests/architecture`` pass. The
no-internal-namespace scan of public code/docs is clean."

* ``lint-imports`` and both architecture suites (the repo-root GUIDELINE suite and
  ``packages/starboard/tests/architecture``, the red-line suite) run in a
  subprocess with a scrubbed environment: no Databricks credentials, and HTTP(S)
  proxies pointed at a closed local port so any accidental HTTP call fails fast.
* The namespace scan is the spec grep, done in Python over the same roots. Test
  files (which hold the red-line guard lists) and the governance rule that names
  the list are allowlisted; everything else must be clean.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
BIN = Path(sys.executable).parent

SCAN_ROOTS = ("packages/starboard", "packages/starboard-core", "packages/starboard-skills",
              "plugin", "docs")
NAMESPACES = re.compile(r"centralized_system_tables|fin_live_gold|logfood|dbr-doctor|"
                        r"logs-summariser|gtm_|eng_|ClickHouse|hmr_stack_hash")
SKIP_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                       "node_modules", "htmlcov", "site"})

# (relpath, reason). Matched files are skipped entirely.
ALLOWLIST: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|/)tests/"), "red-line guard lists in tests"),
    (re.compile(r"^plugin/rules/README\.md$"),
     "the governance invariant that names the forbidden namespaces"),
)


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("DATABRICKS_", "STARBOARD_", "GOOGLE_", "OPENAI_"))}
    closed = "http://127.0.0.1:9"
    env.update(PYTHONDONTWRITEBYTECODE="1", HTTP_PROXY=closed, HTTPS_PROXY=closed,
               http_proxy=closed, https_proxy=closed, NO_PROXY="", no_proxy="")
    env["PATH"] = f"{BIN}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), cwd=REPO, env=_env(), capture_output=True,
                          text=True, timeout=600, check=False)


def _pytest(target: str) -> subprocess.CompletedProcess[str]:
    return _run(sys.executable, "-m", "pytest", target, "-q", "--no-cov",
                "-p", "no:cacheprovider")


def _hits() -> list[str]:
    found: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if not path.is_file() or SKIP_DIRS.intersection(path.parts):
                continue
            rel = path.relative_to(REPO).as_posix()
            if any(pat.search(rel) for pat, _ in ALLOWLIST):
                continue
            try:
                text = path.read_text("utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary assets
            for lineno, line in enumerate(text.splitlines(), 1):
                if NAMESPACES.search(line):
                    found.append(f"{rel}:{lineno}: {line.strip()[:160]}")
    return found


@pytest.mark.unit
class TestContracts:
    """Spec P2-G14 item 11."""

    def test_import_linter_keeps_all_five_contracts(self) -> None:
        proc = _run(str(BIN / "lint-imports"), "--no-cache")
        out = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout + proc.stderr)
        assert proc.returncode == 0, out
        assert "Contracts: 5 kept, 0 broken." in out, out
        assert out.count("KEPT") == 5

    @pytest.mark.parametrize("target", ["tests/architecture",
                                        "packages/starboard/tests/architecture"])
    def test_architecture_suite_passes(self, target) -> None:
        proc = _pytest(target)
        assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
        assert " passed" in proc.stdout and " failed" not in proc.stdout

    def test_allowlist_still_matches_real_hits(self) -> None:
        # The allowlisted governance rule really does carry the list (not stale).
        rule = (REPO / "plugin/rules/README.md").read_text("utf-8")
        assert NAMESPACES.search(rule)

    def test_no_internal_namespace_in_public_code_or_docs(self) -> None:
        assert _hits() == []
