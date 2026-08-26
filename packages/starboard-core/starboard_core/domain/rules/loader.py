# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Fail-fast YAML loader for workload-review rules (Phase-1 D3).

Reuses the loading style of
``starboard.tools.domain.diagnostic.patterns.registry``: ``yaml.safe_load`` +
pydantic ``model_validate``, raising a single ``RuleLoadError`` on any failure.

``pyyaml`` is **not** a hard dependency of the kernel (it lives in the
``starboard-core[diagnostics]`` extra), so it is imported lazily inside the
load functions with an actionable install error. Importing this module never
pulls ``yaml``, keeping the kernel surface clean.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from starboard_core.domain.rules.schema import RuleSet


class RuleLoadError(Exception):
    """Raised when a rule YAML file/string fails to load or validate."""


def _require_yaml():  # type: ignore[no-untyped-def]
    """Import ``yaml`` lazily with an actionable error if it is absent."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - env-dependent
        raise RuleLoadError(
            "Loading rule YAML requires PyYAML. Install it with "
            "`pip install starboard-core[diagnostics]` (or `pip install pyyaml`)."
        ) from exc
    return yaml


def seed_rules_dir() -> Path:
    """Return the directory containing the bundled seed rule YAML files."""
    return Path(__file__).parent / "seed"


def load_ruleset_from_string(content: str, source: str = "<string>") -> RuleSet:
    """Parse + validate a single ``RuleSet`` from a YAML string.

    Raises:
        RuleLoadError: If the YAML is malformed or fails schema validation.
    """
    yaml = _require_yaml()
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"Invalid YAML from {source}: {exc}") from exc

    if raw is None:
        raise RuleLoadError(f"Empty rule document from {source}")

    try:
        return RuleSet.model_validate(raw)
    except ValidationError as exc:
        raise RuleLoadError(
            f"Rule validation failed from {source}:\n{exc}"
        ) from exc


def load_ruleset_from_file(path: Path) -> RuleSet:
    """Load + validate a single ``RuleSet`` from a YAML file.

    Raises:
        RuleLoadError: If the file is missing, malformed, or invalid.
    """
    if not path.exists():
        raise RuleLoadError(f"Rule file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return load_ruleset_from_string(content, source=str(path))


def load_rulesets_from_directory(directory: Path) -> list[RuleSet]:
    """Load + validate every ``*.yaml`` / ``*.yml`` ruleset in a directory.

    Raises:
        RuleLoadError: If the directory is missing or any file is invalid.
    """
    if not directory.is_dir():
        raise RuleLoadError(f"Rule directory not found: {directory}")

    yaml_files = sorted(
        list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
    )
    return [load_ruleset_from_file(path) for path in yaml_files]
