"""Table metadata service for UC table information and fingerprints.

Handles fetching comprehensive table metadata and generating
table fingerprints using workload analysis.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from starboard_core.domain.models.uc import (
    CostMetrics,
    ReadWorkloadMetrics,
    TableFingerprint,
    UCTableMetadata,
    WriteWorkloadMetrics,
)
from starboard_core.domain.transformers import TableFingerprintTransformer

from starboard_server.exceptions import AdapterError, QueryExecutionError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import (
    UCServiceBase,
    parse_timestamp,
    safe_int,
)

logger = get_logger(__name__)


class TableMetadataService(UCServiceBase):
    """Service for table metadata retrieval and fingerprint generation."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with shared providers."""
        super().__init__(**kwargs)
        self.fingerprint_transformer = TableFingerprintTransformer()

    async def fetch_table_metadata(
        self,
        table_name: str,
    ) -> UCTableMetadata | None:
        """Fetch comprehensive table metadata.

        Args:
            table_name: Fully qualified table name

        Returns:
            UCTableMetadata or None if not found
        """
        from starboard_core.domain.models.uc import ColumnInfo

        logger.debug("fetching_table_metadata", table_name=table_name)

        raw_table = await self.uc_provider.get_table(
            table_name, include_delta_metadata=True
        )
        if not raw_table:
            logger.warning("table_not_found", table_name=table_name)
            return None

        # Parse table name parts
        parts = table_name.split(".")
        if len(parts) != 3:
            logger.warning("invalid_table_name_format", table_name=table_name)
            return None

        catalog, schema, table = parts

        # Extract raw columns
        raw_columns = raw_table.get("columns", [])

        # Extract storage info from delta_runtime_properties_kvpairs
        delta_props = raw_table.get("delta_runtime_properties_kvpairs", {})
        num_files = safe_int(delta_props.get("numFiles"))
        size_bytes = safe_int(delta_props.get("sizeInBytes"))
        row_count = safe_int(delta_props.get("numRows"))

        # Extract table properties
        table_properties = raw_table.get("properties", {}) or {}

        # Extract clustering columns from delta.liquid.clustering.columns property
        # Format: "col1,col2,col3" or JSON array
        clustering_columns: tuple[str, ...] | None = None
        clustering_prop = (
            table_properties.get("delta.liquid.clustering.columns")
            or table_properties.get("delta.clustering.columns")
            or delta_props.get("clusteringColumns")
        )
        if clustering_prop:
            if isinstance(clustering_prop, str):
                # Comma-separated or JSON array string
                if clustering_prop.startswith("["):
                    import json

                    try:
                        clustering_columns = tuple(json.loads(clustering_prop))
                    except json.JSONDecodeError:
                        clustering_columns = tuple(
                            c.strip()
                            for c in clustering_prop.strip("[]").split(",")
                            if c.strip()
                        )
                else:
                    clustering_columns = tuple(
                        c.strip() for c in clustering_prop.split(",") if c.strip()
                    )
            elif isinstance(clustering_prop, list):
                clustering_columns = tuple(clustering_prop)

        # Extract statistics freshness from table properties
        statistics_freshness: datetime | None = None
        stats_last_updated = table_properties.get("delta.stats.lastUpdated")
        if stats_last_updated:
            statistics_freshness = parse_timestamp(stats_last_updated)

        # Build columns with clustering flag
        clustering_set = set(clustering_columns) if clustering_columns else set()
        columns = tuple(
            ColumnInfo(
                name=c.get("name", ""),
                data_type=c.get("type_text", c.get("type_name", "STRING")),
                position=c.get("position", i),
                nullable=c.get("nullable", True),
                comment=c.get("comment"),
                is_partition=c.get("partition_key_index") is not None,
                is_clustering=c.get("name", "") in clustering_set,
            )
            for i, c in enumerate(raw_columns)
        )

        # Extract partition columns
        partition_cols = tuple(c.name for c in columns if c.is_partition)

        return UCTableMetadata(
            full_name=table_name,
            catalog=catalog,
            schema=schema,
            table=table,
            table_type=raw_table.get("table_type", "MANAGED"),
            data_format=raw_table.get("data_source_format", "DELTA"),
            columns=columns,
            column_count=len(columns),
            location=raw_table.get("storage_location"),
            num_files=num_files,
            size_bytes=size_bytes,
            partition_columns=partition_cols if partition_cols else None,
            clustering_columns=clustering_columns,
            row_count=row_count,
            last_modified=parse_timestamp(raw_table.get("updated_at")),
            statistics_freshness=statistics_freshness,
            properties=table_properties,
            owner=raw_table.get("owner"),
            created_at=parse_timestamp(raw_table.get("created_at")),
            created_by=raw_table.get("created_by"),
            updated_at=parse_timestamp(raw_table.get("updated_at")),
            updated_by=raw_table.get("updated_by"),
        )

    async def fetch_table_fingerprint(
        self,
        table_name: str,
        window_days: int = 30,
    ) -> TableFingerprint | None:
        """Generate comprehensive table fingerprint using QueryWorkloadService.

        Uses fast parallel queries + Python-side sqlglot analysis:
        - Simple SQL fetch (~5-10 seconds vs 2-3 minute monolithic query)
        - Accurate query parsing via sqlglot AST
        - Parallel billing data fetch

        Args:
            table_name: Fully qualified table name (catalog.schema.table)
            window_days: Analysis window in days (default 30)

        Returns:
            TableFingerprint with comprehensive analysis, or None if unavailable
        """
        logger.debug(
            "generating_fingerprint",
            table_name=table_name,
            window_days=window_days,
        )

        if not self.workload_service:
            logger.warning(
                "workload_service_not_configured", operation="generate_fingerprint"
            )
            return None

        try:
            # Fetch workload data using efficient parallel queries
            history_df, billing_df = await self.workload_service.fetch_all_data(
                [table_name], window_days, limit=1000
            )

            if history_df.is_empty():
                logger.warning("no_query_history_found", table_name=table_name)
                # Return minimal fingerprint with just metadata
                metadata = await self.fetch_table_metadata(table_name)
                return TableFingerprint(
                    table_name=table_name,
                    window_days=window_days,
                    table_type=metadata.table_type if metadata else None,
                    storage_format=metadata.data_format if metadata else None,
                    storage_path=metadata.location if metadata else None,
                    created=metadata.created_at if metadata else None,
                    last_altered=metadata.updated_at if metadata else None,
                    comment=None,  # UCTableMetadata doesn't expose comment
                    read_metrics=None,
                    write_metrics=None,
                    cost_metrics=None,
                    workload_type="archive",
                    recommended_tier="cold",
                )

            # Analyze workload using Polars + sqlglot
            analysis = self.workload_service.analyze_workload(history_df, billing_df)

            # Build read metrics from analysis
            read_metrics: ReadWorkloadMetrics | None = None
            if analysis.read_query_count > 0:
                # Convert filter columns to tuple of column names
                common_filters = tuple(
                    fc.column_name for fc in analysis.top_filter_columns[:5]
                )
                # Convert aggregations to tuple of function names
                common_aggs = tuple(ap.function for ap in analysis.top_aggregations[:5])

                # Calculate avg/p95 from totals (approximation)
                avg_read_gb = (
                    (analysis.total_read_bytes / 1e9) / analysis.read_query_count
                    if analysis.read_query_count > 0
                    else 0.0
                )

                read_metrics = ReadWorkloadMetrics(
                    query_count=analysis.read_query_count,
                    total_read_gb=analysis.total_read_bytes / 1e9,
                    avg_read_gb=avg_read_gb,
                    p95_read_gb=avg_read_gb * 2.0,  # Estimate
                    total_runtime_sec=analysis.total_read_duration_ms / 1000.0,
                    avg_runtime_sec=(
                        analysis.total_read_duration_ms
                        / 1000.0
                        / analysis.read_query_count
                        if analysis.read_query_count > 0
                        else 0.0
                    ),
                    p95_runtime_sec=(
                        analysis.total_read_duration_ms
                        / 1000.0
                        / analysis.read_query_count
                        * 2.0
                        if analysis.read_query_count > 0
                        else 0.0
                    ),
                    distinct_readers=analysis.distinct_readers,
                    last_read_time=analysis.last_read_time,
                    peak_queries_per_hour=0,  # Would need hourly aggregation
                    common_filters=common_filters,
                    common_aggregations=common_aggs,
                    pct_queries_with_groupby=analysis.pct_queries_with_groupby,
                )

            # Build write metrics from analysis
            write_metrics: WriteWorkloadMetrics | None = None
            if analysis.write_query_count > 0:
                # Determine dominant operation
                op_counts = {
                    "INSERT": analysis.insert_count,
                    "MERGE": analysis.merge_count,
                    "UPDATE": analysis.update_count,
                    "DELETE": analysis.delete_count,
                }
                dominant_op = max(op_counts, key=lambda k: op_counts[k])

                write_metrics = WriteWorkloadMetrics(
                    write_op_count=analysis.write_query_count,
                    merge_op_count=analysis.merge_count,
                    insert_op_count=analysis.insert_count,
                    update_op_count=analysis.update_count,
                    delete_op_count=analysis.delete_count,
                    total_written_gb=analysis.total_written_bytes / 1e9,
                    p95_write_runtime_sec=0.0,  # Would need detailed stats
                    dominant_write_operation=dominant_op,
                )

            # Build cost metrics (from billing data analysis)
            # Note: Would need to join billing with query data for accurate attribution
            cost_metrics: CostMetrics | None = None
            # TODO(BACKLOG-004): Implement billing attribution in workload service

            # Classify workload type
            read_heavy = analysis.read_query_count > analysis.write_query_count * 10
            write_heavy = analysis.write_query_count > analysis.read_query_count * 10

            if read_heavy and analysis.read_query_count > 100:
                workload_type: str = "analytical"
            elif write_heavy:
                workload_type = "operational"
            elif analysis.read_query_count + analysis.write_query_count < 10:
                workload_type = "archive"
            else:
                workload_type = "hybrid"

            # Determine tier
            total_queries = analysis.read_query_count + analysis.write_query_count
            if total_queries == 0:
                tier: str = "cold"
            elif read_heavy or write_heavy:
                tier = "hot"
            else:
                tier = "warm"

            # Get table metadata for structural info
            metadata = await self.fetch_table_metadata(table_name)

            return TableFingerprint(
                table_name=table_name,
                window_days=window_days,
                # Structural metadata from UC API
                table_type=metadata.table_type if metadata else None,
                storage_format=metadata.data_format if metadata else None,
                storage_path=metadata.location if metadata else None,
                created=metadata.created_at if metadata else None,
                last_altered=metadata.updated_at if metadata else None,
                comment=None,  # UCTableMetadata doesn't expose comment
                # Workload metrics from analysis
                read_metrics=read_metrics,
                write_metrics=write_metrics,
                cost_metrics=cost_metrics,
                # Classifications
                workload_type=workload_type,
                recommended_tier=tier,
            )

        except (QueryExecutionError, AdapterError) as e:
            logger.error(
                "error_generating_fingerprint", table_name=table_name, error=str(e)
            )
            return None
