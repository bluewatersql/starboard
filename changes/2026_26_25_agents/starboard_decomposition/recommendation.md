# Starboard Decomposition — Recommendation

> Ranked recommendation for **how to decompose & package** Starboard into individually
> consumable units, with sequencing and a proposed target catalog. Evidence in
> `opportunities.md`; manifests in `technical.md`.

---

## 1. Headline recommendation

Adopt a **"layered catalog" model**: keep the uv monorepo, but re-cut it into **many thin,
independently-versioned distributables organized in three tiers**, and publish an **umbrella
Claude Code plugin marketplace** so the same capability is consumable as lib / CLI / skill /
plugin / MCP tool / subagent without duplicating source.

```
Tier 0  starboard-kernel      pure, dependency-light math + DTOs   (lib only)
Tier 1  capability packages   one per atomic unit                  (lib + CLI + MCP tool)
Tier 2  experience packages   agents, skills, plugins, MCP server  (compose Tier 0/1)
        starboard (meta)      back-compat umbrella (installs all)
```

**Why not the alternatives:**

| Option | Verdict | Reason |
|---|---|---|
| Keep 3 packages, do nothing | ✗ | Can't consume the exit-code triager without fastapi+postgres+redis (`packages/starboard/pyproject.toml:8-84`) |
| Explode into N standalone repos | ✗ | Loses the shared DTO/prompt contracts; multiplies CI; the analyzers depend on shared models (`core/domain/models`) |
| Monorepo + many thin wheels (**recommended**) | ✓ | Preserves one source of truth + golden tests, enables independent install/version, matches existing uv workspace (`pyproject.toml:tool.uv.workspace`) |
| Plugin marketplace **on top** of the wheels | ✓ | Gives Claude Code / Isaac users one-command install; wheels back the skills' non-MCP path |

## 2. The single most important fix first: **collapse the skill duplication**

This is the highest-ROI, lowest-risk move and unblocks everything else.

**Evidence of the problem:** `skills/starboard/*/SKILL.md` (10 skills, uppercase, bare
`name:`/`description:` metadata with **no `---` fence**) vs
`packages/starboard-skills/skills/starboard/*/skill.md` (9 skills, lowercase filename,
open with `# Starboard: …` and **no frontmatter at all**). `diff -rq` confirms different
filenames and different content — two divergent, partly-invalid sources of truth.

**Fix:** one canonical `skills/` directory of valid `SKILL.md` files (fenced YAML frontmatter),
consumed by (a) the plugin, and (b) packaged into the pip wheel via build config — never copied
by hand. See `technical.md §4`.

## 3. Ranked sequencing (what to extract first)

Ordered by **(value ÷ LOE) × independence**. Each step is shippable on its own.

| Rank | Move | Units | Why now | LOE |
|---|---|---|---|---|
| **1** | **De-dup + fence skills**; add a build step that vendors `skills/` into the wheel | R5, all skills | Removes drift; makes skills actually discoverable; no code risk | S |
| **2** | **Carve `starboard-kernel`** (pure DTOs + analyzers, only pydantic/polars) out of `starboard-core` | P2,P3,P15,P16 + P5,P9,P13 | Establishes the dependency-light nucleus every other unit imports | M |
| **3** | **Extract `starboard-sparklog`** as a standalone product (parse + loaders as extras) | P1,P7 | Highest external reuse; already a self-contained hexagon | L |
| **4** | **Extract `starboard-charts`** (Vega-Lite→image) | P4 | Zero Databricks coupling; instant standalone demo | S |
| **5** | **Ship 4 "primitive" CLIs+MCP tools**: exit-code-triager, query-profile-extractor, sql-validator, dataframe-profiler | P5,P6,P9,P13 | Tiny, deterministic, demo-friendly; proves the per-unit surface pattern | M |
| **6** | **Extract `starboard-discovery`** = query-packs (data) + heuristics + engine (`data_only` CLI) | P10,P11,L10 | Reusable SQL asset; deterministic path needs no LLM | L |
| **7** | **Isolate `starboard-databricks` fetchers** behind an I/O port package | A1,A2,A5 | Concentrates the SDK/auth boundary; lets pure units stay clean | L |
| **8** | **Package agents as subagent+skill pairs** + fix discovery MCP exclusion (`agent_bridge.py:63`) | L1-L9 | Turns each domain agent into an installable experience | L |
| **9** | **Refactor MCP server to compose per-capability bundles** using existing `tool_scope` | R3 | `server.py:352` already scope-filters; formalize into named bundles | L |
| **10** | **Publish the marketplace + meta plugin** | R2,R3 + all skills | The recombination layer; one-command install | M |

Steps 1-5 are a coherent **Phase 1** (a quarter): de-risk, prove the pattern, ship 2 genuinely
standalone products (sparklog, charts) + 4 primitives. Steps 6-10 are **Phase 2**.

## 4. Consumption-surface policy (which unit gets which surface)

A decision rule, not a per-unit list:

| Nature | Lib | CLI | MCP tool | Skill | Subagent | Plugin |
|---|---|---|---|---|---|---|
| Pure primitive (P5,P6,P9,P13) | ✓ always | ✓ | ✓ | only if user-facing verb | ✗ | via bundle |
| Pure product (P1,P4,P10) | ✓ | ✓ | ✓ | ✓ (wraps CLI) | ✗ | ✓ standalone |
| Pure analyzer needing DTO (P2,P3,P12) | ✓ | rarely | ✓ | ✗ | ✗ | via bundle |
| I/O fetcher (A1-A4) | ✓ | rarely | ✓ | ✗ | ✗ | via bundle |
| LLM agent (L1-L8) | (runtime dep) | ✗ | `*_agent` tool | ✓ | ✓ | ✓ |
| Orchestrator (L9,L10,R2) | ✓ | ✓ (data_only) | ✓ | ✓ meta-skill | ✓ router | ✓ meta |

**Principle:** *every pure unit is a lib + MCP tool; it earns a CLI when it has a standalone verb,
and a skill/subagent only when an LLM adds value.* LLM units never ship as bare CLIs — they ship
as skills/subagents that call the libs.

## 5. Proposed target catalog of consumable units

### Tier 0 — kernel (1 package)
- **`starboard-kernel`** — DTOs, transformers, prompt templates, and the pure analyzers
  (warehouse, uc, exit-code, sql-validate, dataframe-profile). Deps: `pydantic`, `polars` only.

### Tier 1 — capability packages (independently versioned wheels, each with a CLI + MCP tool)
| Package | Units | Extra deps |
|---|---|---|
| `starboard-sparklog` | P1, P7 | loaders as extras (`[s3]`,`[dbfs]`,`[https]`) |
| `starboard-charts` | P4 | `altair`, `vl-convert-python` |
| `starboard-diagnostics` | P5, P6, P8 (+P7 re-export) | kernel |
| `starboard-discovery` | P10, P11, L10 | kernel; LLM as extra |
| `starboard-databricks` | A1-A4, A5 | `databricks-sdk`, `databricks-sql-connector` |
| `starboard-warehouse` | P2, A3 | kernel + databricks |
| `starboard-uc` | P3, A1(uc) | kernel + databricks |

### Tier 2 — experiences
| Package / artifact | Contents |
|---|---|
| `starboard-agents` | R1 runtime + L1-L9 agents (each also exported as a subagent `.md`) |
| `starboard-mcp` | The FastMCP surface (R3), now composing Tier-1 MCP tools via named bundles |
| `starboard-cli` | Umbrella CLI dispatching to Tier-1 CLIs (replaces R4 + R5) |
| **skills** (canonical `skills/`) | 10 valid `SKILL.md` skills, vendored into wheels + the plugin |
| **`starboard` (meta plugin + wheel)** | Marketplace entry that pulls in agents + skills + MCP server + service-catalog router (P14) |

### Marketplace
- **`starboard-marketplace`** — `.claude-plugin/marketplace.json` listing: the meta `starboard`
  plugin, plus optional single-domain plugins (e.g. `starboard-diagnostics`,
  `starboard-finops`) for users who want just one capability.

## 6. Versioning & dependency boundaries

- **Independent SemVer per Tier-0/1 package**; Tier-2 pins Tier-1 with compatible ranges.
- **Dependency direction is strictly downward**: Tier 2 → Tier 1 → Tier 0. No Tier-0 package may
  import `databricks-sdk` (fixes today's `starboard-core` depending on it — `core/pyproject.toml:16`).
- **I/O is quarantined** in `starboard-databricks` (A1) and sparklog's loader extras. Pure units
  never import an SDK.
- **The meta `starboard` package** keeps the current name for back-compat and simply depends on
  the tiers, so `pip install starboard[all]` still yields today's experience.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Version-matrix explosion across many wheels | Keep them in one monorepo with a single lockfile (`uv.lock`); release in lockstep initially, decouple only proven-stable units |
| DBR-runtime dep pins are load-bearing (`packages/starboard/pyproject.toml` CVE/DBR comments) | Keep those pins in the *databricks/server* tiers only; pure tiers are free of them |
| Skill de-dup breaks existing installs | Ship a shim: old `packages/starboard-skills` re-exports the canonical `skills/` |
| MCP surface regressions during bundle refactor | `tool_scope` already exists (`server.py:352`); refactor behind it with golden tool-list tests |
| Discovery agent currently MCP-excluded | Explicit decision needed (re-include vs skill-only) — see open questions |

## 8. Success criteria

1. `pip install starboard-charts` works with **zero** Databricks/LLM deps.
2. One canonical skill source; wheel + plugin both consume it; `diff` between locations is empty.
3. `starboard-diagnostics triage --exit-code 137` runs as a standalone CLI **and** appears as an MCP tool **and** is invoked by the `starboard-diagnostic` skill — all from one implementation.
4. A user can install *only* the FinOps experience via the marketplace without the other six domains.
