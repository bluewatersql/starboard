# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the cluster_right_sizing query pack (CRS-01…08).

Verifies:
- All 8 CRS queries construct and carry required metadata.
- ``required_tables``/``required_columns`` name the intended ``system.*`` objects.
- Templates render with test params (no unfilled ``{placeholders}``).
- Preview/lakeflow-dependent queries carry ``required=False`` (degrade, don't fail).
- Registry wires the pack to compute/jobs/DLT product surfaces.
- Governance: no internal namespaces; only public ``system.*`` tables; cost
  columns use the ``list_`` naming convention (list-price DBU estimate).
- Complementarity: CRS does NOT re-implement CR-01…03 (instance reliability,
  warehouse churn); it adds right-sizing depth, cost features, and workload
  attribution that CR-01…03 intentionally omit.
"""

from __future__ import annotations

import collections
import re

import pytest
from starboard.discovery.query_packs.cluster_right_sizing import (
    CLUSTER_RIGHT_SIZING_PACK,
)
from starboard.discovery.query_packs.compute_reliability import (
    COMPUTE_RELIABILITY_PACK,
)
from starboard.discovery.query_packs.registry import (
    PRODUCT_TO_DOMAIN_PACKS,
    create_default_registry,
)
from starboard_core.domain.models.discovery.query import QueryPack

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RENDER_PARAMS = {"lookback_days": 30, "result_limit": 50}


def _render(sql_template: str) -> str:
    """Render a SQL template the way the executor does (defaultdict format_map)."""
    return sql_template.format_map(
        collections.defaultdict(str, _RENDER_PARAMS)
    )


# Tables the CRS pack is allowed to read (all public ``system.*``).
_ALLOWED_CRS_TABLES: frozenset[str] = frozenset(
    {
        "system.compute.clusters",
        "system.compute.node_types",
        "system.compute.node_timeline",
        "system.billing.usage",
        "system.billing.list_prices",
        "system.lakeflow.jobs",
        "system.lakeflow.job_run_timeline",
        "system.lakeflow.job_task_run_timeline",
        "system.lakeflow.pipelines",
        "system.lakeflow.pipeline_update_timeline",
    }
)

# Tables owned exclusively by compute_reliability — CRS must NOT read these.
_COMPUTE_RELIABILITY_EXCLUSIVE_TABLES: frozenset[str] = frozenset(
    {
        "system.compute.instance_events",   # CR-01: spot/on-demand reliability
        "system.compute.warehouse_events",  # CR-03: warehouse scaling churn
    }
)

# Internal namespaces that must never appear in public packs.
_FORBIDDEN_NAMESPACES: tuple[str, ...] = (
    "centralized_system_tables",
    "fin_live_gold",
    "logfood",
    "clickhouse",
    "hmr_stack_hash",
    "go/",
    "gtm_",
    "eng_",
)

# Expected CRS query IDs (ordered).
_EXPECTED_QUERY_IDS: tuple[str, ...] = (
    "CRS-01",
    "CRS-02",
    "CRS-03",
    "CRS-04",
    "CRS-05",
    "CRS-06",
    "CRS-07",
    "CRS-08",
)

# lakeflow-dependent queries — must be required=False (degrade gracefully).
_LAKEFLOW_QUERY_IDS: frozenset[str] = frozenset(
    {"CRS-03", "CRS-04", "CRS-05", "CRS-07", "CRS-08"}
)


# ---------------------------------------------------------------------------
# Pack construction
# ---------------------------------------------------------------------------


class TestCRSPackConstruct:
    def test_is_query_pack(self):
        assert isinstance(CLUSTER_RIGHT_SIZING_PACK, QueryPack)

    def test_pack_id(self):
        assert CLUSTER_RIGHT_SIZING_PACK.pack_id == "cluster_right_sizing"

    def test_has_all_eight_queries(self):
        assert len(CLUSTER_RIGHT_SIZING_PACK.queries) == 8

    def test_query_ids_are_crs_series(self):
        ids = tuple(q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries)
        assert ids == _EXPECTED_QUERY_IDS


# ---------------------------------------------------------------------------
# required_tables — must name real public system.* objects
# ---------------------------------------------------------------------------


class TestRequiredTables:
    def test_all_tables_are_public_system_tables(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert query.required_tables, f"{query.query_id} has no required_tables"
            for table in query.required_tables:
                assert table.startswith("system."), (
                    f"{query.query_id} references non-public table {table!r}"
                )

    def test_all_tables_in_allowed_set(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table in _ALLOWED_CRS_TABLES, (
                    f"{query.query_id} reads undocumented table {table!r}. "
                    f"Add it to _ALLOWED_CRS_TABLES if it is a real system.* table."
                )

    def test_node_timeline_present(self):
        """Core right-sizing signal comes from node_timeline."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.compute.node_timeline" in all_tables

    def test_billing_tables_present(self):
        """DBU cost features require billing.usage (DBU-only; no list_prices join)."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" in all_tables

    def test_lakeflow_attribution_tables_present(self):
        """Workload attribution needs lakeflow job/pipeline tables."""
        all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.lakeflow.job_task_run_timeline" in all_tables
        assert "system.lakeflow.job_run_timeline" in all_tables
        assert "system.lakeflow.pipelines" in all_tables


# ---------------------------------------------------------------------------
# required_columns — must name the intended source columns
# ---------------------------------------------------------------------------


class TestRequiredColumns:
    def test_all_queries_declare_required_columns(self):
        """Phase-0 contract: every CRS query must declare required_columns."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert query.required_columns, (
                f"{query.query_id} has no required_columns — "
                "add them for the schema-drift guard."
            )

    def test_required_columns_appear_in_sql(self):
        """Every declared column must be referenced in the SQL template."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            for col in query.required_columns:
                assert col in rendered, (
                    f"{query.query_id} declares required_column {col!r} "
                    "but it does not appear in the SQL template."
                )


# ---------------------------------------------------------------------------
# Template rendering — no unfilled placeholders; tables present in SQL
# ---------------------------------------------------------------------------


class TestTemplatesRender:
    def test_no_unfilled_placeholders(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            leftovers = re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered)
            assert not leftovers, (
                f"{query.query_id} has unfilled placeholders after render: {leftovers}"
            )

    def test_templates_reference_their_declared_tables(self):
        """Each required_table must appear verbatim in the SQL."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            rendered = _render(query.sql_template)
            for table in query.required_tables:
                assert table in rendered, (
                    f"{query.query_id} declares required_table {table!r} "
                    "but does not reference it in the SQL."
                )


# ---------------------------------------------------------------------------
# Optional queries — lakeflow-dependent must be required=False
# ---------------------------------------------------------------------------


class TestOptionalQueries:
    def test_lakeflow_queries_are_optional(self):
        """Workspaces without lakeflow tables must degrade gracefully."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in _LAKEFLOW_QUERY_IDS:
                assert query.required is False, (
                    f"{query.query_id} reads lakeflow tables and must be "
                    "required=False so a missing table degrades the query, "
                    "not the whole pack."
                )

    def test_non_lakeflow_queries_are_required(self):
        """Queries over GA compute+billing tables should be required=True."""
        ga_queries = {
            q.query_id
            for q in CLUSTER_RIGHT_SIZING_PACK.queries
            if q.query_id not in _LAKEFLOW_QUERY_IDS
        }
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in ga_queries:
                assert query.required is True, (
                    f"{query.query_id} reads only GA tables and should be required=True."
                )

    def test_lakeflow_queries_read_lakeflow_tables(self):
        """Every query in _LAKEFLOW_QUERY_IDS should reference at least one lakeflow table."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            if query.query_id in _LAKEFLOW_QUERY_IDS:
                has_lakeflow = any(
                    "lakeflow" in t for t in query.required_tables
                )
                # CRS-07 and CRS-08 may inline node_timeline plus lakeflow
                # but they should still read at least one lakeflow table.
                assert has_lakeflow, (
                    f"{query.query_id} is marked as lakeflow-dependent "
                    "but declares no lakeflow tables in required_tables."
                )


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestRegistryRegistration:
    def test_pack_in_registry(self):
        registry = create_default_registry()
        assert registry.get_pack("cluster_right_sizing") is not None

    @pytest.mark.parametrize("product", ["ALL_PURPOSE", "INTERACTIVE", "BASE_ENVIRONMENTS"])
    def test_compute_products_route_to_crs(self, product: str):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({product})}
        assert "cluster_right_sizing" in selected, (
            f"product {product!r} should select cluster_right_sizing"
        )

    def test_jobs_product_routes_to_crs(self):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({"JOBS"})}
        assert "cluster_right_sizing" in selected

    def test_dlt_product_routes_to_crs(self):
        registry = create_default_registry()
        selected = {p.pack_id for p in registry.get_packs_for_products({"DLT"})}
        assert "cluster_right_sizing" in selected

    def test_product_to_domain_packs_wired(self):
        """PRODUCT_TO_DOMAIN_PACKS should list cluster_right_sizing for expected products."""
        products_that_should_route = {"ALL_PURPOSE", "INTERACTIVE", "JOBS", "DLT"}
        for product in products_that_should_route:
            packs = PRODUCT_TO_DOMAIN_PACKS.get(product, [])
            assert "cluster_right_sizing" in packs, (
                f"PRODUCT_TO_DOMAIN_PACKS[{product!r}] should include "
                "'cluster_right_sizing'"
            )


# ---------------------------------------------------------------------------
# Governance guard
# ---------------------------------------------------------------------------


class TestGovernanceGuard:
    def test_no_internal_namespaces(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            blob = (
                query.sql_template + query.description + query.name
            ).lower()
            for needle in _FORBIDDEN_NAMESPACES:
                assert needle.lower() not in blob, (
                    f"{query.query_id} contains forbidden namespace {needle!r}"
                )

    def test_only_public_system_tables_in_required_tables(self):
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table.startswith("system."), (
                    f"{query.query_id} references non-public table {table!r}"
                )

    def test_no_usd_columns_in_sql(self):
        """DBU-only pack policy: no _usd columns; list-price $ is a tool-layer concern."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            sql_lower = query.sql_template.lower()
            usd_cols = re.findall(r'\b\w+_usd(?:_per_day)?\b', sql_lower)
            assert not usd_cols, (
                f"{query.query_id} emits USD column(s) {usd_cols!r}. "
                "This pack is DBU-only; move $ projection to the tool layer."
            )

    def test_no_list_prices_join_in_sql(self):
        """DBU-only policy: pack SQL must not join system.billing.list_prices."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            assert "system.billing.list_prices" not in query.sql_template, (
                f"{query.query_id} joins list_prices, violating the DBU-only pack policy."
            )
            assert "pricing.effective_list" not in query.sql_template, (
                f"{query.query_id} references pricing.effective_list, violating the DBU-only pack policy."
            )

    def test_crs06_order_by_uses_output_alias_not_cte_qualified(self):
        """CRS-06 must ORDER BY the unqualified ``sizing_direction`` output alias.

        Regression guard: it previously ordered by ``cs.sizing_direction``, but
        ``sizing_direction`` is an outer-SELECT alias, not a column of the
        ``cluster_summary`` (``cs``) CTE — so the qualified reference cannot
        resolve and raises AnalysisException at runtime, taking down the whole
        right-sizing path. String-render tests don't catch this; this does.
        """
        crs06 = next(
            q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-06"
        )
        sql = crs06.sql_template
        assert "cs.sizing_direction" not in sql, (
            "CRS-06 ORDER BY qualifies the outer alias with the CTE (cs.) — "
            "will raise AnalysisException. Use the bare output alias."
        )
        assert "AS sizing_direction," in sql, "expected sizing_direction output alias"
        assert "ORDER BY" in sql.upper()


# ---------------------------------------------------------------------------
# Complementarity with compute_reliability (CR-01…03)
# ---------------------------------------------------------------------------


class TestComplementarity:
    def test_crs_does_not_read_compute_reliability_exclusive_tables(self):
        """CRS must NOT overlap with the instance/warehouse lifecycle domain of CR-01/03."""
        for query in CLUSTER_RIGHT_SIZING_PACK.queries:
            for table in query.required_tables:
                assert table not in _COMPUTE_RELIABILITY_EXCLUSIVE_TABLES, (
                    f"{query.query_id} reads {table!r} which belongs to "
                    "compute_reliability (CR-01/03). Keep the packs complementary."
                )

    def test_crs_query_ids_do_not_overlap_cr_ids(self):
        cr_ids = {q.query_id for q in COMPUTE_RELIABILITY_PACK.queries}
        crs_ids = {q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries}
        overlap = cr_ids & crs_ids
        assert not overlap, (
            f"Query IDs overlap between compute_reliability and "
            f"cluster_right_sizing: {overlap}"
        )

    def test_crs_adds_cost_features_absent_from_cr(self):
        """CRS-02/06 should reference billing tables that CR-01…03 never use."""
        cr_all_tables = {
            t for q in COMPUTE_RELIABILITY_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" not in cr_all_tables, (
            "compute_reliability already references billing.usage — "
            "verify CRS is still adding new capability."
        )
        crs_all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.billing.usage" in crs_all_tables

    def test_crs_adds_workload_attribution_absent_from_cr(self):
        """CRS-03…05/07/08 surface workload attribution that CR does not provide."""
        crs_all_tables = {
            t for q in CLUSTER_RIGHT_SIZING_PACK.queries for t in q.required_tables
        }
        assert "system.lakeflow.job_task_run_timeline" in crs_all_tables

    def test_downstream_tool_query_ids_present(self):
        """get_cluster_rightsizing (CRS-06) and get_workload_rightsizing (CRS-07/08)
        must exist so the 09-tools task has stable query_ids to consume."""
        ids = {q.query_id for q in CLUSTER_RIGHT_SIZING_PACK.queries}
        for expected in ("CRS-06", "CRS-07", "CRS-08"):
            assert expected in ids, (
                f"Downstream tool query {expected!r} not found in pack."
            )


# ---------------------------------------------------------------------------
# P4 regression guard — SKIPPED/executed split in CRS-04 and CRS-07
# ---------------------------------------------------------------------------


class TestSkippedExecutedSplit:
    """Regression guard for the SKIPPED-vs-failed fix (demo feedback P4).

    A job dominated by SKIPPED runs (≈ free) must not read as 0% success over
    COUNT(*) — that massively overstates waste.  success_rate_pct is now
    calculated over EXECUTED runs (total minus SKIPPED) and the breakdown
    columns (skipped_runs, executed_runs) are surfaced explicitly.

    SQL correctness validates on a live re-run; these tests protect the
    filter shape so the fix cannot silently regress.
    """

    def _crs04(self) -> str:
        q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-04")
        return _render(q.sql_template)

    def _crs07(self) -> str:
        q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-07")
        return _render(q.sql_template)

    # -- CRS-04 ---------------------------------------------------------------

    def test_crs04_has_skipped_runs(self):
        assert "skipped_runs" in self._crs04(), (
            "CRS-04 must emit skipped_runs to surface SKIPPED-dominated jobs"
        )

    def test_crs04_has_executed_runs(self):
        assert "executed_runs" in self._crs04(), (
            "CRS-04 must emit executed_runs = total - SKIPPED as the true denominator"
        )

    def test_crs04_has_failed_runs(self):
        assert "failed_runs" in self._crs04(), (
            "CRS-04 must emit failed_runs to distinguish ERROR/FAILED/TIMED_OUT from SKIPPED"
        )

    def test_crs04_success_rate_not_over_raw_count(self):
        """success_rate_pct must NOT divide by raw COUNT(*) — that inflates failure rate."""
        sql = self._crs04()
        # The old form is: / NULLIF(COUNT(*), 0) with no subtraction
        # The new form is: / NULLIF(COUNT(*) - COUNT_IF(...SKIPPED...), 0)
        assert "/ NULLIF(COUNT(*), 0)" not in sql, (
            "CRS-04 success_rate_pct still divides by raw COUNT(*) — "
            "SKIPPED runs inflate the denominator, making a mostly-SKIPPED "
            "job look like 0% success.  Use NULLIF(COUNT(*) - COUNT_IF(SKIPPED), 0)."
        )

    def test_crs04_success_rate_uses_executed_denominator(self):
        assert "COUNT(*) - COUNT_IF" in self._crs04(), (
            "CRS-04 success_rate_pct denominator must subtract SKIPPED runs"
        )

    # -- CRS-07 ---------------------------------------------------------------

    def test_crs07_job_runs_cte_has_executed_runs(self):
        assert "executed_runs" in self._crs07(), (
            "CRS-07 job_runs CTE must include executed_runs for consistency with CRS-04"
        )

    def test_crs07_success_rate_not_over_raw_count(self):
        assert "/ NULLIF(COUNT(*), 0)" not in self._crs07(), (
            "CRS-07 job_runs CTE still divides success by raw COUNT(*) — "
            "use NULLIF(COUNT(*) - COUNT_IF(SKIPPED), 0)."
        )


# ---------------------------------------------------------------------------
# CRS-08 zero-signal filter — serverless-only workspace yields empty result
# ---------------------------------------------------------------------------


class TestCRS08ZeroSignalFilter:
    """CRS-08 must not return NOT_SCORED / priority_score=0 noise rows.

    CRS-08 scores JOB workloads only (node_timeline utilisation is
    cluster-grained). Pipelines carry no per-pipeline right-sizing signal, so
    the pipeline branch was removed entirely rather than emitting always-unscored
    (priority 0 / NOT_SCORED) placeholder rows. On an all-serverless workspace
    with no classic cluster rows, CRS-08 returns zero rows rather than a page of
    meaningless placeholders.
    """

    def _crs08(self) -> str:
        q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-08")
        return _render(q.sql_template)

    def test_filter_excludes_zero_priority_rows(self):
        """Final SELECT must contain a WHERE priority_score > 0 filter."""
        sql = self._crs08()
        assert "WHERE priority_score > 0" in sql, (
            "CRS-08 final SELECT must filter out priority_score = 0 rows "
            "so an all-serverless workspace returns an empty result instead "
            "of zero-signal noise rows."
        )

    def test_pipeline_branch_removed(self):
        """The always-unscored pipeline branch must be gone, not just filtered.

        Emitting pipeline rows with a hardcoded priority_score = 0 and then
        dropping them with WHERE priority_score > 0 is dead, self-contradictory
        work — the branch is removed at the source instead.
        """
        sql = self._crs08()
        assert "pipeline_workloads" not in sql
        assert "'PIPELINE'" not in sql
        assert "system.lakeflow.pipelines" not in sql

    def test_unified_cte_present(self):
        """unified CTE (thin wrapper over the scored job set) must be present."""
        sql = self._crs08()
        assert "unified AS (" in sql, (
            "CRS-08 must use a 'unified' CTE over the scored job_workloads set "
            "so the WHERE / ORDER BY apply to it."
        )

    def test_from_unified_in_final_select(self):
        """The filtered SELECT must read from the unified CTE."""
        sql = self._crs08()
        assert "FROM unified" in sql, (
            "CRS-08 final SELECT must read FROM unified so the WHERE filter "
            "applies to the scored result set."
        )

    def test_real_scored_rows_survive(self):
        """Rows with priority_score > 0 (UNDER/OVERPROVISIONED) must still appear.

        We cannot run live SQL in unit tests, but we verify that the filter
        condition is strictly > 0 (not >= 1 or anything stricter) so that
        priority scores 1…4 all pass through.
        """
        sql = self._crs08()
        # The filter must be exactly > 0, not > 1 or > 2.
        assert "priority_score > 0" in sql
        assert "priority_score > 1" not in sql, (
            "CRS-08 filter is too aggressive — priority scores 1 and 2 "
            "(OVERPROVISIONED) must not be excluded."
        )


# ---------------------------------------------------------------------------
# D13 — explicit NO_WORKER_SAMPLES status row instead of a silent 0-row result
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("qid", "worker_cte", "n_cols"),
    [("CRS-06", "worker_stats", 11), ("CRS-07", "worker_stats", 10), ("CRS-08", "worker_util", 5)],
)
def test_no_worker_samples_emits_status_row(qid: str, worker_cte: str, n_cols: int) -> None:
    from starboard.discovery.query_packs.cluster_right_sizing import (
        NO_WORKER_SAMPLES_REASON,
    )

    q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == qid)
    sql = _render(q.sql_template)
    # Verdict rows are tagged SCORED; the status row only exists when the worker
    # sample CTE is empty.
    assert "'SCORED'" in sql and "AS status" in sql and "AS reason" in sql
    assert "UNION ALL" in sql
    assert "'NO_WORKER_SAMPLES'" in sql
    assert f"FROM (SELECT COUNT(*) AS n FROM {worker_cte})" in sql
    assert NO_WORKER_SAMPLES_REASON in sql
    assert "@NO_WORKER_SAMPLES_REASON@" not in sql
    # Every data column is NULL on the status row (same arity as the verdict).
    assert "SELECT " + ", ".join(["NULL"] * n_cols) + "," in sql
    assert "NO_WORKER_SAMPLES" in q.metadata.output_hint


def test_crs05_and_cr03_descriptions_name_their_real_domain() -> None:
    """C9: CRS-05 is DLT pipeline reliability; CR-03 is warehouse lifecycle."""
    crs05 = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-05")
    assert "PIPELINE" in crs05.description and "NOT jobs" in crs05.description
    assert "SVA-03" in crs05.description
    cr03 = next(q for q in COMPUTE_RELIABILITY_PACK.queries if q.query_id == "CR-03")
    assert "WAREHOUSE" in cr03.description
    assert "NOT job failures" in cr03.description and "exit" in cr03.description


def test_crs05_success_rate_collapses_per_update() -> None:
    """CRS-05 success_rate_pct must count DISTINCT updates, not raw timeline rows.

    The pipeline_update_timeline has many lifecycle rows per update (NULL
    result_state until terminal); counting them all inflated the denominator and
    produced a misleading ~50% 'success rate'. Collapsing to one row per
    update_id (MAX(result_state)) makes it the per-update complement of the
    authoritative dlt_pipelines/P-DLT03 failure_rate (real failure ~2%).
    """
    q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-05")
    sql = _render(q.sql_template)
    assert "per_update" in sql
    assert "GROUP BY pipeline_id, update_id" in sql
    # run_stats aggregates the collapsed per_update rows, not the raw timeline.
    assert "FROM per_update" in sql


# ---------------------------------------------------------------------------
# W1 — CRS-04 / CRS-07 runtimes aggregate ALL timeline periods per run
# ---------------------------------------------------------------------------
# job_run_timeline slices a long run into ~hourly periods and sets result_state
# only on the terminal one. The old "per-segment max" (runtime_max_minutes 59.9 /
# 60.0) was that bug: filtering terminal periods first measured only the last
# slice, so no run could exceed ~60 min.


def _crs(qid: str) -> str:
    q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == qid)
    return _render(q.sql_template)


@pytest.mark.parametrize(("qid", "cte"), [("CRS-04", "runs"), ("CRS-07", "run_rollup")])
def test_crs_runtime_cte_aggregates_all_periods(qid: str, cte: str) -> None:
    sql = _crs(qid)
    body = sql.split(f"{cte} AS (", 1)[1]
    where = re.search(r"\bWHERE\b(.*?)\bGROUP BY\b", body, re.S)
    assert where is not None
    assert "result_state IS NOT NULL" not in where.group(1), (
        f"{qid} filters terminal periods before the per-run GROUP BY — "
        "runtimes cap at ~60 min"
    )
    assert re.search(r"GROUP BY (jrt\.)?workspace_id, (jrt\.)?job_id, (jrt\.)?run_id", body)
    assert "MAX_BY(" in body and "IF(" in body
    # Percentiles are over per-run runtimes, never a single period's length.
    assert "PERCENTILE(\n" not in sql
    assert "runtime_secs" in sql


def test_crs04_no_per_segment_annotation() -> None:
    assert "SINGLE job_run_timeline period" not in _crs("CRS-04")


@pytest.mark.parametrize("qid", ["CRS-06", "CRS-07", "CRS-08"])
def test_rollups_explain_empty_result(qid: str) -> None:
    """W25/D13: with no worker samples the rollup emits an explicit status row, and
    the hint says what it means (not 'no action needed') and where to look instead."""
    q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == qid)
    hint = q.metadata.output_hint
    assert "NO_WORKER_SAMPLES" in hint or "status" in hint
    assert "not 'no action needed'" in hint.lower() or "NOT 'no action needed'" in hint
    assert "CRS-01" in hint and "coverage_pct" in hint


# ---------------------------------------------------------------------------
# Round-8: CRS-01 latency + driver attribution; node_types fan-out family
# ---------------------------------------------------------------------------


def _crs(qid: str) -> str:
    return next(
        q.sql_template for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == qid
    )


def test_crs01_rows_carry_job_attribution_and_cluster_dbus() -> None:
    """Driver/worker rows name the cluster's job and its window DBU so a
    driver selection is actionable without a separate billing extract."""
    sql = _crs("CRS-01")
    for col in ("tb.job_id", "tb.job_name", "tb.attributed_job_count", "tb.cluster_dbus"):
        assert col in sql, col
    # Join path: node_timeline.cluster_id = billing.usage.usage_metadata.cluster_id.
    assert "u.usage_metadata.cluster_id                                AS cluster_id" in sql
    assert "MAX_BY(u.usage_metadata.job_id" in sql
    assert "MAX_BY(u.usage_metadata.job_name" in sql
    q = next(q for q in CLUSTER_RIGHT_SIZING_PACK.queries if q.query_id == "CRS-01")
    assert "system.billing.usage" in q.required_tables
    # No lakeflow dependency: CRS-01 stays required=True.
    assert not any(t.startswith("system.lakeflow.") for t in q.required_tables)


def test_crs01_scopes_to_billed_clusters_ranked_by_dbu() -> None:
    sql = _crs("CRS-01")
    # Semi-join: only clusters with billed classic usage, top-N by window DBU.
    assert "JOIN top_billed tb" in sql
    assert "ORDER BY cluster_dbus DESC" in sql
    assert "<= {result_limit} * 4" in sql
    # Output keeps the highest-DBU rows under the cap (not first-N by cluster_id).
    assert "ORDER BY tb.cluster_dbus DESC" in sql
    assert "ORDER BY s.workspace_id, s.cluster_id" not in sql


@pytest.mark.parametrize("qid", ["CRS-01", "CRS-06"])
def test_node_types_aggregated_not_windowed(qid: str) -> None:
    """node_types carries many rows per type on a multi-account source (~800M on
    the fleet mirror): a window over all of it was ~190 s of CRS-01, and an
    un-deduped join fans out every cluster row. One GROUP BY row per *sampled*
    node_type instead."""
    sql = _crs(qid)
    nt = sql[sql.index("FROM system.compute.node_types"):]
    nt = nt[: nt.index("GROUP BY node_type") + len("GROUP BY node_type")]
    assert "WHERE node_type IN (SELECT node_type FROM" in nt
    assert "QUALIFY" not in nt
    assert "MAX_BY(memory_mb, core_count)" in sql


def test_cr02_node_types_join_is_deduplicated() -> None:
    sql = next(
        q.sql_template for q in COMPUTE_RELIABILITY_PACK.queries if q.query_id == "CR-02"
    )
    assert "LEFT JOIN system.compute.node_types nt" not in sql
    assert "WHERE node_type IN (SELECT node_type FROM util)" in sql
    assert "GROUP BY node_type" in sql
