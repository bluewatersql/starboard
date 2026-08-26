# Starboard — Databricks Analysis (Claude Code plugin)

Skills-only Claude Code plugin for AI-powered Databricks workload analysis: queries, jobs,
Unity Catalog, clusters, FinOps, warehouses, and diagnostics.

This plugin bundles the canonical Starboard skills. Each skill is **dual-mode**: it prefers the
in-context `mcp__starboard__*` agent tools when a Starboard MCP server is present, and otherwise
falls back to the `starboard-helper` CLI. This plugin ships **skills only, no MCP** — so out of the
box every skill takes the CLI-helper path (no server, no LLM credentials required). The optional
MCP toggle is a separate add-on (Task B6).

## Prerequisite — install the helper CLI

The skills shell out to the `starboard-helper` CLI and, for the richer diagnostic path, to
`python -m starboard_core.x.diagnostic`. Install the dep-ful middle tier before using the plugin:

```bash
pip install "starboard-x[diagnostics]"
```

This pulls the diagnostic trio with only a light dependency set (pydantic + structlog + pyyaml —
no `databricks-sdk`, no heavy binaries). `starboard-helper` itself is provided by the
`starboard-skills` distribution; install it if it is not already on `PATH`:

```bash
pip install starboard-skills
```

Authentication uses the Databricks unified auth chain (`DATABRICKS_HOST`/`DATABRICKS_TOKEN` or
`~/.databrickscfg`). Under Isaac, Databricks credentials are injected automatically.

`${CLAUDE_PLUGIN_ROOT}` (and, per-skill, `${CLAUDE_SKILL_DIR}`) resolve the bundled `scripts/`
helpers at runtime, so pre-approved skill commands run without a permission prompt.

## Install flows

The marketplace manifest (`.claude-plugin/marketplace.json` at the repo root) is **identical** for
the public GitHub org and an internal Isaac (`vibe`-style) marketplace — only the install command
differs (D-1.4).

### Claude Code (public)

```
/plugin marketplace add databricks/starboard
/plugin install starboard@starboard-marketplace
```

You can also add a local checkout by path:

```
/plugin marketplace add /path/to/starboard
/plugin install starboard@starboard-marketplace
```

### Isaac (internal)

```
isaac plugin add starboard@<marketplace>
isaac -- plugin list | grep starboard   # verify
```

### Databricks customers (external)

Distribution to external Databricks customers is via `databricks aitools` (skills-only bundle).
That packaging flow is tracked as Task **B4** and documented there once the exact `aitools` CLI /
manifest surface is confirmed with the owner.

## What is bundled

- `skills/` — the nine canonical Starboard skills (`starboard-query`, `starboard-job`,
  `starboard-warehouse`, `starboard-uc`, `starboard-cluster`, `starboard-finops`,
  `starboard-diagnostic`, `starboard-discovery`, `starboard-analyze`).
- `commands/starboard-triage.md` — a one-shot `/starboard-triage` workspace triage command.

### Skill source of truth (D-1.5)

`plugin/skills` is **not** a hand copy. It is a build-time vendoring of the single canonical skills
tree at `packages/starboard-skills/skills/starboard/` — in this repo it is a relative symlink, so the
plugin and the wheel always ship byte-identical `SKILL.md` files. A unit test
(`packages/starboard/tests/unit/plugin/test_plugin_manifest.py`) enforces byte-identity as a drift
guard. When producing a standalone, extraction-based artifact (e.g. the B4 `aitools` bundle), the
symlink is materialized into real files by the same vendoring step.
