# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Workload-review rule schema + fail-fast YAML loader (Phase-1 D3).

Schema + seed YAML + scorer only — **no engine**. The ``RuleRegistry`` and
reviewer flow land in Phase 3 (D1). Kernel-clean: pure pydantic + a lazy YAML
loader.
"""

from starboard_core.domain.rules.loader import (
    RuleLoadError,
    load_ruleset_from_file,
    load_ruleset_from_string,
    load_rulesets_from_directory,
    seed_rules_dir,
)
from starboard_core.domain.rules.schema import Rule, RuleSet

__all__ = [
    "Rule",
    "RuleSet",
    "RuleLoadError",
    "load_ruleset_from_file",
    "load_ruleset_from_string",
    "load_rulesets_from_directory",
    "seed_rules_dir",
]
