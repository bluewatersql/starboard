# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for rank_and_trim_artifacts — Phase 6 context budget ranking.

TDD: tests written before implementation.
"""

from starboard_core.domain.source.ranking import rank_and_trim_artifacts


def _make(
    key: str,
    code: str,
    reason: str | None = None,
    depth: int | None = None,
    path: str | None = None,
) -> dict:
    return {"key": key, "code": code, "reason": reason, "depth": depth, "path": path}


class TestRankAndTrimEmpty:
    """Edge cases: empty / under-budget."""

    def test_empty_input(self):
        kept, dropped = rank_and_trim_artifacts([], max_total_bytes=1000)
        assert kept == []
        assert dropped == []

    def test_under_budget_passthrough_unchanged(self):
        a = _make("a", "hello", reason="import", depth=1)
        b = _make("b", "world", reason="import", depth=2)
        kept, dropped = rank_and_trim_artifacts([a, b], max_total_bytes=10_000)
        assert len(kept) == 2
        assert dropped == []

    def test_single_artifact_under_budget(self):
        art = _make("only", "print('hi')", reason="entry", depth=0)
        kept, dropped = rank_and_trim_artifacts([art], max_total_bytes=1000)
        assert len(kept) == 1
        assert dropped == []


class TestEntryAdHocAlwaysKept:
    """Entry and adhoc artifacts are pinned — never trimmed."""

    def test_entry_always_kept_even_over_budget(self):
        entry = _make("entry_key", "x" * 200, reason="entry", depth=0)
        other = _make("other", "y" * 200, reason="import", depth=1)
        kept, dropped = rank_and_trim_artifacts([entry, other], max_total_bytes=100)
        kept_keys = [a["key"] for a in kept]
        assert "entry_key" in kept_keys
        assert "other" not in kept_keys

    def test_adhoc_always_kept_even_over_budget(self):
        adhoc = _make("adhoc", "x" * 200)
        other = _make("other", "y" * 200, reason="import", depth=1)
        kept, dropped = rank_and_trim_artifacts([adhoc, other], max_total_bytes=100)
        kept_keys = [a["key"] for a in kept]
        assert "adhoc" in kept_keys
        assert "other" not in kept_keys

    def test_entry_is_first_in_output(self):
        entry = _make("entry_key", "code", reason="entry", depth=0)
        other = _make("other", "other_code", reason="import", depth=1)
        kept, _ = rank_and_trim_artifacts([other, entry], max_total_bytes=10_000)
        assert kept[0]["key"] == "entry_key"

    def test_entry_bytes_count_toward_total(self):
        """Entry bytes count toward budget; non-entry that pushes past budget is dropped."""
        entry = _make("entry_key", "x" * 90, reason="entry", depth=0)  # 90 bytes
        small = _make("small", "y" * 5, reason="import", depth=1)  # 5 bytes; total 95 — fits
        big = _make("big", "z" * 20, reason="import", depth=2)  # 20 bytes; total 115 — does not fit
        kept, dropped = rank_and_trim_artifacts(
            [entry, small, big], max_total_bytes=100
        )
        kept_keys = [a["key"] for a in kept]
        assert "entry_key" in kept_keys
        assert "small" in kept_keys
        assert "big" not in kept_keys
        assert "big" in dropped

    def test_dropped_keys_in_result(self):
        entry = _make("entry_key", "x" * 200, reason="entry")
        other = _make("other", "y" * 200, reason="import", depth=1)
        _, dropped = rank_and_trim_artifacts([entry, other], max_total_bytes=100)
        assert "other" in dropped


class TestHotPaths:
    """hot_paths signal floats matching artifacts to front of non-pinned."""

    def test_hot_path_exact_match_before_cold(self):
        hot = _make(
            "hot_key",
            "hello",
            reason="import",
            depth=2,
            path="/modules/hot_module.py",
        )
        cold = _make("cold_key", "hi", reason="import", depth=1, path="/modules/cold.py")
        kept, _ = rank_and_trim_artifacts(
            [cold, hot],
            max_total_bytes=10_000,
            hot_paths=["/modules/hot_module.py"],
        )
        kept_keys = [a["key"] for a in kept]
        assert kept_keys.index("hot_key") < kept_keys.index("cold_key")

    def test_substring_hot_match(self):
        art = _make(
            "key",
            "code",
            reason="import",
            depth=1,
            path="/project/utils/helper.py",
        )
        kept, dropped = rank_and_trim_artifacts(
            [art],
            max_total_bytes=10_000,
            hot_paths=["utils/helper"],
        )
        assert len(kept) == 1
        assert dropped == []

    def test_hot_path_kept_cold_trimmed(self):
        hot = _make(
            "hot_key",
            "hi" * 10,  # 20 bytes
            reason="import",
            depth=2,
            path="/project/hot.py",
        )
        cold = _make(
            "cold_key",
            "bye" * 100,  # 300 bytes
            reason="import",
            depth=1,
            path="/project/cold.py",
        )
        # Budget fits hot but not cold
        kept, dropped = rank_and_trim_artifacts(
            [cold, hot],
            max_total_bytes=50,
            hot_paths=["/project/hot.py"],
        )
        kept_keys = [a["key"] for a in kept]
        assert "hot_key" in kept_keys
        assert "cold_key" not in kept_keys
        assert "cold_key" in dropped

    def test_no_hot_paths_uses_depth_ordering(self):
        shallow = _make("shallow", "aa", reason="import", depth=1)
        deep = _make("deep", "bb", reason="import", depth=3)
        kept, _ = rank_and_trim_artifacts(
            [deep, shallow], max_total_bytes=10_000
        )
        keys = [a["key"] for a in kept]
        assert keys.index("shallow") < keys.index("deep")

    def test_empty_hot_paths_sequence(self):
        a = _make("a", "code_a", reason="import", depth=1)
        b = _make("b", "code_b", reason="import", depth=2)
        kept, dropped = rank_and_trim_artifacts([a, b], max_total_bytes=10_000, hot_paths=())
        assert len(kept) == 2
        assert dropped == []


class TestBudgetTrimming:
    """Budget enforcement: stop at first overflow, rest go to dropped."""

    def test_budget_trims_lowest_priority(self):
        big = _make("big", "x" * 300, reason="import", depth=2)
        small = _make("small", "y" * 10, reason="import", depth=1)
        kept, dropped = rank_and_trim_artifacts([big, small], max_total_bytes=50)
        kept_keys = [a["key"] for a in kept]
        assert "small" in kept_keys
        assert "big" in dropped

    def test_stop_on_first_overflow_rest_all_dropped(self):
        """After the first artifact that doesn't fit, all subsequent go to dropped."""
        a = _make("a", "x" * 10, reason="import", depth=1)
        b = _make("b", "y" * 100, reason="import", depth=2)
        c = _make("c", "z" * 5, reason="import", depth=3)  # would fit but comes after b
        kept, dropped = rank_and_trim_artifacts([a, b, c], max_total_bytes=50)
        kept_keys = [a["key"] for a in kept]
        assert "a" in kept_keys
        assert "b" in dropped
        assert "c" in dropped

    def test_exact_budget_keeps_all(self):
        a = _make("a", "x" * 20, reason="import", depth=1)
        b = _make("b", "y" * 30, reason="import", depth=2)
        kept, dropped = rank_and_trim_artifacts([a, b], max_total_bytes=50)
        assert len(kept) == 2
        assert dropped == []

    def test_one_over_budget_drops_that_one(self):
        a = _make("a", "x" * 20, reason="import", depth=1)
        b = _make("b", "y" * 31, reason="import", depth=2)  # 51 total
        kept, dropped = rank_and_trim_artifacts([a, b], max_total_bytes=50)
        kept_keys = [k["key"] for k in kept]
        assert "a" in kept_keys
        assert "b" in dropped


class TestDeterministicOrdering:
    """Ordering is stable and deterministic regardless of input order."""

    def test_deterministic_with_ties_by_key(self):
        z = _make("z_key", "code", reason="import", depth=1)
        a = _make("a_key", "code", reason="import", depth=1)
        kept1, _ = rank_and_trim_artifacts([z, a], max_total_bytes=10_000)
        kept2, _ = rank_and_trim_artifacts([a, z], max_total_bytes=10_000)
        assert [x["key"] for x in kept1] == [x["key"] for x in kept2]

    def test_depth_none_treated_as_zero(self):
        no_depth = _make("nd", "aa", reason="import", depth=None)
        shallow = _make("sh", "bb", reason="import", depth=0)
        deep = _make("dp", "cc", reason="import", depth=3)
        kept, _ = rank_and_trim_artifacts([deep, no_depth, shallow], max_total_bytes=10_000)
        keys = [a["key"] for a in kept]
        # Both nd and sh have effective depth 0, deep has depth 3 — so deep is last
        assert keys.index("dp") > keys.index("nd")
        assert keys.index("dp") > keys.index("sh")

    def test_size_ascending_tiebreaker(self):
        """When hot/depth are equal, smaller code comes first."""
        big = _make("big_key", "x" * 100, reason="import", depth=1)
        small = _make("small_key", "y" * 10, reason="import", depth=1)
        kept, _ = rank_and_trim_artifacts([big, small], max_total_bytes=10_000)
        keys = [a["key"] for a in kept]
        assert keys.index("small_key") < keys.index("big_key")
