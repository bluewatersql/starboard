# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Context-budget ranking for source artifacts.

Stdlib-only (collections.abc).  No I/O, no SDK imports.
"""

from __future__ import annotations

from collections.abc import Sequence


def rank_and_trim_artifacts(
    artifacts: list[dict],
    *,
    max_total_bytes: int,
    hot_paths: Sequence[str] = (),
) -> tuple[list[dict], list[str]]:
    """Rank artifacts and keep a prefix within *max_total_bytes*.

    Ranking rules (deterministic, stable):

    - An artifact with ``reason == "entry"`` or ``key == "adhoc"`` is **always
      kept** and ranked first, regardless of budget (pinned).
    - Remaining artifacts are sorted by:
        1. is-hot first — hot = ``path`` is in ``hot_paths`` **or** any hot_path
           is a substring of ``path``.
        2. ``depth`` ascending (treat ``None`` as 0); shallower wins.
        3. ``len(code.encode())`` ascending; cheaper wins.
        4. ``key`` lexicographically for stability.
    - ``len(code.encode())`` is accumulated across kept artifacts.  Once adding
      the next ranked artifact would exceed *max_total_bytes*, **stop** and
      place that artifact and all remaining in ``dropped_keys``.  Pinned
      (entry/adhoc) bytes **count** toward the total but the pinned artifacts
      are never placed in ``dropped_keys``.

    Args:
        artifacts: List of artifact dicts, each containing at minimum
            ``"key"`` (str), ``"code"`` (str), and optionally ``"reason"``,
            ``"depth"``, and ``"path"``.
        max_total_bytes: Maximum cumulative byte budget for kept artifacts.
        hot_paths: Optional runtime-signal paths that should float to the
            front of the non-pinned ranking.

    Returns:
        ``(kept, dropped_keys)`` where *kept* is the ordered list of artifact
        dicts to analyse and *dropped_keys* is the list of keys that were
        excluded to fit the budget.
    """
    if not artifacts:
        return [], []

    def _is_pinned(art: dict) -> bool:
        return art.get("reason") == "entry" or art.get("key") == "adhoc"

    def _is_hot(art: dict) -> bool:
        path = art.get("path") or ""
        if not path or not hot_paths:
            return False
        return any(hp == path or hp in path for hp in hot_paths)

    def _sort_key(art: dict) -> tuple:
        is_hot_val = 0 if _is_hot(art) else 1
        depth_val = art.get("depth") if art.get("depth") is not None else 0
        size_val = len((art.get("code") or "").encode())
        key_val = art.get("key") or ""
        return (is_hot_val, depth_val, size_val, key_val)

    pinned = [a for a in artifacts if _is_pinned(a)]
    rest = sorted((a for a in artifacts if not _is_pinned(a)), key=_sort_key)

    kept: list[dict] = []
    dropped: list[str] = []
    total_bytes = 0

    # Pinned artifacts always go first; bytes counted but never trimmed.
    for art in pinned:
        total_bytes += len((art.get("code") or "").encode())
        kept.append(art)

    # Non-pinned: greedy prefix — stop at first overflow.
    budget_exhausted = False
    for art in rest:
        size = len((art.get("code") or "").encode())
        if not budget_exhausted and total_bytes + size <= max_total_bytes:
            total_bytes += size
            kept.append(art)
        else:
            budget_exhausted = True
            dropped.append(art.get("key") or "")

    return kept, dropped
