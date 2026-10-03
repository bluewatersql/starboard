# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Guard test: every skill/bundle pip install of a Starboard package must
reference the canonical **internal** source repo
(git+https://github.com/bluewatersql/starboard).

Internal is the source of truth: in-repo trees (canonical skills, vendored
plugin, distribution bundles) reference the internal repo so internal/EMU
testers install the real HEAD. ``scripts/mirror-public.sh`` rewrites this URL to
the ``bluewatersql/starboard`` public mirror when it builds the public snapshot,
so external users of the mirror still get a working install.

Bare ``pip install "starboard-kernel[uc]"`` (etc.) do not work from a git
source — pip cannot resolve the bare package name without a registry. All
install references must carry the canonical git+https@ form.

Scanned locations:

* ``packages/starboard-skills/skills/starboard/`` — canonical skills tree
* ``plugin/skills/``                              — vendored plugin skills
* ``packages/starboard-distribution/aitools/``   — aitools distribution bundle
* ``packages/starboard-distribution/opencode/``  — opencode distribution bundle

This test goes **RED** while bare refs exist, then **GREEN** after every bare
ref has been rewritten to the canonical git+https form and the mirrors are
re-vendored.  To fix and re-vendor:

    python scripts/vendor_plugin_skills.py   # re-vendor plugin/skills
    python scripts/skills.py                 # re-vendor aitools bundle
    python scripts/port_to_opencode.py       # re-vendor opencode bundle
    make vendor-skills-check                 # verify all mirrors in-sync
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "packages" / "starboard-skills" / "skills").is_dir():
            return parent
    raise AssertionError(
        "could not locate repo root containing packages/starboard-skills/skills"
    )


REPO_ROOT = _repo_root()

# All four public-facing locations that must not ship bare install refs
_SCAN_ROOTS: dict[str, Path] = {
    "canonical-skills": REPO_ROOT / "packages" / "starboard-skills" / "skills" / "starboard",
    "plugin-skills":    REPO_ROOT / "plugin" / "skills",
    "aitools-bundle":   REPO_ROOT / "packages" / "starboard-distribution" / "aitools",
    "opencode-bundle":  REPO_ROOT / "packages" / "starboard-distribution" / "opencode",
}

# Matches a pip install line that references any public Starboard package name.
# Covers quoted/unquoted forms and optional extras, e.g.:
#   pip install "starboard-kernel[uc]"
#   pip install starboard-skills
#   pip install 'starboard[redis]'
#   pip install starboard
_STARBOARD_INSTALL_RE = re.compile(
    r'pip\s+install\s+["\']?'
    r'(starboard(?:-kernel|-skills|-core|-x)?'
    r'(?:\[[^\]]+\])?)'
    r'\b'
)

# The canonical internal source that must be present in every matched line.
# The public mirror URL is substituted by scripts/mirror-public.sh on export.
_MIRROR_MARKER = "git+https://github.com/bluewatersql/starboard"


# ---------------------------------------------------------------------------
# Collect violations at module-load time (parametrize over findings)
# ---------------------------------------------------------------------------

class _Violation(NamedTuple):
    location: str   # "path/to/file.md:N"
    line: str       # offending line, stripped


def _collect_violations() -> list[_Violation]:
    violations: list[_Violation] = []
    for _label, root in _SCAN_ROOTS.items():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            for lineno, raw_line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if (
                    _STARBOARD_INSTALL_RE.search(raw_line)
                    and _MIRROR_MARKER not in raw_line
                ):
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(_Violation(f"{rel}:{lineno}", raw_line.strip()))
    return violations


_VIOLATIONS = _collect_violations()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_scan_roots_present() -> None:
    """Canonical-skills root must exist to prevent a silently-empty scan."""
    canonical = _SCAN_ROOTS["canonical-skills"]
    assert canonical.is_dir(), (
        f"canonical skills root not found at {canonical}; "
        "is the test running from the repo root?"
    )


@pytest.mark.parametrize(
    "location,line",
    [(v.location, v.line) for v in _VIOLATIONS],
    ids=[v.location for v in _VIOLATIONS],
)
def test_public_pip_install_references_mirror(location: str, line: str) -> None:
    """Each public pip install of a Starboard package must include the mirror URL.

    A bare ``pip install "starboard-kernel[uc]"`` cannot be resolved from a git
    source.  Use the canonical git+https@ form instead, e.g.:

        pip install "starboard-kernel[uc] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core"

    After fixing the canonical skill(s), re-vendor all mirrors:

        python scripts/vendor_plugin_skills.py && \\
        python scripts/skills.py && \\
        python scripts/port_to_opencode.py
    """
    raise AssertionError(
        f"Bare public-package pip install at {location}:\n"
        f"  {line!r}\n\n"
        "Rewrite to the canonical git+https form (see test docstring)."
    )
