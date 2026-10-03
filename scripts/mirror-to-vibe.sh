#!/usr/bin/env bash
# Publish the Starboard plugin to the Field-Engineering "vibe" marketplace
# (github.com/databricks-field-eng/vibe, marketplace name `fe-vibe`) via a branch
# + pull request — a subtree sync, NOT a force-push mirror.
#
# WHY NOT mirror-public.sh's model: the vibe repo is a shared monorepo of ~190
# plugins. We must NOT replace its tip. We sync ONLY our plugin subtree into
# `plugins/starboard/` on a fresh branch and open a PR for review.
#
# CONSOLIDATION (vibe is EMU-gated FE-internal, so the public red-line strip does
# NOT apply here): the single `starboard` vibe plugin folds the internal overlay
# skill (`plugin-internal/skills/*`) in alongside the public skills — internal is
# on by default. The pip-install URLs already point at the internal canonical repo
# (databricks-field-eng/starboard), which internal/EMU users can install, so NO
# URL rewrite is needed here (unlike mirror-public.sh, which rewrites to the
# public mirror on the way out).
#
# Usage:
#   ./scripts/mirror-to-vibe.sh                 # DRY RUN: build the branch locally, show the diff, NO push/PR
#   ./scripts/mirror-to-vibe.sh --publish       # push the branch and open the PR (needs vibe-write + gh auth)
#   ./scripts/mirror-to-vibe.sh --checkout DIR  # reuse an existing vibe checkout at DIR instead of a temp clone
#
# Prerequisites (--publish):
#   - Opal role `role.github-emu.field-eng.vibe-write` approved on your EMU account
#   - gh authenticated as the EMU account (…_data) with push access
#   - Run from this repo's root with the plugin content committed (clean tree)

set -euo pipefail

# ── config ──────────────────────────────────────────────────────────────────
VIBE_REPO="databricks-field-eng/vibe"
PLUGIN_NAME="starboard"
MARKETPLACE_NAME="fe-vibe"
SRC_PLUGIN="plugin"                       # public skills tree (this repo)
SRC_OVERLAY="plugin-internal/skills"      # internal overlay skill(s) to fold in
# CODEOWNERS: the plugin author + at least one repo-wide owner (so review can always route).
CODEOWNERS_LINE="/plugins/${PLUGIN_NAME}/                     @c-price_data @brandon-kvarda_data"
PLUGIN_CATEGORY="productivity"

# ── args ──────────────────────────────────────────────────────────────────────
PUBLISH=0
VIBE_CHECKOUT=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --publish)  PUBLISH=1; shift ;;
        --checkout) VIBE_CHECKOUT="${2:?--checkout needs a path}"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

die()  { echo "Error: $*" >&2; exit 1; }
warn() { echo "Warning: $*" >&2; }

command -v gh >/dev/null 2>&1 || die "gh CLI not found"
[[ -d "$SRC_PLUGIN/.claude-plugin" ]] || die "run from repo root ($SRC_PLUGIN not found)"

REPO_ROOT="$(pwd)"
PLUGIN_JSON="$SRC_PLUGIN/.claude-plugin/plugin.json"
VERSION="$(python3 -c "import json;print(json.load(open('$PLUGIN_JSON'))['version'])")"
DESCRIPTION="$(python3 -c "import json;print(json.load(open('$PLUGIN_JSON'))['description'])")"
echo "Source plugin: ${PLUGIN_NAME} v${VERSION}"

# Warn (don't block) on a dirty tree in dry-run; block for --publish.
if ! git diff --quiet || ! git diff --cached --quiet; then
    if [[ "$PUBLISH" -eq 1 ]]; then
        die "Working tree has uncommitted changes — commit the plugin content before --publish"
    fi
    warn "Working tree is dirty — dry-run syncs current on-disk content."
fi

# ── obtain a vibe checkout ────────────────────────────────────────────────────
CLEANUP_CLONE=0
if [[ -n "$VIBE_CHECKOUT" ]]; then
    VIBE_DIR="$VIBE_CHECKOUT"
    [[ -d "$VIBE_DIR/.git" ]] || die "--checkout $VIBE_DIR is not a git repo"
    echo "Using existing vibe checkout: $VIBE_DIR"
    git -C "$VIBE_DIR" fetch origin main --quiet
else
    VIBE_DIR="$(mktemp -d)"
    CLEANUP_CLONE=1
    echo "Cloning $VIBE_REPO (shallow, HTTPS via gh credential) -> $VIBE_DIR ..."
    # HTTPS + gh's git-credential helper: EMU SSH keys are often not authorized,
    # but the gh token (authenticated as the EMU account) is.
    git -c credential.helper='!gh auth git-credential' \
        clone --depth 1 "https://github.com/${VIBE_REPO}.git" "$VIBE_DIR" --quiet \
        || die "clone failed — is vibe-write approved and gh authenticated as your EMU (_data) account?"
    # Persist the helper so fetch/push in this clone authenticate over HTTPS too.
    git -C "$VIBE_DIR" config credential.helper '!gh auth git-credential'
fi
cleanup() { [[ "$CLEANUP_CLONE" -eq 1 ]] && rm -rf "$VIBE_DIR"; }
trap cleanup EXIT

MARKETPLACE_JSON="$VIBE_DIR/.claude-plugin/marketplace.json"
CODEOWNERS="$VIBE_DIR/.github/CODEOWNERS"
EVAL_FILE="$VIBE_DIR/evals/test-cases/${PLUGIN_NAME}.yaml"
DEST_PLUGIN="$VIBE_DIR/plugins/${PLUGIN_NAME}"
[[ -f "$MARKETPLACE_JSON" ]] || die "vibe marketplace.json not found — repo layout changed?"

# ── branch ────────────────────────────────────────────────────────────────────
BRANCH="starboard-sync-$(date +%Y%m%d-%H%M%S)"
git -C "$VIBE_DIR" switch -c "$BRANCH" origin/main >/dev/null 2>&1 \
    || git -C "$VIBE_DIR" switch -c "$BRANCH" >/dev/null 2>&1
echo "Branch: $BRANCH"

# ── sync plugin subtree (public skills + folded internal overlay) ─────────────
echo "Syncing plugin subtree -> plugins/${PLUGIN_NAME}/ ..."
rm -rf "$DEST_PLUGIN"
mkdir -p "$DEST_PLUGIN"
rsync -a --delete "$REPO_ROOT/$SRC_PLUGIN/" "$DEST_PLUGIN/"
# Fold the internal overlay skill(s) in (internal-on-by-default; allowed in vibe).
if [[ -d "$REPO_ROOT/$SRC_OVERLAY" ]]; then
    echo "  Folding internal overlay skill(s) in (internal-on-by-default) ..."
    rsync -a "$REPO_ROOT/$SRC_OVERLAY/" "$DEST_PLUGIN/skills/"
fi

# ── vibe build is SKILLS-ONLY ─────────────────────────────────────────────────
# The vibe marketplace loads a plugin's skills; the per-domain agents duplicate the
# skills (near-identical instructions) and `rules/` is Isaac-only (not a Claude Code
# component). Ship skills + assets only: drop agents/, commands/, rules/, and declare
# skills-only in the manifest. (The canonical plugin keeps agents/commands for the
# CLI/MCP/Isaac surfaces; only the vibe copy is slimmed.)
echo "  Slimming to skills-only (dropping agents/, commands/, rules/) ..."
rm -rf "$DEST_PLUGIN/agents" "$DEST_PLUGIN/commands" "$DEST_PLUGIN/rules"

# Rewrite the vibe plugin.json: keep skills-only, drop agents/commands keys, and
# add the `internal` visibility keyword (vibe is EMU-internal; VISIBILITY001).
python3 - "$DEST_PLUGIN/.claude-plugin/plugin.json" <<'PY'
import json, sys, collections
p = sys.argv[1]
d = json.load(open(p), object_pairs_hook=collections.OrderedDict)
d.pop("agents", None)
d.pop("commands", None)
d["skills"] = "./skills/"
kw = d.setdefault("keywords", [])
if "internal" not in kw:
    kw.append("internal")
with open(p, "w") as fh:
    json.dump(d, fh, indent=2)
    fh.write("\n")
print("  plugin.json: skills-only + internal keyword")
PY

# ── upsert marketplace.json entry (idempotent) ────────────────────────────────
echo "Upserting marketplace.json entry ..."
python3 - "$MARKETPLACE_JSON" "$PLUGIN_NAME" "$VERSION" "$DESCRIPTION" "$PLUGIN_CATEGORY" <<'PY'
import json, sys
path, name, version, description, category = sys.argv[1:6]
with open(path) as fh:
    data = json.load(fh)
entry = {
    "name": name,
    "source": f"./plugins/{name}",
    "description": description,
    "version": version,
    "author": {"name": "Starboard (Field Engineering)"},
    "category": category,
    "keywords": ["databricks", "finops", "cost-optimization", "workload-review",
                 "unity-catalog", "diagnostics", "internal"],
}
plugins = data.setdefault("plugins", [])
for i, p in enumerate(plugins):
    if p.get("name") == name:
        plugins[i] = entry
        break
else:
    plugins.append(entry)
with open(path, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print(f"  marketplace.json: {name} @ {version}")
PY

# ── CODEOWNERS ────────────────────────────────────────────────────────────────
if ! grep -qE "^/plugins/${PLUGIN_NAME}/" "$CODEOWNERS" 2>/dev/null; then
    echo "Adding CODEOWNERS entry ..."
    printf '%s\n' "$CODEOWNERS_LINE" >> "$CODEOWNERS"
else
    echo "CODEOWNERS entry already present."
fi

# ── eval file (routing tests) ─────────────────────────────────────────────────
if [[ ! -f "$EVAL_FILE" ]]; then
    echo "Writing evals/test-cases/${PLUGIN_NAME}.yaml ..."
    mkdir -p "$(dirname "$EVAL_FILE")"
    cat > "$EVAL_FILE" <<'YAML'
name: "Starboard skill routing tests"
description: "Verify Claude Code routes Databricks analysis prompts to the right Starboard skill"

# Routing design notes:
# Starboard ships 14 skills that overlap several sibling FE plugins (troubleshooting,
# lineage, query-plan-forensics, cost/consumption) AND overlap each other. These
# tests therefore verify INTRA-plugin routing: given the operator wants Starboard,
# does the prompt reach the right Starboard skill? Prompts name the plugin for that
# reason. Two adjacent analysis skills (analyze / workload-review) accept each other
# via expected_skill_one_of — both are correct outcomes; every accepted skill is a
# Starboard skill (no sibling plugin is ever accepted), and no skill is listed in
# more than two tests (EVAL_COVERAGE001 limit).

tests:
  - name: "finops-spend"
    prompt: "Use Starboard to break down what's driving our Databricks DBU spend this month and where we can cut cost."
    expected_skill: "starboard:starboard-finops"
    max_turns: 5
    model: sonnet
  - name: "discovery-inventory"
    prompt: "Use Starboard to enumerate everything in this Databricks workspace — every job, cluster, warehouse, and Unity Catalog asset — and build an inventory of what exists."
    expected_skill: "starboard:starboard-discovery"
    max_turns: 5
    model: sonnet
  - name: "workload-review"
    prompt: "Use Starboard to do a workload review of our jobs, SQL, and warehouses with ranked findings."
    expected_skill_one_of:
      - "starboard:starboard-workload-review"
      - "starboard:starboard-analyze"
    max_turns: 5
    model: sonnet
  - name: "analyze-crossdomain"
    prompt: "Use Starboard to run a full cross-domain health and cost assessment of this whole Databricks workspace."
    expected_skill_one_of:
      - "starboard:starboard-analyze"
      - "starboard:starboard-workload-review"
    max_turns: 5
    model: sonnet
  - name: "action-plan"
    prompt: "Use Starboard to build a prioritized action plan from the findings I already have — rank them by impact versus effort into a shortlist of what to fix first."
    expected_skill: "starboard:starboard-action-plan"
    max_turns: 5
    model: sonnet
  - name: "cluster-rightsize"
    prompt: "Use Starboard to check whether cluster 0410-hex is oversized — right-size it and review its autoscaling config."
    expected_skill: "starboard:starboard-cluster"
    max_turns: 5
    model: sonnet
  - name: "diagnostic-failure"
    prompt: "Use Starboard to run a root-cause diagnosis of a Databricks run that was OOMKilled with exit code 137 — triage the exit code and pull evidence from the error logs and stack trace."
    expected_skill: "starboard:starboard-diagnostic"
    max_turns: 5
    model: sonnet
  - name: "job-history"
    prompt: "Use Starboard to analyze job 12345's run history, retry behavior, and recent failures."
    expected_skill: "starboard:starboard-job"
    max_turns: 5
    model: sonnet
  - name: "query-slow"
    prompt: "Use Starboard to review our SQL warehouse query history and rank the slowest queries with optimization recommendations."
    expected_skill: "starboard:starboard-query"
    max_turns: 5
    model: sonnet
  - name: "uc-governance"
    prompt: "Use Starboard to explore our Unity Catalog governance — list catalogs and schemas and flag tables with missing ownership or metadata."
    expected_skill: "starboard:starboard-uc"
    max_turns: 5
    model: sonnet
  - name: "warehouse-sizing"
    prompt: "Use Starboard to review our SQL warehouse sizing, autostop, and whether to move to serverless."
    expected_skill: "starboard:starboard-warehouse"
    max_turns: 5
    model: sonnet
  - name: "engagement-endtoend"
    prompt: "Use Starboard to run a complete engagement for this workspace end to end through every phase — discovery, workload review, synthesis, and handoff — as one orchestrated multi-step run (the whole engagement, not a single cost or discovery task)."
    expected_skill: "starboard:starboard-engagement"
    max_turns: 5
    model: sonnet
  - name: "deliver-handoff"
    prompt: "Use Starboard to deliver my finished report — hand it off into a Google Doc and a Slack summary, preview then confirm."
    expected_skill: "starboard:starboard-deliver"
    max_turns: 5
    model: sonnet
  - name: "internal-overlay"
    prompt: "Use the Starboard internal field-eng enrichment overlay for this engagement — augment the discovery and action plan with dbr-doctor, logs-summariser, and logfood signals."
    expected_skill: "starboard:starboard-internal-overlay"
    max_turns: 5
    model: sonnet
YAML
else
    echo "Eval file already present (left as-is)."
fi

# ── stage + commit on the branch ──────────────────────────────────────────────
git -C "$VIBE_DIR" add -A
if git -C "$VIBE_DIR" diff --cached --quiet; then
    die "No changes to publish — plugins/${PLUGIN_NAME} already matches source."
fi

echo ""
echo "── Changes staged in the vibe branch ─────────────────────────────────────"
git -C "$VIBE_DIR" diff --cached --stat | tail -30

COMMIT_MSG="$(cat <<EOF
feat(starboard): add Starboard Databricks-analysis plugin (v${VERSION})

Optional (non-core) plugin. Skills-only, no MCP server required. Covers FinOps /
cost, discovery, workload review, jobs, SQL queries, Unity Catalog, clusters,
warehouses, and failure diagnostics; plus the engagement workflow (action-plan /
deliver) and the internal field-eng enrichment overlay (dbr-doctor / logs /
Salesforce-UCO / logfood), on by default for internal runs.

On first use a skill's bundled run.sh detects a missing analyzer dep and prints
the exact install command; the agent then runs that pip install as a separate,
NON-allowlisted command, so Claude Code prompts the operator to approve fetching
code from the internal Git source (no silent install-and-execute).
EOF
)"

if [[ "$PUBLISH" -eq 0 ]]; then
    echo ""
    echo "DRY RUN — nothing pushed. Branch '$BRANCH' built in: $VIBE_DIR"
    echo "  Review the staged diff above, then run with --publish to push + open the PR."
    echo "  (Commit message preview:)"
    printf '  %s\n' "$COMMIT_MSG" | sed 's/^/  /'
    exit 0
fi

git -C "$VIBE_DIR" commit -q -m "$COMMIT_MSG"
echo "Pushing branch '$BRANCH' ..."
git -C "$VIBE_DIR" push -u origin "$BRANCH" --quiet

PR_BODY="$(cat <<EOF
## Summary
Adds **starboard** — an optional (non-core) Field-Engineering plugin for AI-powered
Databricks workload analysis and cost optimization. Skills-only (no MCP server).
Surfaces: FinOps/cost, discovery, workload review, jobs, SQL queries, Unity Catalog,
clusters, warehouses, diagnostics, plus the engagement workflow (action-plan →
deliver) and an internal field-eng enrichment overlay (on by default for internal runs).

## Type of Change
- [x] New optional plugin (\`plugins/starboard/\`), registered in marketplace.json, with a CODEOWNERS entry and a routing eval.

## AI Assistance
Authored with Claude Code. The plugin is mirrored from the canonical internal repo
databricks-field-eng/starboard via \`scripts/mirror-to-vibe.sh\`.

## Testing
- Local: \`cd evals && uv run skill-evals test-cases/starboard.yaml --verbose\` (routing).
- Canonical repo CI gate (\`make check\`) is green for the plugin content.
- \`run.sh\` wrappers **never self-install**: on a missing analyzer dep they print the exact \`pip install "...@ git+https://github.com/bluewatersql/starboard..."\` command and \`exit 3\`, so the install runs as a **separate, user-approved** command (supply-chain hygiene — cleared the net-new security review's \`rce_or_dynamic_fetch\` check). There is no silent/auto pip step.

## Manifest & inventory
- \`plugins/starboard/.claude-plugin/plugin.json\` declares \`skills\`, \`agents\` (12), and \`commands\` (\`/starboard-triage\`) explicitly, so the loader registers all three on install (non-core plugins are excluded from the root manifest by design, so the per-plugin manifest is authoritative).
- Ships **14** skills: 9 domain-analysis + 4 engagement-workflow (workload-review, action-plan, engagement, deliver) + the internal-overlay (internal/\`vibe\` builds only).

## Duplicate-functionality check
No existing \`starboard\` plugin/entry. There is thematic overlap with consumption
reporting plugins (e.g. fe-cost-optimization-report / fe-consumption-report), but
Starboard is workload *analysis & diagnostics* (ranked, evidence-cited findings and
remediation across jobs/SQL/warehouses/UC/clusters), not consumption reporting.

## Related Issues
N/A

## Screenshots/Demos
N/A (CLI/agent plugin; sample run dirs available on request).
EOF
)"

echo "Opening PR ..."
gh pr create --repo "$VIBE_REPO" --base main --head "$BRANCH" \
    --title "feat(starboard): add Starboard Databricks-analysis plugin (v${VERSION})" \
    --body "$PR_BODY"
echo "Done."
