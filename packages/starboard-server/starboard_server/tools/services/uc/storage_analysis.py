"""Storage analysis service for UC Delta history, optimization, costs, and impact.

Handles Delta table history, storage optimization recommendations,
query impact analysis, and cost attribution.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.analyzers import UCAnalyzer
from starboard_core.domain.models.uc import (
    CostBreakdown,
    DeltaHistory,
    DeltaHistoryEntry,
    QueryImpactAnalysis,
    StorageOptimizationReport,
    StorageState,
)

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import UCServiceBase, parse_timestamp
from starboard_server.tools.services.validation import (
    QualifiedTableName,
    validate_limit,
)

if TYPE_CHECKING:
    from starboard_core.domain.models.uc import UCTableMetadata

logger = get_logger(__name__)


class StorageAnalysisService(UCServiceBase):
    """Service for storage analysis: history, optimization, impact, and costs."""

    async def fetch_delta_history(
        self,
        table_name: str,
        limit: int = 50,
    ) -> DeltaHistory | None:
        """Fetch Delta table history.

        Args:
            table_name: Fully qualified table name
            limit: Maximum history entries

        Note:
            Requires SQL provider for DESCRIBE HISTORY query.
        """
        logger.debug("fetching_delta_history", table_name=table_name)
        if not self.sql_provider:
            logger.warning("sql_provider_not_configured", operation="fetch_history")
            return None

        validated_name = QualifiedTableName.from_string(table_name)
        validated_limit = validate_limit(limit)
        query = f"DESCRIBE HISTORY {validated_name.to_sql_identifier()} LIMIT {validated_limit}"
        try:
            rows = await self.sql_provider.execute_query(query)
        except Exception as e:
            logger.error("error_fetching_history", table_name=table_name, error=str(e))
            return None

        if not rows:
            return None

        entries: list[DeltaHistoryEntry] = []
        operations: dict[str, int] = {}
        last_optimize: datetime | None = None
        last_vacuum: datetime | None = None
        schema_changes = current_version = 0

        for row in rows:
            version = row.get("version", 0)
            current_version = max(current_version, version)
            operation = row.get("operation", "UNKNOWN")
            operations[operation] = operations.get(operation, 0) + 1
            timestamp = parse_timestamp(row.get("timestamp"))

            if (
                operation == "OPTIMIZE"
                and timestamp
                and (last_optimize is None or timestamp > last_optimize)
            ):
                last_optimize = timestamp
            if (
                operation == "VACUUM"
                and timestamp
                and (last_vacuum is None or timestamp > last_vacuum)
            ):
                last_vacuum = timestamp

            is_schema_change = (
                "schema" in str(row.get("operationParameters", {})).lower()
            )
            if is_schema_change:
                schema_changes += 1

            entries.append(
                DeltaHistoryEntry(
                    version=version,
                    timestamp=timestamp or datetime.now(),
                    user=row.get("userName", row.get("userId", "unknown")),
                    operation=operation,
                    operation_parameters=row.get("operationParameters"),
                    metrics=row.get("operationMetrics"),
                    is_schema_change=is_schema_change,
                )
            )

        return DeltaHistory(
            table_name=table_name,
            current_version=current_version,
            entries=tuple(entries),
            total_versions=len(entries),
            operations_summary=operations,
            last_optimize=last_optimize,
            last_vacuum=last_vacuum,
            schema_changes_count=schema_changes,
        )

    async def recommend_storage_optimization(
        self,
        table_name: str,
        *,
        _metadata_service: Any = None,
        _governance_service: Any = None,
    ) -> StorageOptimizationReport | None:
        """Generate storage optimization recommendations.

        Args:
            table_name: Fully qualified table name
            _metadata_service: Injected by the UCService facade.
            _governance_service: Injected by the UCService facade.
        """
        logger.debug("generating_storage_recommendations", table_name=table_name)
        if _metadata_service is None:
            logger.error("metadata_service_not_available_for_storage_optimization")
            return None

        metadata: UCTableMetadata | None = await _metadata_service.fetch_table_metadata(
            table_name
        )
        if not metadata:
            return None

        access_patterns = None
        if _governance_service is not None:
            access_patterns = await _governance_service.analyze_access_patterns(
                table_name, window_days=30
            )

        num_files = metadata.num_files or 0
        size_bytes = metadata.size_bytes or 0
        size_gb = size_bytes / 1e9
        avg_file_size_mb = (
            (size_bytes / num_files) / (1024 * 1024) if num_files > 0 else 0.0
        )

        health_status, _ = UCAnalyzer.analyze_storage_health(
            num_files=num_files, total_size_bytes=size_bytes
        )
        history = await self.fetch_delta_history(table_name, limit=100)

        storage_state = StorageState(
            num_files=num_files,
            total_size_gb=size_gb,
            avg_file_size_mb=avg_file_size_mb,
            min_file_size_mb=0.0,
            max_file_size_mb=0.0,
            partition_count=len(metadata.partition_columns)
            if metadata.partition_columns
            else None,
            clustering_columns=metadata.clustering_columns,
            last_optimize=history.last_optimize if history else None,
            last_vacuum=history.last_vacuum if history else None,
            file_size_health=health_status,
            partition_skew=None,
        )

        access_pattern = (
            access_patterns.access_pattern if access_patterns else "unknown"
        )
        recommendations = UCAnalyzer.generate_storage_recommendations(
            storage_state=storage_state,
            access_pattern=access_pattern,
            has_liquid_clustering=bool(metadata.clustering_columns),
        )
        impact = UCAnalyzer.estimate_optimization_impact(
            current_avg_file_size_mb=avg_file_size_mb,
            current_num_files=num_files,
            has_clustering=bool(metadata.clustering_columns),
            workload_type="analytical"
            if access_pattern == "high_read_low_write"
            else "hybrid",
        )

        return StorageOptimizationReport(
            table_name=table_name,
            current_state=storage_state,
            recommendations=tuple(recommendations),
            estimated_impact=impact,
        )

    async def analyze_query_impact(
        self,
        table_names: list[str],
        query_pattern: str | None = None,
        *,
        _metadata_service: Any = None,
    ) -> QueryImpactAnalysis | None:
        """Analyze query performance impact for table joins.

        Args:
            table_names: Tables involved in query
            query_pattern: Optional query pattern hint (aggregation, point_lookup, etc.)
            _metadata_service: Injected by the UCService facade.
        """
        logger.debug("analyzing_query_impact", table_names=table_names)
        if not table_names or _metadata_service is None:
            return None

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_metadata_service.fetch_table_metadata(n))
                for n in table_names
            ]
        table_metadata: list[UCTableMetadata] = [
            t.result() for t in tasks if t.result()
        ]

        if not table_metadata:
            return None

        sizes_gb = [(m.size_bytes or 0) / 1e9 for m in table_metadata]
        row_counts = [m.row_count or 0 for m in table_metadata]

        # Analyze query patterns if workload service available
        join_keys_hist: list[tuple[str, str, str, str, str]] = []
        filter_cols_hist: list[tuple[str, str | None]] = []

        if self.workload_service:
            try:
                history_df, _ = await self.workload_service.fetch_all_data(
                    table_names, window_days=30, limit=500
                )
                if not history_df.is_empty():
                    analysis = self.workload_service.analyze_workload(history_df)
                    join_keys_hist = [
                        (
                            jk.left_table,
                            jk.right_table,
                            jk.left_column,
                            jk.right_column,
                            jk.join_type,
                        )
                        for jk in analysis.top_join_keys
                    ]
                    filter_cols_hist = [
                        (fc.column_name, fc.table_name)
                        for fc in analysis.top_filter_columns
                    ]
            except Exception as e:
                logger.warning("could_not_analyze_query_history", error=str(e))

        # Predict joins (pairwise analysis + historical data)
        join_predictions: list = []
        for i, left_meta in enumerate(table_metadata):
            for right_meta in table_metadata[i + 1 :]:
                prediction = UCAnalyzer.predict_join_behavior(
                    left_table_rows=left_meta.row_count or 0,
                    left_table_size_gb=(left_meta.size_bytes or 0) / 1e9,
                    right_table_rows=right_meta.row_count or 0,
                    right_table_size_gb=(right_meta.size_bytes or 0) / 1e9,
                )
                actual_key = None
                for lt, rt, lc, rc, _ in join_keys_hist:
                    if (left_meta.full_name in lt and right_meta.full_name in rt) or (
                        right_meta.full_name in lt and left_meta.full_name in rt
                    ):
                        actual_key = f"{lc} = {rc}"
                        break
                rec = prediction.recommendation
                if actual_key:
                    rec = f"Join on {actual_key}. {rec or ''}"
                prediction = replace(
                    prediction,
                    left_table=left_meta.full_name,
                    right_table=right_meta.full_name,
                    recommendation=rec,
                )
                join_predictions.append(prediction)

        broadcast_risk, shuffle_risk, skew_risk = UCAnalyzer.detect_query_risks(
            table_sizes_gb=sizes_gb,
            table_row_counts=row_counts,
            query_pattern=query_pattern,
        )

        join_hints: list[str] = []
        if broadcast_risk:
            small = [m.full_name for m, s in zip(table_metadata, sizes_gb) if s < 1.0]
            if small:
                join_hints.append(
                    f"Consider explicit broadcast hint for: {', '.join(small)}"
                )
        if shuffle_risk:
            join_hints.append(
                "Large shuffle expected. Consider pre-bucketing or repartitioning."
            )
        if skew_risk:
            join_hints.append(
                "Data skew detected. Consider salting join keys or skew hints."
            )

        clustering_recs = [
            f"Enable liquid clustering on {m.full_name} for better query performance"
            for m in table_metadata
            if not m.clustering_columns and (m.size_bytes or 0) > 10e9
        ]
        filter_recs = [
            f"Consider partitioning or clustering on '{cn}' {'(' + tn + ')' if tn else ''} - frequently filtered"
            for cn, tn in filter_cols_hist[:5]
        ]
        if query_pattern == "aggregation":
            filter_recs.append(
                "For aggregation queries, consider Z-ORDER on GROUP BY columns"
            )
        elif query_pattern == "point_lookup":
            filter_recs.append("For point lookups, ensure Z-ORDER on lookup columns")

        return QueryImpactAnalysis(
            tables=tuple(m.full_name for m in table_metadata),
            total_rows_estimate=sum(row_counts),
            total_size_gb=sum(sizes_gb),
            join_predictions=tuple(join_predictions),
            broadcast_risk=broadcast_risk,
            shuffle_explosion_risk=shuffle_risk,
            skew_risk=skew_risk,
            join_hints=tuple(join_hints),
            clustering_recommendations=tuple(clustering_recs),
            filter_recommendations=tuple(filter_recs),
        )

    async def attribute_table_costs(
        self,
        table_name: str,
        window_days: int = 30,
        *,
        _metadata_service: Any = None,
    ) -> CostBreakdown | None:
        """Attribute costs to a table using fingerprint and billing data.

        Args:
            table_name: Fully qualified table name
            window_days: Analysis window
            _metadata_service: Injected by the UCService facade.
        """
        logger.debug("attributing_costs", table_name=table_name)
        if _metadata_service is None:
            logger.error("metadata_service_not_available_for_cost_attribution")
            return None

        fingerprint = await _metadata_service.fetch_table_fingerprint(
            table_name, window_days
        )
        if not fingerprint:
            logger.warning(
                "fingerprint_unavailable_for_cost_attribution", table_name=table_name
            )
            return None

        metadata = await _metadata_service.fetch_table_metadata(table_name)
        size_gb = (
            (metadata.size_bytes / 1e9) if metadata and metadata.size_bytes else 0.0
        )
        storage_cost = size_gb * 0.023 * (window_days / 30)

        read_count = (
            fingerprint.read_metrics.query_count if fingerprint.read_metrics else 0
        )
        write_count = (
            fingerprint.write_metrics.write_op_count if fingerprint.write_metrics else 0
        )
        total_dbu = (
            fingerprint.cost_metrics.total_dbus if fingerprint.cost_metrics else 0.0
        )

        total_ops = read_count + write_count
        read_ratio = read_count / total_ops if total_ops > 0 else 1.0
        write_ratio = write_count / total_ops if total_ops > 0 else 0.0

        compute_cost = total_dbu * read_ratio * 0.55
        write_cost = total_dbu * write_ratio * 0.55
        total_cost = storage_cost + compute_cost + write_cost

        cost_trend: str = "stable"
        cost_change_pct = 0.0
        if fingerprint.cost_metrics and window_days > 7:
            expected = fingerprint.cost_metrics.avg_dbus_per_day * window_days
            if expected > 0:
                variance = abs(total_dbu - expected) / expected
                if variance > 0.2:
                    cost_trend, cost_change_pct = "variable", round(variance * 100, 1)

        return CostBreakdown(
            table_name=table_name,
            window_days=window_days,
            storage_cost_usd=round(storage_cost, 2),
            storage_gb=round(size_gb, 2),
            compute_cost_usd=round(compute_cost, 2),
            total_dbu_consumed=round(total_dbu, 2),
            query_count=read_count + write_count,
            write_cost_usd=round(write_cost, 2),
            write_dbu_consumed=round(total_dbu * write_ratio, 2),
            total_cost_usd=round(total_cost, 2),
            cost_per_gb=round(total_cost / max(size_gb, 0.001), 2),
            cost_per_query=round(total_cost / max(read_count + write_count, 1), 4),
            cost_trend=cost_trend,
            cost_change_pct=cost_change_pct,
        )
