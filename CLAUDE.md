# CLAUDE.md — Starboard project context

Project context for coding agents (Claude Code, Cursor, Codex, etc.) working in this repo. Keep this
file and [`AGENTS.md`](AGENTS.md) command-accurate; they must agree with [`CONTRIBUTING.md`](CONTRIBUTING.md)
and the engineering standards under [`.cursor/`](.cursor/).

## What Starboard is

AI-powered Databricks workload analysis and optimization. It ships three surfaces over the same kernel:

- **CLI** (`starboard`) — a natural-language goal agent plus focused subcommands (`review`, `genie ask`, `auth`).
- **MCP server** (`starboard-mcp`) — optional tools server for Claude Code / Cursor / Claude Desktop.
- **Skills** — a Claude Code plugin (skills-only) mirrored from the canonical skills tree; reaches Isaac
  (which wraps Claude Code), and Codex/OpenCode via `python -m starboard_x.<capability>`.

`$` figures on the public path are **list-price DBU estimates** — label them as such. Finance-grade cost is
internal-only and not shipped here.

## Monorepo layout (5 packages, `uv` workspace)

```
packages/
├── starboard-core/          # Pure kernel: DTOs, ports, analyzers (starboard_core)
│                            #   + starboard_x/ progressive helpers (python -m starboard_x.<cap>)
├── starboard/               # FastAPI server + adapters + tools + CLI (the full experience wheel)
├── starboard-skills/        # Canonical skills tree + starboard-helper
├── starboard-internal/      # INTERNAL-ONLY gated port adapters — never in a public wheel
└── starboard-plugin-sample/ # Sample MCP-tools plugin (entry-point discovery demo)
```

Workspace members are declared in `[tool.uv.workspace]` in the root `pyproject.toml`. `starboard-internal`
is a workspace member for local dev/verification only; it is **not** a dependency of any public wheel.

## Architecture model

- **Kernel purity.** `starboard_core` / the `starboard_x` dep-light tiers must not import `databricks-sdk`,
  `openai`, `fastapi`, or `mcp`. Enforced by import-linter (4 contracts — see below).
- **Ports + internal-data gate.** Public packages ship the ports, the public adapters, the registry, and
  the `starboard.port_adapters` entry-point **contract**. Gated internal adapters live only in
  `starboard-internal` (`log_retrieval`, `diagnostic_backend`, `fleet_sql`, `nl_query`). The gate is
  **closed by default** (`internal_context_host_allowlist` is empty) and **additive**: closing it — or
  removing `starboard-internal` entirely — must leave a fully-functional public path.
- **State.** `database_backend` defaults to `"memory"`; the durable option is UC-native (`"uc"`).
  `sqlite`/`postgres`/`lakebase` are opt-in extras (`databricks` is a deprecated alias of `lakebase`).
- **RAG.** `vector_backend` defaults to `"none"` — on-disk curated reference files + query packs, not an
  embedding/vector DB. Managed Databricks Vector Search is opt-in behind `starboard[vectorsearch]`.
- **Memory/cache.** Semantic cache is TTL-only by default; reflexion is off by default.
- **Auth by subtraction.** One resolver (`starboard.infra.auth.resolver`) delegates to the SDK credential
  chain (`--profile`/ambient; PAT optional). Apps OBO via the `credentials_strategy` seam.
- **Public API facade.** `starboard/__init__.py` lazily re-exports the small public API the CLI composes
  (PEP 562). First-party CLI code imports from `starboard`, never from `starboard.infra`/`adapters`/`tools`
  internals (enforced by `tests/architecture/test_package_boundaries.py`).

## Key commands (tools live in `.venv/bin`)

```bash
export PATH="$PWD/.venv/bin:$PATH"   # ruff/mypy/pytest/mkdocs are here

make setup          # first-time env (uv venv + editable installs)
make check          # lint + type-check + test-unit + test-architecture  (the CI gate)
make lint           # ruff check
make type-check     # mypy
make test-unit      # core + starboard unit suites
make test-architecture             # import-linter (4 contracts, all KEPT)
make test-architecture-guidelines  # pytest tests/architecture/ (GUIDELINE-* suite)
make test-integration / test-golden / test-contract
make docs           # generate diagrams (scripts/generate_diagrams.py) + mkdocs build --strict
```

CLI smoke: `starboard --help`, `starboard review --help`, `starboard genie ask --help`,
`python -m starboard_x.review --help`.

## Import-linter contracts (all KEPT — do not break)

1. Kernel is free of `databricks-sdk` / `openai` / `fastapi` / `mcp`.
2. `starboard_x` diagnostics-core trio is stdlib-only (no SDK / heavy deps).
3. `starboard_x` pure analyzers (`warehouse`/`uc`/`review`) are SDK-free.
4. Public packages import no `starboard_internal`.

Config in `[tool.importlinter]` (root `pyproject.toml`). Run: `lint-imports` (or `make test-architecture`).

## Governance red-lines (public packages)

- No internal namespaces in public code/docs: `centralized_system_tables`, `fin_live_gold`, `gtm_*`,
  `eng_*`, `logfood`, ClickHouse, `hmr_stack_hash`, internal shortlinks. These live only in
  `starboard-internal`. Grep before every commit.
- No capability regression: every public import path, CLI command, skill, config value, port, and backend
  keeps working. Prefer deleting truly-dead code (with unreachability evidence) over deprecation.
- `$` = list-price DBU estimates on the public path.

## Key files

- Config: `packages/starboard/starboard/infra/core/config.py`; env template: `examples/env.example`.
- CLI entry: `starboard.cli.main:main`; MCP: `starboard.mcp.cli:main`.
- Workload Review: `starboard.tools.services.workload_review_service`, `validator_council.py`.
- Skills (canonical): `packages/starboard-skills/skills/starboard/`; plugin bundle: `plugin/`.
- Build/workflow: `Makefile`; packaging + contracts: root `pyproject.toml`.

## Standards & further docs

Engineering standards live in [`.cursor/01_engineering_standards.md`](.cursor/) … `08_frontend_standards.md`.
User/developer/ops docs are under [`docs/`](docs/) (built with MkDocs). Contribution workflow:
[`CONTRIBUTING.md`](CONTRIBUTING.md) → [`docs/guides/CONTRIBUTING.md`](docs/guides/CONTRIBUTING.md).
Agent operating rules: [`AGENTS.md`](AGENTS.md).
