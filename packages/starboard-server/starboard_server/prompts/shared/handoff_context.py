"""
Shared handoff context components for domain agent prompts.

This module provides reusable components for the [Handoff Context] sections
that all domain agents need to handle agent-to-agent transitions.

The handoff context is injected by DomainAgent._initialize_state() when
an agent is invoked via routing from another agent. The context appears
in the user message as:

    [Handoff Context]
    tables: catalog.schema.table1, catalog.schema.table2
    statement_id: 01948a0b-1ebb-17a4-959c-70dde9c5e3fc
    Previous analysis summary: Query shows full table scan...

Agents should look for this block and use the provided IDs directly
without asking the user for them again.
"""

# =============================================================================
# SHARED HANDOFF COMPONENTS
# =============================================================================

SHARED_HANDOFF_INTRO = """
**CRITICAL:** When routed from another agent, check [Handoff Context] in the user message.
"""

SHARED_RESOURCE_IDS = """
**Resource IDs (use directly without asking user):**
- `statement_id:` / `query_ids:` - Query statement(s) to analyze
- `job_id:` / `job_ids:` - Job(s) to analyze
- `cluster_id:` / `cluster_ids:` - Cluster(s) to analyze
- `warehouse_id:` / `warehouse_ids:` - Warehouse(s) to analyze
- `table_name:` / `tables:` - Table(s) to analyze
- `Previous analysis summary:` - Context from routing agent
- `From previous agent:` - Additional context or summary
"""

SHARED_BEHAVIOR_RULES = """
**Handoff Behavior Rules:**
1. If IDs are provided → Start analysis immediately (do NOT ask user for IDs)
2. Use EXACTLY the provided identifiers - do NOT fabricate different values
3. If multiple IDs provided → Process in PARALLEL where possible
4. Reference previous findings in your analysis to show continuity
"""

SHARED_HANDOFF_EXAMPLE = """
**Example:**
```
[Handoff Context]
tables: cprice_main.core.orders, cprice_main.core.products
statement_id: 01948a0b-1ebb-17a4-959c-70dde9c5e3fc
Previous analysis summary: Query shows full table scan on orders table
```
→ Immediately use the provided IDs; reference previous findings in analysis
"""

# Combined section for easy use
SHARED_HANDOFF_SECTION = f"""{SHARED_HANDOFF_INTRO}
{SHARED_RESOURCE_IDS}
{SHARED_BEHAVIOR_RULES}
{SHARED_HANDOFF_EXAMPLE}"""


def build_handoff_section(domain_extension: str = "") -> str:
    """
    Build complete handoff section with optional domain extension.

    Args:
        domain_extension: Domain-specific handoff guidance to append.
            Should describe domain-specific behavior for received IDs.

    Returns:
        Complete handoff section string ready to embed in a prompt.

    Example:
        >>> UC_EXTENSION = '''
        ... **UC-Specific:**
        ... - When receiving `tables:` → Call get_table_metadata for EACH table (PARALLEL)
        ... '''
        >>> handoff_section = build_handoff_section(UC_EXTENSION)
    """
    base = SHARED_HANDOFF_SECTION
    if domain_extension:
        base += f"\n{domain_extension}"
    return base


# =============================================================================
# DOMAIN-SPECIFIC EXTENSIONS
# =============================================================================
# These can be imported and used with build_handoff_section()

UC_HANDOFF_EXTENSION = """
**UC-Specific:**
- When receiving `tables:` → Call get_table_metadata for EACH table (PARALLEL)
- When receiving `query_ids:` → Cross-reference with table usage patterns
- When receiving `job_ids:` → Cross-reference with table operations
"""

QUERY_HANDOFF_EXTENSION = """
**Query-Specific:**
- When receiving `statement_id:` → Use directly with resolve_query
- When receiving `warehouse_id:` → Note compute context for recommendations
- When receiving `tables:` → Use for get_table_metadata after query analysis
"""

JOB_HANDOFF_EXTENSION = """
**Job-Specific:**
- When receiving `job_id:` → Use directly with resolve_job
- When receiving `cluster_id:` → Cross-reference with job compute config
- When receiving `tables:` → Context for data-related tasks
"""

CLUSTER_HANDOFF_EXTENSION = """
**Cluster-Specific:**
- When receiving `cluster_id:` → Use directly with get_cluster_config
- When receiving `job_id:` → Cross-reference with cluster workload patterns
- For warehouse analysis → Route to warehouse agent
"""

WAREHOUSE_HANDOFF_EXTENSION = """
**Warehouse-Specific:**
- When receiving `warehouse_id:` → Start with portfolio or fingerprint tools
- When receiving `query_ids:` → Cross-reference with warehouse performance
- For fleet-wide analysis → Use get_warehouse_portfolio first
"""

DIAGNOSTIC_HANDOFF_EXTENSION = """
**Diagnostic-Specific:**
- Accepts ALL resource types (most flexible agent)
- When receiving IDs → Skip initial triage and start targeted diagnostics
- When receiving error context → Focus on relevant failure patterns
- May need to route to specialist after initial diagnosis
"""

ANALYTICS_HANDOFF_EXTENSION = """
**Analytics-Specific:**
- When receiving resource IDs → Use in cost/usage queries
- When receiving `warehouse_id:` → Focus on warehouse cost analysis
- When receiving `job_id:` → Focus on job cost attribution
- Use DBUs as primary metric (convert dollars only when requested)
"""
