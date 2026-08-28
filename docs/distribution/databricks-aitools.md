# External-customer distribution — `databricks aitools` (skills-only)

> **Tasks O5 + DOC-6 (PHASE_1.md §6).** How the Starboard skills reach *external
> Databricks customers* — as a skills-only bundle, no server, no MCP — through the
> first-party `databricks aitools` channel and/or the open-source Skills CLI.
>
> **Status (2026-08-27):**
> - **G4 RESOLVED** — the confirmed agent-skills distribution format is defined by
>   [`databricks-solutions/ai-dev-kit`](https://github.com/databricks-solutions/ai-dev-kit).
>   The mirror is now **materialized** at `packages/starboard-distribution/aitools/`
>   with a generated `manifest.json`; see [Distribution mirror](#4-distribution-mirror).
> - **`databricks aitools` command surface** — CONFIRMED (publicly documented;
>   see [Verification](#verification)).
> - **Third-party inclusion mechanics** — still owner-gated; see
>   [Confirmation needed](#5-confirmation-needed-owner-questions).
>
> Per D-1.4 this task is **packaging + docs**: the bundle is aitools-agnostic, so
> adopting whatever the owner confirms about third-party inclusion is a localized
> packaging step against the existing mirror.

## 1. What gets installed (the bundle)

The externally-distributed artifact is **skills only** — the canonical Starboard skill
tree, with no MCP server and no LLM credentials required. Out of the box every skill
takes the `starboard-helper` CLI path (the Tier-0/Tier-1 "no-server" UX).

Canonical source of truth (single tree, vendored into the plugin by
`scripts/vendor_plugin_skills.py`; drift-checked by `make vendor-skills-check` — D-1.5).
The tree has **10** skills:

```
packages/starboard-skills/skills/starboard/
├── starboard-analyze/SKILL.md
├── starboard-cluster/SKILL.md
├── starboard-diagnostic/
│   ├── SKILL.md
│   ├── reference.md
│   ├── examples.md
│   └── scripts/run.sh          # Tier-1 helper: python -m starboard_x.diagnostic
├── starboard-discovery/SKILL.md
├── starboard-finops/SKILL.md
├── starboard-job/SKILL.md
├── starboard-query/SKILL.md
├── starboard-uc/SKILL.md
├── starboard-warehouse/SKILL.md
└── starboard-workload-review/SKILL.md
```

Each directory is a self-contained Agent Skill: a `SKILL.md` plus optional
`scripts/` / `references/` / `assets/` — exactly the layout the Agent Skills standard
prescribes. The bundle carries **no** server, MCP, wheel, or internal-namespace
artifacts; that "skills-tree-only" invariant is what the external channel ships.

Prerequisite on the customer's machine (documented in the plugin `README.md`): the
`starboard-helper` CLI on `PATH`, and — for the richer diagnostic Tier-1 path —
`pip install "starboard-kernel[diagnostics]"` (the `starboard_x` helpers ship in the
`starboard-core` wheel; the `diagnostics` extra adds `pyyaml`; no `databricks-sdk`,
no heavy binaries). Auth uses the Databricks unified chain
(`DATABRICKS_HOST`/`DATABRICKS_TOKEN` or `~/.databrickscfg`).

## 2. Agent Skills standard conformance

`databricks aitools` and the Skills CLI install **Agent-Skills-standard** skill files
into whichever AI assistants they detect (Claude, Copilot, Cursor, …). That standard is
narrower than Claude Code's superset, so the bundle must use only the **portable
frontmatter field set** — otherwise a skill that relies on a Claude-Code-only field
would misbehave in another host.

Portable fields defined by the spec (agentskills.io/specification):

| Field           | Required | Constraint                                                          |
|-----------------|----------|---------------------------------------------------------------------|
| `name`          | yes      | ≤ 64 chars, lowercase alnum + single hyphens, **must match the directory name** |
| `description`   | yes      | ≤ 1024 chars, non-empty; says *what* the skill does and *when* to use it |
| `license`       | no       | license name or a bundled-file reference                            |
| `compatibility` | no       | ≤ 500 chars; environment requirements (intended product, packages, network) |
| `metadata`      | no       | arbitrary `map<string, string>`                                     |
| `allowed-tools` | no       | **space-separated** string of pre-approved tools (experimental)     |

The Starboard bundle is already conformant: every canonical `SKILL.md` uses only
`name`, `description`, and `allowed-tools` — all three in the portable set — with `name`
equal to the directory name and descriptions well under 1024 chars. No Claude-Code-only
frontmatter (no `model`, `disable-model-invocation`, `argument-hint`, `when_to_use`,
etc.) is present. A machine-checkable guard enforces this:

- `packages/starboard/tests/unit/skills/test_skill_portability.py` — asserts each
  canonical `SKILL.md`'s frontmatter uses **only** the portable field set (any extra key
  fails), and that `name`/`description`/`compatibility`/`metadata`/`allowed-tools` obey
  their spec constraints. This is the "flags Claude-Code-only fields" contract from the
  B4 validation requirement, collectable by `pytest`.

### Known portability nuance — `allowed-tools` separator

The spec models `allowed-tools` as a **space-separated** string
(`Bash(git:*) Bash(jq:*) Read`), while Claude Code accepts a **comma-separated** list,
which is what the canonical skills currently use
(`Bash(starboard-helper:*), Read`). The field is optional and marked *experimental* in
the spec ("support may vary between agent implementations"), so this is a soft nuance,
not a hard break — but a non-Claude host could parse the comma form differently, and the
diagnostic skill's rule `Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)` embeds both a
Claude-specific variable (`${CLAUDE_SKILL_DIR}`) and an internal space. See the owner
questions below before relying on pre-approval outside Claude Code. The functional
fallback is unaffected: a host that does not pre-approve the tool simply prompts (or the
skill degrades to the raw `starboard-helper` path).

## 3. How customers would install

### 3a. `databricks aitools` (first-party channel)

The Databricks CLI exposes an `aitools` command group for installing Agent Skills into
detected coding assistants:

```bash
databricks aitools install                       # all detected agents, global scope
databricks aitools install --agents claude-code  # a specific agent
databricks aitools install --scope project        # into the current project, not global
databricks aitools install --skills bundles,sql   # specific (Databricks-authored) skills
databricks aitools list                            # list installed skills
databricks aitools update                          # update installed skills
databricks aitools uninstall                       # remove installed skills
```

**Important limitation (from the docs):** `databricks aitools install` installs
**Databricks-authored** skills only; it exposes no flag for an arbitrary GitHub repo or
local path. So Starboard reaches customers through this command **only if** the Starboard
skills are accepted into the Databricks-curated skill catalog under a skill/bundle name
(e.g. a future `--skills starboard`). That inclusion process is **not publicly
documented** — it is the primary owner question below.

### 3b. Skills CLI (third-party GitHub channel)

The docs point third-party skills at a separate tool: *"To install skills from arbitrary
GitHub repositories that are not distributed through the Databricks CLI, use the Skills
CLI, an open-source package manager for agent skills."* It scans a GitHub repo for skill
files and installs them into the project so the assistant discovers them automatically.
This is the channel that works **today** for a third-party bundle like Starboard, pointed
at the Starboard repo's canonical skill tree — no Databricks-side inclusion required. Its
exact invocation/package name is not reproduced in the Databricks page and should be
pinned against the Skills CLI's own docs before we put a copy-paste command in front of
customers.

### 3c. Relationship to the other install paths

The same skills-only bundle already installs via the Claude Code plugin
(`/plugin marketplace add … && /plugin install starboard@starboard-marketplace`) and via
Isaac (`isaac plugin add starboard@<marketplace>`) — see `plugin/README.md`. `aitools`
adds the **external-customer, multi-assistant** row to that table. The bundle content is
identical; only the installer differs.

## 4. Distribution mirror

**G4 resolved (2026-08-27).** The confirmed agent-skills distribution format from
[`databricks-solutions/ai-dev-kit`](https://github.com/databricks-solutions/ai-dev-kit)
(@main, verified 2026-08-27) is:

- **Skill layout:** one directory per skill (`<skill-name>/SKILL.md` + optional
  `scripts/`, `references/`, etc.) under a `<host>/skills/` root — the standard
  [Agent Skills layout](https://agentskills.io/specification).
- **Frontmatter:** `name` (required, ≤64 chars, lowercase alnum+hyphens, no XML/reserved
  words) and `description` (required, ≤1024 chars, non-empty, no XML) — enforced by
  ai-dev-kit's `validate_skills.py` and by our portability test.
- **Deprecated:** the `ai-dev-kit .claude-plugin/plugin.json` is deprecated; skills now
  ship via `databricks aitools install` from a separate `databricks-agent-skills` repo.
- **No bundle-level manifest.json in ai-dev-kit:** the `.test/skills/<name>/manifest.yaml`
  files are internal evaluation manifests (scorers, quality gates) — not distribution
  artifacts. Our `manifest.json` is a generated bundle index for drift-check CI and
  downstream tooling.

### Materialized mirror

The mirror lives at `packages/starboard-distribution/aitools/` and is generated by
`scripts/skills.py`:

```
packages/starboard-distribution/aitools/
├── manifest.json                    # Generated bundle index (not part of ai-dev-kit format)
├── starboard-analyze/SKILL.md
├── starboard-cluster/SKILL.md
├── starboard-diagnostic/
│   ├── SKILL.md
│   ├── reference.md
│   ├── examples.md
│   └── scripts/run.sh
├── starboard-discovery/SKILL.md + scripts/run.sh
├── starboard-finops/SKILL.md
├── starboard-job/SKILL.md
├── starboard-query/SKILL.md
├── starboard-uc/SKILL.md + scripts/run.sh
├── starboard-warehouse/SKILL.md + scripts/run.sh
└── starboard-workload-review/SKILL.md + scripts/run.sh
```

**Regenerate the mirror:**

```bash
python scripts/skills.py            # vendor + generate manifest.json
python scripts/skills.py --check    # verify in sync (CI drift guard)
```

**Drift check (recommended Makefile target — wire centrally):**

```makefile
.PHONY: test-distribution
test-distribution:
	python scripts/skills.py --check
```

Unit tests (`make test-unit`) validate the committed mirror at
`packages/starboard/tests/unit/distribution/test_distribution_manifest.py` (52 tests):
manifest schema, canonical roster match, frontmatter validity per-skill, and
byte-level file stability checks.

### manifest.json schema

```json
{
  "schema_version": "1.0",
  "bundle_name": "starboard",
  "bundle_version": "<semver>",
  "description": "...",
  "format": "agent-skills",
  "repository": "https://github.com/databricks/starboard",
  "generated_at": "<ISO-8601 UTC>",
  "skills": [
    {
      "name": "<skill-name>",
      "path": "<skill-name>/",
      "description": "<frontmatter description>",
      "allowed_tools": "<frontmatter allowed-tools, if present>"
    }
  ]
}
```

If/when the owner confirms a concrete `databricks aitools` manifest/registry shape for
third-party skills, aligning the mirror is a localized packaging step — not a redesign.

## 5. Confirmation needed (owner questions)

Route these to the `databricks aitools` / Agent Skills owner before an external release:

1. **Third-party inclusion.** Can a *non-Databricks* bundle like Starboard be installed
   through `databricks aitools install` (e.g. `--skills starboard`)? If yes, what is the
   contribution / catalog-inclusion process and where does the curated catalog live?
   *(Docs state `aitools` installs Databricks-authored skills only; no third-party flag.)*
2. **Manifest / registry shape.** If third-party skills are supported, what manifest or
   registry entry must Starboard provide (file name, schema, versioning)? The docs
   describe skills only as "a Markdown file with front-matter metadata" and specify no
   installer-side manifest.
3. **Skills CLI as the sanctioned third-party path.** Is the open-source Skills CLI the
   intended channel for third-party Databricks-ecosystem skills, and if so what is its
   exact package name / invocation to publish in customer-facing docs?
4. **`allowed-tools` separator + variables.** For multi-assistant installs, should
   `allowed-tools` be normalized to the spec's **space-separated** form, and are
   Claude-specific rules like `Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)` honored,
   ignored, or a problem outside Claude Code?
5. **Install locations & precedence.** Where does `aitools` place skills per agent
   (global vs `--scope project` paths), and how does an `aitools`-installed Starboard
   interact with a plugin- or Isaac-installed copy (precedence / duplication — open
   question I7 in `agent_integration/opportunities.md`)?
6. **Prerequisites.** Minimum Databricks CLI version and auth required to run
   `databricks aitools` (not stated on the docs page).
7. **`starboard-helper` prerequisite.** `aitools` installs *skills*; the skills shell out
   to `starboard-helper` / `python -m starboard_core.x.diagnostic`. How should external
   customers obtain that CLI in the `aitools` flow (bundled? separate `pip install`?
   documented prerequisite?).

## Verification

Verified against live sources (2026-08-27):

- **`databricks aitools` command group — CONFIRMED.**
  <https://docs.databricks.com/aws/en/agent-skills> ("Agent skills for AI coding
  assistants"). Documents `databricks aitools install|list|update|uninstall`, the
  `--agents` / `--scope` / `--skills` flags, and the example invocations reproduced in
  §3a. States the command installs Databricks-authored skills and points third-party
  GitHub repos at the open-source **Skills CLI**.
- **Agent Skills standard field set — CONFIRMED.**
  <https://agentskills.io/specification> — the portable frontmatter table in §2
  (name/description/license/compatibility/metadata/allowed-tools) and their constraints
  (name ≤ 64 & matches dir; description ≤ 1024; compatibility ≤ 500; allowed-tools
  space-separated & experimental). Standard overview + client list:
  <https://agentskills.io>.
- **G4 RESOLVED — confirmed agent-skills distribution format.**
  Inspected `databricks-solutions/ai-dev-kit` @main
  (<https://github.com/databricks-solutions/ai-dev-kit>):
  - Skill layout: `<host>/skills/<name>/SKILL.md` (Agent Skills standard).
  - Frontmatter constraints: `name` (≤64, lowercase alnum+hyphens, no XML/reserved
    words) and `description` (≤1024, non-empty) — enforced by `validate_skills.py`.
  - `.claude-plugin/plugin.json` deprecated; distribution now via
    `databricks aitools install` + `databricks-agent-skills`.
  - `.test/skills/<name>/manifest.yaml` = internal eval manifests (not distribution).
  - No bundle-level manifest.json in ai-dev-kit format — our `manifest.json` is a
    generated bundle index.
  - Mirror materialized: `packages/starboard-distribution/aitools/` generated by
    `scripts/skills.py`.
- **UNCONFIRMED (still owner-gated):** third-party inclusion in `databricks aitools`, the
  installer-side manifest/registry shape, install locations/precedence, CLI-version/auth
  prerequisites, and the `starboard-helper` acquisition step — see
  [Confirmation needed](#5-confirmation-needed-owner-questions).

> G4 is fully resolved for the *distribution format* (skill directory layout + frontmatter
> rules confirmed from ai-dev-kit source). The *third-party inclusion mechanics* (questions
> 1–7 below) remain owner-gated; adopting them is a localized packaging step against the
> existing mirror.
