# Contributing to Starboard

Thanks for contributing! This is the short version — the full guide is
[`docs/contributing.md`](docs/contributing.md). If you are a coding agent, also read
[`AGENTS.md`](AGENTS.md) and [`CLAUDE.md`](CLAUDE.md).

## Quick start

```bash
make setup                       # first-time environment (uv venv + editable installs)
cp examples/env.example .env     # then edit with your Databricks + LLM credentials
export PATH="$PWD/.venv/bin:$PATH"   # ruff/mypy/pytest/mkdocs live in .venv/bin
```

## Before you open a PR

```bash
make format         # auto-format (ruff)
make check          # lint + type-check + test-unit + test-architecture  (the CI gate)
```

For larger changes also run `make test-integration`, `make test-golden`, `make test-contract`, and
`make test-architecture-guidelines`. Docs changes: `make docs` (builds diagrams + mkdocs `--strict`).

## Ground rules

- **Smallest safe change**; preserve public APIs, CLI commands, skills, config keys, ports, and backends
  (no capability regression). Add/update tests for every change.
- **Keep the 4 import-linter contracts KEPT** (kernel purity + the public↔internal boundary).
- **Governance:** no internal namespaces in public packages; internal adapters live only in
  `starboard-internal`; `$` = list-price DBU estimates. See [`CLAUDE.md`](CLAUDE.md) for the full red-lines.
- Use [Conventional Commits](https://www.conventionalcommits.org/) and open PRs against `main`.

Full workflow, code standards, testing requirements, and the PR/review process:
[`docs/contributing.md`](docs/contributing.md).
