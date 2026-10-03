# Run checklist (human version of the run-check contract)

Every engagement run — attended or unattended — must satisfy every item below before it is
complete. The final step runs `starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json`
and fixes every failure until it exits 0.

All paths are relative to `<run-dir>` (e.g. `starboard-reports/<workspace>-<YYYY-MM-DD>/`, or
`starboard-reports/ws-<id>-<YYYY-MM-DD>/` for an internal workspace id). The checklist is the same
on the live-connect (`--profile`) and no-connect (`--internal-workspace-id`) paths.

---

## Checklist

1. **`README.md`** — present and contains both required sections:
   - `## Delivery` — one line per artifact listing where it went: a URL or `deliverables/` path,
     or `local: <reason>` / `not delivered: <reason>` (e.g. `Exec summary: https://docs.google.com/…`,
     `Notebooks: local: gcloud not authenticated (run gcloud auth login)`).
   - `## Recur` — `baseline — no prior run` on a first run, or the delta note
     (`delta vs <prior-date>: N improved, M regressed, K newly expensive, …`) on a recurrence.
     `starboard-helper run recur <run-dir> --workspace-root starboard-reports/<workspace>` writes it
     (`--baseline` skips the prior lookup on a known first run).
   - Done-criterion: file exists; both section headings are present; `## Recur` is not empty;
     `## Delivery` has at least one **real** artifact entry (a `deliverables/` path, a URL, or a
     `local:` / `not delivered:` outcome). A placeholder such as "(filled at delivery)", "TBD" or
     "pending" fails, so run the final check after delivery, not before.

2. **`discovery/discovery.json`** (or `discovery.json` at the run-dir root) — the raw discovery
   envelope. `starboard --discover … --json --out-dir <run-dir>/discovery` writes it; no copy to
   the root is needed.
   - Done-criterion: file exists; parseable JSON; contains `data.facts` with at least a
     `total` key.

3. **`discovery/domains/*.md`** — at least 3 domain write-ups. The discovery command does **not**
   write these: the discovery skill's Step 4 does, one file per domain. On `--data-only`,
   `data.domain_analyses` has one `kind: "data_only_summary"` entry per domain (counts,
   `nonempty_query_ids`, `limit_reached_ids`, `raw_paths`; no grade or findings): use it as the
   index and write the analysis from the rows in `raw/<pack>.json`.
   - Done-criterion: `discovery/domains/` exists with ≥3 `.md` files.

4. **`discovery/analysis.md`** — the rollup with a graded report card.
   - Done-criterion: file exists; contains a line with the word `Grade` (the report card table).

5. **`analysis/verify/*.sql` and `analysis/verify/*.json` pairs** — at least
   `min(8, count of Act-now + Investigate items)` matching `.sql`/`.json` pairs.
   `starboard-helper verify run <vt-id> --templates <verify-sql.md | overlay mirror-verify.md> --ws <id>
   --start … --end … --out analysis/verify/` writes each pair (see `verify.md`; on the no-connect
   path `--internal-workspace-id <id>` replaces `--ws`, which defaults to it). Id lists take commas,
   spaces or repeated flags. Run at most 3 at once on a shared warehouse (one sequential stream is
   fine). A failed verify still writes its `.json` (`ok: false`) and exits non-zero: re-run it
   alone, or keep it and add the one-day staged fallback. The minimum is a floor, not a budget:
   verify every Act-now/Investigate candidate.
   - Done-criterion: for every `.sql` file under `analysis/verify/`, a same-stem `.json`
     exists; total pairs ≥ `min(8, act_now_count + investigate_count)`.

6. **`analysis/backlog.json`** — the machine-readable opportunity list.
   - Done-criterion: file exists; valid JSON; contains `workspace_id`, `generated_at`,
     `facts_window`, and `items[]`; each item has `id` matching `^OPP-[A-Z0-9-]+$`, `tier`
     in `{act_now, investigate, not_now}`, and `confidence` in 1–10; `sizing.value` is a number
     or `null` (never a string — the unit goes in `sizing.unit`, prose in `sizing.formula`).
   - **Canonical perf metric:** a `perf_metric` item's `sizing.metric` + `sizing.unit` must be the
     id's row in the catalog's canonical perf metrics table. The failure prints the exact fragment
     to put inside `sizing` (e.g. `{"metric": "dbus_per_billed_hour_after", "unit": "DBU/hour"}`),
     so copy it rather than guessing. Check every `perf_metric` item against that table **before**
     you render notebooks: a missing metric on one item is the commonest first-attempt failure.
   - **Confidence breakdown:** each `act_now` / `investigate` item carries
     `confidence_breakdown`, the rubric points per component (verify.md's confidence rubric), and
     `confidence` is their sum (minimum 1). A missing breakdown is a warning; a breakdown that
     doesn't sum to `confidence`, or a component above its row's points, fails the check.
   - **`depends_on`** (optional): `["<OPP-ID>:<target>", …]` naming the items to do first (the
     cause before the symptom); the "Start this week" view orders by it.
   - **Coverage:** every catalog id whose trigger fired is in `items` or in the top-level
     `cut: [{"id", "rule", "reason"}]` list (e.g. `{"id": "OPP-WH-IDLE", "rule": "disqualifier",
     "reason": "no idle to remove"}`). A fired id in neither fails the check.
   - **Cut rule:** `rule` ∈ `disqualifier` / `no_evidence` / `duplicate`. `no_evidence` means the
     source lacks the evidence; a `no_evidence` cut fails the check when none of that id's catalog
     `Verify` templates was attempted (a saved `ok: false` `.json` counts).
   - **Target:** one item per `(id, target)`, with the target kind from the catalog entry's
     `Target kind` row (e.g. OPP-JOB-OVERLAP one item per `job:<id>`, OPP-STEP-CHANGE `workspace`).

7. **`analysis/action-plan.md`** — the verified action plan.
   - Done-criterion: file exists; non-empty.

8. **`analysis/technical-review.md`** — the accuracy gate record.
   - Done-criterion: file exists; contains a `## Humanize` section (confirms the humanize
     pass ran).

9. **`deliverables/exec-summary.md`**, **`deliverables/evidence-pack.md`**,
   **`deliverables/action-plan.md`**, **`deliverables/slack-post.md`** — the standard
   customer artifact set.
   - Done-criterion: all four files exist and are non-empty.

10. **One notebook per Act-now AND Investigate item** — each item in `analysis/backlog.json`
    whose `tier` is `act_now` or `investigate` must have a non-null `notebook` field, and the
    file at that path must exist. `starboard-helper notebook render --backlog analysis/backlog.json
    --all --run-dir <run-dir> --out deliverables/notebooks/` writes them **and registers each path
    in the item's `notebook` field** (default; `--no-update-backlog` skips it). If you edit
    `backlog.json` afterwards (a new item, a changed target), re-render so the paths stay in step.
    The render result's `rendered` count and `paths` list say what was written: check the count
    equals your Act-now + Investigate items. A remediation cell holds the item's `lever_command`, or
    a default command only when the `lever` states one unambiguous `setting = value`; otherwise it
    is an operator decision note (read it in the technical review).
    - Done-criterion: for every `act_now` and `investigate` item in backlog.json,
      `backlog.items[i].notebook` is set and the file exists under `deliverables/notebooks/`.

11. **`deliverables/charts/*.png`** — at least 1 chart PNG. Render every deliverable chart with
    `starboard-helper charts render --kind <kind> --data <rows.json> --out deliverables/charts/<name>.png`
    (any kind in `starboard-helper charts render --help`; top jobs or other entities use
    `spend-concentration`). `--data` takes a JSON array of row objects or NDJSON (one object per
    line). The trend PNGs `run recur` writes under `charts/trend/` don't count here.
    - Done-criterion: `deliverables/charts/` exists with ≥1 `.png` file.

12. **Sanitized `.clean` siblings (internal runs only — add `--internal` to `run check`)** —
    every file under `deliverables/` that contains customer-facing text, and every notebook
    under `deliverables/notebooks/`, must have a `.clean` sibling (e.g. `evidence-pack.clean.md`,
    `opp-wh-idle.clean.py`).
    - Done-criterion: for every `deliverables/*.md` and `deliverables/notebooks/*.py`,
      a file with the same stem plus `.clean` exists at the same path, and no sanitizer warning
      is left in `.clean` prose (fix the draft and re-sanitize; see the overlay's Beat 4).
    - No vacuous pass: when `deliverables/` is missing or holds no `.md` / `.clean` files, both the
      sibling check and the sanitizer check (`run check` items 12 and 16) **fail** with "see item
      9". An early `run check` before delivery fails them; that is expected, not a sanitizer bug.

13. **`findings-manifest.json` + a successful recur** — the per-run recurrence record, required on
    **both** paths:
    `starboard review --from-discovery <run-dir>/discovery --json --out <run-dir>/analysis/review.json
    --manifest-out <run-dir>/findings-manifest.json [--since <prior-run-dir>/findings-manifest.json]`
    (after discovery finishes — never concurrently; with no discovery run,
    `starboard review <--profile <workspace> | --internal-workspace-id <id>> --lookback-days 30 --json`
    with the same flags). Use `--out`, never `> review.json 2>&1`. A degraded review (`degraded`,
    `unavailable_queries`, `unavailable_domains` in the manifest) still completes the item; say
    which domains were unavailable in the README. `unavailable_queries` lists only skipped queries
    that a review rule reads; `discovery_skipped` lists every query discovery skipped, and
    `coverage_note` says which of them no rule uses. Quote `coverage_note` in the README instead of
    implying full coverage when `unavailable_queries` is empty. Skipped audit, lineage, instance-event
    or statement-text queries are acceptable (the review is not degraded), but the narrative must
    name them as a coverage caveat and never imply full coverage. Then run `starboard-helper run recur` (beat 9), which writes
    `analysis/recur-result.json` (`ok`, `baseline`, `prior_run`, `history_path`, `history_entry`,
    `backlog_delta`, `errors`).
    - Done-criterion: the manifest is valid JSON with a `findings` list; `analysis/recur-result.json`
      has `ok: true` (or `baseline: true`), and the trend history has an entry for this run.

---

## Final step

Run the self-check and fix every failure until it exits 0:

```bash
starboard-helper run check "$RUN_DIR" --out "$RUN_DIR/analysis/run-check.json"
# add --internal on the internal (overlay) path:
# starboard-helper run check "$RUN_DIR" --internal --out "$RUN_DIR/analysis/run-check.json"
```

The tool prints a pass/fail summary (one line per checklist item) and `--out` saves the same
result as JSON. No README `## Run check` section is needed. Do not claim the engagement is
complete until `run check` exits 0.

---

## Environment / known pitfalls

These are session-setup notes, not checklist items. Resolve them before starting the run.

**Shell `<run-dir>` assignment.** Always export the variable before using it in a command:

```bash
export RUN_DIR="starboard-reports/<workspace>-<YYYY-MM-DD>"
starboard --discover … --json --out-dir "$RUN_DIR/discovery"
```

Never use the inline form `RUN_DIR=… cmd "$RUN_DIR/…"` — the inline assignment expands
before the variable is set, so `$RUN_DIR` is empty in the command arguments.

**Blanket rule: run every loop or multi-argument construct under `bash -c`.** Any `for` / `while`
loop, `set -- $spec`, or a flag string held in a variable behaves differently under zsh (the macOS
default shell), and the failure is usually silent (zero PNGs, zero verify files, no error through
`| tail`). Wrap the whole construct, `bash -c '…'`, or use an array. Single commands with literal
flags are fine in either shell.

**zsh doesn't word-split `$VAR`.** Under zsh, an unquoted string variable is passed as **one**
argument, so `ARGS="--ws 123 --start …"; starboard-helper verify run vt-x $ARGS` fails with
`required: --ws …` (exit 4), and so does `for p in …; do set -- $p; … done`. Put the flags in an
array, or run the loop under bash:

```bash
args=(--ws "$WS" --start "$START" --end "$END" --out "$RUN_DIR/analysis/verify/")
starboard-helper verify run vt-daily-totals --templates "$TPL" "${args[@]}"
# or: bash -c '…'  (bash word-splits unquoted $ARGS)
```

**Other zsh and pipeline traps.**

- `status` is a **read-only** variable in zsh: `status=$?` fails. Use a neutral name
  (`check_rc=$?`).
- A bare `echo ===` breaks a zsh chain (`=` triggers filename expansion: `== not found`). Quote it:
  `echo '==='`.
- `cmd | tail -5` reports `tail`'s exit code, so a failed `verify run` looks green. Use
  `set -o pipefail`, or read the `ok` field of the saved `.json` (`jq -e .ok file.json`).
- **`verify run` exit 4 (bad arguments).** An argument error found **after** the template id is
  known (a flag the template needs is missing, a placeholder is unfilled) writes
  `<vt-id>[-<suffix>].json` with `ok: false` and the error, so the attempt is on record. One found
  **before** that (an unknown template id, an unsplit flag string under zsh, an unparseable
  command line) writes **no** `.json`: check the exit code as well as the files, since a missing
  `.json` is a command to re-run, not a failed verify you can cite for a `no_evidence` cut.
  `--start` / `--end` are required only by templates with date-derived placeholders; `verify list`
  shows each template's `required` set, and the runner enforces exactly that set.
- **Dependent artifact scripts: `set -euo pipefail`.** A script whose later steps read an earlier
  step's output (build `backlog.json`, then render notebooks, then sanitize) must stop at the
  first failure. Start it with `set -euo pipefail` (under `bash -c '…'` in zsh). One run's inline
  backlog script raised a `NameError` before saving, and the next command re-rendered notebooks
  from the stale backlog because nothing stopped the chain.
- **Verify rows are column-keyed.** `verify run` writes `data.rows` as objects keyed by column
  name by default (`--rows arrays` for positional rows). Sum by name, e.g.
  `jq '[.data.rows[].excess_dbus // 0] | add' file.json`, never by column index.
- Literal JSON for a chart data file needs `jq -n` (`jq -n '[{"label":"a","value":1}]' > rows.json`);
  without `-n`, `jq` waits on stdin and writes an empty file.
- **Chart data is a JSON array or NDJSON.** A jq transform of a verify file wrapped in `[ … ]`
  gives an array: `jq '[.data.rows[] | {usage_date, total_dbus: .dbus}]' analysis/verify/vt-daily-totals.json > rows.json`.
  Without the brackets jq streams one object per line (NDJSON), which `charts render` also
  accepts. Anything else (a single object, a pretty-printed stream mixed with other output) fails
  with `ok: false`; check `ok` before counting PNGs.

**Isolated run dir (prompt tests).** When the prompt supplies the run dir and forbids reading
other runs (e.g. `RUN_DIR=starboard-reports/<MODEL>/<RUN_ID>`), keep the workspace trend root
inside it and skip the prior lookup:

```bash
starboard-helper run recur "$RUN_DIR" --workspace-root "$RUN_DIR/ws-root" --baseline
```

The trend history lands at `$RUN_DIR/ws-root/trend/history.json`; nothing outside `$RUN_DIR` is
read or written. The workspace root may be any directory except the run dir itself. The same
carve-out applies to the recur beat's `starboard-reports/schedule.log` append: skip it on an
isolated run dir.

**Drive folder race (parallel or repeated runs).** If multiple runs write to the same
`starboard/_prompt-tests/<MODEL>/<RUN_ID>/` parent, the find-or-create logic can create
duplicate folders. Pre-create the destination folder once before starting the runs and
pass its folder id directly, rather than relying on each run to find-or-create it. Parallel
test runs have already left several `_prompt-tests` folders under `starboard`. Resolve each segment
by **listing the parent's child folders** (`'<parentId>' in parents and mimeType =
'application/vnd.google-apps.folder' and trashed = false`) and matching the name yourself: a name
query can return nothing for a folder that exists. When duplicates already exist, reuse the
**oldest**: `drive_file_list` may omit `createdTime` even when `fields` asks for it, so call
`drive_file_get` on each duplicate to read its `createdTime`, and create your own subfolder
inside the oldest instead of creating another `_prompt-tests` (see capability-bind's
find-or-create rule).

**Docs land outside the folder until you move them.** `docs_document_create_from_markdown` has no
parent argument, so every Doc is created in My Drive root (or another default parent). Move it
with `drive_file_update` (`add_parents` = the run folder, `remove_parents` = the parent read with
`drive_file_get`), then `drive_file_get` again and confirm the Doc has exactly one parent, the run
folder, before listing it in `## Delivery` (capability-bind Rule 6).

**OMC PostToolUse noise.** Inside an OMC session, PostToolUse hooks can print "Command failed" /
"Write operation failed" on **successful** calls (any step, not only discovery). Judge success by
the command's own output and exit code, or the saved file, not the hook note; `OMC_SKIP_HOOKS`
in the environment suppresses it.

**Network sandbox.** Some host environments (e.g. a code-execution sandbox) block outbound
network calls by default. The discovery command (`starboard --discover …`) requires network
access to the Databricks workspace. Approve network access — or disable the sandbox for
this step — before running Beat 0, not after it fails.
