# Starboard baseline rules

Baseline guidance injected into agent sessions where Starboard is available
(ships with the plugin; copy into a workspace's `.isaac/rules/` to activate).
Public path only — no internal data or namespaces.

## When to use Starboard

- Use the Starboard skills/helpers for **Databricks workload analysis**: workspace
  discovery, jobs/queries/warehouse review, cost/utilization framing, failure
  diagnosis, and NL→SQL.
- Prefer the **helper CLI over ad-hoc SDK calls**: `python -m starboard_x.<capability>`
  (`discovery`, `warehouse`, `uc`, `sparklog`, `diagnostic`, `review`). Each emits a
  compact JSON envelope (`{ok, domain, command, data|error, meta}`) and standard exit
  codes (`0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error`).
- For a full workspace review, use `starboard review [--domains jobs,sql,warehouse]`;
  for NL→SQL, `starboard genie ask "<question>"`.

## Ground rules

- **Dollar figures are list-price DBU estimates**, not finance-grade — always label
  them as estimates.
- **Single workspace by default.** Analysis targets the resolved workspace; do not
  assume fleet/cross-account scope.
- **Auth by subtraction:** rely on the resolved Databricks credential chain
  (`--profile`/`STARBOARD_WORKSPACE` or ambient); never hard-code hosts or tokens.
- **Read-only advisory:** Starboard analyzes and recommends; it does not modify the
  customer workspace.
- Present findings **highest-priority first** with their evidence (`query_id` + row).
