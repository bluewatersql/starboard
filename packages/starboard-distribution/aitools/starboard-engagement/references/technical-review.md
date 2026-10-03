# Primitive: technical-review — the accuracy gate

Modeled on **the host's code-review pass**, applied to *recommendations* instead of code.
Run this after you synthesize the plan and before you humanize/deliver. It is host-led — you run the
verify pass yourself; there is no second LLM.

## The verify pass, not a vibe check

Each candidate recommendation gets a **verdict**:

- **CONFIRMED** — re-verified against live evidence this run (re-ran the query / fetched the resource).
- **PLAUSIBLE** — reasoned from system-table or prior evidence, not live-verified this run.

Only findings that survive verification stay in the plan as recommendations. PLAUSIBLE items are
labeled as such (lower confidence); anything that fails moves to "needs validation" or is cut.

## Findings, ranked most-severe-first

State review findings about the plan the way a code-review pass reports code findings — each with a
one-line summary, a concrete **failure scenario** (what breaks or misleads if asserted as-is), and a
severity. Example: *"Action 1's recoverable is overstated — ~17K of it is DLT-managed clusters where a
cluster ALTER misfires (min_workers already 1)"* is a finding with a failure scenario, not a footnote.

## The rubric (the review's categories) — every action must pass

1. **Lever-correctness** — is the remediation the *right* mechanism? (A cluster `ALTER` on a
   DLT-managed cluster is the wrong lever; the lever is pipeline/serverless config.)
2. **Scope-match** — does the *data-source scope* equal the *remediation scope*? Account-wide system
   tables + single-workspace API is a trap. If they differ, the item is investigation-only until the
   right-scoped access exists.
3. **Resource-liveness** — does the target still exist and is it reachable through the caller's
   profile? (A deleted/cross-workspace job is not actionable.)
4. **Number reconciliation** — does the recoverable estimate survive workload-type classification
   (standing vs transient/personal vs deliberate benchmark vs DLT-managed)? Assert only the defensible
   slice; disclose the rest. **Recompute every sum you certify.** For each `bounded_dbu` item and
   every other summed sizing figure (Σ `excess_dbus`, failed-run DBU, overlapping-run counts), re-add
   it yourself from the **full** saved verify json: every row of `data.rows`, not the preview you
   read while drafting, not the first N rows. Record the recomputed value next to the backlog value
   in `analysis/technical-review.md`; a mismatch is a finding (fix the backlog, then re-render the
   notebooks). Also confirm framing matches the template: vt-job-run-tail returns the 20 longest
   runs, not every CRON run; vt-step-change returns the top 15 workloads, not the workspace total.
5. **Artifact validity** — is the SQL/diff/patch syntactically valid and does it name the real target
   (never a `<placeholder>` in customer-facing output)?
6. **Confidence honesty** — confidence reflects live verification, not vibes; unverified → PLAUSIBLE.
7. **Generated-code review** — for every notebook or script delivered with the plan, assign a
   CONFIRMED or PLAUSIBLE verdict on each of the following, using the same standard as prose
   findings:
   - **Query reproduces the number** — the `system.billing.usage` query in the read-only cell, when
     run against the scoped `workspace_id`, returns a DBU figure that matches the cited recoverable
     within the stated arithmetic. CONFIRMED = re-ran it this session; PLAUSIBLE = reconciled from
     prior evidence.
   - **Remediation commands are valid** — every CLI command and SQL statement in the remediation
     cell is syntactically correct, names a real resource type, and uses no `<placeholder>` strings.
     An item without `lever_command` (owner-context changes such as OPP-JOB-OVERLAP's cadence
     question) gets a decision note or a bundle YAML fragment, not an unconditional update command.
     A bundle-deployed job's cell is bundle YAML + redeploy, never `jobs update`; a warehouse
     resize's Apply sets the proposed value and its Rollback restores the current one (check both
     against vt-warehouse-config-history).
   - **Post-change cells compare separate windows** — the measurement cell returns a baseline
     window and an after-change window as separate rows, each bounded at both ends (a fixed 7 full
     days, not "up to today"), scoped to the named target and the id's canonical metric
     (OPP-SERVERLESS-STANDARD-MODE: CRON DBU/run and wall-clock/run on the pilot job, not the
     workspace mode mix; OPP-WH-SCAN: the cited source's GB/query, not the warehouse average). One
     combined window is context, not a measurement.
   - **Targets are live** — the named resource IDs (endpoint IDs, warehouse IDs, job IDs, instance
     IDs) can be resolved through the caller's profile to resources that still exist.
   - **Read-only cells are actually read-only** — the evidence/query cells contain no DDL, DML, or
     API writes; they run `SELECT` or `display()` only.
   - **Destructive commands are gated** — every command that modifies or terminates a resource is
     commented out and marked with a `# DESTRUCTIVE` annotation, with an explicit instruction
     requiring the operator to uncomment before it can run.

   A notebook that fails any of these checks is treated identically to a prose finding that fails
   the rubric: **downgrade to Investigate** (if one confirming step would fix it) or **drop** (if
   the finding is unsound). Never deliver a notebook that passes only a subset of these checks
   without labeling the gap explicitly.

## Output

Write to `analysis/technical-review.md`. Content: a short accuracy note — findings, verdicts (prose
**and** generated-code), what got demoted, residual risk — that becomes the plan's provenance, **not**
a customer-facing section. When the host provides a code-review pass, this beat can hand the drafted
plan to it for an independent pass; otherwise you self-review to this rubric.

Close the file with a `## Humanize` section. Leave it blank until the humanize pass is done, then
record there that the pass ran and which artifacts were reviewed (see
[`humanize.md`](humanize.md)).
