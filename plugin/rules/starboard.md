# Starboard Rules — Index

Baseline guidance injected into agent sessions where Starboard is available.
Copy this directory into `.isaac/rules/` (or `{project}/.isaac/rules/`) to activate.

Public path only — no internal data or namespaces. Dollar figures are
**list-price DBU estimates** — always label them as such.

## Per-domain rulesets

Each domain has its own ruleset with MCP path, CLI fallback, heuristics, and
success criteria derived from the canonical skills tree:

- [`starboard-cluster.md`](starboard-cluster.md) — starboard-cluster rules
- [`starboard-discovery.md`](starboard-discovery.md) — starboard-discovery rules
- [`starboard-jobs.md`](starboard-jobs.md) — starboard-job rules
- [`starboard-sql.md`](starboard-sql.md) — starboard-query rules
- [`starboard-uc.md`](starboard-uc.md) — starboard-uc rules
- [`starboard-warehouse.md`](starboard-warehouse.md) — starboard-warehouse rules

## Quick-start rules (all domains)

- Use `mcp__starboard__*` tools when available; fall back to
  `python -m starboard_x.<capability>` then `starboard-helper`.
- Prefer the **helper CLI over ad-hoc SDK calls** — each emits a compact
  JSON envelope (`{ok, domain, command, data|error, meta}`) and standard exit codes
  (`0` ok · `1` auth · `2` not-found · `3` api-error · `4` arg-error).
- **Auth by subtraction**: rely on the resolved Databricks credential chain
  (`--profile` / `STARBOARD_WORKSPACE` or ambient); never hard-code hosts or tokens.
- **Read-only advisory**: Starboard analyzes and recommends; it does not modify the workspace.
- Present findings **highest-priority first** with their evidence (`query_id` + row).

## Full workspace review

```bash
starboard review [--domains jobs,sql,warehouse]   # multi-domain review
starboard genie ask "<question>"                  # NL→SQL
```

## Content-model schema

See [`README.md`](README.md) for the ruleset content-model schema and
regeneration instructions.
