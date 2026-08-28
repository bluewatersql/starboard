# Install Tiers

Starboard publishes as **four independently-installable wheels**, one per layer of
the [layered catalog](../architecture/SYSTEM_ARCHITECTURE.md). Install exactly the
tier you need and layer the next one on top — each tier depends on the one below it.

| Wheel | Import package(s) | Contents | Install when you need… |
|-------|-------------------|----------|------------------------|
| **`starboard-kernel`** | `starboard_core`, `starboard_x` | Pure DTOs, domain rules, analyzers, log parser, and the `starboard_x` progressive-helper modules | Embedded / offline analysis with no Databricks SDK on the base install |
| **`starboard-capability`** | (meta — re-uses the kernel) | Kernel **plus every `starboard_x` per-domain extra** (`diagnostics`, `discovery`, `sparklog`, `warehouse`, `uc`, `cluster`, `charts`) | Programmatic / CLI analysis via `python -m starboard_x.<domain>` |
| **`starboard`** | `starboard` | The full experience tier: FastAPI server, MCP server, CLI, agents, public adapters | The MCP server, the `starboard` CLI, or the domain agents |
| **`starboard-skills`** | `starboard_skills` | The Claude Code / Cursor / Claude Desktop skills tree + `starboard-helper` | Skills inside a Claude Code-compatible host |

> **Naming note.** The kernel wheel was renamed `starboard-core` → **`starboard-kernel`**.
> The *import* package is unchanged — `import starboard_core` (and `import starboard_x`)
> work exactly as before. `starboard-core` remains installable as a **thin, one-release
> deprecation alias** that simply pulls `starboard-kernel`; switch to `starboard-kernel`
> at your convenience. The alias will be removed in the next release.

## Choosing a tier

```bash
# 1. Pure kernel — DTOs + analyzers, no heavy runtime deps on the base install
pip install starboard-kernel

# 2. Kernel + progressive helpers (all domains) — offline/CLI analysis
pip install starboard-capability
#    …or install only the domains you need, straight from the kernel extras:
pip install "starboard-kernel[warehouse,uc]"

# 3. Full experience — MCP server + CLI + agents (the default)
pip install starboard

# 4. Just the skills (Claude Code / Cursor / Claude Desktop)
pip install starboard-skills

# Typical user journey: experience tier + skills
pip install starboard starboard-skills
```

## Dependency graph

```
starboard-kernel               (starboard_core + starboard_x)
      └─→ starboard-capability  (= starboard-kernel[all])
              └─→ starboard     (experience: MCP + CLI + agents)

starboard-skills                (independent; optional soft dependency on the MCP path)
```

## Version alignment

All tier wheels are stamped and published with a **single, matching version tag** so a
consumer can pin one version across the stack (e.g. `starboard==X.Y.Z` and
`starboard-kernel==X.Y.Z`). CI builds and publishes every tier on a tagged release and
verifies the versions match before upload.

## Notes

- **Optional store/vector backends** stay opt-in on the experience tier via extras
  (`starboard[sqlite|postgres|redis|memory|vectorsearch|all-stores]`); the default
  install runs store-free.
- **Per-domain tool plugins** are separate thin wheels discovered at runtime through
  the `starboard.mcp_tools` entry-point group — never a hard dependency of any tier.
- The internal-only `starboard-internal` adapters are **never** part of the public path;
  installing them is an internal-distribution concern and no public wheel depends on them.
- `$` figures on the public path are **list-price DBU estimates** — label them as such.
