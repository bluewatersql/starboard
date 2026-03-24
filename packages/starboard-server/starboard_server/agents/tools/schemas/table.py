"""Table metadata and lineage tool schemas (UC/Unity Catalog domain)."""

LIST_UC_ASSETS = {
    "name": "list_uc_assets",
    "description": (
        "List Unity Catalog assets: catalogs, schemas, tables, volumes, functions.\n"
        "Use to explore catalog structure and discover available objects.\n"
        "Returns: List of assets with name, owner, creation time.\n"
        "Cost: ~300 tokens | Prerequisites: None (catalogs), catalog (schemas), catalog+schema (tables)\n"
        "⚡ Parallel-safe: Call for different scopes in ONE turn (executes in parallel)\n"
        "→ Next: get_table_metadata (for specific table details)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "catalog": {
                "type": "string",
                "description": "Catalog name (required for schemas/tables/volumes/functions)",
            },
            "schema": {
                "type": "string",
                "description": "Schema name (required for tables/volumes/functions)",
            },
            "asset_type": {
                "type": "string",
                "description": "Type of assets to list",
                "enum": ["catalogs", "schemas", "tables", "volumes", "functions"],
                "default": "tables",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of assets to return (default: 100)",
                "default": 100,
            },
        },
        "required": [],
    },
}

GET_TABLE_METADATA = {
    "name": "get_table_metadata",
    "description": (
        "Get table metadata: columns, row count, size, partitioning, statistics.\n"
        "Returns: Schema, stats, partitioning scheme.\n"
        "Cost: ~500 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call multiple times for different tables in ONE turn (executes in parallel)\n"
        "→ Next: analyze_query_plan | Why important: Stats validate optimization opportunities"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified: catalog.schema.table or schema.table",
            }
        },
        "required": ["table_name"],
    },
}

GET_TABLE_HISTORY = {
    "name": "get_table_history",
    "description": (
        "Get Delta table history: recent operations, timestamps, versions.\n"
        "Cost: ~300 tokens | Prerequisites: Delta table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn (executes in parallel)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified Delta table",
            },
            "limit": {"type": "integer", "description": "Max entries (default: 10)"},
        },
        "required": ["table_name"],
    },
}

DISCOVER_TABLES = {
    "name": "discover_tables",
    "description": (
        "Extract table references from SQL queries or source code (PySpark, Scala, notebooks).\n"
        "Identifies: catalogs, schemas, tables, temp tables, CTEs.\n"
        "Works with both raw SQL and code patterns like spark.table(), spark.read.table().\n"
        "Returns: List of tables with source/target distinction.\n"
        "Cost: ~300-500 tokens | Prerequisites: SQL text or source code\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn (executes in parallel)\n"
        "→ Next: get_table_metadata (for each table)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_text": {
                "type": "string",
                "description": "SQL query or source code (Python/Scala/notebook) to analyze for table references",
            },
        },
        "required": ["source_text"],
    },
}

GET_TABLE_LINEAGE = {
    "name": "get_table_lineage",
    "description": (
        "Get upstream/downstream table dependencies for impact analysis.\n"
        "Returns: Source tables feeding this table, consumers depending on it.\n"
        "Cost: ~400 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn (executes in parallel)\n"
        "→ Use for: Schema change impact, data quality tracing"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name",
            },
        },
        "required": ["table_name"],
    },
}

GET_ENRICHED_TABLE_METADATA = {
    "name": "get_enriched_table_metadata",
    "description": (
        "Get enriched metadata for multiple tables with detailed schemas, properties, Delta history.\n"
        "Returns: Complete metadata for all tables.\n"
        "Cost: ~800-1200 tokens | Prerequisites: Table references from discover_tables\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn (executes in parallel)\n"
        "→ Next: analyze_query_plan (with context)"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_references": {
                "type": "array",
                "description": "Array of table objects from discover_tables",
                "items": {"type": "object"},
            },
        },
        "required": [],
    },
}

# =============================================================================
# Phase 1 Tools: Core UC Analysis
# =============================================================================

GET_TABLE_GRANTS = {
    "name": "get_table_grants",
    "description": (
        "Get table access grants and effective permissions.\n"
        "Returns: Owner, direct grants, inherited grants, effective permissions.\n"
        "Cost: ~400 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Access control audit, permission troubleshooting"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
        },
        "required": ["table_name"],
    },
}

ANALYZE_TABLE_SCHEMA = {
    "name": "analyze_table_schema",
    "description": (
        "Analyze table schema for patterns, classification, and anomalies.\n"
        "Returns: Table classification (fact/dimension), data layer (bronze/silver/gold),\n"
        "health score, detected patterns (id/timestamp columns), anomalies.\n"
        "Cost: ~500 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Schema quality assessment, table classification"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
        },
        "required": ["table_name"],
    },
}

ANALYZE_ACCESS_PATTERNS = {
    "name": "analyze_access_patterns",
    "description": (
        "Analyze table access patterns from system tables.\n"
        "Returns: Read/write profiles, access pattern classification,\n"
        "top readers, daily trend data.\n"
        "Cost: ~600 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Usage analysis, identifying hot/cold tables"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
            "window_days": {
                "type": "integer",
                "description": "Days to analyze (default: 30)",
                "default": 30,
            },
        },
        "required": ["table_name"],
    },
}

ANALYZE_SCHEMA_DRIFT = {
    "name": "analyze_schema_drift",
    "description": (
        "Analyze schema drift over time for Delta tables.\n"
        "Returns: Drift severity, schema changes (adds/removes/modifications),\n"
        "last stable version.\n"
        "Cost: ~500 tokens | Prerequisites: Delta table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Schema evolution tracking, breaking change detection"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified Delta table name",
            },
            "versions_to_analyze": {
                "type": "integer",
                "description": "Number of versions to analyze (default: 50)",
                "default": 50,
            },
        },
        "required": ["table_name"],
    },
}

# =============================================================================
# Phase 2 Tools: Advanced UC Analysis
# =============================================================================

ANALYZE_STORAGE_OPTIMIZATION = {
    "name": "analyze_storage_optimization",
    "description": (
        "Analyze storage and generate optimization recommendations for a table.\n"
        "Returns: Current storage state, prioritized recommendations\n"
        "(OPTIMIZE, VACUUM, clustering, partitioning), estimated impact.\n"
        "Cost: ~700 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Storage tuning, performance optimization"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
        },
        "required": ["table_name"],
    },
}

ANALYZE_QUERY_IMPACT = {
    "name": "analyze_query_impact",
    "description": (
        "Analyze query performance impact for table joins.\n"
        "Returns: Join predictions, shuffle estimates, risk levels,\n"
        "join hints and optimization recommendations.\n"
        "Cost: ~600 tokens | Prerequisites: Table names\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn\n"
        "→ Use for: Query planning, join optimization"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of fully qualified table names involved in query",
            },
            "query_pattern": {
                "type": "string",
                "description": "Query pattern hint: join, aggregate, filter, full_scan",
                "enum": ["join", "aggregate", "filter", "full_scan"],
            },
        },
        "required": ["table_names"],
    },
}

GET_TABLE_FINGERPRINT = {
    "name": "get_table_fingerprint",
    "description": (
        "Get comprehensive table fingerprint from system tables.\n"
        "Returns: Metadata, read/write workload metrics, cost attribution,\n"
        "workload classification and tier recommendation.\n"
        "Cost: ~800 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Table profiling, workload analysis, cost tracking"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days (default: 30)",
                "default": 30,
            },
        },
        "required": ["table_name"],
    },
}

ANALYZE_TABLE_COSTS = {
    "name": "analyze_table_costs",
    "description": (
        "Analyze and attribute storage and compute costs to a table.\n"
        "Returns: Storage costs, compute costs (read/write), total cost,\n"
        "cost per GB, cost per query, cost trend.\n"
        "Cost: ~600 tokens | Prerequisites: Table name\n"
        "⚡ Parallel-safe: Call for multiple tables in ONE turn\n"
        "→ Use for: Cost attribution, chargeback, optimization ROI"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified table name (catalog.schema.table)",
            },
            "window_days": {
                "type": "integer",
                "description": "Analysis window in days (default: 30)",
                "default": 30,
            },
        },
        "required": ["table_name"],
    },
}

GENERATE_SCHEMA_DIFF = {
    "name": "generate_schema_diff",
    "description": (
        "Generate schema diff between Delta table versions.\n"
        "Returns: Version range, columns added/removed/modified,\n"
        "breaking change detection, migration SQL.\n"
        "Cost: ~500 tokens | Prerequisites: Delta table name, version\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn\n"
        "→ Use for: Schema migration planning, version comparison"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Fully qualified Delta table name",
            },
            "version_from": {
                "type": "integer",
                "description": "Starting version number",
            },
            "version_to": {
                "type": "integer",
                "description": "Ending version (defaults to current)",
            },
        },
        "required": ["table_name", "version_from"],
    },
}

ANALYZE_POLICY_COVERAGE = {
    "name": "analyze_policy_coverage",
    "description": (
        "Analyze security policy coverage across UC assets.\n"
        "Returns: Coverage percentages (ownership, access control, data protection),\n"
        "policy gaps, security score.\n"
        "Cost: ~700 tokens | Prerequisites: Scope (catalog/schema/table)\n"
        "⚡ Parallel-safe: Can call with other tools in ONE turn\n"
        "→ Use for: Security audit, governance compliance"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "Analysis scope: catalog, schema, or table",
                "enum": ["catalog", "schema", "table"],
                "default": "catalog",
            },
            "catalog": {
                "type": "string",
                "description": "Catalog name (required for schema/table scope)",
            },
            "schema": {
                "type": "string",
                "description": "Schema name (required for table scope)",
            },
        },
        "required": [],
    },
}
