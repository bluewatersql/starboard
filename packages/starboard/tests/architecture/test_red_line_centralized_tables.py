# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Red-line guard: the internal-only mirror catalog literal must never ship publicly.

``centralized_system_tables`` is the internal logfood mirror catalog that backs
``starboard_internal.mirror_source.MirrorSource``. It is gated to
``packages/starboard-internal/`` only — import-linter contract 4 already keeps
public packages from *importing* ``starboard_internal``, but nothing previously
stopped the literal table name itself from leaking into public source, docs, or
config. This test greps every text file under ``packages/`` (excluding
``packages/starboard-internal/``) and asserts the literal appears nowhere.

Scope note: directories literally named ``tests`` are excluded from the walk.
Several existing pack-governance tests (e.g.
``packages/starboard/tests/unit/discovery/test_serverless_attribution_pack.py``)
already embed this term as an entry in a ``_FORBIDDEN_NAMESPACES`` tuple used to
assert the term is absent from *rendered SQL* — the same defensive, non-shipping
usage this guard itself uses below. Test suites are also not part of the
distributed wheel (see ``packages/starboard/pyproject.toml`` -> ``packages =
["starboard"]``), so they are outside the "public path" this guard protects.

This guard file follows its own rule: it never spells the literal out — it is
built at runtime via string concatenation so this file does not trip itself.
"""

from __future__ import annotations

from pathlib import Path

# Built at runtime so this guard file cannot trip its own check.
_FORBIDDEN = "centralized_" + "system_tables"

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PACKAGES_DIR = _REPO_ROOT / "packages"

_SKIP_DIR_NAMES = {".venv", "__pycache__", "htmlcov", ".git", "tests"}
_SKIP_TOP_LEVEL_PACKAGES = {"starboard-internal"}
_TEXT_SUFFIXES = {".py", ".toml", ".md", ".cfg", ".txt"}


def _iter_candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(_PACKAGES_DIR.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        rel_parts = path.relative_to(_PACKAGES_DIR).parts
        if rel_parts and rel_parts[0] in _SKIP_TOP_LEVEL_PACKAGES:
            continue
        if _SKIP_DIR_NAMES.intersection(rel_parts[:-1]):
            continue
        files.append(path)
    return files


def test_repo_root_and_packages_dir_resolved_correctly() -> None:
    """Sanity-check the __file__-relative path math before trusting the walk."""
    assert (_REPO_ROOT / "pyproject.toml").is_file()
    assert (_PACKAGES_DIR / "starboard-internal").is_dir()
    assert (_PACKAGES_DIR / "starboard").is_dir()


def test_no_public_file_contains_the_internal_mirror_catalog_literal() -> None:
    hits: list[str] = []
    for path in _iter_candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _FORBIDDEN in text:
            hits.append(str(path.relative_to(_REPO_ROOT)))

    assert not hits, (
        f"Found the internal-only mirror catalog literal '{_FORBIDDEN}' in "
        f"public file(s): {hits}. This name is gated to "
        "packages/starboard-internal/ only (import-linter contract 4) — move "
        "the reference there or remove it."
    )


def test_legitimate_internal_hits_are_not_flagged() -> None:
    """Prove the skip-list is real: starboard-internal genuinely contains the
    literal (it's the only place allowed to), so an empty result above isn't
    an artifact of an overly-broad skip rule.
    """
    internal_dir = _PACKAGES_DIR / "starboard-internal"
    found_in_internal = any(
        _FORBIDDEN in p.read_text(encoding="utf-8")
        for p in internal_dir.rglob("*.py")
        if p.is_file()
    )
    assert found_in_internal, (
        "Expected packages/starboard-internal/ to contain the mirror catalog "
        "literal (e.g. in _namespace_rewrite.py / mirror_source.py) — if it "
        "no longer does, this test's premise needs re-checking."
    )
