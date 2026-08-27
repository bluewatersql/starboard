---
title: "Package: starboard-internal"
description: The gated internal port adapters package (internal-index-only) — described at the seam only.
last_reviewed: 2026-08-27
status: current
---

# starboard-internal

> **Docs** > **Packages** > **starboard-internal**

The **gated internal port adapters** package (import package `starboard_internal`). This
page documents the **seam**, not internal contents — Starboard's governance red-line is
that public docs never name internal namespaces, hosts, or capabilities.

---

## What it is

`starboard-internal` is a **separately-distributed, internal-index-only** wheel. It is
deliberately **not** a dependency of any public wheel (`starboard`, `starboard-core`,
`starboard-skills`) and **is never published to a public index** — `pip install
starboard` from a public index never pulls it.

It exists to satisfy the **internal-data enablement gate**: the public packages ship the
data-access **ports** (`starboard_core.ports`) plus **public adapters** and the
`starboard.port_adapters` entry-point **contract**; `starboard-internal` provides the
gated adapters that back those ports when an operator explicitly enables them.

## How it plugs in

It registers one provider per gated port under the public entry-point group
(`packages/starboard-internal/pyproject.toml`):

```toml
[project.entry-points."starboard.port_adapters"]
log_retrieval      = "starboard_internal.adapters:log_retrieval_provider"
diagnostic_backend = "starboard_internal.adapters:diagnostic_backend_provider"
fleet_sql          = "starboard_internal.adapters:fleet_sql_provider"
nl_query           = "starboard_internal.adapters:nl_query_provider"
```

At runtime, `starboard.ports.discovery` loads these providers and lets an internal-tier
provider **supersede the public adapter only when the enablement gate is open**. The gate
is `internal_context_host_allowlist` (config), which defaults to **empty = closed**. Each
registered adapter is a stub/injected-backend factory that **raises unless a live client
is wired** at deploy time (open item O1).

## Enforced boundary

An import-linter contract (root `pyproject.toml`, `make test-architecture`) forbids the
public packages from importing `starboard_internal.*`:

> **Public packages import no `starboard_internal`** — the dependency edge only ever
> flows `internal -> public`, never the reverse.

## What this means for docs

- Public documentation describes the **ports + gate + entry-point contract** only.
- Internal adapter contents, namespaces, hosts, and finance-grade `$` are **out of
  bounds** for public docs — they live behind the gate.
- With the gate closed (the default) and this package absent, every public capability
  keeps working unchanged.

---

## Related documentation

- [Package Integration](../../integration/PACKAGE_INTEGRATION.md) — the two entry-point seams
- [System Architecture → Ports + Internal-Data Gate](../../architecture/SYSTEM_ARCHITECTURE.md#ports-internal-data-enablement-gate)
- [starboard-core](../starboard-core/index.md) — the ports live in the kernel
