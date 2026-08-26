# Starboard — Optimize & Simplify: Open Questions

> Unresolved questions surfaced during the envisioning study.

## Data-source / pack questions
1. **Preview-schema stability** — many gap tables (`predictive_optimization_operations_history`,
   `data_quality_monitoring.table_results`, `data_classification.results`, `instance_events`,
   `assistant_events`, `alert.*`) are Preview/Beta. Which are stable enough to build packs against
   now vs. gate behind availability checks?
2. **`monitoring` / `delta_sharing` / `workflow` packs** — these `pack_id`s exist
   (`query_performance.py`, `product_surfaces.py`) but the `monitoring` pack does not query
   `system.data_quality_monitoring.*`. What was the original intent — placeholder, or querying a
   different surface (Lakehouse Monitoring output tables in user catalogs)?
3. **Region/cloud availability** — do all target system tables exist across AWS/Azure/GCP and all
   regions? Packs assume presence; some Preview tables are region-gated.
4. **Query-history freshness** — is `system.query.history` latency acceptable, or should a REST
   Query History API adapter provide sub-minute freshness for live triage?

## Internal-integration questions
5. **dbr-doctor governance** — `run_workflow` writes Delta tables to `main.eng_dp_debug_tools`. Is
   that acceptable side-effecting from Starboard? Quota/cost/cleanup ownership?
6. **logs-summariser scope** — the ≤2h window and `kube_context` requirement: how does Starboard
   obtain the correct `kube_context` from a customer workspace/cluster id automatically?
7. **LogFood access model** — `--profile=logfood`, VPN, and schema churn (`gtm_data` deprecated
   2/2026). Is LogFood integration intended for FE-operated analysis only, or embeddable in a
   customer-facing deployment (likely not)? Which deployments get which backends?
8. **Fleet mode trust boundary** — cross-account `centralized_system_tables` crosses customer trust
   boundaries and depends on `users.tanner_wendland.account_workspace_mappings` (a personal-schema
   mapping). Where should a production mapping live, and what auth/governance gates apply?
9. **Genie room selection** — how to deterministically map a Starboard question domain to the right
   curated Genie room, and handle rate limits (5/min), 120s timeouts, 5k-row caps?
10. **Isaac extension model** — what is Isaac's actual skill/agent extension API and packaging
    format? (Requires internal research via Glean; not verifiable from this repo.)

## Auth / multi-workspace questions
11. Multi-workspace auth is env-var only (no OAuth2/token refresh per brief). Does fleet mode (I4)
    require a real credential-vending story first?
12. Server-side auth `validate_session()` is a no-op assuming Databricks Apps reverse-proxy. Do any
    new integrations (logs-summariser, dbr-doctor) break that assumption when run outside Apps?

## Simplification questions
13. **MCP `tool_scope`** — RESOLVED: implemented as `phase_a`/`phase_b`/`full` (`mcp/config.py:104`
    default `phase_b`; `tool_bridge.py:117-151`; `server.py:353`). Remaining question is a product
    decision: what should the default scope be, and should scope be per-client/per-workspace? Also
    confirm the other `changes/mcp_claude/` gaps (progress notifications for long agent tools,
    ToolRegistry/AgentFactory wiring) against current `server.py`.
14. **Skills layout** — the brief's second directory `packages/starboard/starboard/skills/` is
    absent in the current tree (only `starboard-skills/skills/starboard/*` remains), so the
    duplication seems resolved. Confirm no build step re-copies skills, and confirm whether a
    `starboard-workspace` skill dir should exist (a `starboard-workspace` skill is registered in the
    environment but no matching dir is present under the skills package).
15. **pandas vs polars** — how deep is pandas usage? Is matplotlib load-bearing (chart_renderer) or
    replaceable by a lighter/server-side renderer?
16. **Caching correctness** — for discovery caching (S4), what staleness is acceptable per table
    class, and how to invalidate on lookback/param changes without masking fresh incidents?

## Product / scope questions
17. Which persona is primary — Databricks FE/internal (favors dbr-doctor/LogFood/fleet) vs external
    customer/OSS (favors pack gaps + Lakeview publish)? This reorders the roadmap.
18. Should Starboard *publish* findings (Lakeview dashboards, alerts) or stay read-only analysis?
    Publishing expands value but adds write-path risk and governance.
