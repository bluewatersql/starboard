# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workload-review rule schema + loader + kernel ``RuleRegistry`` (Phase-1 D3 / Phase-3 D1a).

Schema + seed YAML + scorer + a pure-kernel ``RuleRegistry`` — still **no I/O
engine**; the reviewer flow (query execution, LLM council) lands later in
Phase 3 (D1b/D1c). Kernel-clean: pure pydantic + a lazy YAML loader; the
registry wires the D3 ``severity × impact / effort`` scorer into a stable
total order and validates each rule's ``evidence_query`` against a
caller-supplied set of real ``query_id`` values.
"""

from starboard_core.domain.rules.loader import (
    RuleLoadError,
    load_ruleset_from_file,
    load_ruleset_from_string,
    load_rulesets_from_directory,
    seed_rules_dir,
)
from starboard_core.domain.rules.registry import (
    DanglingEvidenceQueryError,
    RuleRegistry,
    rank_findings,
)
from starboard_core.domain.rules.schema import Rule, RuleSet

__all__ = [
    "Rule",
    "RuleSet",
    "RuleLoadError",
    "RuleRegistry",
    "DanglingEvidenceQueryError",
    "rank_findings",
    "load_ruleset_from_file",
    "load_ruleset_from_string",
    "load_rulesets_from_directory",
    "seed_rules_dir",
]
