# Starboard — the new agent-centric build

*Internal share · updated 2026-09-17*

## TL;DR

Starboard now ships as a **skills-only Claude Code / Isaac plugin**. Install it from GitHub in two
lines and just talk to Isaac — every skill runs read-only against a live Databricks workspace using
the credentials you already have. **No server, no LLM keys, nothing to set up**: the skills pull in
whatever they need on first use, and under Isaac your Databricks auth is already there.

The headline is the **engagement workflow**: instead of a one-shot "analyze this," Starboard runs a
composable, verify-before-present flow that turns raw findings into a customer-ready action plan and
delivers it — a Doc, a deck, a Slack message — every number cited to its source.

---

## What's in the build

**Domain skills** — focused, single-domain reviews you can call directly or let Isaac route to:
discovery (workspace map), finops (cost & DBU drivers), workload-review (ranked findings across
jobs / queries / warehouses), query, job, warehouse, cluster, unity-catalog, and diagnostic
(failure root-cause).

**Engagement workflow** — the agent-centric layer composed on top:

- **engagement** — the shared flow: *gather → scope → verify → present → synthesize → review →
  humanize → deliver*, with doc/slide templates so the output reads like a Solutions Architect
  wrote it, not an agent dump.
- **action-plan** — turns findings into a **verified, ranked** plan (impact ÷ effort across cost and
  performance), checking the top candidates live before it shows you anything.
- **deliver** — publishes the finished plan where you want it (Google Doc, Slides, Slack, Jira),
  rendered native to the destination.

**Two audiences, one product.** External users get the full experience over public data channels
only. Databricks employees can add an **internal overlay** that lights up internal tools —
dbr-doctor, logs-summariser, LogFood, Salesforce/UCO — and Starboard weaves them in automatically
for deeper root-cause and account context when they're present. Nothing internal ever ships in the
public build. `$` figures are **list-price DBU estimates**, always labeled.

---

## Install

In Isaac / Claude Code:

```
/plugin marketplace add databricks-field-eng/starboard
/plugin install starboard@starboard-marketplace
```

**Databricks employees — add the internal overlay** (optional, field-eng only) to light up the
internal tools above:

```
/plugin install starboard-internal@starboard-marketplace
```

That's it. Under Isaac your Databricks credentials are already wired; there's nothing else to
configure.

---

## Try it (talk to Isaac in plain language)

These run as-is against `e2-demo-field-eng`, our shared FE demo workspace — copy one and go.

**Map a workspace**
> Discover and map the e2-demo-field-eng workspace — jobs, clusters, warehouses, and Unity Catalog.
> Give me a health snapshot with customer 360 context.

**Find the money**
> Analyze the last 30 days — top DBU drivers and the biggest optimization opportunities for the
> primary workspace in e2-demo-field-eng.

**Findings → a plan you'd actually send**
> Build a cost + performance action plan for e2-demo-field-eng: rank by impact vs. effort, verify the
> top candidates live, and show me the shortlist before building anything.

**Deliver it**
> Turn that into a Google Doc plus a short deck I can share with the customer.

**Debug a failure**
> A job is failing in e2-demo-field-eng — triage the exit code, pull the error evidence, and give me
> the root cause with remediation steps.

**Track it over time**
> Schedule a monthly workload review of e2-demo-field-eng and, each run, compare against last month —
> what's newly expensive, what improved, and what regressed.

*The domain skills also trigger implicitly — "why is my query slow?", "why is this warehouse so
expensive?" each route natively.*

---

## What good looks like

A recent run against a live field-eng workspace mapped it end to end, found that the real spend lived
in serverless AI (Vector Search, Model Serving, Lakebase) rather than jobs or SQL, corrected a couple
of its own first-pass numbers during the live verify step, ranked the opportunities by impact ÷ effort,
and delivered an exec-summary Doc, a branded deck, and self-validating notebooks. That's the shape to
try.

---

*Questions / feedback → `#starboard` on Slack. Repo: `databricks-field-eng/starboard`.*
