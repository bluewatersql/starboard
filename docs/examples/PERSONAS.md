# Personas

> ## INTERNAL — Isaac personas (gated path)
>
> **This page describes INTERNAL Isaac flows.** They integrate the **gated
> internal-data ports** and are only reachable inside the internal deployment
> with the internal-context gate open. The gate is **closed by default** — on the
> public path these flows degrade to the public agents and never touch gated
> data. This is the one page that names the gated path; it references ports by
> their public identifier only and exposes **no** internal secrets, endpoints, or
> shortlinks.

The two personas below show how internal teams reach the same Databricks-analysis
kernel through Isaac, enriched by the four gated internal-data ports:
`log_retrieval`, `diagnostic_backend`, `nl_query`, and `fleet_sql` (see
[`starboard.ports.registry.Port`](../reference/CATALOG.md)). Each gated port
**enriches, never replaces** the public path — closing the gate leaves a fully
functional public flow.

---

## Persona 1 — Account team: multi-tenant management

<!-- VALIDATED: 2026-08-29 -->

**Who.** An account executive / account team managing several customer workspaces.

**Goal.** "Show me the workload distribution and cost trends across my Pro-tier
customers."

**Invocation.** Isaac, connected to `starboard-mcp` on the internal network with
the internal-context gate open.

**Flow.**

1. The public `starboard-discovery` agent profiles each customer workspace
   (public `system.*` data only).
2. The public `starboard-finops` agent (`mcp__starboard__analytics_agent`)
   attributes cost per workspace.
3. The gated **`fleet_sql`** port fans the query across accounts; the gated
   **`log_retrieval`** port enriches failing workloads with backend evidence the
   public path cannot see.

**What the user sees.** A cross-account portfolio view: per-customer health
scores, top issues, and cost trends under the **internal cost model** (not
list-price), with upsell/rebalancing recommendations.

**Public vs gated.**

| Public (always) | Gated (internal, gate-open only) |
|-----------------|----------------------------------|
| `starboard-discovery`, `starboard-finops` agents | `fleet_sql`, `log_retrieval` ports |
| Per-workspace health + list-price `$` | Cross-account roll-up + internal cost model |

---

## Persona 2 — Field engineer: pre-sales proof-of-concept

<!-- VALIDATED: 2026-08-29 -->

**Who.** A field engineer / pre-sales architect running a customer POC.

**Goal.** "I'm running a POC across five customer workspaces. What should I
measure, and where are the bottlenecks?"

**Invocation.** Isaac with the internal-context gate open.

**Flow.**

1. The public `starboard-discovery` agent profiles each workspace.
2. The gated **`nl_query`** port answers cross-account sizing questions in natural
   language; the gated **`fleet_sql`** port surfaces multi-workspace bottlenecks;
   the gated **`diagnostic_backend`** port supplies internal RCA evidence for any
   failing workload.

**What the user sees.** A POC measurement plan: baseline profiles, sizing
recommendations, and a ranked bottleneck list — with an internal cost model for
ROI, never exposed to the customer.

**Public vs gated.**

| Public (always) | Gated (internal, gate-open only) |
|-----------------|----------------------------------|
| `starboard-discovery` agent + analysis techniques | `nl_query`, `fleet_sql`, `diagnostic_backend` ports |
| Workload profiles | Internal POC-sizing + RCA evidence |

---

## See also

- [Hero Workflows](HERO_WORKFLOWS.md) — the public flows (no gated path)
- [Validated Examples](VALIDATED_EXAMPLES.md) — the tested registry
- [Capability Catalog](../reference/CATALOG.md)
