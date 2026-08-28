# Host Setup Guide — Reproducing the Smoke Tests

This guide explains how to set up each Starboard host and reproduce the
per-host integration smoke tests locally.  The CI workflow
(`.github/workflows/test-host-coverage.yml`) runs the same test suite against a
clean install; follow these steps to replicate it.

**Quick start — run all smoke tests without any live host:**

```bash
export PATH="$PWD/.venv/bin:$PATH"
pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov
```

All five host test classes (Claude Code, Isaac, Codex, OpenCode, MCP server)
pass without live hosts.  Claude Code and Isaac tests check checked-in
artifacts; Codex and OpenCode invoke `python -m starboard_x.*` directly; the
MCP server test checks entry-point metadata only.

---

## Prerequisites

```bash
# 1. Python 3.12 (any 3.9+ works; 3.12 matches CI)
python --version   # must be >=3.9

# 2. uv (recommended) or pip
uv --version

# 3. Install workspace (installs all packages in editable mode)
make setup          # runs: uv venv + uv pip install -e packages/...
# or manually:
uv sync --all-extras

# 4. Activate the venv
export PATH="$PWD/.venv/bin:$PATH"
```

---

## Host 1: Claude Code

Claude Code discovers Starboard through its plugin marketplace.  The smoke
tests check the checked-in `plugin/` tree — no Claude Code installation needed.

### Artifact locations

| Artifact | Path |
|---|---|
| Plugin manifest | `plugin/.claude-plugin/plugin.json` |
| Skill definitions | `plugin/skills/<name>/SKILL.md` |
| Tier-1 entry points | `plugin/skills/<name>/scripts/run.sh` |
| Agent definitions | `plugin/agents/*.md` |

### Install into Claude Code (optional — not required for smoke tests)

```bash
# Option A: Marketplace (when published)
# Install via the Claude Code plugin marketplace using the plugin name "starboard".

# Option B: Local dev install via starboard-maint (when E1 task lands)
starboard-maint install --scope project   # installs into ./.claude/

# Option C: Manual copy
cp -r plugin/skills/* ~/.claude/skills/starboard/
cp -r plugin/agents/* ~/.claude/agents/
```

### Run the Claude Code smoke tests

```bash
pytest packages/starboard/tests/integration/host_coverage/test_host_coverage.py \
    -v --no-cov -k "TestClaudeCodeHost"
```

**What is tested:**
- `plugin.json` parses as valid JSON and has all required fields
- `plugin/skills/` contains at least 5 skill directories
- Every `SKILL.md` has valid frontmatter (`name`, `description`, `allowed-tools`)
- `SKILL.md` `name` field matches the containing directory name
- Skills with `scripts/run.sh` delegate to `python -m starboard_x.*`
- `allowed-tools` gates the `run.sh` invocation path
- No SKILL.md embeds hardcoded Databricks credentials
- `plugin.json` and SKILL.md content is stable across reads (idempotence)

---

## Host 2: Isaac

Isaac wraps Claude Code and uses the identical plugin bundle, plus
`plugin/rules/` for agent guidance rules deployed to `~/.isaac/rules/`.

### Artifact locations

| Artifact | Path |
|---|---|
| Same as Claude Code | `plugin/` (identical plugin bundle) |
| Baseline rules | `plugin/rules/starboard.md` |
| Per-domain rules | `plugin/rules/starboard-{domain}.md` (O7 task) |

### Install into Isaac (optional — not required for smoke tests)

```bash
# Option A: Marketplace (when published)
isaac plugin add starboard@databricks-marketplace

# Option B: Local dev install
starboard-maint install --scope project   # registers ./plugin, vendors skills

# Option C: Manual rules install
cp plugin/rules/starboard.md ~/.isaac/rules/
# Start an Isaac session:
isaac --claude
```

### Run the Isaac smoke tests

```bash
pytest packages/starboard/tests/integration/host_coverage/test_host_coverage.py \
    -v --no-cov -k "TestIsaacHost"
```

**What is tested:**
- Canonical `packages/starboard-skills/skills/starboard/` tree is present
- `plugin/rules/` directory exists with at least one `.md` ruleset
- All canonical SKILL.md files have `name` and `allowed-tools`
- Rule files are non-empty
- `scripts/run.sh` delegates to `python -m starboard_x.*`
- No rule file embeds hardcoded PATs (auth via SDK chain only)
- Canonical SKILL.md content and rule files are stable across reads

---

## Host 3: Codex

Codex has no plugin loader; it calls `python -m starboard_x.<capability>`
directly.  Install the `starboard-core` (or `starboard-kernel`) wheel and the
invocation path is ready.

### Install

```bash
# Install the tier-0 / tier-1 helper (required)
pip install "starboard-kernel[diagnostics,discovery,warehouse,uc,review]"
# or from the workspace:
uv pip install -e packages/starboard-core
```

### Invocation pattern

```bash
# Discovery
python -m starboard_x.discovery run [--host URL] [--profile NAME]

# Warehouse analysis (pure in-process, no SDK required)
python -m starboard_x.warehouse analyze --history '[]'

# UC analysis (pure in-process)
python -m starboard_x.uc analyze --input '{"columns": [...]}'

# Diagnostic triage
python -m starboard_x.diagnostic <exit_code> [--context "..."]

# All capabilities support --help
python -m starboard_x --help
python -m starboard_x.warehouse --help
```

### Environment / auth

```bash
# SDK credential chain (preferred)
export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_TOKEN=<pat>

# Or use a profile
python -m starboard_x.discovery run --profile my-profile
```

### Run the Codex smoke tests

```bash
pytest packages/starboard/tests/integration/host_coverage/test_host_coverage.py \
    -v --no-cov -k "TestCodexHost"
```

**What is tested:**
- `starboard_x` and all 6 capabilities are importable
- `starboard_x.contract` exposes `EXIT_OK/AUTH/NOT_FOUND/API/ARG` with correct values
- `python -m starboard_x --help` exits 0
- `python -m starboard_x.<cap> --help` exits 0 for each of the 6 capabilities
- `warehouse analyze --history '[]'` exits 0 and emits a valid JSON envelope
- `discovery run` with mock credentials exits gracefully (no unhandled exception)
- `AuthError.exit_code == 1` (auth chain maps to standard exit code)
- `--help` output and `warehouse analyze` envelope are identical on two runs

---

## Host 4: OpenCode

OpenCode uses the same invocation pattern as Codex (`python -m starboard_x.*`)
and additionally reads agent definition files from `plugin/agents/`.

### Install

Same as Codex (install the `starboard-kernel` wheel).

### Invocation pattern

Same as Codex.  OpenCode agent config files reference:
```
python -m starboard_x.<capability> [args]
```

### Run the OpenCode smoke tests

```bash
pytest packages/starboard/tests/integration/host_coverage/test_host_coverage.py \
    -v --no-cov -k "TestOpenCodeHost"
```

**What is tested:**
- `plugin/agents/` has at least 5 agent `.md` definition files
- Agent files are non-empty and contain markdown headings
- `starboard_x` is importable
- `python -m starboard_x --help` and per-capability `--help` exit 0
- At least one agent `.md` references `python -m starboard_x` or `starboard-helper`
- `uc analyze` with mock credentials exits gracefully
- No agent file embeds hardcoded PATs
- `warehouse --help` and agent file content are stable across runs

---

## Host 5: MCP Server (optional)

The MCP server is an additive channel that exposes Starboard's tools to hosts
that support the Model Context Protocol (Cursor, Claude Desktop, Claude Code).

### Install

```bash
pip install starboard          # includes starboard-mcp console script
# or from workspace:
uv pip install -e packages/starboard
```

### Start the server

```bash
# stdio transport (default; for Claude Desktop / Claude Code)
starboard-mcp

# Check available tools
starboard-mcp --help
```

### Auth configuration

```bash
# Databricks credentials (SDK chain — same as CLI)
export DATABRICKS_HOST=https://<workspace>.azuredatabricks.net
export DATABRICKS_TOKEN=<pat>
```

Full MCP server setup (Cursor, Claude Desktop config snippets, tool-scope
selection, troubleshooting) is documented in
[CLAUDE_CODE_INTEGRATION.md](../CLAUDE_CODE_INTEGRATION.md).

### Run the MCP smoke tests

```bash
pytest packages/starboard/tests/integration/host_coverage/test_host_coverage.py \
    -v --no-cov -k "TestMCPServerHost"
```

**What is tested:**
- `starboard.mcp.cli` is importable
- `starboard-mcp` is registered as a `console_scripts` entry point
- `starboard.mcp.cli.main` is callable
- `starboard-mcp` is on PATH or registered as entry point
- `starboard-mcp --help` exits 0 (when binary is on PATH)
- Importing `starboard.mcp.cli` does not trigger credential lookup
- Module identity is stable across imports (idempotence)
- Entry-point lookup returns consistent results on two calls

---

## Running the full host coverage suite

```bash
# All five hosts, verbose output, no coverage instrumentation
pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov

# Single host
pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov \
    -k "TestCodexHost"

# Specific check across all hosts
pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov \
    -k "discovery"

# With the distribution drift check (requires O5 to have landed)
make test-distribution
```

---

## CI configuration

The CI workflow at `.github/workflows/test-host-coverage.yml` runs the suite on
Ubuntu and macOS against Python 3.12 on every push to `main`, `phase1/**`, and
`wave4/**` branches.

To reproduce the CI run locally:

```bash
# Simulate the CI install step
uv sync --all-extras

# Run exactly what CI runs
pytest packages/starboard/tests/integration/host_coverage/ -v --no-cov -m integration
```

---

## Test matrix summary

| Host | Discovery | Invocation | Auth (mock) | Idempotence |
|---|---|---|---|---|
| **Claude Code** | plugin.json + SKILL.md valid | run.sh → `python -m starboard_x.*` | no hardcoded creds | plugin.json stable |
| **Isaac** | canonical skills + rules/ | same run.sh check | no PAT in rules | SKILL.md/rules stable |
| **Codex** | `starboard_x` importable | `--help` exits 0 per cap | mock creds → graceful exit | `--help` output stable |
| **OpenCode** | `starboard_x` + agents/ | `--help` exits 0 per cap | mock creds → graceful exit | `--help` output stable |
| **MCP server** | `mcp.cli` importable | `main` callable | import needs no creds | module identity stable |
