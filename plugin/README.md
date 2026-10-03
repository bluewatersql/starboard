# Starboard — Databricks Analysis (Claude Code plugin)

Skills-only Claude Code plugin for AI-powered Databricks workload analysis: queries, jobs,
Unity Catalog, clusters, FinOps, warehouses, and diagnostics.

This plugin bundles the canonical Starboard skills. Each skill is **dual-mode**: it prefers the
in-context `mcp__starboard__*` agent tools when a Starboard MCP server is present, and otherwise
falls back to the Starboard CLIs. This plugin ships **skills only, no MCP** — so every skill takes
the CLI path (no MCP server and no LLM credentials required for it).

> **Not zero-setup — plan for a one-time install.** The skills shell out to the Starboard CLIs
> (`starboard-helper`, `python -m starboard_x.*`, and — for review-driven skills — the full
> `starboard` CLI), and **none of these are bundled in the plugin**. The first run of a skill whose
> dependency is missing **prompts you to approve a one-time `pip install`** from the internal
> `databricks-field-eng/starboard` repo (which requires access to that repo). The `run.sh` wrappers
> never install silently — they print the exact command and `exit 3`, and the skill then runs the
> install as a separate, permission-prompted step. See **Prerequisite** below.

Enabling the full 7-agent MCP stack is a further, separate opt-in you wire up yourself (see
[Optional: enable the MCP server](#optional-enable-the-mcp-server-full-agent-stack)).

## Prerequisite — install the helper CLI

The skills shell out to the `starboard-helper` CLI and, for the richer diagnostic path, to
`python -m starboard_x.diagnostic`. Install the dep-ful middle tier before using the plugin:

```bash
pip install "starboard-kernel[diagnostics] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core"
```

This pulls the diagnostic trio with only a light dependency set (pydantic + structlog + pyyaml —
no `databricks-sdk`, no heavy binaries). `starboard-helper` itself is provided by the
`starboard-skills` distribution; install it if it is not already on `PATH`:

```bash
pip install "starboard-skills @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-skills"
```

A few skills — **`starboard-workload-review`**, the engagement **recur** beat, and the internal
overlay — shell out to `starboard review`, which is provided by the **full `starboard` wheel**
(heavier: it pulls `databricks-sdk`). Their `run.sh` detects a missing `starboard` binary and
prompts for it on first use:

```bash
pip install "starboard @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard"
```

You only need the full wheel if you use those review-driven skills; the other skills run on
`starboard-helper` + the `starboard_x` analyzers above.

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

1. Install the server and its dependencies: `pip install "starboard @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard"` and set the LLM credentials
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
[`docs/guide/skills.md`](../docs/guide/skills.md).

## What is bundled

- `skills/` — the canonical Starboard skills, in three groups:
  - **Nine domain-analysis skills**: `starboard-query`, `starboard-job`, `starboard-warehouse`,
    `starboard-uc`, `starboard-cluster`, `starboard-finops`, `starboard-diagnostic`,
    `starboard-discovery`, `starboard-analyze`.
  - **Four engagement-workflow skills**: `starboard-workload-review`, `starboard-action-plan`,
    `starboard-engagement`, `starboard-deliver` (the verify → present → synthesize → deliver flow).
  - **Internal builds only**: `starboard-internal-overlay` — the field-eng enrichment overlay,
    folded in on internal/`vibe` builds only (never in the public wheel or public marketplace).
- `assets/` — the `starboard_logo.png` brand emblem (1:1 square), used by the engagement
  exec-summary Doc.

**Full distribution only (not the skills-only marketplace build):**

- `agents/` — twelve subagents: the per-domain analyzers (`starboard-query`, `-job`, `-warehouse`,
  `-uc`, `-cluster`, `-finops`, `-diagnostic`, `-discovery`, `-analyze`) plus the workload-review
  agent and two autonomous monitors (`starboard-workload-review-auto`, `starboard-cluster-monitor`).
- `commands/starboard-triage.md` — a one-shot `/starboard-triage` workspace triage command.

The **marketplace (`vibe`) build is skills-only**: it ships `skills/` + `assets/` (declared via
`skills` in `.claude-plugin/plugin.json`) and deliberately omits `agents/` and `commands/`, which
duplicate the skills' routing. The agents and the `/starboard-triage` command are part of the full
CLI / MCP / Isaac distribution, where `.claude-plugin/plugin.json` additionally declares `agents`
and `commands` so that loader registers them explicitly.

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
