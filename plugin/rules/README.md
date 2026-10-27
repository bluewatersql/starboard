# Starboard Ruleset Content Model

Rules files in this directory are **generated** from the canonical skills tree at
`packages/starboard-skills/skills/starboard/`.

Regenerate at any time:

```bash
python scripts/gen_rulesets.py           # write all files
python scripts/gen_rulesets.py --check   # exit 1 if stale (CI gate)
```

---

## Content-model schema — `starboard-ruleset/1`

Every per-domain ruleset (`jobs.md`, `sql.md`, …) must conform to this schema.
The test suite at `packages/starboard/tests/unit/rulesets/test_gen_rulesets.py`
enforces it automatically.

### Frontmatter (required fields)

```yaml
---
schema:    starboard-ruleset/1     # version sentinel — must be literal
domain:    <slug>                  # one of: jobs | sql | warehouse | uc | cluster | discovery
title:     "Starboard: <Title> Agent Rules"
skill:     <skill-dir-name>        # e.g. starboard-job
mcp_agent: mcp__starboard__<tool>  # canonical MCP tool identifier
triggers:  ["<kw1>", "<kw2>", ...] # YAML inline list of trigger keywords
generated: true                    # must be the boolean true
source:    packages/starboard-skills/skills/starboard/<skill-dir>/SKILL.md
---
```

| Field | Type | Constraint |
|-------|------|-----------|
| `schema` | string | Must equal `"starboard-ruleset/1"` |
| `domain` | string | Must be one of `jobs`, `sql`, `warehouse`, `uc`, `cluster`, `discovery` |
| `title` | string | Non-empty |
| `skill` | string | Must correspond to a real directory under `packages/starboard-skills/skills/starboard/` |
| `mcp_agent` | string | Must match `mcp__starboard__\w+` |
| `triggers` | list | Non-empty list of strings |
| `generated` | bool | Must be `true` |
| `source` | string | Must end with `/SKILL.md` |

### Required sections (by H2 heading)

Every ruleset body must contain **all five** of these sections, in any order:

| Section | Purpose |
|---------|---------|
| `## When to use` | Activation conditions — when should an agent apply this ruleset? |
| `## Tool guidance` | Tiered tool selection: Tier-2 MCP → Tier-1 bundled helper → Tier-0 raw fetch |
| `## Domain heuristics` | Domain-specific analytical patterns, derived from `SKILL.md` reasoning steps |
| `## Success criteria` | What a complete, correct analysis looks like for this domain |
| `## Ground rules` | Cross-cutting invariants (dollar labeling, auth, read-only, exit codes) |

### Tool guidance sub-structure

The `## Tool guidance` section must contain three sub-headings:

```
### Tier-2 — MCP agent (preferred)
### Tier-1 — bundled helper
### Tier-0 — raw fetch via `starboard-helper`
```

---

## Governance invariants

1. **No internal namespaces** — the following strings must not appear in any ruleset:
   `centralized_system_tables`, `fin_live_gold`, `gtm_`, `eng_`, `logfood`,
   `ClickHouse`, `hmr_stack_hash`.

2. **Dollar figures** — any `$` sign must be accompanied by "list-price" (or "estimate")
   somewhere in the same paragraph.  Never present cost figures as finance-grade.

3. **Read-only advisory** — rulesets must not instruct agents to modify the workspace.

---

## File layout

```
plugin/rules/
├── README.md           ← this file (content model + regeneration guide)
├── starboard.md        ← router/index pointing at per-domain files
├── jobs.md             ← generated from starboard-job/SKILL.md
├── sql.md              ← generated from starboard-query/SKILL.md
├── warehouse.md        ← generated from starboard-warehouse/SKILL.md
├── uc.md               ← generated from starboard-uc/SKILL.md
├── cluster.md          ← generated from starboard-cluster/SKILL.md
└── discovery.md        ← generated from starboard-discovery/SKILL.md
```

Install into `.isaac/rules/` (or `{project}/.isaac/rules/`) via:

```bash
starboard-maint rules install --scope user    # user scope (~/.isaac/rules/)
starboard-maint rules install --scope project # project scope (./.isaac/rules/)
```
