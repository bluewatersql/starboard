# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Schema operations service for UC schema analysis, drift detection, and diffs.

Handles table schema analysis, schema drift detection over time,
and schema diff generation between versions.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from starboard_core.domain.analyzers import AnomalyThresholds, UCAnalyzer
from starboard_core.domain.models.uc import (
    ColumnDiff,
    SchemaAnalysis,
    SchemaChange,
    SchemaDiff,
    SchemaDriftAnalysis,
)
from starboard_core.domain.transformers import SchemaHistoryTransformer

from starboard_server.exceptions import AdapterError, QueryExecutionError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.services.uc.base import UCServiceBase, parse_timestamp

if TYPE_CHECKING:
    from starboard_core.domain.models.uc import DeltaHistory, UCTableMetadata

logger = get_logger(__name__)

# Shared SQL fragment: normalizes ADD/DROP/REPLACE COLUMNS into uniform JSON
_NORMALIZED_COLUMNS_SQL = """
  to_json(
    CASE
      WHEN operation = 'ADD COLUMNS' THEN
        transform(
          from_json(raw_columns,
            'array<struct<column:struct<name:string,type:string,nullable:boolean,metadata:map<string,string>>>>'),
          c -> named_struct('column', named_struct(
            'name', c.column.name, 'type', c.column.type, 'nullable', c.column.nullable)))
      WHEN operation = 'REPLACE COLUMNS' THEN
        transform(
          from_json(raw_columns,
            'array<struct<name:string,type:string,nullable:boolean,metadata:map<string,string>>>'),
          c -> named_struct('column', named_struct(
            'name', c.name, 'type', c.type, 'nullable', c.nullable)))
      WHEN operation = 'DROP COLUMNS' THEN
        transform(
          from_json(raw_columns, 'array<string>'),
          n -> named_struct('column', named_struct(
            'name', n, 'type', cast(null as string), 'nullable', cast(null as boolean))))
    END
  ) AS schema_json_normalized"""


def _build_schema_changes_query(
    table_name: str,
    where_clause: str,
    order: str = "DESC",
    extra_select: str = "",
) -> str:
    """Build the normalized schema changes SQL query."""
    extra = f",\n    {extra_select}" if extra_select else ""
    return f"""
    WITH history AS (
      SELECT version, timestamp, operation{extra},
        operationParameters['columns'] AS raw_columns
      FROM (DESCRIBE HISTORY {table_name})
      WHERE operation IN ('ADD COLUMNS', 'DROP COLUMNS', 'REPLACE COLUMNS')
        AND {where_clause}
    )
    SELECT version, timestamp, operation{extra},{_NORMALIZED_COLUMNS_SQL}
    FROM history ORDER BY version {order}"""


class SchemaOperationsService(UCServiceBase):
    """Service for schema analysis, drift detection, and diff generation."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.schema_history_transformer = SchemaHistoryTransformer()

    async def analyze_table_schema(
        self,
        table_name: str,
        thresholds: AnomalyThresholds | None = None,
        *,
        _metadata_service: Any = None,
    ) -> SchemaAnalysis | None:
        """Analyze table schema for patterns and anomalies.

        Args:
            table_name: Fully qualified table name
            thresholds: Optional custom thresholds
            _metadata_service: Injected by the UCService facade.
        """
        logger.debug("analyzing_table_schema", table_name=table_name)
        if _metadata_service is None:
            logger.error("metadata_service_not_available_for_schema_analysis")
            return None

        metadata: UCTableMetadata | None = await _metadata_service.fetch_table_metadata(
            table_name
        )
        if not metadata:
            return None

        columns_list = list(metadata.columns)
        anomalies = UCAnalyzer.detect_schema_anomalies(columns_list, thresholds)
        table_type, type_confidence = UCAnalyzer.classify_table_type_heuristic(
            table_name, columns_list
        )
        data_layer, layer_confidence = UCAnalyzer.classify_data_layer_heuristic(
            table_name
        )
        patterns = UCAnalyzer.detect_semantic_patterns(columns_list)
        health = UCAnalyzer.calculate_schema_health(
            column_count=metadata.column_count,
            anomaly_count=len(anomalies),
            has_partitioning=bool(metadata.partition_columns),
            has_clustering=bool(metadata.clustering_columns),
            stats_age_days=None,
        )

        return SchemaAnalysis(
            table_name=table_name,
            column_count=metadata.column_count,
            table_classification=table_type,
            data_layer=data_layer,
            classification_confidence=min(type_confidence, layer_confidence),
            id_columns=tuple(patterns.get("id_columns", [])),
            timestamp_columns=tuple(patterns.get("timestamp_columns", [])),
            partition_columns=metadata.partition_columns or (),
            clustering_columns=metadata.clustering_columns or (),
            anomalies=tuple(anomalies),
            health_score=health,
        )

    async def detect_schema_drift(
        self,
        table_name: str,
        versions_to_analyze: int = 50,
        *,
        _storage_service: Any = None,
    ) -> SchemaDriftAnalysis | None:
        """Detect schema drift over time using DESCRIBE HISTORY.

        Args:
            table_name: Fully qualified table name
            versions_to_analyze: Number of history versions to analyze
            _storage_service: Injected by the UCService facade.
        """
        logger.debug("detecting_schema_drift", table_name=table_name)
        if _storage_service is None:
            logger.error("storage_service_not_available_for_schema_drift")
            return None

        history: DeltaHistory | None = await _storage_service.fetch_delta_history(
            table_name, limit=versions_to_analyze
        )
        if not history:
            return None

        changes: list[SchemaChange] = []
        adds = removes = modifies = type_changes = 0

        if self.sql_provider:
            try:
                query = _build_schema_changes_query(
                    table_name,
                    where_clause=f"1=1 ORDER BY version DESC LIMIT {versions_to_analyze}",
                    order="DESC",
                    extra_select="userName",
                )
                rows = await self.sql_provider.execute_query(query)
                for row in rows:
                    operation = row.get("operation", "")
                    version = row.get("version", 0)
                    timestamp = parse_timestamp(row.get("timestamp"))
                    user = row.get("userName", "")
                    schema_json = row.get("schema_json_normalized")
                    if not schema_json:
                        continue
                    try:
                        parsed = json.loads(schema_json)
                    except json.JSONDecodeError:
                        continue
                    for col_entry in parsed:
                        col_info = col_entry.get("column", {})
                        col_name = col_info.get("name", "unknown")
                        col_type = col_info.get("type")
                        if operation == "ADD COLUMNS":
                            ct, adds = "ADD_COLUMN", adds + 1
                            old_value, new_value = None, col_type
                        elif operation == "DROP COLUMNS":
                            ct, removes = "DROP_COLUMN", removes + 1
                            old_value, new_value = "dropped", None
                        elif operation == "REPLACE COLUMNS":
                            ct, modifies = "MODIFY_COLUMN", modifies + 1
                            old_value, new_value = "replaced", col_type
                        else:
                            ct, old_value, new_value = "UNKNOWN", None, None
                        changes.append(
                            SchemaChange(
                                version=version,
                                timestamp=timestamp or datetime.now(),
                                change_type=ct,
                                column_name=col_name,
                                old_value=old_value,
                                new_value=new_value,
                                user=user,
                            )
                        )
            except (QueryExecutionError, AdapterError) as e:
                logger.warning("error_querying_schema_changes", error=str(e))

        # Transformer fallback if SQL yielded no changes
        if not changes:
            history_dicts = [
                {
                    "version": e.version,
                    "timestamp": e.timestamp.timestamp() * 1000 if e.timestamp else 0,
                    "operation": e.operation,
                    "operationParameters": e.operation_parameters or {},
                    "userName": e.user,
                }
                for e in history.entries
            ]
            for change in self.schema_history_transformer.transform(history_dicts).get(
                "schema_changes", []
            ):
                ct = change.get("change_type", "UNKNOWN")
                if ct == "ADD_COLUMN":
                    adds += 1
                elif ct == "DROP_COLUMN":
                    removes += 1
                elif ct in ("TYPE_CHANGE", "RENAME", "NULLABLE_CHANGE"):
                    modifies += 1
                changes.append(
                    SchemaChange(
                        version=change.get("version", 0),
                        timestamp=datetime.fromisoformat(change["timestamp"])
                        if change.get("timestamp")
                        else datetime.now(),
                        change_type=ct,
                        column_name=change.get("column_name", "unknown"),
                        old_value=change.get("old_value"),
                        new_value=change.get("new_value"),
                        user=change.get("user", ""),
                    )
                )

        total_changes = adds + removes + modifies
        if total_changes == 0:
            severity = "none"
        elif total_changes <= 2:
            severity = "low"
        elif total_changes <= 5:
            severity = "medium"
        else:
            severity = "high"

        return SchemaDriftAnalysis(
            table_name=table_name,
            current_version=history.current_version,
            versions_analyzed=len(history.entries),
            drift_detected=total_changes > 0,
            drift_severity=severity,
            schema_changes=tuple(changes),
            columns_added=adds,
            columns_removed=removes,
            columns_modified=modifies,
            type_changes=type_changes,
            last_stable_version=history.current_version,
            last_stable_date=history.entries[0].timestamp
            if history.entries
            else datetime.now(),
        )

    async def generate_schema_diff(
        self,
        table_name: str,
        version_from: int,
        version_to: int | None = None,
    ) -> SchemaDiff | None:
        """Generate schema diff between versions using DESCRIBE HISTORY.

        Args:
            table_name: Fully qualified table name
            version_from: Starting version
            version_to: Ending version (defaults to current)
        """
        logger.debug(
            "generating_schema_diff",
            table_name=table_name,
            version_from=version_from,
            version_to=version_to,
        )
        if not self.sql_provider:
            logger.warning(
                "sql_provider_not_configured", operation="generate_schema_diff"
            )
            return None

        version_filter = f"version >= {version_from}"
        if version_to is not None:
            version_filter += f" AND version <= {version_to}"

        query = _build_schema_changes_query(table_name, version_filter, order="ASC")

        try:
            rows = await self.sql_provider.execute_query(query)
        except (QueryExecutionError, AdapterError) as e:
            logger.error(
                "error_querying_schema_history", table_name=table_name, error=str(e)
            )
            return None

        added: list[ColumnDiff] = []
        removed: list[ColumnDiff] = []
        modified: list[ColumnDiff] = []
        is_breaking = False
        breaking_reason: str | None = None
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        actual_version_to = version_to or version_from

        for row in rows:
            version = row.get("version", 0)
            actual_version_to = max(actual_version_to, version)
            operation = row.get("operation", "")
            timestamp = parse_timestamp(row.get("timestamp"))
            if timestamp:
                if first_ts is None or timestamp < first_ts:
                    first_ts = timestamp
                if last_ts is None or timestamp > last_ts:
                    last_ts = timestamp

            schema_json = row.get("schema_json_normalized", "[]")
            try:
                columns_data = json.loads(schema_json) if schema_json else []
            except json.JSONDecodeError:
                logger.warning("failed_to_parse_schema_json", version=version)
                continue

            for col_entry in columns_data:
                col = col_entry.get("column", {})
                name, ctype, nullable = (
                    col.get("name", ""),
                    col.get("type"),
                    col.get("nullable"),
                )
                if operation == "ADD COLUMNS":
                    added.append(
                        ColumnDiff(
                            column_name=name,
                            change_type="added",
                            new_type=ctype,
                            new_nullable=nullable,
                        )
                    )
                    if nullable is False:
                        is_breaking, breaking_reason = (
                            True,
                            f"Added non-nullable column: {name}",
                        )
                elif operation == "DROP COLUMNS":
                    removed.append(
                        ColumnDiff(
                            column_name=name,
                            change_type="removed",
                            old_type=None,
                            old_nullable=None,
                        )
                    )
                    is_breaking, breaking_reason = True, f"Dropped column: {name}"
                elif operation == "REPLACE COLUMNS":
                    modified.append(
                        ColumnDiff(
                            column_name=name,
                            change_type="modified",
                            new_type=ctype,
                            new_nullable=nullable,
                        )
                    )
                    is_breaking, breaking_reason = (
                        True,
                        "Schema replaced (REPLACE COLUMNS)",
                    )

        return SchemaDiff(
            table_name=table_name,
            version_from=version_from,
            version_to=actual_version_to,
            timestamp_from=first_ts,
            timestamp_to=last_ts,
            columns_added=tuple(added),
            columns_removed=tuple(removed),
            columns_modified=tuple(modified),
            is_breaking_change=is_breaking,
            breaking_reason=breaking_reason,
            migration_sql=self._generate_migration_hints(added, removed, modified),
        )

    def _generate_migration_hints(
        self,
        added: list[ColumnDiff],
        removed: list[ColumnDiff],
        modified: list[ColumnDiff],
    ) -> str | None:
        """Generate SQL hints for migrating downstream consumers."""
        hints: list[str] = []
        if removed:
            hints.append(
                f"-- Dropped columns (update queries): {', '.join(c.column_name for c in removed)}"
            )
        for col in added:
            nullable = "NULL" if col.new_nullable else "NOT NULL"
            hints.append(
                f"-- New column: {col.column_name} {col.new_type or 'TYPE'} {nullable}"
            )
        if modified:
            hints.append(
                "-- Schema replaced - verify all column types match expectations"
            )
        return "\n".join(hints) if hints else None
