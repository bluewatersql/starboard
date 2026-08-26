# Technical Design — Dep-ful Progressive-Disclosure Helpers

> Companion to `opportunities.md` / `recommendation.md`. Concrete SKILL.md + script +
> reference-file layout, `python -m` interfaces, per-capability pyproject extras, and how
> disclosure keeps context low. All skill-format claims verified against
> `https://code.claude.com/docs/en/skills` (fetched 2026-08-26); confidence **[C]** confirmed,
> **[I]** inferred. Repo anchors cited inline.

---

## 1. The three-level disclosure layout (verified)

Per the docs' "Add supporting files" section, a skill directory has exactly this shape, and each
level loads at a different time:

```
starboard-diagnostic/
├── SKILL.md            # L1 frontmatter (always resident, ≤1536 chars) + L2 body (<500 lines, on fire)
├── reference.md        # L3: extractor semantics, exit-code table — "loaded when needed"
├── examples.md         # L3: sample invocations + expected JSON — "loaded when needed"
└── scripts/
    └── run.sh          # L3: "executed, not loaded" — wraps `python -m starboard_x.diagnostic`
```

- **L1 — always in context:** only `name` + `description` (+ `when_to_use`), truncated at 1,536 chars
  (docs: Frontmatter reference). Sole permanent cost.
- **L2 — on invoke:** the `SKILL.md` body; it "stays in context across turns" (docs: Skill content
  lifecycle) ⇒ keep < 500 lines (docs Tip). Contains the trigger logic + the shell-out command.
- **L3 — on demand:** `reference.md`/`examples.md` read only if Claude needs them; `scripts/*` are
  **executed, not loaded** (docs: Add supporting files) ⇒ the dep-ful code and its polars/altair/
  sqlglot imports **never touch the model context**.

**Why context stays near-zero with real depth:** the model holds ~1.5KB of description → a small body
→ compact JSON from the subprocess. Depth (the analyzers) runs out-of-context in Python.

---

## 2. Concrete SKILL.md (diagnostic, three-branch dual-mode)

Uses the **verified** `${CLAUDE_SKILL_DIR}` + `allowed-tools` pattern so the dep-ful script runs with
**no permission prompt** (docs: "the `allowed-tools` rule then matches the exact command the skill
body tells Claude to run, so the script runs without prompting").

```markdown
---
name: starboard-diagnostic
description: >
  Diagnose Databricks failures — triage exit codes, extract evidence from error
  logs, match known failure patterns, and synthesize a root cause. Use when the
  user mentions a job/query failure, exit code, OOM, stack trace, or "why did
  this fail". Triggers: error, exit code 137/143, OOM, stack trace, root cause.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Read
---

## Path selection
1. If `mcp__starboard__diagnostic_agent` is available → call it (full server RCA).   [Tier 2]
2. Else if `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists → use it (dep-ful helper).     [Tier 1]
3. Else → `starboard-helper diagnostic run-state --run-id <id>` (raw fetch only).     [Tier 0]

## Tier-1 usage (this skill's default)
Fetch failure context, then analyze locally. All commands emit JSON to stdout.

- Exit code:   `${CLAUDE_SKILL_DIR}/scripts/run.sh triage-exit --exit-code <N>`
- Error log:   `${CLAUDE_SKILL_DIR}/scripts/run.sh extract-evidence --text <file>`
- Query slow:  `${CLAUDE_SKILL_DIR}/scripts/run.sh query-profile --profile <file>`
- End-to-end:  `${CLAUDE_SKILL_DIR}/scripts/run.sh rca --text <file> [--exit-code <N>]`

For the exit-code table and evidence-window types, see [reference.md](reference.md).
For sample output, see [examples.md](examples.md).
```

`scripts/run.sh` (bundled; keeps the entry point stable and lets `allowed-tools` match one prefix):

```bash
#!/usr/bin/env bash
set -euo pipefail
exec python -m starboard_x.diagnostic "$@"
```

**Optional zero-turn variant** — inline a result with dynamic-context injection (docs: Inject dynamic
context) so the verdict arrives *with* the body:

```markdown
## Triage
- Verdict: !`python -m starboard_x.diagnostic triage-exit --exit-code $0`
```

**Isolation variant** — push even the body cost off the main thread (docs: Run skills in a subagent):

```yaml
context: fork
agent: Explore
```

---

## 3. `python -m` interfaces + entry points

Every capability is a runnable module (`starboard_x/<domain>/__main__.py`) with an `argparse`
subcommand surface, mirroring today's helper contract (`starboard_skills/helpers/__main__.py:15-52`)
— JSON to stdout, exit codes `0 ok · 1 auth · 2 not-found · 3 api-error · 4 arg-error`.

```
python -m starboard_x.diagnostic  triage-exit | extract-evidence | query-profile | spark-evidence | match-patterns | synthesize | rca
python -m starboard_x.discovery   run --data-only [--packs …]
python -m starboard_x.sparklog    parse --source {dbfs|s3|https|local} --path …
python -m starboard_x.warehouse   analyze | portfolio | workload
python -m starboard_x.uc          analyze | lineage | storage | governance | browse
python -m starboard_x.cluster     health | metrics | fingerprint
python -m starboard_x.charts      render --config c.json --out c.png
```

Console-script aliases (optional, same target) in `pyproject.toml`, mirroring
`starboard-skills/pyproject.toml:12-13`:

```toml
[project.scripts]
starboard-x = "starboard_x.__main__:main"          # dispatches to the sub-modules
```

Each sub-module is a thin CLI wrapper that imports the **existing** class and calls its method — no
logic duplication. Example (`starboard_x/diagnostic/__main__.py`, illustrative):

```python
# exit_code_triager lives at tools/domain/diagnostic/exit_code_triager.py:239
from starboard_x.diagnostic.exit_code_triager import ExitCodeTriager  # re-homed module
def _triage(args):
    return ExitCodeTriager().triage(exit_code=args.exit_code, context=args.context)  # :256
```

**Re-homing note:** `tools/domain/diagnostic/__init__.py:16-96` eagerly imports the whole subsystem
(artifact_explorer, exploration_observability, …). Those siblings are light (stdlib+structlog+
pydantic+pyyaml — verified), but a clean `starboard-x` should carry a **trimmed `__init__`** (or
import modules by full path) so a single verb doesn't pull the entire diagnostic tree. This is the
main mechanical task of the extraction (see recommendation §2 rank 2 LOE).

---

## 4. Per-capability extras in `pyproject.toml`

The lever that makes the middle tier **lighter than the server**: base install is pydantic-only; each
skill installs **only its extra**. Contrast with the server's ~40 hard deps
(`starboard/pyproject.toml:8-82`).

```toml
[project]
name = "starboard-x"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0,<3",            # DTOs — the only unconditional dep
    "structlog>=24.0",            # shared logger (infra/observability/logging.py:19)
]

[project.optional-dependencies]
# --- diagnostics -------------------------------------------------------------
diagnostics-core = []                              # C1,C2,C6 are stdlib-only
diagnostics = ["pyyaml>=6.0.3"]                    # +C5 pattern registry (patterns/registry.py:25)
# --- discovery ---------------------------------------------------------------
discovery = ["polars>=1.17,<2", "databricks-sql-connector>=3.0", "databricks-sdk>=0.73,<1"]
# --- spark log parser --------------------------------------------------------
sparklog       = ["polars>=1.17,<2", "numpy>=2.0,<3", "stream-unzip>=0.0.94", "httpx>=0.28.1"]
sparklog-aws   = ["starboard-x[sparklog]", "boto3>=1.34"]     # mirrors core [aws] (core/pyproject.toml:20)
sparklog-azure = ["starboard-x[sparklog]", "azure-storage-file-datalake>=12.14", "azure-identity>=1.15"]
sparklog-gcp   = ["starboard-x[sparklog]", "google-cloud-storage>=2.14"]
# --- warehouse / uc / cluster ------------------------------------------------
warehouse = ["polars>=1.17,<2", "sqlglot>=27.29,<28", "databricks-sql-connector>=3.0", "databricks-sdk>=0.73,<1"]
uc        = ["databricks-sdk>=0.73,<1", "databricks-sql-connector>=3.0"]
cluster   = ["databricks-sdk>=0.73,<1"]
# --- charts (heavy binary dep, isolated) -------------------------------------
charts    = ["altair>=5.0,<6", "vl-convert-python>=1.0,<2", "polars>=1.17,<2"]

all = ["starboard-x[diagnostics,discovery,sparklog,warehouse,uc,cluster,charts]"]
```

Weight comparison (install footprint):

| Install | Pulls | Heavy binaries? |
|---|---|---|
| `starboard-x` | pydantic, structlog | none |
| `starboard-x[diagnostics]` | +pyyaml | none |
| `starboard-x[charts]` | +altair, **vl-convert-python** | one (isolated) |
| `starboard-x[discovery]` | +polars, sql-connector, sdk | polars/arrow |
| **`starboard` (server, for contrast)** | fastapi, uvicorn, starlette, openai, redis, asyncpg, pgvector, sqlite-vec, mcp, opentelemetry, … (`pyproject.toml:8-82`) | many |

**Source-of-truth options:** (a) `starboard-x` is a **new thin wheel** re-homing the modules (cleanest
deps, needs the trimmed `__init__`); or (b) it re-exports from `starboard-core` + a de-heavied slice of
`starboard` via `tool.uv.workspace` so there's no code copy. Given `starboard-core` already has the
analyzers + log parser + cloud extras (`core/pyproject.toml:19-33`), **extend `starboard-core` with the
diagnostic/discovery/chart modules and add these extras there**, exposing `starboard_x` as its CLI
namespace. This matches the decomposition Tier-0/Tier-1 split (`starboard_decomposition/recommendation.md:114-122`:
"no Tier-0 package may import databricks-sdk" — so keep pure diagnostics/charts free of the SDK).

---

## 5. Packaging the skills alongside the wheel

Two delivery vehicles, one skill source (fixing the current duplication/​drift noted in
`starboard_decomposition/opportunities.md:38`):

1. **Claude Code / Isaac plugin** — bundle `skills/starboard-*/SKILL.md` + `scripts/run.sh` under the
   plugin; `${CLAUDE_PLUGIN_ROOT}` resolves the script path (docs: plugin env vars). The plugin's
   README documents `pip install "starboard-x[…]"`. This is the same plugin the **agent_integration**
   topic specifies (`agent_integration/technical.md:23-68`); the middle tier just adds the Tier-1
   branch + `scripts/` to each skill.
2. **pip wheel** — vendor the same `skills/` into `starboard-x` so `starboard-x --install-skills`
   (or a documented copy step) drops them into `~/.claude/skills/`. Keep the skill body identical;
   only `${CLAUDE_SKILL_DIR}` vs `${CLAUDE_PLUGIN_ROOT}` differs by install path (both verified subs).

Frontmatter portability: keep to the six spec fields (`name, description, license, compatibility,
metadata, allowed-tools`) where the skill must also run in OpenCode `.opencode/skills/` or via the
claude.ai Skills API (docs: Using skill frontmatter outside Claude Code); use Claude-Code-only fields
(`context`, `argument-hint`, `when_to_use`) only in the Claude-Code copy.

---

## 6. End-to-end flow (what actually happens)

```
User: "job run 88123 failed with exit code 137"
  │
  ├─ L1: starboard-diagnostic description matched (only ~1.5KB was ever resident)
  ├─ L2: SKILL.md body loads (<500 lines) → picks Tier-1 branch
  ├─ Bash (pre-approved via allowed-tools, no prompt):
  │      ${CLAUDE_SKILL_DIR}/scripts/run.sh triage-exit --exit-code 137
  │        → python -m starboard_x.diagnostic  (imports ExitCodeTriager, stdlib only)
  │        → {"hypotheses":[{"type":"oom_kill","confidence":0.82,"next_steps":[…]}], …}
  └─ Claude reads compact JSON, explains + recommends.
Resident context afterward: ~1.5KB desc + <500-line body + small JSON. No analyzer source, no deps.
```

---

## 7. Build sequence (technical)

1. Extend `starboard-core` (or new `starboard-x`) with a **trimmed** re-home of the diagnostic
   modules (C1,C2,C6 first) + `starboard_x/diagnostic/__main__.py`; add `[diagnostics*]` extras (§4).
2. Author `starboard-diagnostic/SKILL.md` + `scripts/run.sh` + `reference.md` + `examples.md` (§2);
   verify no-prompt shell-out via `allowed-tools` + `${CLAUDE_SKILL_DIR}`.
3. Add `starboard_x.charts` + `[charts]` extra (isolated heavy dep); ship `starboard-analyze`/viz skill.
4. Add pure analyzers `starboard_x.warehouse analyze` (C10) + `starboard_x.uc analyze` (C13), polars extra.
5. Add `starboard_x.discovery run --data-only` (C8) wrapping `discovery/engine.py:97` with
   `EngineConfig(data_only=True)` (`:65`); `[discovery]` extra.
6. Add `starboard_x.sparklog parse` (C9) with loaders behind `[sparklog-aws|azure|gcp]`.
7. Add I/O service verbs (C11,C12,C14,C15) once the auth story from `databricks_auth/` is fixed.
8. Fold all Tier-1 branches into the canonical `skills/` and wire both the plugin and the wheel to it.
