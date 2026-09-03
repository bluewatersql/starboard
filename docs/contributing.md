# Contributing

Practical developer guide for Starboard. Deep engineering standards live in the repo-root files linked at the bottom — this page stays lean.

---

## Dev setup

**Prerequisites**: Python 3.12+, [`uv`](https://github.com/astral-sh/uv) (recommended).

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# First-time setup — creates .venv, installs all 5 packages editable + dev/test deps
make setup

# Copy and fill in credentials
cp examples/env.example .env
```

Tools (`ruff`, `mypy`, `pytest`, `mkdocs`, `lint-imports`) land in `.venv/bin`:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

To reinstall or pick up dependency changes: `make install-dev` (or `uv sync --all-packages --all-extras`).

---

## Quality gate

`make check` is the CI gate — it must pass before merge:

```bash
make check      # lint + type-check + test-unit + test-architecture
```

### Key make targets

| Target | What it does |
|--------|-------------|
| `make setup` | First-time env setup |
| `make check` | **CI gate**: lint + type-check + test-unit + test-architecture |
| `make lint` | ruff: PEP 8, imports, complexity |
| `make format` | ruff: auto-fix formatting + import sorting |
| `make type-check` | mypy (strict) |
| `make test-unit` | Package unit suites (`packages/*/tests/unit/`) |
| `make test-architecture` | import-linter: 4 kernel-purity contracts |
| `make test-architecture-guidelines` | pytest `tests/architecture/` GUIDELINE-* suite |
| `make test-integration` | Cross-component integration tests |
| `make test-golden` | Prompt/schema snapshot tests (`tests/golden/`) |
| `make test-contract` | Agent/tool output-contract tests (`tests/contract/`) |
| `make test-coverage` | Coverage report (HTML in `packages/starboard/htmlcov/`) |
| `make docs` | `mkdocs build --strict` (docs use inline mermaid) |
| `make docs-serve` | Local docs preview at `http://localhost:8000` |
| `make vendor-skills` | Mirror canonical skills into `plugin/skills/` |
| `make vendor-skills-check` | Fail if `plugin/skills/` has drifted |
| `make build` | Build wheels for the 3 public packages |
| `make clean` | Remove caches, coverage, dist artifacts |
| `make clean-deep` | Also removes `.venv` (re-run `make setup` after) |
| `make info` | Show env: package manager, Python version, tools |

---

## Test organization

```
packages/
  starboard-core/tests/unit/        # kernel + starboard_x unit tests
  starboard/tests/
    unit/                           # starboard unit tests
    integration/                    # package integration tests
    golden/                         # prompt/schema snapshots

tests/                              # cross-cutting suites (run from repo root)
  integration/
  golden/
  contract/                         # agent/tool output-contract tests
  architecture/                     # GUIDELINE-* pytest fitness suite
  benchmarks/
```

The 4 import-linter contracts run via `make test-architecture`; their declarations are in root `pyproject.toml`. See [Architecture](architecture.md) for what each contract enforces.

### Running tests directly

```bash
# Per package (from package dir)
cd packages/starboard && pytest tests/unit/ -v

# Cross-cutting suites (from repo root)
pytest tests/golden/ tests/contract/ tests/architecture/

# With coverage
cd packages/starboard
pytest --cov=starboard --cov-report=html

# Useful flags
pytest -m unit            # unit marker only
pytest -m "not slow"      # skip slow tests
pytest -x                 # stop on first failure
pytest --lf               # re-run last failed
pytest -k "test_tool"     # name pattern
pytest -n auto            # parallel execution
```

**Coverage targets**: ≥80% overall; 100% for domain logic, agent policies, schema validators, tool routers.

### Golden tests

Golden tests snapshot LLM prompts and data-transformation outputs. Update them only when a change is intentional:

```bash
pytest tests/golden/ --snapshot-update   # update syrupy snapshots
```

Review the diff carefully before committing.

---

## Code conventions (brief)

- **Three-layer tool architecture**: Domain (pure logic, no I/O) → Service (orchestration + I/O) → Adapter (agent-facing). Never put I/O in the domain layer.
- **Immutable data**: `@dataclass(frozen=True)`.
- **Type hints** on all public functions/methods; mypy strict must pass.
- **Structured logging**: `get_logger(__name__)` from `starboard.infra.observability.logging`.
- **Kernel purity**: nothing in `starboard_core` may import `databricks-sdk` / `openai` / `fastapi` / `mcp` (enforced by import-linter).

See [Architecture](architecture.md) for the full boundary model and the 4 import-linter contracts.

---

## Commit conventions

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>
```

Common types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`.

Examples:
```
feat(tools): add analyze_cluster_costs tool
fix(agents): fix infinite loop in QueryAgent
docs: update architecture doc
test(tools): add integration tests for warehouse service
```

---

## PR workflow

1. Fork → create branch (`feature/*`, `fix/*`, `docs/*`).
2. Run `make check` locally — all checks must pass.
3. Open PR; fill out the template; link related issues (`Fixes #123`).
4. Automated checks run; maintainer review within 2–3 days.
5. Merge via standard merge commit (not squash), so release tags point to meaningful commits.

**PR checklist**: lint passes, type-check passes, tests pass, coverage targets met, docs updated if you added a tool/agent/API.

---

## Release process

Starboard follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`). Releases are currently cut manually by a maintainer.

| Package | Distribution |
|---------|-------------|
| `starboard-core`, `starboard`, `starboard-skills` | Public PyPI |
| `starboard-internal` | Internal index only — never in a public wheel |
| `starboard-plugin-sample` | Reference scaffold only |

**Flow:**

1. Create branch `release/vX.Y.Z` from `main`.
2. Bump `version` in every package `pyproject.toml` (5 files + workspace root `starboard-meta`).
3. Update `CHANGELOG.md` (root): rename `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`; add new empty `[Unreleased]`.
4. Mirror the entry in `docs/overview/changelog.md`.
5. `make check` — fix any failures.
6. Open PR `chore: release vX.Y.Z`; get one maintainer review; merge.
7. Tag and push: `git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push upstream vX.Y.Z`.
8. Create GitHub Release; paste the CHANGELOG entry as the description.

Pre-release suffixes: `-alpha.N`, `-beta.N`, `-rc.N` (e.g. `0.2.0-rc.1`).

`CHANGELOG.md` (root) is the authoritative source for package version history. `docs/overview/changelog.md` mirrors it for the docs site — keep both in sync on every release.

---

## Further reading

| Resource | Location (repo root) |
|---------|---------|
| Engineering standards (01–08) | `.cursor/01_engineering_standards.md` … `.cursor/08_frontend_standards.md` |
| Full contribution workflow, code of conduct | `CONTRIBUTING.md` |
| Agent operating rules | `AGENTS.md` |
| Architecture & import contracts | [Architecture](architecture.md) |
| Changelog | [Changelog](overview/changelog.md) |
