# Starboard — Databricks Analysis (Claude Code plugin)

Skills-only Claude Code plugin for AI-powered Databricks workload analysis: queries, jobs,
Unity Catalog, clusters, FinOps, warehouses, and diagnostics.

This plugin bundles the canonical Starboard skills. Each skill is **dual-mode**: it prefers the
in-context `mcp__starboard__*` agent tools when a Starboard MCP server is present, and otherwise
falls back to the `starboard-helper` CLI. This plugin ships **skills only, no MCP** — so out of the
box every skill takes the CLI-helper path (no server, no LLM credentials required). Enabling the
full 7-agent MCP stack is an explicit opt-in you wire up yourself (see
[Optional: enable the MCP server](#optional-enable-the-mcp-server-full-agent-stack)).

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

## Optional: enable the MCP server (full agent stack)

The plugin is **skills-only** and ships **no `.mcp.json`** and **no `mcpServers`**. Claude Code
launches any bundled `mcpServers` a plugin declares — and may try to spawn a `.mcp.json` server in
the loaded plugin dir — as soon as the plugin loads, so bundling a server entry would break a
skills-only install (it would try to spawn `starboard-mcp` with no binary and no LLM credentials).
MCP is therefore an explicit opt-in you add to **your own** `.mcp.json`, never inside the plugin.

To run the full 7-agent stack:

1. Install the server and its dependencies: `pip install starboard` and set the LLM credentials
   (`LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL`) plus `DATABRICKS_HOST`.
2. Register the `starboard` stdio server with Claude Code in your own config:

   ```bash
   claude mcp add starboard -- starboard-mcp --transport stdio
   ```

When the server is present, the dual-mode skills automatically prefer the in-context
`mcp__starboard__*` tools; when it is absent they fall back to the `starboard-helper` CLI.

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

Distribution to external Databricks customers is via the first-party `databricks aitools` command
group and/or the open-source Skills CLI (skills-only bundle, no server). The command surface is now
publicly documented; whether a third-party bundle like Starboard is installable through
`databricks aitools` (vs. the Skills CLI) is still owner-gated. The full flow, the Agent Skills
standard conformance, and the confirmation-needed items live in
[`docs/distribution/databricks-aitools.md`](../docs/distribution/databricks-aitools.md).

## What is bundled

- `skills/` — the nine canonical Starboard skills (`starboard-query`, `starboard-job`,
  `starboard-warehouse`, `starboard-uc`, `starboard-cluster`, `starboard-finops`,
  `starboard-diagnostic`, `starboard-discovery`, `starboard-analyze`).
- `commands/starboard-triage.md` — a one-shot `/starboard-triage` workspace triage command.

### Skill source of truth (D-1.5)

`plugin/skills` is **not** a hand copy. It is a vendored, materialized copy of the single canonical
skills tree at `packages/starboard-skills/skills/starboard/`. The skill folders live directly under
`plugin/skills/` (real files — **not** a symlink) so the plugin is fully self-contained: a copied or
published plugin ships every skill.

Keep it in sync with the canonical source with the committed vendoring script (single source of
truth stays `packages/starboard-skills/skills/starboard/`):

```bash
python scripts/vendor_plugin_skills.py          # re-vendor (overwrite + prune)
python scripts/vendor_plugin_skills.py --check   # verify in sync (drift guard)
# or: make vendor-skills / make vendor-skills-check
```

Two unit tests enforce this: `packages/starboard/tests/unit/plugin/test_skills_vendored.py` fails if
`plugin/skills` is a symlink or has drifted from the canonical tree (run the script to re-sync), and
`test_plugin_manifest.py` checks the vendored `SKILL.md` set stays byte-identical to the source.
