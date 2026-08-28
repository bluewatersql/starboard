# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""CI schema-validation guard for Preview system.* query packs.

Decision D-0.5 (PHASE_0.md §11): the CI guard is a **recorded column manifest**
validated against each pack's declared ``required_columns``.  A live ``LIMIT 0``
probe against a real workspace remains the documented owner step for refreshing
the manifest — see ``docs/discovery/preview_pack_schema_guard.md``.

The four Preview packs tested here are:
  - predictive_optimization  (system.storage.predictive_optimization_operations_history)
  - data_quality             (system.data_quality_monitoring.table_results)
  - data_classification      (system.data_classification.results)
  - networking               (system.access.outbound_network)

Positive contract
-----------------
Every column listed in a query's ``required_columns`` must exist in the
manifest's column list for each of that query's ``required_tables``.

Negative contract
-----------------
Removing a column from the manifest (or adding an undeclared column to
``required_columns``) causes the test to fail — ensuring the guard is
non-trivially breakable.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from starboard.discovery.query_packs.data_classification import (
    DATA_CLASSIFICATION_PACK,
)
from starboard.discovery.query_packs.data_quality import DATA_QUALITY_PACK
from starboard.discovery.query_packs.networking import NETWORKING_PACK
from starboard.discovery.query_packs.predictive_optimization import (
    PREDICTIVE_OPTIMIZATION_PACK,
)

# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "system_table_columns.json"

_PREVIEW_PACKS = [
    PREDICTIVE_OPTIMIZATION_PACK,
    DATA_QUALITY_PACK,
    DATA_CLASSIFICATION_PACK,
    NETWORKING_PACK,
]


def _load_manifest() -> dict[str, list[str]]:
    """Load the recorded column manifest from the JSON fixture."""
    raw = json.loads(_FIXTURE_PATH.read_text())
    # Strip the documentation comment key if present
    return {k: v for k, v in raw.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_query_cases() -> list[tuple[str, str, tuple[str, ...], str]]:
    """Return (pack_id, query_id, required_columns, table) for all Preview queries."""
    cases = []
    for pack in _PREVIEW_PACKS:
        for query in pack.queries:
            for table in query.required_tables:
                cases.append((pack.pack_id, query.query_id, query.required_columns, table))
    return cases


# ---------------------------------------------------------------------------
# Positive tests: required_columns ⊆ manifest columns
# ---------------------------------------------------------------------------


def test_manifest_fixture_is_loadable() -> None:
    """Sanity: the JSON fixture exists and parses without error."""
    manifest = _load_manifest()
    assert len(manifest) >= 4, "Manifest must cover all four Preview tables"


@pytest.mark.parametrize(
    "pack_id,query_id,required_columns,table",
    _all_query_cases(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_required_columns_subset_of_manifest(
    pack_id: str,
    query_id: str,
    required_columns: tuple[str, ...],
    table: str,
) -> None:
    """Every column in required_columns must appear in the manifest for that table."""
    manifest = _load_manifest()

    assert table in manifest, (
        f"[{pack_id}/{query_id}] Table '{table}' is not recorded in the manifest. "
        f"Run a LIMIT 0 probe to refresh system_table_columns.json."
    )
    assert len(required_columns) > 0, (
        f"[{pack_id}/{query_id}] Preview pack query declares no required_columns — "
        f"add required_columns to the SystemQuery definition."
    )

    manifest_cols = set(manifest[table])
    missing = set(required_columns) - manifest_cols
    assert not missing, (
        f"[{pack_id}/{query_id}] Column(s) {sorted(missing)} are referenced in "
        f"required_columns but absent from the manifest for '{table}'. "
        f"Either update the manifest (run LIMIT 0 probe) or fix the pack's SQL."
    )


# ---------------------------------------------------------------------------
# Negative tests: guard is non-trivially breakable
# ---------------------------------------------------------------------------


def test_missing_column_in_manifest_causes_failure() -> None:
    """Removing a column from the manifest must trigger a subset-violation."""
    manifest = _load_manifest()

    # Pick the PO pack's table and strip one required column from the manifest
    po_table = "system.storage.predictive_optimization_operations_history"
    po_query = PREDICTIVE_OPTIMIZATION_PACK.queries[0]

    # Ensure the fixture has that column to begin with
    assert po_query.required_columns, "PO-01 must declare required_columns"
    col_to_drop = po_query.required_columns[0]
    assert col_to_drop in manifest[po_table], (
        f"Column '{col_to_drop}' should be in the manifest for the negative test to work"
    )

    # Build a truncated manifest missing that column
    truncated_manifest = copy.deepcopy(manifest)
    truncated_manifest[po_table] = [
        c for c in truncated_manifest[po_table] if c != col_to_drop
    ]

    manifest_cols = set(truncated_manifest[po_table])
    missing = set(po_query.required_columns) - manifest_cols
    assert missing, (
        "Expected a subset violation when a manifest column is removed, but none found. "
        "The guard is not functioning correctly."
    )
    assert col_to_drop in missing


def test_undeclared_column_in_required_columns_causes_failure() -> None:
    """Referencing a column not in the manifest must trigger a subset-violation."""
    manifest = _load_manifest()

    net_table = "system.access.outbound_network"
    net_query = NETWORKING_PACK.queries[0]

    assert net_query.required_columns, "NET-01 must declare required_columns"

    # Inject a column that does not exist in the manifest
    phantom_col = "_nonexistent_column_xyz"
    assert phantom_col not in manifest[net_table], "Phantom column must not pre-exist"

    augmented_required = net_query.required_columns + (phantom_col,)
    manifest_cols = set(manifest[net_table])
    missing = set(augmented_required) - manifest_cols

    assert missing, "Expected a violation when an undeclared column is added"
    assert phantom_col in missing
