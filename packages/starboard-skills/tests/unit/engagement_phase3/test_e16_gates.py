"""E16: architecture gates — import-linter, no ``httpx`` in the kernel, governance grep."""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
BIN = REPO / ".venv" / "bin"
CORE = REPO / "packages" / "starboard-core"
NO_HTTPX = (CORE / "starboard_core" / "engagement", CORE / "starboard_x" / "diagnostic")

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


def _contracts() -> dict[str, list[str]]:
    with (REPO / "pyproject.toml").open("rb") as fh:
        cfg = tomllib.load(fh)["tool"]["importlinter"]
    return {c["name"]: list(c.get("source_modules", ())) for c in cfg["contracts"]}


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


def test_contracts_cover_the_phase3_modules() -> None:
    contracts = _contracts()
    assert len(contracts) == 5
    kernel = next(v for k, v in contracts.items() if k.startswith("Kernel is free"))
    pure = next(
        v for k, v in contracts.items() if k.startswith("starboard_x pure analyzers")
    )
    assert "starboard_core.engagement" in kernel
    assert "starboard_x.diff" in pure


def _httpx_imports(root: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"), str(path))):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(n == "httpx" or n.startswith("httpx.") for n in names):
                hits.append(f"{path.relative_to(REPO)}:{node.lineno}")
    return hits


def test_no_httpx_under_engagement_or_diagnostic() -> None:
    for root in NO_HTTPX:
        assert root.is_dir(), root
    assert [h for root in NO_HTTPX for h in _httpx_imports(root)] == []


def test_governance_grep_is_clean() -> None:
    from ..engagement_phase2 import test_exit_11_contracts as phase2

    # Same roots and allowlist as phase 2 (now covering the phase-3 modules and skills) ...
    assert phase2._hits() == []
    # ... plus the phase-3 test tree itself, which phase 2 allowlists wholesale.
    hits = [
        f"{p.relative_to(REPO)}:{n}"
        for p in sorted(HERE.rglob("*.py"))
        for n, line in enumerate(p.read_text("utf-8").splitlines(), 1)
        if NAMESPACES.search(line)
    ]
    assert hits == []
