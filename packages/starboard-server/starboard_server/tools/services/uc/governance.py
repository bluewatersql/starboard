"""Governance service for UC grants, access patterns, and policy coverage.

Handles table grants, access pattern analysis from query history,
and security policy coverage reporting.
"""

from __future__ import annotations

from typing import Any

from starboard_core.domain.analyzers import UCAnalyzer
from starboard_core.domain.models.uc import (
    AccessPatterns,
    DailyAccess,
    EffectivePermission,
    Grant,
    PolicyCoverageReport,
    TableGrants,
    UserAccess,
)

from starboard_server.exceptions import AdapterError, QueryExecutionError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import (
    UCServiceBase,
    detect_principal_type,
    parse_timestamp,
)

logger = get_logger(__name__)


class GovernanceService(UCServiceBase):
    """Service for UC governance operations: grants, access, and policy coverage."""

    async def fetch_table_grants(
        self,
        table_name: str,
    ) -> TableGrants | None:
        """Fetch table grants and effective permissions.

        Args:
            table_name: Fully qualified table name

        Returns:
            TableGrants or None if access denied
        """
        from databricks.sdk.service.catalog import SecurableType

        logger.debug("fetching_table_grants", table_name=table_name)

        # Get direct grants
        raw_grants = await self.uc_provider.get_grants(SecurableType.TABLE, table_name)
        if raw_grants is None:
            logger.debug("cannot_access_grants", table_name=table_name)
            return None

        # Get effective grants
        raw_effective = await self.uc_provider.get_effective_grants(
            SecurableType.TABLE, table_name
        )

        # Parse direct grants
        direct_grants: list[Grant] = []
        for pa in raw_grants.get("privilege_assignments", []):
            principal = pa.get("principal", "")
            privileges = pa.get("privileges", [])
            if privileges:
                privilege_names = tuple(
                    p.get("privilege", "") if isinstance(p, dict) else str(p)
                    for p in privileges
                )
                direct_grants.append(
                    Grant(
                        principal=principal,
                        principal_type=detect_principal_type(principal),
                        privileges=privilege_names,
                        inherited_from=None,
                    )
                )

        # Parse effective permissions
        effective_perms: list[EffectivePermission] = []
        if raw_effective:
            for pa in raw_effective.get("privilege_assignments", []):
                principal = pa.get("principal", "")
                for priv in pa.get("privileges", []):
                    priv_name = (
                        priv.get("privilege", "")
                        if isinstance(priv, dict)
                        else str(priv)
                    )
                    inherited = (
                        priv.get("inherited_from_name")
                        if isinstance(priv, dict)
                        else None
                    )
                    effective_perms.append(
                        EffectivePermission(
                            principal=principal,
                            privilege=priv_name,
                            source=inherited or table_name,
                        )
                    )

        # Get table owner
        raw_table = await self.uc_provider.get_table(
            table_name, include_delta_metadata=False
        )
        owner = raw_table.get("owner", "unknown") if raw_table else "unknown"

        return TableGrants(
            table_name=table_name,
            owner=owner,
            direct_grants=tuple(direct_grants),
            inherited_grants=(),  # Would require checking parent schemas/catalogs
            effective_permissions=tuple(effective_perms),
        )

    async def analyze_access_patterns(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> AccessPatterns | None:
        """Analyze table access patterns from query history + lineage.

        Uses query.history joined with table_lineage for accurate attribution:
        - executed_by: User who ran the query
        - query_source: Access type (JOB, DASHBOARD, NOTEBOOK, etc.)
        - session_id: Session tracking
        - Metrics: read_rows, read_bytes, cache hits, duration

        Args:
            table_name: Fully qualified table name
            window_days: Days to look back

        Returns:
            AccessPatterns with comprehensive usage metrics

        Note:
            Requires SQL provider for system table queries
        """
        logger.debug("analyzing_access_patterns", table_name=table_name)

        if not self.sql_provider:
            logger.warning("sql_provider_not_configured", operation="access_patterns")
            return None

        # Query query.history joined with table_lineage
        query = f"""
        WITH target_lineage AS (
            -- Reads from this table
            SELECT DISTINCT
                statement_id,
                'READ' AS access_type
            FROM system.access.table_lineage
            WHERE source_table_full_name = '{table_name}'
              AND event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS

            UNION ALL

            -- Writes to this table
            SELECT DISTINCT
                statement_id,
                'WRITE' AS access_type
            FROM system.access.table_lineage
            WHERE target_table_full_name = '{table_name}'
              AND event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        ),
        query_details AS (
            SELECT
                h.statement_id,
                h.executed_by,
                h.start_time,
                h.total_duration_ms,
                h.statement_type,
                -- Read metrics
                COALESCE(h.read_rows, 0) AS read_rows,
                COALESCE(h.read_bytes, 0) AS read_bytes,
                -- Write metrics
                COALESCE(h.written_rows, 0) AS written_rows,
                COALESCE(h.written_bytes, 0) AS written_bytes,
                -- Cache info
                COALESCE(h.from_result_cache, false) AS from_cache,
                -- Source info (job, dashboard, notebook, etc.)
                h.query_source,
                h.session_id,
                -- Access type from lineage
                tl.access_type,
                -- Date for daily aggregation
                DATE(h.start_time) AS query_date
            FROM system.query.history h
            INNER JOIN target_lineage tl ON h.statement_id = tl.statement_id
            WHERE h.execution_status = 'FINISHED'
              AND h.start_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        )
        SELECT
            -- Overall counts
            COUNT(CASE WHEN access_type = 'READ' THEN 1 END) AS read_query_count,
            COUNT(CASE WHEN access_type = 'WRITE' THEN 1 END) AS write_query_count,

            -- Read metrics
            SUM(CASE WHEN access_type = 'READ' THEN read_bytes ELSE 0 END) AS total_read_bytes,
            SUM(CASE WHEN access_type = 'READ' THEN read_rows ELSE 0 END) AS total_read_rows,
            AVG(CASE WHEN access_type = 'READ' THEN read_bytes END) AS avg_read_bytes,
            APPROX_PERCENTILE(
                CASE WHEN access_type = 'READ' THEN read_bytes END, 0.95
            ) AS p95_read_bytes,
            MAX(CASE WHEN access_type = 'READ' THEN start_time END) AS last_read_time,

            -- Write metrics
            SUM(CASE WHEN access_type = 'WRITE' THEN written_bytes ELSE 0 END) AS total_written_bytes,
            SUM(CASE WHEN access_type = 'WRITE' THEN written_rows ELSE 0 END) AS total_written_rows,
            MAX(CASE WHEN access_type = 'WRITE' THEN start_time END) AS last_write_time,

            -- User metrics
            COUNT(DISTINCT executed_by) AS distinct_users,
            COUNT(DISTINCT CASE WHEN access_type = 'READ' THEN executed_by END) AS distinct_readers,
            COUNT(DISTINCT CASE WHEN access_type = 'WRITE' THEN executed_by END) AS distinct_writers,

            -- Cache metrics
            SUM(CASE WHEN from_cache THEN 1 ELSE 0 END) AS cache_hits,
            COUNT(*) AS total_queries,

            -- Source breakdown (jobs, dashboards, notebooks, etc.)
            -- Note: query_source is a STRUCT in newer Databricks versions
            COUNT(CASE WHEN query_source.job_info.job_id IS NOT NULL THEN 1 END) AS queries_from_jobs,
            COUNT(CASE WHEN query_source.dashboard_id IS NOT NULL OR query_source.legacy_dashboard_id IS NOT NULL THEN 1 END) AS queries_from_dashboards,
            COUNT(CASE WHEN query_source.notebook_id IS NOT NULL THEN 1 END) AS queries_from_notebooks,
            COUNT(CASE WHEN query_source.sql_query_id IS NOT NULL THEN 1 END) AS queries_from_sql_editor,

            -- Performance metrics
            AVG(total_duration_ms) AS avg_duration_ms,
            APPROX_PERCENTILE(total_duration_ms, 0.95) AS p95_duration_ms
        FROM query_details
        """

        try:
            rows = await self.sql_provider.execute_query(query)
        except (QueryExecutionError, AdapterError) as e:
            logger.error("error_querying_access_patterns", error=str(e))
            return None

        if not rows:
            return AccessPatterns(
                table_name=table_name,
                window_days=window_days,
                read_query_count=0,
                total_read_bytes=0,
                avg_read_gb=0.0,
                p95_read_gb=0.0,
                distinct_readers=0,
                last_read=None,
                write_operation_count=0,
                total_written_bytes=0,
                last_write=None,
                access_pattern="inactive",
            )

        row = rows[0]

        read_count = row.get("read_query_count") or 0
        write_count = row.get("write_query_count") or 0
        total_read_bytes = row.get("total_read_bytes") or 0
        total_written_bytes = row.get("total_written_bytes") or 0
        p95_read_bytes = row.get("p95_read_bytes") or 0

        # Now fetch daily breakdown for trend
        daily_query = f"""
        WITH target_lineage AS (
            SELECT DISTINCT statement_id
            FROM system.access.table_lineage
            WHERE source_table_full_name = '{table_name}'
               OR target_table_full_name = '{table_name}'
              AND event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        )
        SELECT
            DATE(h.start_time) AS query_date,
            COUNT(*) AS query_count
        FROM system.query.history h
        INNER JOIN target_lineage tl ON h.statement_id = tl.statement_id
        WHERE h.execution_status = 'FINISHED'
          AND h.start_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        GROUP BY DATE(h.start_time)
        ORDER BY query_date DESC
        LIMIT 30
        """

        try:
            daily_rows = await self.sql_provider.execute_query(daily_query)
            daily_trend = tuple(
                DailyAccess(
                    date=str(r.get("query_date", "")), count=r.get("query_count", 0)
                )
                for r in daily_rows
            )
        except (QueryExecutionError, AdapterError):
            daily_trend = ()

        # Also fetch top readers
        top_readers_query = f"""
        WITH target_lineage AS (
            SELECT DISTINCT statement_id
            FROM system.access.table_lineage
            WHERE source_table_full_name = '{table_name}'
              AND event_time >= CURRENT_TIMESTAMP() - INTERVAL {window_days} DAYS
        )
        SELECT
            h.executed_by,
            COUNT(*) AS query_count,
            SUM(COALESCE(h.read_bytes, 0)) AS total_bytes
        FROM system.query.history h
        INNER JOIN target_lineage tl ON h.statement_id = tl.statement_id
        WHERE h.execution_status = 'FINISHED'
        GROUP BY h.executed_by
        ORDER BY query_count DESC
        LIMIT 10
        """

        try:
            reader_rows = await self.sql_provider.execute_query(top_readers_query)
            top_readers = tuple(
                UserAccess(
                    user=r.get("executed_by", ""),
                    access_count=r.get("query_count", 0),
                    total_bytes=r.get("total_bytes", 0),
                )
                for r in reader_rows
            )
        except (QueryExecutionError, AdapterError):
            top_readers = ()

        # Classify pattern
        pattern = self._classify_access_pattern(read_count, write_count)

        return AccessPatterns(
            table_name=table_name,
            window_days=window_days,
            read_query_count=read_count,
            total_read_bytes=total_read_bytes,
            avg_read_gb=round((row.get("avg_read_bytes") or 0) / 1e9, 4),
            p95_read_gb=round(p95_read_bytes / 1e9, 4),
            distinct_readers=row.get("distinct_readers") or 0,
            last_read=parse_timestamp(row.get("last_read_time")),
            write_operation_count=write_count,
            total_written_bytes=total_written_bytes,
            last_write=parse_timestamp(row.get("last_write_time")),
            daily_trend=daily_trend,
            top_readers=top_readers,
            access_pattern=pattern,
        )

    def _classify_access_pattern(self, reads: int, writes: int) -> str:
        """Classify access pattern based on read/write counts."""
        if reads == 0 and writes == 0:
            return "inactive"
        if writes == 0:
            return "high_read_low_write"
        ratio = reads / max(writes, 1)
        if ratio > 10:
            return "high_read_low_write"
        elif ratio < 0.1:
            return "high_write_low_read"
        return "balanced"

    async def analyze_policy_coverage(
        self,
        scope: str,
        catalog: str | None = None,
        schema: str | None = None,
        *,
        _catalog_browser: Any = None,
    ) -> PolicyCoverageReport | None:
        """Analyze security policy coverage.

        Args:
            scope: 'catalog', 'schema', or 'table'
            catalog: Catalog name (required for schema/table scope)
            schema: Schema name (required for table scope)
            _catalog_browser: Internal reference to CatalogBrowserService for
                asset enumeration. Injected by the UCService facade.

        Returns:
            PolicyCoverageReport or None if scope invalid
        """
        logger.debug("analyzing_policy_coverage", scope=scope)

        # Use injected catalog browser or fall back to own enumerate if available
        enumerate_fn = (
            _catalog_browser.enumerate_assets if _catalog_browser is not None else None
        )
        if enumerate_fn is None:
            logger.error("catalog_browser_not_available_for_policy_coverage")
            return None

        # Enumerate assets in scope
        if scope == "catalog":
            assets = await enumerate_fn(asset_type="catalogs")
        elif scope == "schema":
            if not catalog:
                return None
            assets = await enumerate_fn(catalog=catalog, asset_type="schemas")
        elif scope == "table":
            if not catalog or not schema:
                return None
            assets = await enumerate_fn(
                catalog=catalog, schema=schema, asset_type="tables"
            )
        else:
            return None

        assets_count = assets.total_count
        assets_with_owner = sum(1 for a in assets.assets if a.owner)
        assets_with_grants = 0
        assets_with_row_filters = 0
        assets_with_column_masks = 0

        # For each table, check grants (limited for performance)
        for asset in assets.assets[:20]:  # Sample first 20
            if asset.asset_type == "table":
                grants = await self.fetch_table_grants(asset.full_name)
                if grants and grants.direct_grants:
                    assets_with_grants += 1

        # Scale up based on sample
        if assets_count > 20:
            sample_ratio = assets_count / 20
            assets_with_grants = int(assets_with_grants * sample_ratio)

        # Calculate coverage
        ownership_pct = (assets_with_owner / max(assets_count, 1)) * 100
        access_pct = (assets_with_grants / max(assets_count, 1)) * 100
        protection_pct = (
            (assets_with_row_filters + assets_with_column_masks)
            / max(assets_count * 2, 1)
            * 100
        )

        # Analyze gaps
        gaps = UCAnalyzer.analyze_policy_gaps(
            assets_count=assets_count,
            assets_with_owner=assets_with_owner,
            assets_with_grants=assets_with_grants,
            assets_with_row_filters=assets_with_row_filters,
            has_pii_columns=False,  # Would need column analysis
            has_public_access=False,  # Would need grant analysis
        )

        # Calculate score
        critical_gaps = sum(1 for g in gaps if g.severity == "critical")
        score = UCAnalyzer.calculate_security_score(
            ownership_coverage=ownership_pct / 100,
            access_control_coverage=access_pct / 100,
            data_protection_coverage=protection_pct / 100,
            gap_count=len(gaps),
            critical_gap_count=critical_gaps,
        )

        return PolicyCoverageReport(
            scope=f"{catalog}.{schema}" if schema else catalog or "all",
            assets_analyzed=assets_count,
            assets_with_owner=assets_with_owner,
            assets_with_grants=assets_with_grants,
            assets_with_row_filters=assets_with_row_filters,
            assets_with_column_masks=assets_with_column_masks,
            ownership_coverage_pct=round(ownership_pct, 1),
            access_control_coverage_pct=round(access_pct, 1),
            data_protection_coverage_pct=round(protection_pct, 1),
            policy_gaps=tuple(gaps),
            overall_security_score=round(score, 2),
        )
