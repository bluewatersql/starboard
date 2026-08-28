# Portfolio Readiness — workload-maturity reference

The **Portfolio Readiness** review (`starboard review --domains portfolio-readiness`)
grades a workspace's workloads against a *runtime-observable* maturity model. It
is a public-safe generalization of a use-case lifecycle: instead of tracking a
workload's stage in an external system of record, it infers maturity purely from
signals every workspace already emits.

All money references on this surface are **list-price DBU estimates**, never
finance-grade dollar figures.

## Signals (public `system.*` only)

| Signal | Source | Used for |
|--------|--------|----------|
| Consumption (DBU, list-price estimate) | `system.billing.usage` (via `C-B01`, `C-J01`) | Is the workload at production scale? |
| Run error-rate | `system.lakeflow.*` (via `C-J04`) | Is it reliable enough to be optimized? |
| Owner attribution (`run_as` identity) | `identity_metadata.run_as` (via `C-B01`, `C-J01`) | Is it tracked / governed? |

No CRM or system-of-record fields, no forecast figures, and no cross-account data are used
or required. A workspace missing the optional `system.lakeflow.*` tables degrades
the reliability signal gracefully rather than failing the review.

## Maturity stages

The stages generalize a validate → live lifecycle into four runtime-observable
bands. They are **derived**, not stored; a workload's stage is whatever its
current signals imply.

| Stage | Consumption | Owner | Reliability | Meaning |
|-------|-------------|-------|-------------|---------|
| **Dormant** | none / negligible | — | — | No meaningful consumption in the window. |
| **Pilot** | present, below production scale | — | — | Exploratory or intermittent usage. |
| **Production** | at/above production scale | — | — | Sustained, material consumption. |
| **Optimized** | at/above production scale | attributed | error-rate below the ceiling | Tracked *and* reliable at production scale. |

A workload only reaches **Optimized** when it is simultaneously
production-scale, owned (attributable identity), and reliable. The review
surfaces the specific gap that blocks advancement, each with a concrete
progression action (the suggested fix).

## Thresholds (configurable defaults)

Defaults live as named constants in
`starboard_core.domain.rules.detectors`; they are review knobs, not physical
constants — tune them to a workspace's baseline. No magic numbers are embedded
in the rules themselves.

| Constant | Default | Rationale |
|----------|---------|-----------|
| `PORTFOLIO_PRODUCTION_DBU_THRESHOLD` | `100.0` DBU / window | The pilot → production boundary. A workload sustaining this much DBU (list-price estimate) over the review window is consuming like production rather than like an experiment. |
| `PORTFOLIO_UNTRACKED_MIN_DBU_THRESHOLD` | `50.0` DBU / window | Noise floor for *unattributed* consumption. Below this, untracked spend is not worth a finding; at/above it, unattributed consumption is a real governance gap. |
| `PORTFOLIO_MATURITY_MAX_ERROR_RATE_PCT` | `10.0` % | The reliability ceiling for the Optimized stage. Deliberately stricter than the jobs-domain acute-failure threshold: the Optimized stage requires *sustained* reliability, not merely the absence of an outage. |
| `PORTFOLIO_UNATTRIBUTED_USER_TYPE` | `"Unattributed"` | The consumption query's label for usage with no attributable `run_as` identity. |

## Rules and their progression actions

| Rule | Evidence query | Fires when | Progression action |
|------|----------------|-----------|--------------------|
| `portfolio_untracked_production_consumption` | `C-B01` | A product's consumption is `Unattributed` and at/above the untracked DBU floor | Attribute the workload — set an identity and owner / cost-center tags so it is tracked. |
| `portfolio_unattended_production_job` | `C-J01` | A job is at/above production-scale DBU with a missing/unattributed `run_as` | Assign an explicit owner so the production-scale job is accountable and governable. |
| `portfolio_unreliable_production_workload` | `C-J04` | A job is at/above production-scale DBU with a failure rate at/above the maturity ceiling | Root-cause and stabilize the failures before treating the workload as optimized. |

Findings are ranked by the shared severity × impact / effort scorer and cite the
exact evidence query and triggering row, so every recommendation is traceable to
public consumption/reliability data.
