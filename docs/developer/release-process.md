---
title: Release Process
description: How to cut a versioned release of Starboard AI Agent.
last_reviewed: 2026-06-25
status: current
---

# Release Process

> **Docs** > **Developer** > **Release Process**

This document describes the steps a maintainer follows to publish a new version of Starboard AI Agent. It is intentionally a starter guide — CI release automation is not yet wired up and steps are performed manually.

---

## Table of Contents

1. [Versioning Scheme](#versioning-scheme)
2. [Branch and Tag Conventions](#branch-and-tag-conventions)
3. [Pre-Release Checklist](#pre-release-checklist)
4. [Step-by-Step Release Flow](#step-by-step-release-flow)
5. [CHANGELOG Maintenance](#changelog-maintenance)
6. [Post-Release](#post-release)
7. [Known Inconsistency: Two Changelogs](#known-inconsistency-two-changelogs)

---

## Versioning Scheme

Starboard follows [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH
```

| Increment | When to use |
|-----------|-------------|
| `MAJOR` | Backward-incompatible API or protocol changes |
| `MINOR` | New features that are backward compatible |
| `PATCH` | Backward-compatible bug fixes and security patches |

All five packages (`starboard-core`, `starboard-server`, `starboard-log-parser`, `starboard-cli`, `starboard-sdk`) and the workspace root share a single version number and are released together. The current development version is `0.1.0`.

Pre-release versions use the suffix `-alpha.N`, `-beta.N`, or `-rc.N` (e.g., `0.2.0-rc.1`).

---

## Branch and Tag Conventions

| Ref | Pattern | Purpose |
|-----|---------|---------|
| Main branch | `main` | Stable, always releasable |
| Feature branches | `feature/<description>` | New work; merged via PR |
| Fix branches | `fix/<description>` | Bug or security fix |
| Release tags | `v<MAJOR>.<MINOR>.<PATCH>` | Immutable tag on `main` for every release |
| Release candidate tags | `v<MAJOR>.<MINOR>.<PATCH>-rc.<N>` | Optional pre-release tagging |

There are no long-lived release branches at this stage of the project. Patch releases are cut directly from `main` after cherry-picking any necessary fixes.

---

## Pre-Release Checklist

Before cutting a release, verify:

- [ ] All tests pass: `make test`
- [ ] Type checking passes: `make type-check`
- [ ] Linting passes: `make lint`
- [ ] Coverage targets are met: `make test-coverage`
- [ ] Golden tests are up to date: `make test-golden`
- [ ] No open security advisories on pinned dependencies (`pip-audit`, `npm audit`)
- [ ] `CHANGELOG.md` (root) has entries for the new version under `## [Unreleased]`
- [ ] `docs/overview/changelog.md` is consistent with `CHANGELOG.md` (see [Known Inconsistency](#known-inconsistency-two-changelogs))
- [ ] All package `pyproject.toml` versions match the intended release version
- [ ] `frontend/package.json` version matches the intended release version (if versioned separately)

---

## Step-by-Step Release Flow

### 1. Confirm the target version

Decide the next version (e.g., `0.2.0`) following the versioning scheme above.

### 2. Create a release-prep branch

```bash
git checkout main
git pull upstream main
git checkout -b release/v0.2.0
```

### 3. Bump version numbers

Update the `version` field in every package `pyproject.toml`:

```
packages/starboard-core/pyproject.toml
packages/starboard-server/pyproject.toml
packages/starboard-log-parser/pyproject.toml
packages/starboard-cli/pyproject.toml
packages/starboard-sdk/pyproject.toml
pyproject.toml  (workspace root)
```

And in `frontend/package.json` if the frontend is versioned with the release.

### 4. Update CHANGELOG.md

In `CHANGELOG.md` at the repo root:

1. Rename the `## [Unreleased]` section to `## [0.2.0] - YYYY-MM-DD`.
2. Add a new empty `## [Unreleased]` section at the top with the standard subsections (`Added`, `Changed`, `Fixed`, `Removed`, `Security`).
3. Update the comparison link at the bottom of the file if present.

### 5. Update docs/overview/changelog.md

Mirror the same version entry in `docs/overview/changelog.md` so that the MkDocs documentation site stays in sync (see [Known Inconsistency](#known-inconsistency-two-changelogs) for background).

### 6. Run final checks

```bash
make check   # lint + type-check + test
```

Fix any failures before proceeding.

### 7. Open and merge a pull request

Push the release-prep branch and open a PR titled `chore: release v0.2.0`. Request a review from at least one other maintainer. Merge using a standard merge commit (not squash) so that the tag points to a meaningful commit.

### 8. Tag the release

After the PR is merged to `main`:

```bash
git checkout main
git pull upstream main
git tag -a v0.2.0 -m "Release v0.2.0"
git push upstream v0.2.0
```

### 9. Create a GitHub Release

On GitHub, go to **Releases > Draft a new release**, select the `v0.2.0` tag, and paste the relevant section from `CHANGELOG.md` as the release description. Attach any built artifacts if applicable.

---

## CHANGELOG Maintenance

Keep `CHANGELOG.md` up to date as part of normal development:

- Every merged PR that changes user-visible behavior should include a `CHANGELOG.md` update.
- Use the standard [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) subsections: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.
- Security fixes should always appear under `Security`, even if they also appear elsewhere.
- Never delete `## [Unreleased]`; new work always goes there first.

Commit message convention for changelog-only commits:

```
docs(changelog): add entry for <feature/fix>
```

---

## Post-Release

After the release tag is pushed and the GitHub Release is created:

1. Announce the release in the project's GitHub Discussions or community channels.
2. Open a follow-up issue for any items intentionally deferred from this release.
3. Verify that the MkDocs site (`make docs-build`) renders the new changelog entry correctly.
4. Monitor the issue tracker for regressions in the first 48 hours.

---

## Known Inconsistency: Two Changelogs

The repository currently maintains **two separate changelog files**:

| File | Audience | Format |
|------|----------|--------|
| `CHANGELOG.md` (root) | Developers, GitHub visitors | Keep a Changelog + semver; currently only has `[Unreleased]` and `[0.1.0]` |
| `docs/overview/changelog.md` | End users via MkDocs site | Same format but richer history going back to `1.0.0` |

The two files diverged during an earlier documentation overhaul: `docs/overview/changelog.md` reflects the docs versioning (`1.0.0`, `1.1.0`, `1.2.0`) while `CHANGELOG.md` reflects the package versioning (`0.1.0`). This is tracked as finding **F-3-1c-008** in the OSS readiness backlog.

**Interim guidance until reconciled:**

- Keep both files updated on every release.
- `CHANGELOG.md` is the authoritative source for package version history.
- `docs/overview/changelog.md` is the authoritative source for the documentation site's release notes.
- A future cleanup task will merge these into a single source of truth (see `F-3-1c-008`).

---

## Related Documents

- [Contributing Guide](../guides/CONTRIBUTING.md) — PR workflow and commit conventions
- [CHANGELOG.md](../../CHANGELOG.md) — Root changelog
- [docs/overview/changelog.md](../overview/changelog.md) — Docs-site changelog
- [Engineering Standards](./standards/) — Code quality requirements
