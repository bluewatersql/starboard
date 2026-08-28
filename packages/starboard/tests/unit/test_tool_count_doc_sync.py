# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""DOC-12 guard: the documented tool count must equal the live registry.

`docs/tools/TOOL_CATALOG.md` states a canonical ``**Total Tools**: N`` figure. This test pins
that figure to ``len(ALL_TOOL_METADATA)`` so the docs cannot silently drift from the registry
(the historical "45+" claim was stale; the real count is derived here, not hard-coded).
"""

from __future__ import annotations

import re
from pathlib import Path

from starboard.agents.tools.registry import ALL_TOOL_METADATA


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "docs" / "tools" / "TOOL_CATALOG.md").is_file():
            return parent
    raise AssertionError("could not locate repo root containing docs/tools/TOOL_CATALOG.md")


_TOTAL_RE = re.compile(r"\*\*Total Tools\*\*:\s*(\d+)")


def test_tool_catalog_total_matches_registry() -> None:
    catalog = (_repo_root() / "docs" / "tools" / "TOOL_CATALOG.md").read_text(encoding="utf-8")
    match = _TOTAL_RE.search(catalog)
    assert match is not None, "TOOL_CATALOG.md must state '**Total Tools**: <n>'"
    documented = int(match.group(1))
    assert documented == len(ALL_TOOL_METADATA), (
        f"TOOL_CATALOG.md says {documented} tools but the registry has "
        f"{len(ALL_TOOL_METADATA)} — update the doc (and the other '{documented}'/'45+' mentions)."
    )
