---
name: starboard-engagement
description: 'The reusable Starboard engagement scaffold — the shared phase flow, primitives, and templates that every customer-facing workflow composes (cost action plans, reliability reviews, QBR decks, CRM touchpoints). Load this alongside a vertical skill (e.g. starboard-action-plan, starboard-deliver): it supplies the beats (gather → scope → verify → analyze → present → synthesize → technical-review → humanize → deliver → recur), the composable primitives, and the doc/slide templates so the vertical stays thin and the output is customer-ready, not an agent dump. Use whenever you are running or authoring any Starboard engagement workflow.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-engagement/SKILL.md
---

# Starboard: Engagement scaffold

> **Before you start:** open [`references/run-checklist.md`](references/run-checklist.md); you are done only when `run check` exits 0 (`starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json` on a Drive run, `starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json` on a local one). The saved `analysis/run-check.json` is the record; don't paste the summary into `README.md`.

This is the **shared engagement workflow** — one shape reused across many verticals, so a new
workflow is a *thin vertical that composes this scaffold*, never a new monolithic skill. It is the
parent skill: load it **together with** a vertical (`starboard-action-plan`, `starboard-deliver`, or a
future one). The vertical supplies *what* is analyzed; this scaffold supplies *how* an engagement runs
and how it's made customer-ready.

**You are the analyst.** You (the host) are the LLM. You reason, prioritize, validate, and write —
there is no second LLM in this loop, and no deterministic ranking kernel. Do not call the `starboard`
goal agent or an MCP `*_analysis` / `synthesize_*` tool for the reasoning; the data comes from the
vertical's fetch layer (host **MCP** tools where present, else the **`starboard-helper`** CLI), and the
judgment is yours.

## The phase flow (the beats — do not skip scope, verify, present, review, humanize)

(A `health_check` run skips technical-review and humanize: `run check` lists them under
`skipped_by_profile`.)

```
preflight: storage (CONFIRM) → verify-identity → route → gather → commit capture
      → scope: workspace (CONFIRM) → verify → analyze
      → present: verified shortlist (CONFIRM) → synthesize → technical-review → humanize
      → recur → commit analysis → run check → commit check
      → deliver: report → approve (CONFIRM) → deliver | receipt
```

0. **preflight — task, run and storage policy, before the first workspace read.** Fix the run's
   task first: it decides the run's folder and which beats run (see **One task per run** below).
   Then ask the helper which sources and stores this task can use:
   ```bash
   starboard-helper engagement source-options --task <task>
   ```
   Read `data.options[]` (each has `source_mode`, `storage_policy`, `storage_choices`,
   `default_storage` and `needs_workspace_auth`). When `data.choice_required` is true, ask the
   operator once which source to use, using `data.question` as written (it lists each option's
   storage and auth need), unless the prompt already names it; never pick one silently. An unattended run must already carry `--source-mode`. A customer or hybrid leg
   with no customer profile is never given one: start a new `internal_only` run instead — a new
   preflight with `--source-mode internal_only`, then `route`; never re-label the current run —
   and write `- customer workspace: not acquired (no customer profile)` under the report's
   `## Unknowns`.
   Preflight mints the run ID and decides where the run is stored:
   ```bash
   starboard-helper engagement preflight --task <task> --task-name <task-name> \
     --account-key <account_key> --account-name "<account name>" --source-mode <mode> \
     [--storage drive|local]
   ```
   - `<task>`: `action_plan` (this scaffold with `starboard-action-plan`), `discovery` (a
     discovery run with no plan), `review` (a standalone `starboard review`), `health_check`
     (a workspace health review: the `starboard-health-review` entry skill) or
     `troubleshooting` (one focused job/query/pipeline case: the `starboard-troubleshoot` entry
     skill). A health check or a troubleshooting case needs no action plan, no verify floor and
     no notebooks.
   - `<task-name>`: a stable case name, `ws-<workspace_id>` for a workspace run and
     `job-<id>` / `query-<id>` / `pipeline-<id>` for a focused case. Never a date or anything
     sensitive; the run ID carries the date.
   - `<account_key>` / `<account name>` (**the account key rule**, the same on every skill and
     surface): `--account-key` names the account's folder, registry and history, so every run of
     an account passes the same key. At preflight use the key the operator gave; else the
     WORKSPACE ID. Never use the account name as the key (preflight warns
     `account_key_looks_like_name:` when the key looks like a name). `verify-identity` runs after
     preflight and only returns a `provisional_account_key`; the key never changes mid-run. Use
     the name the operator gave; else the verified account name; else `ws-<workspace_id>` (only
     when no name exists; say so). Never guess either from the prompt. Route finds the account
     folder by key whatever its name (`account_name_differs` warning); a different key starts a
     separate folder with no history.
   - `<mode>`: `customer_workspace` when you will read a customer workspace live (`--profile <name>`),
     `internal_only` on the overlay's no-connect path (`--internal-workspace-id` /
     `--internal-account`), `hybrid` for both. `--internal-workspace-id` is valid at preflight
     only with `--source-mode internal_only`. Pass `--storage` only when the operator named a
     store.
   - Pass `--unattended` only when the prompt says the run is scheduled or unattended, or says
     not to ask anything: any fallback, override or missing auth is then an error, never a
     prompt, and nothing can be approved for a customer. A prompt that pre-supplies answers but
     says neither is attended: take the answers from it and leave the flag off.
     "Non-interactive" or "nobody will answer" next to an operator script is attended too: the script is the operator.

   Read `data`. Keep **`run_id`** (`$RUN_ID` below) and act on **`storage_decision`**, which is
   exactly one of these lowercase JSON strings: `drive_required`, `drive_default` and
   `drive_optional` are Drive runs; `internal_only_local` and `local` are local runs.
   - **`drive_required` — a covered run** (internal overlay installed plus a customer or hybrid
     leg): **nothing is written locally**, not even a working copy. Preflight staged the run in
     Drive (`staging_folder_id`, `staging_link`) and route returns the run folder; from then on
     every writer takes `--run-folder $RUN_FOLDER` and every output flag is a run-relative path
     (`--out analysis/review.json`, never `<run-dir>/…`). An input outside the run is
     `drive:<object_id>`. On a covered run the helpers refuse, with exit code 2 and
     `LOCAL_STORAGE_REFUSED`: a local `--out` path, `--stdout` (full envelope), `--log-file` and
     a local `--authorization <run-dir>`; `--session` is refused on any overlay install. Never
     answer a refusal by writing the file yourself: there is no local fallback.
     The same goes for the shell, on every Drive run (`drive_*`): let stderr go to the terminal and
     never redirect stdout or stderr anywhere, or `tee` them: not to a file, not under `/tmp`,
     and not to `/dev/null` (`2>/dev/null` hides the warnings); to filter the output, pipe it.
   - **`drive_default`** (internal-only, no customer leg): the same Drive run folder and the same
     `--run-folder` commands. The operator may choose local instead with `--storage local`, which
     gives `internal_only_local`.
   - **`drive_optional`** (a public install where the operator chose `--storage drive`): a Drive
     run, with the same run folder and the same `--run-folder` commands. Without that choice a
     public run is `local`.
   - **`internal_only_local`** or **`local`** (a public install without the overlay, or an
     internal-only run the operator chose to keep local): **`data.local_run_dir`**
     is the run dir (`<run-dir>` below):
     `starboard-reports/<account-slug>/<task>/<task-name>/<run_id>/`. Every writer takes local
     paths rooted at it, and its parent (the **case root**) holds every run of the case and its
     trend history. A prompt that fixes the run dir passes it as `--run-dir <path>` at preflight.
     `route` creates `<run-dir>/deliverables/`, so the first write needs no `mkdir`.
     Never build a run dir by hand. Drive stays optional at deliver.

   **The two forms of every command.** The commands below are written in the Drive form
   (`--run-folder $RUN_FOLDER` plus run-relative paths). On a local run, drop `--run-folder` and
   root each path at `<run-dir>/` (`--out <run-dir>/analysis/review.json`), and pass
   `--authorization <run-dir>` to a customer acquisition. Shell variables don't survive between
   tool calls: substitute the literal IDs that preflight and route printed.

   **Refusals and exit codes.** Two families, each with its own codes:

   | Exit | `starboard-helper engagement …` | every other helper (`run …`, `job fetch`, `query …`, …) |
   |---|---|---|
   | 0 | ok | ok |
   | 1 | `INTERNAL` (unexpected error) | auth |
   | 2 | usage or refusal (`USAGE`, `LOCAL_STORAGE_REFUSED`, `STORAGE_UNAVAILABLE`, …) | a missing input / target, a storage refusal (`LOCAL_STORAGE_REFUSED`, `STORAGE_UNAVAILABLE`) or `PROFILE_MISMATCH` |
   | 3 | auth (`AUTH_REQUIRED`, `WORKSPACE_AUTH_REQUIRED`) | API error (`WORKSPACE_TIMEOUT` included) |
   | 4 | storage (`BLOCKED_ACCESS`, `NOT_FOUND`, `STORAGE_ERROR`) | argument error (a bad `--prior` included) |
   | 5 | identity (`IDENTITY_MISMATCH`, `RUN_QUARANTINED`) | — |
   | 6 | `WORKSPACE_API_ERROR` | — |
   | 7 | — | storage failure: `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND` (a Drive object missing during a run read or write) or `STORAGE_ERROR` |
   | 8 | `STORAGE_TRANSIENT` (a Drive 5xx / 429 / timeout that outlasted the adapter's own retries; `errors[0].retryable: true`) | `STORAGE_TRANSIENT` (the same; `errors[0].retryable: true`) |

   A failure of the other helpers that has a machine code also carries
   `errors: [{code, message, retryable}]` (`error` stays the message): `WORKSPACE_TIMEOUT`
   (exit 3, retryable: the workspace call ran out of its retry budget, `error` "API error: Timed
   out after …") and `CODE_NOT_IN_WORKSPACE` (exit 2, `job code` on code that lives outside the
   workspace, not a missing job). `python -m starboard_x.<capability>` uses the helper codes;
   `starboard review` uses them too (2 is a refusal there); `starboard` is 2 usage or refusal,
   3 config, 4 auth, 5 connection, 6 timeout, 7 storage failure, 8 `STORAGE_TRANSIENT`, 130
   interrupted. On every surface exit 8 is `STORAGE_TRANSIENT` (`retryable: true`).

   The bullets below are the `engagement` family.
   The `engagement` envelope has no top-level `error`: its failure is `errors[0]`
   (`{code, message}`), so wherever an `engagement` step says show `error`, show
   `errors[0].message`. Exit code 2 with `errors[0].code` `LOCAL_STORAGE_REFUSED` or
   `STORAGE_UNAVAILABLE` is a refusal: show `errors[0].message` verbatim and stop. Any other
   helper (e.g. `job fetch` on a Drive run without `--run-folder`) exits 2 with a top-level
   `error` that starts with the same code: show `error` verbatim and stop.
   - `ACCOUNT_NAME_TAKEN` (exit 2): the `--account-name` folder already belongs to another
     account key (the message names it). If it is the same account, start over with
     `starboard-helper engagement preflight` with `--account-key` set to the key the message names (the key never
     changes mid-run); otherwise choose a different `--account-name`. Never merge folders.
   - `LOCAL_STORAGE_REFUSED`: the operator asked for local on a covered run. Say the request was
     not honored and quote the reason; never satisfy it by writing local-only.
   - `STORAGE_UNAVAILABLE`: the Drive storage adapter isn't installed, so a Drive run can't
     start. Stop; nothing was written. From preflight, `run_id` is null and nothing was staged,
     so there is no run to resume: once the adapter is installed, re-run the same preflight. A
     local run never needs the adapter: `verify-identity`, `route` and `status` take its
     `--run-id` and read its run dir under `starboard-reports/` (`--run-dir` for one kept
     elsewhere).
   - Exit code 1 (`INTERNAL`) is an unexpected helper error (traceback on stderr): stop and
     report it; don't retry or work around it.
   - Exit code 3 means auth failed (Drive or Databricks; the `code` says which). `AUTH_REQUIRED`:
     Google Drive isn't authenticated; show `errors[0].message` (it carries the
     `gcloud auth login --enable-gdrive-access` step) and wait for the operator to sign in. A
     preflight that returns `run_id: null` staged nothing: re-run the same preflight. Any other
     stage resumes as below.
     `WORKSPACE_AUTH_REQUIRED`: the Databricks profile didn't authenticate; show `error` and ask
     the operator to fix that profile's sign-in, then retry the same stage.
   - Exit code 4 means storage access failed, a Drive object the run needs is gone
     (`NOT_FOUND`), or the run folder's sharing changed (`BLOCKED_ACCESS`): stop all writes and
     show `errors[0].message`; restore the folder's previous sharing and resume, or start a new
     run.
     `STORAGE_ERROR` naming folders that clash with one identity (the same account kept under
     different names or keys) is not retryable as is:
     have the operator move the contents into one folder in Drive, trash the other, then run
     `starboard-helper engagement rebuild-index --account-key <account_key>` and retry; never delete or
     merge folders yourself. Duplicate folders of the same account identity (two concurrent
     first runs) are not an error: route uses the earliest-created one and reads merge every
     copy, each with a `duplicate_account_folders` warning; show it, and the operator may
     reconcile the same way. Two `My Drive/starboard` folders (two first runs at once) are
     not an error either: new folders go under the earliest-created one, run and account
     lookups search both, and the envelope warns `duplicate_starboard_roots`; show it and
     carry on. A route that found the account folder under another name warns
     `account_name_differs`: the key matched, so the run is in the right folder.
   - A `USAGE` refusal on a run (exit 2) changes nothing: its envelope echoes the run's current
     `run_status` and `resume` unchanged, so fix the argument and retry the same stage.
   - Exit code 5 is an identity mismatch: the run is `quarantined` and can't resume.
   - Exit code 6 (`WORKSPACE_API_ERROR`) means the Databricks workspace API failed or gave no
     usable answer. Drive wasn't touched: show `error` and retry the same stage once the
     workspace is reachable.
   - Exit code 8 (`STORAGE_TRANSIENT`) means Drive failed transiently (5xx, 429 or a timeout
     after the adapter's own retries) and nothing was refused. With exit 8, or any
     `errors[0].retryable: true`, retry the same command once; if it fails again, stop and
     record it (what failed, the `errors[0].message`) in the report's `## Unknowns`. A fetch
     that fails again with `WORKSPACE_TIMEOUT` is narrowed instead (one warehouse per
     `query slow`, a smaller `--lookback-days`) or recorded under `## Unknowns`.
   Never run a write test to check Drive access; the helper reads folder capabilities.

   **Verify the workspace (customer leg).** Unless `--source-mode` is `internal_only`, prove the
   workspace behind the profile is the expected one before any other customer call:
   ```bash
   starboard-helper engagement verify-identity --run-id $RUN_ID --profile <profile> \
     --expected-workspace-id <workspace_id> [--expected-host <workspace-url>]
   ```
   Always pass `--profile <name>` with the profile the operator chose; never pick one yourself.
   The expected workspace comes from the operator or a `ws-<id>` task name, never from a profile
   name. A mismatch exits non-zero and quarantines the run: stop, show `error` and read nothing;
   start a new run with preflight once the profile or workspace is fixed. `internal_only` runs
   skip this step.

   **Route the run (every destination).**
   ```bash
   starboard-helper engagement route --run-id $RUN_ID [--override-folder-id <folder_id>]
   ```
   Keep **`run_folder_id`** (`$RUN_FOLDER` below) and `run_link`; show any `fallback_warning`
   (the chosen folder wasn't writable, so the run went to the `My Drive` account route). Route
   writes the run descriptor (the run's `authorized_scope`) and registers the run in the
   account's registry (`registry_folder_id`, `registration_id`), so every later writer reads
   its authorization from the run folder and a later run finds this one as history. On a local
   run route writes `<run-dir>/analysis/run-authorization.json` instead, and every customer
   acquisition passes `--authorization <run-dir>`. In that record `intent` is the preflight
   `--task` (`action_plan`, `health_check`, `troubleshooting`) and `task` is the `--task-name`
   (`ws-<id>`, `job-<id>` ...). A discovery that exits non-zero is a
   stop-and-report; never retry it without the run folder or authorization. If the route can't
   be resolved on a covered run, stop before gather (attended: fix and retry; unattended: end
   the run and report the error). On an internal-only Drive-default run, offer `--storage local`
   instead (unattended: report why and stop).

   Record the storage outcome under README `## Storage`: `run_id`, `task`, `task_name`,
   `storage_decision`, the run folder link (or the local run dir) and every warning shown.

   **Resume, never restart.** A run that stopped part-way keeps its run ID. Ask the helper where
   it stands:
   ```bash
   starboard-helper engagement status --run-id $RUN_ID
   ```
   `run_status` is `staged`, `routed`, `capture_pending`, `analysis_pending`, `check_pending`,
   `publication_pending`, `complete`, `blocked_access` or `quarantined`, and `pending[]` names
   what is left. Select the run with `--run-id` (a Drive run found by its staging folder, a local
   run in `starboard-reports/`), `--run-folder` or `--run-dir`. `--run-id` may also accompany the
   run's own `--run-folder` or `--run-dir`; a different run's ID is `RUN_ID_MISMATCH` (exit 2).
   `--run-dir` together with `--run-folder`, or no selector at all, is `USAGE` (exit 2). With
   `--run-folder`, `drift[]` (`{path, committed_md5, current_md5}`, plus a
   `drift:` warning) names a file rewritten after its commit: re-run `engagement commit` for its
   stage to bind the current bytes. A preflight that stopped (Drive auth, or a staging folder whose sharing isn't
   restricted: fix the sharing first) continues with
   `starboard-helper engagement preflight --resume-run-id $RUN_ID --task <task> --task-name <task-name> --account-key <account_key>`.
   A writer that fails prints `{ok: false, run_status, resume: {run_id, run_folder_id, stage}}`:
   re-run that stage with the same run folder. Committed objects are reused, so nothing
   duplicates. A `quarantined` run can't resume: start a new run with preflight.

   **Commit each stage.** A Drive run's manifest records what each stage produced. After the
   stage's writers finish, commit it:
   ```bash
   starboard-helper engagement commit --run-folder $RUN_FOLDER --stage <stage> \
     [--state complete|failed]
   ```
   `<stage>` is `capture` after gather (discovery and fetches), `analysis` after synthesize (review,
   verify, backlog, notebooks, charts, recur) and `check` after `run check`. Commit never
   publishes anything; publication is the deliver beat's report → approve → deliver | receipt
   chain. A local run has no commit step.

   **Read run files through the helper.** On a Drive run there is no local copy to open. Read a
   run file for analysis with a bounded excerpt:
   ```bash
   starboard-helper engagement read --run-folder $RUN_FOLDER --path discovery/discovery.json \
     [--jsonpath '$.data.facts' [--jsonpath '$.data.packs[*].pack_id' ...]] \
     [--offset <next_offset>] [--max-bytes <n>]
   ```
   `truncated: true` means the excerpt was cut: narrow it with `--jsonpath` rather than raising
   the cap. `--jsonpath` is repeatable: prefer ONE read with several `--jsonpath` slices over
   repeated reads (one download). With `--jsonpath` the excerpt is always an object keyed by each
   expression, even for one. A path the file lacks (or a `[*]` item without the
   field) is `null` and listed in `missing_paths` (`[]` when every path resolved), with a
   warning; it is not an error. Over the byte budget a value is cut to a prefix that is still
   valid JSON, or dropped (its key is absent), and each cut or dropped expression is named in
   `truncated_paths`: the excerpt itself is always valid JSON, never cut mid-string. A read takes
   at most 50 `--jsonpath` (more is `USAGE`, exit 2; split them over reads). Pass every
   `--jsonpath` and its value as separate words: a zsh variable holding `--jsonpath a --jsonpath b`
   expands to one word, so write each flag out or use an array. A list returns at most 50
   items (a `[*]` over `plays.json`, `observations.json` or the findings is cut there and named
   in `truncated_paths`). Page it with a slice: `next_paths` maps each cut (or slice-limited)
   expression to the slice that reads the next items (`'$[*].play_id'` →
   `'$[50:100].play_id'` → `'$[100:150].play_id'`), and it is `{}` once the list is read; item
   `k` of `[a:b]` is position `a + k`. There are no filters (`[?(...)]`): to find one item, page
   `--jsonpath '$[*].finding_id'` (or `play_id`) until it appears, then read `--jsonpath
   '[<n>].<field>'` at its position. The leading `$` is optional. The
   default `--max-bytes` is the cap (about 21 KB, the stdout budget), so a plain read does not
   warn; only an explicit larger `--max-bytes` is lowered to the cap with a warning; below 8 it
   is `USAGE` (exit 2). For a long
   text file (Markdown), page it with `--offset <bytes>`: pass the previous read's
   `next_offset` (null at end of file); `--offset` does not combine with `--jsonpath`. There is
   no local `--out`: a read never writes customer content to the laptop. `--jsonpath` takes
   dotted names and indexes (`data.packs.0`, `data.packs[0]`), `[*]` for every item
   (`data.packs[*].pack_id`) and `[a:b]` for a slice (`[50:100]`, `[140:]`, `[-2:]`); it reads JSON artifacts only (Markdown such as `README.md`: drop
   `--jsonpath`, exit 2 `USAGE` otherwise). Helper output on a covered run is a bounded summary (IDs, counts, excerpts), never
   the raw rows, which stay in the run folder. On a local run, read `<run-dir>/…` directly.

   **Files you author.** README, `analysis/backlog.json`, `analysis/analysis.md`,
   `action-plan.md`, chart row files, focused reports, the delta narrative and the deliverable
   Markdown are written by you, not by a helper. On a local run write them under `<run-dir>/`. On
   a Drive run, put each one into the run folder at its run-relative path, the bytes on stdin,
   never with a local `Write`, a shell redirect or the host's own Drive tool:
   ```bash
   starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
   <the README Markdown>
   EOF
   ```
   It returns `{path, object_id, md5, size, unchanged}`: a changed file is updated in place and
   identical bytes are a no-op (`unchanged: true`), so a retry is safe. Put each file before the
   commit of its stage; that commit records it. To change a file a helper wrote (the README after
   recur, the delta skeleton), read it with `engagement read`, edit it and put the whole file
   back, only when `truncated` is false; if it is true, stop and report, and never put back an excerpt (it would replace the file with the excerpt). `put` refuses the run's control files with exit 2 (the descriptor,
   `run-authorization.json`, `manifest/`, the preflight, identity and baseline records under
   `analysis/`, `evidence/index.json`, `analysis/observations.json`, `analysis/findings.json`,
   `findings-manifest.json`, `analysis/run-check.json`, `analysis/recur-result.json`, and a
   report's revisions, approvals and receipts), as well as empty input and input over
   `--max-bytes` (5 MiB by default, which is also the hard cap: a larger value exits 2). Those
   records are written only by their owning commands (`starboard review --manifest-out`,
   `run check --out analysis/run-check.json`, `run recur`, …); an `--out` that names one from
   any other command is refused with exit 2 as well.

   **One task per run.** The task fixed at preflight decides what this run does; never mix two.
   The run is set up before the first workspace read, whatever the task.
   - `action_plan`, `discovery`, `review` and `health_check` are workspace runs: the beats below,
     over the workspace's system tables and discovery packs. They never fetch or mention a single
     run's logs, cluster event logs, query profiles or job-run diagnosis, and never record a
     "skipped" or "not pulled" line for that work: it isn't part of the task.
   - `troubleshooting` is one focused case (one job, query or pipeline): it fetches only that
     case's metadata, logs, profiles and code, and needs no full workspace scan.
   - A finding that calls for the other kind of work (a failing job seen in an action plan, a
     cost pattern seen while troubleshooting) goes in the backlog or the README as a suggested
     follow-up. The follow-up is a new run under its own task, started only when the operator
     asks: a focused case with [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md)
     (`--task troubleshooting --task-name job-<id>`, opened with `--finding-id <finding_id>`), or
     a workspace health read with [`starboard-health-review`](../starboard-health-review/SKILL.md)
     (`--task health_check --task-name ws-<id>`).
1. **gather** — the vertical fetches findings/data (MCP or `starboard-helper`). Pull **both** the
   cost picture (`system.billing.usage` by product — jobs, SQL, serverless, Lakebase, Vector Search,
   etc.) **and** the performance/reliability findings across the review domains (latency, failure
   rates, SLA/stability). A workspace discovery writes straight into the run:
   ```bash
   starboard --discover --profile <profile> --warehouse-id <wh-id> --run-folder $RUN_FOLDER \
     --data-only --json --out-dir discovery
   ```
   (local run: `starboard --discover --profile <profile> --warehouse-id <wh-id> --authorization
   <run-dir> --data-only --json --out-dir <run-dir>/discovery`). `--warehouse-id` is the
   **existing** warehouse the operator chose (`starboard-helper warehouse list` as in *verify*;
   discovery never creates or picks one). An `internal_only` run uses the overlay's capture form
   instead (an `internal_only_local` run passes `--authorization <run-dir>` with the internal
   flags). Run the capture in the foreground with Bash `timeout: 600000`, never in the background. A
   run capture (`--run-folder`, or a local `--authorization <run-dir>`) stops itself at
   `--max-seconds` (default 480) and saves its progress in the run (`capture/`):
   exit 9 `CAPTURE_INCOMPLETE` (`retryable: true`, with `progress` and `resume`) means "not
   finished yet", so re-run the identical command until it exits 0 (the same after a host kill
   at its time limit), then commit. Report `resumed.queries_reused` (and `resumed.fresh_reason`).
   Then `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture`.
   Read `data.status` in the discovery's stdout summary (`ok`, `partial` or `no_evidence`):
   `partial` carries on, and `data.failed` (`[{query_id, pack, error}]`) names the failed queries
   to list under Unknowns, so don't open `discovery/discovery.json` for them. The Drive
   (`--run-folder`) stdout has the same fields at other keys: `data.status` is `status`,
   `data.counts` is `counts`, `data.failed` is `summary.failed`,
   `data.coverage_summary.packs_with_gaps` is `summary.packs_with_gaps` (the packs with a
   skipped or failed query) and `data.facts` is `summary.facts`. That Drive summary is at most
   8 KB: `ok`, `status` and `counts` come first and files appear as compact refs `{path,
   object_id, size}`, so read `$.status` straight from stdout (never `tail` it). The progress
   banner and logs go to stderr, so `2>&1` is not needed (still no redirect to a file);
   `no_evidence` (`ok: false`, exit 4 when every failure is a permission error, else 1) and
   `WAREHOUSE_PERMISSION_DENIED` (exit 4, with the visible `candidates`) stop the run: report
   them. Never retry a permission error; only timeouts are retried (discovery does it, bounded). Tag every number with its source (`query_id`/pack/row) **and its
   `workspace_id`**. `system.billing.usage` is account-scoped; never present an account-wide total
   as one workspace. Retain the full evidence — later beats surface it, they don't discard it.
   **Quote headline numbers verbatim from `data.facts` in the discovery envelope** (on a Drive
   run, `summary.facts` in the stdout, or `engagement read --path discovery/discovery.json
   --jsonpath '$.data.facts'`) — never recompute them.
   A field named in `data.facts.fallbacks` (`{field: query_id}`) was filled from a fallback pack
   because its primary query was unavailable; quote it and cite that query id. For the spend
   story's "current run-rate", quote `data.facts.step_change.current_7d_avg_daily_dbus`,
   `pre_step_avg_daily_dbus` and `current_vs_pre_ratio` verbatim (don't derive them from daily
   totals). Read **every** row of a pack you scan for a pattern, not the first few: a
   `wait_for_*_readiness` task at row 7 or 11 of C-J09 is still a fired OPP-JOB-WAIT-TASK, and it is
   often the root-cause link between a run-length step change and job overlap.
2. **scope — CONFIRM the workspace, and only the workspace.** If the data spans multiple workspaces,
   say so and ask which to analyze: the verified workspace or all of them. Do **not** ask
   the user to pick opportunities yet — that gate moves to `present`, after they are verified.
3. **verify** — on an `action_plan` run, re-check at least the top **~8** candidate opportunities — selected by composite
   priority across cost and performance (see [`references/verify.md`](references/verify.md)) — and
   every candidate you will carry as Act now or Investigate (on `action_plan`, eight is a floor, not a budget) — live (read-only
   `query sql`): reconcile each headline number against `system.billing.usage` (not a 50-row-capped
   pack floor), push attribution to a workspace and, where the product allows, an endpoint/instance,
   assign confidence 1–10 and an expected **recoverable DBU** (bounded — never a per-day rate
   projected across the window). Never fabricate. Run each check with
   `starboard-helper verify run <vt-id> --ws <id> --start … --end … [--job-ids …] --limit 1000 --warehouse-id <wh-id> --run-folder $RUN_FOLDER --out analysis/verify/`
   (local run: `--out <run-dir>/analysis/verify/` and no `--run-folder`). `--templates` is
   optional: the default is this skill's bundled `references/verify-sql.md`. The overlay passes
   its own template file and `--internal-workspace-id` on the no-connect path; `--ws` then
   defaults to that id. The public path needs `--warehouse-id` of an **existing** warehouse: save
   `starboard-helper warehouse list --profile <profile> --run-folder $RUN_FOLDER --out raw/warehouses.json`,
   ask the operator which one verify may use, and with no answer skip the slice and record it
   under Unknowns; never create a warehouse; on a timeout use the staged 1-day fallback in
   [`references/verify.md`](references/verify.md). Always pass `--limit`: a result with
   `limit_reached: true` is missing rows, so split the ids or the window and re-run. A template
   whose own SQL ends in `LIMIT n` (n not above `--limit`, e.g. `vt-step-change` `LIMIT 15`) is a
   ranked top-N by design: the result is `limit_reached: false` with `top_n: n`. The row cap
   is 20000 for `verify run` and 1000 for `query sql`; a `--limit` above the cap is capped with a
   stderr warning and `requested_limit` / `limit_capped: true` in the result, so a capped
   result is never silent. The examples below use 20000 for `vt-job-run-states` (one row per run)
   and 1000 for the other checks.

   **Candidate jobs (reliability).** For each job you carry on failures, also save its runs:
   ```bash
   starboard-helper verify run vt-job-run-states \
     --ws <id> --start … --end … --job-ids <id1>,<id2> --limit 20000 --suffix <id1> \
     --warehouse-id <wh-id> --run-folder $RUN_FOLDER --out analysis/verify/
   starboard-helper verify run vt-job-runs \
     --ws <id> --start … --end … --job-ids <id1> --limit 1000 --suffix <id1> \
     --warehouse-id <wh-id> --run-folder $RUN_FOLDER --out analysis/verify/
   ```
   vt-job-run-states gives one row per run (failed = `FAILED`, `ERROR`, `TIMED_OUT`, `TIMEDOUT`;
   `CANCELLED` is separate) and is what analyze reads for the per-job failure rate; vt-job-runs
   adds duration and DBU per run. The workspace failure rate stays `data.facts.job_reliability`.
4. **analyze — the deterministic health read.** Starboard computes; you reason over the result.
   After verify and before present, run:
   ```bash
   starboard-helper engagement analyze --run-folder $RUN_FOLDER [--warehouse-id <wh-id>] [--prior drive:<run_folder_id> | --baseline]
   starboard-helper engagement analyze --run-dir <run-dir> --workspace-root <case-root> [--warehouse-id <wh-id>] [--baseline]
   ```
   `--prior` / `--baseline` are recur's flags: when you will pass one to `run recur`, pass the
   same one here, so both compare the same prior run (a local analysis reads every prior run of
   its root, as local recur does).
   Pass `--warehouse-id` whenever the operator named a warehouse: it is the SQL warehouse the
   printed verify / discovery commands use. Without it they print `<warehouse_id>` and list it
   under each play's `placeholders`; fill it in before running one. It reads `discovery/facts.json`, `findings-manifest.json` and every
   `analysis/verify/vt-job-run-states*.json`, compares against the account's prior runs, and
   writes `analysis/{observations,findings,health,plays,changes,cases,actions}.json` and
   `analysis/baseline-selection.json`. Read the summary it prints: `verdict`, per-family
   assessment and coverage, `top_plays`, `finding_states`, and the window comparison
   (`comparable`, `not_comparable_reason`, `window`, `prior_runs`; the same task-aware rule as
   `run recur`, see *recur*). `prior_runs` also lists the account's runs that are not compared, with
   `interval: null` where none is known and `skipped_reason` `other_task` (another task, a
   troubleshooting run included) or `no_observations`. A first run (no prior at all) reports
   `baseline: true`, `comparable: false` and `not_comparable_reason: "baseline"`. The only verify
   files it reads are job run-state slices (`analysis/verify/vt-job-run-states*`, listed in
   `inputs.verify`): run it again after a new one; another verify file changes nothing. It is
   idempotent.

   **Read the digest, not the files.** The envelope carries `top_plays[]` (up to 10, in effective
   order; each has `effective_rank`, `play_id`, `action_id`, `play_code`, `interaction_type`,
   `next_step_kind`, `target` (`kind:id`), `finding_ids`, `severity`, `urgency`, `exposure`,
   `host_rank`, `reason`, `next_commands`, `placeholders`, `acceptance_state` (the action's
   `pending`/`accepted`/`rejected`, null with no action) and `review_rule_id` (the review rule
   behind the play's finding, e.g. `spend_step_change`; null for a non-rule finding)), `plays_by_code`
   (`{<code>: {count, play_ids, samples}}`, `play_ids` the first 25 in effective order and
   `samples` the top 3 plays of the code as `{play_id, effective_rank, target, reason,
   exposure}`, so a code's plays can be ranked without opening `plays.json`), `coverage`
   (`{complete, partial, unknown}`: the family names at each coverage), `observations_by_family`
   and `findings_by_rule` (`{<rule_id>: {findings, dropped}}`, most findings first: the findings
   the manifest lists per review rule and, for a rule at its cap, `rule_findings_dropped`).
   `top_plays` has one entry per entity target: the lead play carries
   the target's exposure, and the target's other plays are listed under `same_target_plays`
   (`[{play_id, play_code, action_id, effective_rank, acceptance_state}]`) so no exposure is
   counted twice; a
   workspace-grain play is its own entry. Order and present the plays from it; open
   `analysis/plays.json` or `analysis/observations.json` only for a field the digest lacks, with
   `engagement read --jsonpath` slices (`'$[*].play_id'`, paged with `next_paths`, then
   `'[<n>].<field>'`). Each
   `plays.json` item carries `target` (`kind:id`), `effective_rank`, `action_id`, `severity` and
   `review_rule_id` as the digest does (`action_id` refreshes on `analyze`, `run recur` and `play
   rank`, not on `action propose`; `play rank` returns it too). A play's `rule_id` is the play rule
   set (`play_rules_v1`), so find a review rule's play by `review_rule_id`.
   "Top-ranked" always means the lowest `effective_rank`: host-ranked plays come first, ordered by
   `host_rank` (a tie keeps the computed order), then the computed plays, and `effective_rank` is
   the final position, so a single `--rank 5` moves that play to effective rank 1 and `--rank 2`
   behind another play's rank 2 lands at 3. There is no demote: a play can only be moved up.

   **Suppressed rules.** An uncertainty `suppressed:<rule_id>[:missing_column:<col>]` means the
   review ran the rule's evidence but could not evaluate the rule because the source lacks that
   column (e.g. `run_as` on the internal mirror); the manifest lists it in `suppressed_rules`
   (`{rule_id: reason}`). The rule is not counted in `rules_evaluated`. Its family reads partial, or
   reads unknown with `unknown_reason` `suppressed:<rule ids>` when every rule in the family is
   suppressed. Report it as "not assessed (source lacks <col>)". Never report it as healthy or as
   a "no owner" finding. A review re-run does not fix it, and no follow-up request is emitted for
   it: a family whose only gap is `suppressed:*` has no acquisition request (`acquisition_request`
   is null), because there is nothing to re-run when the source does not carry the column.

   **Cap fields.** `evidence_capped` means the rule's evidence query hit its row limit.
   `rule_finding_cap` (default 20) and `rule_findings_dropped` on a manifest finding mean more
   entities matched than the rule lists: the manifest lists exactly `rule_finding_cap` findings of
   that rule, and `rule_findings_dropped` more matched but are not listed (matched = cap + dropped).
   The listed ones are the highest-scoring, except `job_high_failure_rate`, which keeps its
   highest failure rates (then most runs), so a cheap job failing every run is never cut for a
   costlier, less failing one.
   A family's `active_rule_findings` counts the findings the manifest lists for the family's rules
   (one per `rule::entity`, all rules of the family, dropped ones never). It and `rules_evaluated`
   are workspace-grain observations in `analysis/observations.json` (metric name, family), not
   fields of `analysis/health.json` or the manifest. Take a rule's listed and dropped counts from
   the digest's `findings_by_rule` rather than paging the manifest's `findings`. `per_job_cap_25` means the reliability facts cover
   only the top 25 jobs per workspace. Say which cap applies; a count of exactly 20 is a cap, not
   the total.

   The governance family is assessed only from the `uc` and `portfolio-readiness` review domains,
   which the default `starboard review` does not run. A `health_check` run passes
   `--domains jobs,sql,warehouse,uc,portfolio-readiness` to its review (see
   [`starboard-health-review`](../starboard-health-review/SKILL.md)); without them governance is
   unknown with the reason `not_reviewed:<domains>`, not a missing manifest. The second form is the local run (public install, or an
   internal-only run kept local): `--run-dir` is preflight's `data.local_run_dir` and
   `--workspace-root` its case root (exactly the run dir's parent; any other root is
   `OUTSIDE_RUN_DIR`). The account's prior local runs, across every task, are the history
   (local prior is account-wide); the trend stays per case root. Cases are carried unchanged:
   `analysis/cases.json` lists the account's earlier cases (a troubleshooting run's case
   included) exactly as last revised. That is by design: `analyze` never opens, revises or closes
   a case, and a carried case is context, not a finding of this run. The case, action and play commands below take the same pair in place
   of `--run-folder`. Without a run descriptor they refuse ("run engagement preflight --storage
   local and route first").

   `analysis/health.json` covers six families: consumption_trajectory, efficiency, reliability,
   adoption_breadth, concentration and governance. Each is assessed or **unknown**; there is no
   overall score and no "healthy" label, and an unknown family is never read as fine. A family
   is assessed only on positive evidence: a rule whose evidence query succeeded, or a finding.
   When no discovery query succeeded (for example every query `PermissionDenied`), analyze
   returns `insufficient_evidence` with every family unknown and a warning: fix access and
   re-run discovery before any health read.
   - **Insufficient evidence.** When `verdict` is `insufficient_evidence` (no family assessed),
     the report says so on its own line, exactly `Insufficient evidence`, and lists what to
     acquire (the `acquire_family_evidence` plays). Never write a health read without evidence.
   - **Unknowns.** Every report has a `## Unknowns` section with one `- <family>: unknown` line
     per unknown family. `run check` fails (`health_read`) when either is missing.
5. **present — CONFIRM the shortlist and the artifact set.** Lead with `analysis/health.json`
   (assessed families, then unknowns) and the plays in `analysis/plays.json` (see **Host rubric**
   below). Show the **verified** backlog tiered
   Act now / Investigate / Not now (each with number + evidence + confidence). Ask the user which
   opportunities to carry and **which artifacts to generate** (deck / exec summary / evidence pack +
   notebooks / Slack / CRM draft). Because the list is already verified, selection can't collapse to
   nothing. Build only after they answer.
6. **synthesize** — build the substance: the evidence pack + action plan + charts + one notebook per
   carried Act-now AND Investigate item, composing the primitives below. Write
   `analysis/backlog.json` (a file you author: see **Files you author**). On a Drive run, put it
   before anything reads it:
   ```bash
   starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/backlog.json <<'EOF'
   <the backlog JSON>
   EOF
   ```
   Then generate the notebooks from it with
   `starboard-helper notebook render --run-folder $RUN_FOLDER --backlog analysis/backlog.json --all --out deliverables/notebooks/`
   (local run: `--backlog <run-dir>/analysis/backlog.json --all --run-dir <run-dir> --out
   <run-dir>/deliverables/notebooks/`; `--item <OPP-ID>[:<target>]` for one item) — don't
   hand-build them. Render writes each notebook path into its item's `notebook` field in
   `backlog.json` by default (`--no-update-backlog` to skip), so there is no separate
   path-registration step; a bundle-deployed job's remediation cell is always bundle YAML plus a
   redeploy. Map every opportunity to its catalog id (e.g. `OPP-WH-IDLE`); see
   `starboard-action-plan/references/opportunity-catalog.md` (contract §2). Render every
   deliverable chart to PNG with
   `starboard-helper charts render --run-folder $RUN_FOLDER --kind <kind> --data analysis/charts/<name>.json --out deliverables/charts/<name>.png --window-days <data.facts.window.days>`
   (local run: `--data <run-dir>/analysis/charts/<name>.json --out
   <run-dir>/deliverables/charts/<name>.png`; needs the `starboard-skills[render]` extra;
   `--help` lists every kind and its required columns). The data file is a **JSON array** of row
   objects, or **NDJSON** (one object per line), whose keys are the kind's **required columns**,
   so rename the source fields first:

   | Kind | Source rows | Rename (source → required column) |
   |---|---|---|
   | `dbu-trend` | vt-daily-totals rows | `usage_date` → `usage_date`, `dbus` → `total_dbus` |
   | `spend-by-product` | `data.facts.product_mix` | `product` → `billing_origin_product`, `dbus` → `total_dbus` |
   | `spend-concentration` | `data.facts.top_jobs` / `top_pipelines` (or any entity list) | `name` → `driver`, `pct` → `share_pct` |
   | `recoverable-dbu` | `analysis/backlog.json` `bounded_dbu` items | `title` → `opportunity`, `sizing.value` → `recoverable_dbus`, `tier` → `confidence_tier` |

   The row file is a file you author. On a local run, write literal JSON with `jq -n` (plain `jq`
   with no input writes an empty file); to transform a verify file, wrap the result in `[ … ]` for
   an array, e.g.
   `jq '[.data.rows[] | {usage_date, total_dbus: .dbus}]' <run-dir>/analysis/verify/vt-daily-totals.json`
   (without the brackets jq streams one object per line, which `charts render` reads as NDJSON),
   saved to `<run-dir>/analysis/charts/<name>.json`. On a Drive run, take the rows from
   `engagement read --jsonpath` and put the renamed array before `charts render` reads it:
   `starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/charts/<name>.json`,
   the JSON array on stdin (`<<'EOF'`).
   `python -m starboard_x.charts` emits specs only and doesn't render.
7. **technical-review** — accuracy gate, now covering the generated code too:
   [`references/technical-review.md`](references/technical-review.md).
8. **humanize** — the de-AI-slop voice gate: [`references/humanize.md`](references/humanize.md).
9. **deliver — publish through report revisions.** Bind capabilities to tools, preview +
   confirm, degrade visibly ([`references/capability-bind.md`](references/capability-bind.md)).
   Deliver comes after recur (beat 10), `engagement commit --stage analysis`, `run check` and
   `engagement commit --stage check`, so every report points at final files. On a Drive run each
   artifact that leaves the run folder is published in this order:
   1. **Register the report.**
      `starboard-helper engagement report --run-folder $RUN_FOLDER --report-id <report-id> --audience <internal|customer> --path deliverables/<file>`
      returns its `revision` and `state`. A `customer` report that cites internal-only evidence
      is `blocked_audience` (with the offending IDs): rewrite it from customer-shareable
      evidence and register a new revision (`--derived-from <report-id>@<n>`). It refuses
      (`REPORT_REFUSED`, exit 2) a body under `raw/` or `evidence/`, a `customer` report with no
      `--cite-evidence` / `--cite-observation`, and a `customer` report whose body is itself
      internal-sourced evidence; and (`UNCOMMITTED_ARTIFACT`) a body the latest commit doesn't
      bind, so commit its stage before registering it.
   2. **Approve it (customer audience).** Show the operator the exact revision and ask. On yes:
      `starboard-helper engagement approve --run-folder $RUN_FOLDER --report-id <report-id> --revision <n>`.
      The approval binds that revision's content, so any edit needs a new revision and a new
      approval. An unattended run can't approve (`can_approve` is false): leave the customer
      report `pending` and say so; never record an approval the operator didn't give. An
      `internal` report needs no approval and no delivery: the internal run folder is its
      delivery, so it never holds the run in `publication_pending`.
   3. **Deliver it, or record the delivery.** Copy it to a Drive destination with
      `starboard-helper engagement deliver --run-folder $RUN_FOLDER --report-id <report-id> --revision <n> --destination-folder-id <folder_id>`
      (the destination must be internal-only, else `DELIVERY_REFUSED`),
      or, after you publish it yourself through a host tool (a Google Doc, Slides or a Slack
      post), record that with
      `starboard-helper engagement receipt --run-folder $RUN_FOLDER --report-id <report-id> --revision <n> --external-object-id <object_id> --channel <google_doc|slides|slack> --destination-id <folder_or_channel_id>`.
      Pass `--destination-id` (the folder holding the object, or the Slack channel ID) whenever
      no verified `deliver` of that revision is recorded.

   **Only a verified receipt completes the run.** The run is `complete` when every report that
   needs delivery has a verified receipt; until then it is `publication_pending`, and a failed
   delivery leaves it pending (analysis stays complete). A Drive, Doc or Slides receipt is
   verified only when the delivered object sits directly in `--destination-id` (or in the
   destination of a verified `deliver`), is outside the run folder and staging, is not a run
   artifact, matches the revision's md5 when Drive reports one, and was created after the
   approval; otherwise `receipt` returns `warnings` and the run stays pending. So create a Doc
   or Slides deck outside the run folder and staging (for example in the case folder, or an
   owner-only folder the operator owns) and pass that folder as `--destination-id`.
   A Slack receipt is recorded as unverified: **a Slack receipt never completes**
   a customer delivery, so pair it with a Drive, Doc or Slides receipt. A local run has no report
   chain: record each artifact's outcome in README `## Delivery` (see Outputs layout).

   **Record the delivery in the README (Drive run).** After the receipts, fill README
   `## Delivery` with each artifact's outcome. Read the README with `engagement read --path
   README.md`, only when `truncated` is false; if it is true, stop and report, and never put back an excerpt (it would replace the file with the excerpt). Put the whole file back, then commit the check stage again so the
   manifest records the new md5; without that commit a later `engagement read` of the README
   returns `committed: false`. A commit after publication updates the changed file in place and
   leaves the reports, approvals and receipts untouched:
   ```bash
   starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
   <the whole README, with the ## Delivery lines filled in>
   EOF
   starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
   ```
10. **recur** — a stateless run-over-run comparison; no standing service, no daemon. Each recurrence
   is a fresh review compared against prior measurements. It works the same on the live-connect
   path (`--profile <name>`) and the no-connect path (`--internal-workspace-id <id>`, overlay
   installed): both write `findings-manifest.json`. Recur runs after synthesize (it reads
   `analysis/backlog.json`) and before deliver.

   **Drive run — history comes from the account registry.**
   1. **Find eligible history.**
      `starboard-helper engagement history --run-folder $RUN_FOLDER` looks up every registered
      run of the account (any task, ticket or override folder) and picks a baseline **per
      observation** (same account, workspace, family, entity and metric, same unit and method, an
      earlier window), not per run. It writes `analysis/baseline-selection.json` and returns
      `selected[]` (`{key, current_observation_id, baseline_observation_id, comparison}`: it
      names observations, not runs; the compared run is recur's `window.prior_run_id`),
      `rejected[]` (`{key, candidate_observation_id, candidate_run_id, interval, reason}`),
      `unavailable[]` (`{registration_id, reason}`) and `candidates`, a count of the earlier
      observations considered (a number, not a list). The printed lists stop at 50 items
      (`truncated: true`, counts in `omitted`); the full lists are in
      `analysis/baseline-selection.json` (page them with `engagement read --jsonpath`). An entry with
      `history_unavailable` is a registered run you can't read (another operator's folder, a
      revoked share): name it as a coverage gap; it is never a baseline and never "no change".
      Its reporting interval is `--interval-start`/`--interval-end` when given, else this run's
      observations, else (before `analyze`) the captured `discovery/facts.json` window;
      `reporting_interval_source` names it (`flags`, `observations`, `facts`). Before the
      capture there is none, and without the flags it exits 2 `USAGE`.
      This call is optional: `run recur` makes the same selection and writes the same file.
   2. **Run the review into the run.** When this run has a discovery output (beat 1), review it
      after discovery finishes, never concurrently:
      ```bash
      starboard review --from-discovery discovery --run-folder $RUN_FOLDER --json \
        --out analysis/review.json --manifest-out findings-manifest.json
      ```
      A live customer review (`--profile`) cannot write to a run folder and is refused: on a
      standalone or scheduled review, run discovery into the run folder first, then the
      command above:
      ```bash
      starboard --discover --profile <name> --lookback-days 30 --data-only --json \
        --out-dir discovery --run-folder $RUN_FOLDER
      ```
   3. **Run recur.**
      `starboard-helper run recur --run-folder $RUN_FOLDER [--warehouse-id <wh-id>] [--prior drive:<run_folder_id> | --baseline]`
      uses the same registry selection (`--prior` pins one run, still eligibility-checked, and
      waives the task and manifest rules below; `--baseline` skips the lookup on a first run).
      Pass `--warehouse-id` whenever the operator named a warehouse, as on `engagement analyze`
      (without it the printed commands carry `<warehouse_id>` under `placeholders`). It writes
      `analysis/baseline-selection.json`,
      `analysis/recur-result.json` and the delta outputs into the run folder. Each comparison is
      `no_prior_measurement`, `missing_current_evidence`, `not_comparable`, `continuing`,
      `recovered` or `new`; carry those words, and never read `missing_current_evidence` or
      `not_comparable` as improvement. Only a prior run of this run's task that committed a
      `findings-manifest.json` is ever the compared run; any other prior is listed in
      `prior_runs` with `skipped_reason` `other_task`, `no_findings_manifest` or `no_observations`. A prior whose
      reporting window differs in length from this run's (7 vs 30 vs 90 days, beyond ±1 day of
      the declared lookback) is rejected as `window_mismatch` and reads `not_comparable` (its
      `baseline-selection.json` reject names `candidate_run_id` and `interval`); a same-length
      prior is chosen when one exists. On a comparable run of a backlog task whose
      `analysis/review.json` has no `cost_delta`, recur warns "re-run review with --since
      drive:<id>" (`<id>` is the compared run's committed `findings-manifest.json`): re-run the
      step 2 review with that `--since drive:<id>`, then recur again. The result and README
      `## Recur` follow the shared recur contract below.

   **Local run — history comes from the case root.**
   1. **Locate the prior run.** The newest *other* run of this case with a manifest:
      `ls -1 <case-root>/*/findings-manifest.json` (skip the current run). Order by each run's
      `analysis/storage-preflight.json` `created_at`, not by name: the run ID is random after
      the date. None = this is the **baseline** run: omit `--since`, and this run's manifest
      becomes the baseline for next time. Runs of another task (another `<task>` folder) are
      never a prior.
   2. **Run the review, write the manifest, save the JSON.**
      ```bash
      starboard review --from-discovery <run-dir>/discovery --json \
        --out <run-dir>/analysis/review.json \
        --manifest-out <run-dir>/findings-manifest.json \
        --since <case-root>/<prior-run-id>/findings-manifest.json
      ```
      With no discovery run, use `starboard review --profile <name> --lookback-days 30 --json
      --out <run-dir>/analysis/review.json` with the same `--manifest-out` / `--since` flags.
      (Drop `--since` on the baseline.) `--since` may also name a prior run's
      `findings-manifest.json` inside the same case root on an `internal_only_local` run (the
      review is run with `--run-dir <run-dir>`); a `--since` outside the case root is refused
      with `LOCAL_FILE_INTAKE_REFUSED`.
   3. **Run the recur helper** — deterministic; do not hand-build the trend JSON:
      ```bash
      starboard-helper run recur <run-dir> --workspace-root <case-root> [--warehouse-id <wh-id>] [--prior <case-root>/<prior-run-id> | --baseline]
      ```
      It auto-locates the same prior run: the newest other run dir under the case root with a
      manifest (same day: by preflight `created_at`), never the wider tree. Pass `--prior` to pin
      it (a prompt-supplied run dir), or `--baseline` to skip the lookup on a
      first run. `--workspace-root` may be any directory except the run dir itself. It appends
      the run to `<case-root>/trend/history.json` (keyed on `(run_date, run)`, so two same-day recurs are two entries). Auto-locate
      prefers the newest prior with the same `lookback_days`; if only a different-length prior
      exists it is used but flagged `comparable: false` / `window_mismatch` (see below).
      **Isolated run dir (prompt tests).** When the prompt fixes `RUN_DIR` (passed to preflight
      as `--run-dir`) and forbids reading other runs, use
      `--workspace-root "$RUN_DIR/ws-root" --baseline`: history goes to
      `$RUN_DIR/ws-root/trend/history.json` and nothing outside `$RUN_DIR` is touched.

   **Both forms.** `--out` writes the review JSON envelope; never redirect stdout (`> review.json
   2>&1` saves the banner and logs into the file) or stderr (`2>file`), not even to `/tmp` on a Drive run. `--from-discovery` evaluates the rules on the
   saved discovery rows: offline (no second scan, no connection), workspace + lookback inherited
   from the discovery output, so review and discovery agree. A query that failed or was skipped
   in discovery degrades its domain: the review JSON and the manifest carry `degraded`,
   `unavailable_queries` and `unavailable_domains`, and recur marks those domains "not
   comparable" (their finding counts aren't a trend). `unavailable_queries` lists every evidence
   query a review rule reads that failed, was skipped or is missing from the capture; the
   manifest's `discovery_skipped` lists every query discovery skipped and `coverage_note` says
   which of them no rule uses, so an empty
   `unavailable_queries` is not "full coverage". The manifest is the machine-readable per-run
   record: per-finding `rule_id`, `entity_id`, `composite_key` (`rule_id::entity_id`),
   `severity`, `score`, and `evidence_dbu_estimate` (list-price DBU; null for
   reliability/latency findings with no DBU attribution). With a prior, the review JSON carries
   the cost-aware `cost_delta`, keyed on `composite_key`: `newly_expensive` / `regressed` /
   `improved` / `persisting` / `new_low_cost`, with per-entry `prior_dbu` / `current_dbu` /
   `dbu_delta` / `dbu_delta_pct`, plus `products_dbu_delta`. Manifests are never written to the
   customer workspace.

   **The recur contract (both forms).** `run recur` (Drive or local) returns, and writes to
   `analysis/recur-result.json`, `{ok, baseline, comparable, not_comparable_reason, window,
   prior_runs, delta_skipped_reason, errors, warnings}`: `window` is `{comparable, reason,
   prior_run_id, prior_lookback_days, current_lookback_days}` (`prior_run_id` is the compared
   run) and `prior_runs` is `[{run_id, interval: {start, end} | null, task, skipped_reason}]`, newest
   first (empty with no prior; `skipped_reason` is `other_task`, `no_findings_manifest`,
   `no_observations` or null
   for a run that may be compared). `baseline` is true when no prior run has observations (none at
   all, or only rows skipped as `no_observations`) or with `--baseline`; a prior skipped as
   `other_task` or `no_findings_manifest` gives `no_eligible_prior` instead; a baseline reports `comparable: false` and `not_comparable_reason:
   "baseline"` (nothing was compared). Check `baseline` first: describe a baseline as "baseline —
   no comparison", never as "not comparable"; only `window_mismatch` and `interval_overlap` (and
   `no_eligible_prior`) mean a prior existed and could not be compared. A run whose every eligible prior has another window length is not a
   baseline but `comparable: false`, `not_comparable_reason: "window_mismatch"` with a
   `window_mismatch:` warning naming both lengths. With prior runs but none eligible (another
   task, or no committed manifest) it is `comparable: false` with `no_eligible_prior`. When an
   eligible prior exists but no comparison key has a baseline (for example the reporting
   intervals overlap), the run is `comparable: false` with the dominant per-key reason as
   `not_comparable_reason` (`interval_overlap`). In every not-comparable case no outcome is
   computed, carried actions get no `outcome_state`, and README `## Recur` says so. Never read
   it as "no change". `delta_skipped_reason` says why no delta file was written: null (a delta
   was written, or a baseline), `no_eligible_prior`, `prior_no_findings_manifest` or
   `prior_manifest_unreadable` (Drive only; a local prior always has a manifest).

   Both forms upsert README `## Recur`: `baseline — no prior run (<date>)` on the first run;
   when not comparable a line led by `not comparable (<reason>)` (`window_mismatch`: "— windows
   differ: the prior run covers N days, this run M"; `no_eligible_prior`: "no prior run of this task committed
   a findings-manifest.json") and, on Drive, `Prior run(s): <ids> (skipped: <reason>)`; else the
   delta summary naming the prior run(s) (Drive: `delta vs <ids> (per-observation baselines)`,
   `Finding states: …` and `Skipped prior run(s): …` when any was skipped). A Drive result adds
   `verdict`, `comparisons`, `finding_states`, `run_date`, `prior_run_folder` and the counts,
   and writes `analysis/delta-vs-<prior_date>.md` plus a README `- Delta:` line like a local run;
   the Drive result and the local stdout carry `prior_run_date`, `history_entry` (local stdout:
   `entry`), `delta_path`, `delta_counts`, `backlog_delta` and `backlog_sizing` (on a
   `health_check`, `backlog_delta` holds empty lists and `backlog_sizing` is `[]`, never null); a Drive one
   also carries `prior_entry` (a Drive run's history entry has `window.prior_run_id`), and a
   local `recur-result.json` adds `prior_run` and `history_path`. A `health_check`
   run has no backlog: its recur has no backlog sections and no missing-backlog warning. `run check` requires `ok: true` (or `baseline: true`); on a failure read
   `errors`, fix, and re-run (it is idempotent).

   A local recur also (the Drive form writes the delta file and the README `## Recur` summary the
   same way; only the trend charts and `history.json` are local):
   - writes the trend rows (`charts/data/spend-over-time.json` + `finding-count-over-time.json`)
     and renders `charts/trend/spend-over-time.png` + `finding-count-over-time.png` (if the
     render extra is missing it writes the data and says so in `warnings`);
   - writes the `analysis/delta-vs-<prior-date>.md` skeleton from `analysis/review.json`'s
     `cost_delta` — improved / regressed / newly expensive / persisting / new low-cost tables
     (entity, prior→current DBU, %), with both trend PNGs embedded (a Drive delta file has no
     image embeds); a comparable `health_check` delta with no `cost_delta` says "No review findings
     cost delta (`analysis/review.json` carries none)." (a not-comparable delta has no cost-delta
     section; see below) — plus the **primary trend**:
     the backlog's `sizing.value` per `(id, target)`, prior → current (Δ only when the metric and
     unit match), and a backlog delta by catalog id (new / resolved / tier changed). Write
     `backlog.json` before running recur;
   - writes the README `## Recur` delta summary as `delta vs <prior-date>: N improved, M
     regressed, …` with links;
   - **Different window lengths.** When the prior's `lookback_days` differs from this run's
     (`window.prior_lookback_days` / `window.current_lookback_days`), recur sets
     `comparable: false` and `not_comparable_reason: "window_mismatch"`, computes no sizing delta
     (rows read `not_comparable`), charts spend only against runs of the same window, and the
     delta file and README lead with "not comparable (window_mismatch) — windows differ".
     `review --since <prior manifest>` applies the same window rule to its `cost_delta`: overlapping
     windows give `interval_overlap`, lookbacks more than ±1 day apart give `window_mismatch`. In
     both cases `cost_delta.comparable` is false, there is no DBU delta and no improved / regressed
     classes, only `persisting` (capture repeatability). Never present improved or regressed from a
     not-comparable `cost_delta`; a real change needs a same-length, non-overlapping window.
   - **Not comparable (any reason).** The delta file leads with `**not comparable (<reason>)**`
     and, in place of the change tables, a `## Capture repeatability (not a change)` table
     (`| Rule | Findings in both | Prior DBU | Current DBU |`) that counts, per rule id, the findings
     (`rule::entity`) present in both captures, taken from the two manifests even when there is no
     `cost_delta`: it shows the capture repeats, never an improvement, regression or new finding.
     It names no entity (a rule may key one by a name that embeds a user name); the entity ids are
     in the two `findings-manifest.json` files, and never copy them into a report. The window totals print as
     `prior X · current Y (not compared)`, with no arrow. The delta file is still
     `analysis/delta-vs-<prior_date>.md`; its title is ``Delta vs <prior_date> (prior run `<short
     id>`)``, so two same-day runs are told apart.
     The "re-run review with --since" and "analysis/review.json not found" warnings appear only
     on a comparable run of a backlog task. Tell the operator the windows
     differ and show per-day normalised list-price DBU (`dbu_per_day`) as indicative only; never
     report the raw total difference as a change.

   **Actions and outcomes.** `engagement analyze` and `run recur` propose at most one action per
   play (`actions.json`, acceptance `pending`); on a troubleshooting case you propose one with
   `action propose --case-id <case_id>` (*Cases*). Only the operator moves it, and only on their word:
   ```bash
   starboard-helper engagement action accept --run-folder $RUN_FOLDER --action-id <action_id> --note "<who agreed, no names>"
   starboard-helper engagement action execute --run-folder $RUN_FOLDER --action-id <action_id> --executed-at <YYYY-MM-DD>
   starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
   ```
   (`action reject` and `action withdraw` take the same flags.) `execute` needs a prior `accept`,
   else `INVALID_TRANSITION` (exit 2), and `reject` is final. Repeating a verb on an action
   already in that state (`accept`, `reject`, `execute`, `withdraw`) is idempotent: the data
   carries `already: "<state>"` and nothing is written, so a retry after exit 8 is safe. The outcome comes only from
   measurement: recur sets `improved` / `unchanged` / `worsened` from the finding's next
   comparison, and lost coverage gives `unknown`, never `improved`. Attribution is at most
   `consistent_with_action` (executed, `executed_at` before the verification window, outcome
   improved); otherwise `not_established`. Never write that an action caused a change.
   **Improvement is not adoption**: an improved metric leaves `acceptance_state` as it was, so
   report "the metric improved" and "the customer adopted the change" as separate facts.

   **Write the narrative.** You (the analyst) replace the `_Analyst:` placeholder in
   `analysis/delta-vs-<prior-date>.md`: what improved, what regressed, what is newly expensive,
   and why. Don't read a change in a "not comparable" (degraded) domain as improvement or
   regression — say the evidence was unavailable on one side. `$`/DBU = list-price estimate;
   the skeleton's scope line says whether product DBU totals cover one workspace ("cover workspace
   <id>", when the manifest or discovery is scoped) or are account-scoped (unscoped evidence);
   finding-level DBU is workspace/entity-attributable — carry that caveat as the skeleton states it. A real trend needs ≥2 runs; the baseline renders a single point. On a
   Drive run, read the skeleton with `engagement read --path analysis/delta-vs-<prior-date>.md`
   (only when `truncated` is false; if it is true, stop and report, and never put back an excerpt (it would replace the file with the excerpt)) and put the finished file back to the same path, along with the updated README, before
   the analysis commit:
   ```bash
   starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/delta-vs-<prior-date>.md <<'EOF'
   <the delta narrative Markdown>
   EOF
   starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
   <the README Markdown, keeping the ## Recur section recur wrote>
   EOF
   ```

   **Finish the run.** `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage
   analysis`, then `starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json`
   (local: `starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json`),
   then `starboard-helper engagement commit --run-folder
   $RUN_FOLDER --stage check`, then deliver (beat 9). `run check` can take several minutes: run it
   in the foreground with Bash `timeout: 600000`. Its warnings are at `data.warnings` (the
   envelope's top-level `warnings` stays null). `run check` checks the items of the run's
   task profile (`data.profile`, from the run descriptor's task) and lists the rest under
   `skipped_by_profile`: the verify floor, backlog, notebooks and action-plan items are
   `action_plan` only. A `health_check` run is checked for `deliverables/health-read.md` (see
   [`starboard-health-review`](../starboard-health-review/SKILL.md)); a `troubleshooting` run for
   `deliverables/case-report.md` and a revised case (see
   [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md)). On a local run, append a one-line audit entry
   to `starboard-reports/schedule.log`, except on an isolated run dir (record the line in README
   `## Recur` instead).

   **Scheduling.** For unattended recurrence, wire the `starboard-workload-review-auto` agent to a
   **durable** `CronCreate` schedule — `0 8 1 * *` for a monthly review — and confirm it with
   `CronList` (see that agent's **Scheduling** section; recipes for both `--profile` and
   `--internal-workspace-id`). The agent finds the prior run itself each time. The internal path
   works unattended but needs the internal credentials/profile on the machine that runs it. The
   `recur` beat itself stays stateless: each run is a fresh review compared against stored runs.

## Host rubric (ordering plays)

`analysis/plays.json` lists candidate plays in Starboard's order. Each carries six factors:
`urgency`, `criticality`, `exposure` (always the four keys `failed_runs`, `failed_run_dbus`,
`exposure_dbus`, `exposure_dbus_per_day`: `exposure_dbus` is the finding's list-price DBU
estimate over the window, on every play except a run-rate rule; `spend_step_change` carries
its DBU/day lift as `exposure_dbus_per_day` with `exposure_dbus` null (it equals the manifest's
`evidence_dbu_estimate` and the cited row's `lift_daily_dbus`; that row also has `step_date`,
`before_daily_dbus` and `after_daily_dbus`), and its reason reads
"~N DBU/day run-rate (list-price estimate)": never sum it with window totals (the computed
order weighs it as DBU/day × the interval's days, so it ranks against window totals); `failed_runs`
and `failed_run_dbus` are set only by the job-failure rules, `failed_run_dbus` only with
`failed_runs`, and `failed_run_dbus` is never an estimate for another kind of rule),
`evidence_strength`,
`reversibility` and `owner_availability` (`unknown` until someone states it). Weigh all six; you
may reorder, but only with a stated reason:

```bash
starboard-helper engagement play rank --run-folder $RUN_FOLDER --play-id <play_id> --rank <n> --reason "<why it moves>"
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
```

A host rank belongs to this run only: the next run's `analyze` starts with `host_rank: null`
(play IDs are stable), so re-apply `play rank` when the reason still holds.

(A `health_check` run does not commit here: it makes one analysis commit after its last write, as
`starboard-health-review` Step 6 says.)

A play's `next_commands` run as printed: a verify line carries the run target (`--run-folder`
and `--out analysis/verify` on Drive, `--out <run-dir>/analysis/verify` locally), a per-entity
`--suffix`, a `--limit` within the verb's cap and, on the public path, `--warehouse-id` (the
`analyze` / `recur` `--warehouse-id`, else `<warehouse_id>`, the only placeholder, listed in
the play's `placeholders`). A `health_check` run has no `job fetch` command (a health review
never fetches a single job's logs), and an `internal_only` run gets the internal verify form
(`--internal-workspace-id <ws>`, plus `--templates ~/<overlay skill path>/mirror-verify.md`
when the overlay skill is installed), never the public `--profile` form. The printed path is the
overlay copy the host loaded (the plugin root or dev-mode path), preferred over any plugin cache;
set `STARBOARD_OVERLAY_DIR` to the overlay skill dir to pin it. A rule play never
prints a `starboard review` re-run (it would overwrite the run's review). Its verify command is the
rule's template: `spend_step_change` → `vt-daily-totals` (`vt-step-change` needs `--split-date
<step_date>`), `portfolio_untracked_production_consumption` → `vt-product-totals`,
`warehouse_recent_resize` → `vt-warehouse-config-history`; a job rule with no template →
`vt-job-runs --job-ids <id>`; anything else → `vt-product-totals`. A workspace-grain
rule with one manifest entry per product is one finding and one play, at the highest review
severity, with the entries' DBU summed. The digest in `analyze`'s envelope carries them.

The reason must name the factor that moved it (e.g. "criticality high: the job feeds the board
report"). You can't edit a play's `reason`, `exposure`, measurements or `evidence_strength`; if
you think one is wrong, say so in the report. A play with `missing_evidence` is an
investigation, not an act: present what to acquire, not a fix.

## Cases (one focused question on a finding)

A case asks one question about one finding and records what the evidence says. Open it in a
`troubleshooting` run (beat 0: `--task troubleshooting --task-name job-<id>`), never inside a
workspace run.

```bash
starboard-helper engagement case open --run-folder $RUN_FOLDER --finding-id <finding_id> --question "<why did job 42 start failing?>"
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue job:<id> --question "<the operator's question>"
starboard-helper engagement case revise --run-folder $RUN_FOLDER --case-id <case_id> --evidence raw/job-run-output-<run_id>.json --hypothesis "<statement>" --hypothesis-status supported
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
starboard-helper engagement action propose --run-folder $RUN_FOLDER --case-id <case_id> --next-step "<the change>" --owner-role <role> --verify-method "<how the outcome is checked>"
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
starboard-helper engagement case show --run-folder $RUN_FOLDER --case-id <case_id>
starboard-helper engagement case open --run-dir <run-dir> --workspace-root <case-root> --clue job:<id> --question "<the operator's question>"
```

The last line is the local-run form. A troubleshooting run's write-up is
`deliverables/case-report.md` (from [`templates/case-report.md`](templates/case-report.md)); its
README `## Recur` reads `not applicable: troubleshooting run`. The whole case flow is the
[`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md) entry skill.

Commit (`--stage analysis`) after every `case revise`, `action …` and `play rank`: each one
rewrites `analysis/*.json`, and an uncommitted write is not part of the run. (A health review makes
its one analysis commit after its last write: `starboard-health-review` Step 6.)

- **From a health finding.** `--finding-id` may come from another run of the account: a
  `troubleshooting/` run can open a case on a finding from a `health_check/` run. The prior finding
  is loaded through the registry and revised (same `finding_id`, revision + 1, reason
  `investigated`).
- **From a clue.** `--clue job:<id>`, `query:<id>`, `pipeline:<id>` or `run:<id>` (or `--drive-object drive:<id>`)
  opens a standalone case with its own `case:<kind>` finding; a later health run links it when the
  same entity carries a rule finding.
- Gather the evidence with the focused skills (`starboard-job`, `starboard-query`,
  `starboard-diagnostic`), saved into the run, then `case revise` with each file. Compare two
  saved documents with
  `python -m starboard_x.diff settings --a raw/job-<id>-before.json --b raw/job-<id>-after.json --run-folder $RUN_FOLDER`
  (`diff metrics` for two `query fetch` or `profile` outputs).
- A case's `finding_id` and `finding_key` are the ones `case open` printed, for good: no
  revision re-keys them, so two standalone cases on one job share one `case:job` finding.
  `finding_revision` is the finding's latest revision across the account's runs
  (`finding_revision_run_id` wrote it); `case open` and `case show` never change it, and each
  `case revise` adds 1. A `case revise` that cites a `job run-output` with `--evidence`
  reports its `error_signature`, `<category>/<exception>[:<code>]` (e.g.
  `unknown/restexception:not_found`; null without one). `--question` and `--hypothesis` are at
  most 500 characters, with no emails or credentials (refused, exit 2).
- A hypothesis is `untested`, `supported` or `refuted`; mark it `supported` only
  when a cited file shows it. The evidence the same `case revise` registers
  (`--evidence`, `--verify`) always joins the targeted hypothesis's list, and a reword or
  status-only step with no new evidence keeps the stored evidence and status.
  `--hypothesis-evidence <evidence_id>` (repeatable) names evidence already in the run (an
  unknown ID exits 2) and REPLACES the stored IDs with exactly those, but the step's own evidence
  is still added. `--hypothesis-id <id>` revises that
  hypothesis in place (it keeps its position in `hypotheses[]`) instead of adding one, and `--hypothesis-id <id> --hypothesis-status
  <status>` alone reuses the stored statement (no `--hypothesis` text needed). `--verify` takes
  only a job run-state verify result (`vt-job-run-states`); cite any other verify file
  (warehouse, query, pipeline) with `--evidence <path>`. `case open`, `revise` and `show` list
  the case's `hypotheses` (`[{hypothesis_id, statement, status, evidence_ids}]`); `case show`
  adds its evidence and an `evidence_paths` map (evidence ID to run-relative path). Evidence
  carried from the finding's other runs has a null path there and is listed in `evidence_from_run`
  (evidence ID to the run that cited it): a null path is normal for carried evidence.
  `--cause-confidence` raises the finding's `cause_confidence` in order `unassessed` (the
  start, never passed) → `hypothesis` → `supported`; `supported` needs a hypothesis with status
  `supported` that cites evidence; omit it to keep the current value.
  A case never makes a health family assessed.
- **The next step.** Once the cause is recorded, `action propose --case-id <case_id>` records
  the host's next step as a `pending` action on the case's finding (`--owner-role` is
  `job_owner`, `pipeline_owner`, `warehouse_owner`, `platform_admin`, `operator` or
  `account_team`; `--owner-label` and `--verify-method` are optional free text). It needs the
  case's finding in this run (after `case revise`; else `CASE_NOT_REVISED`, exit 2), and the same
  next step on the same case names the same action. A case action has a `case_id` and no
  `play_id`; a later `analyze` never withdraws it. Then `accept` / `execute` it only on the
  operator's word (*Actions and outcomes*).

**Internal-only local runs and the registry.** An internal-only run the operator kept local
(`--storage local`, `internal_only_local`) isn't in the account registry, so a later Drive run
can't use it as history. To publish it, run
`starboard-helper engagement import-local --run-dir <run-dir> --account-key <account_key> --confirm`
once the operator agrees (`--confirm` records that consent; an unattended run never imports). It
uploads an observation/action summary and a reference, never the local raw files, and refuses a
run that holds customer-workspace evidence. A run is imported once: re-importing it after it
changed is `IMPORT_REFUSED`, so start a new local run instead. If the registry index looks stale (a run you just
routed is missing from `history`), rebuild it with
`starboard-helper engagement rebuild-index --account-key <account_key>`; the registrations themselves are
the record.

**Unattended / prompt-pre-answered fallback.** When the prompt already fixes the deliverable, or no
interactive user is present (scheduled run, unattended agent, or prompt test), the CONFIRM gates
collapse to a documented default rather than pausing:
- **scope**: use all workspaces in the gathered data without asking.
- **present**: carry all verified items from the Act-now and Investigate tiers; generate the artifact
  set specified in the prompt, or the full default set — on an `action_plan` run: exec summary +
  evidence pack + action plan + one notebook per Act-now AND Investigate item + charts + Slack
  draft (draft only); on a `health_check` run: the health read — if none was specified.
- **preflight**: pass `--unattended` only on a run the prompt calls scheduled or unattended (or
  one that says not to ask anything); a pre-answered prompt stays attended, even one that calls
  itself non-interactive. A covered unattended run needs Google Drive already
  authenticated, and stops before gather if `engagement verify-identity` or `engagement route`
  fails.
- **deliver**: on a Drive run the run folder **is** the internal record. Register each report;
  `internal` reports deliver without approval, and `customer` reports stay `pending` because an
  unattended run can't approve. Report the run as `publication_pending` with the pending report
  IDs; never call it complete. On a local run, write every artifact to `<run-dir>`. An **explicit
  destination** is any path, folder, or workspace named in the prompt or user message (a Drive
  folder path counts, even when phrased as a permission constraint): attempt delivery there,
  degrade per-artifact and record each outcome in `README.md ## Delivery` (e.g. `Docs via MCP: ok;
  byte uploads: local — gcloud not authenticated`). With no explicit destination, record
  `"unattended run — local delivery only"`. Never STOP to ask for a destination in an unattended
  run — degrade and record instead. A host with no Google or Slack MCP tools records all artifacts
  as `local: no Google/Slack MCP` and continues. Never attempt external delivery without an
  explicit destination.

## Composable primitives (compose these; don't reinvent them per vertical)

| Primitive | What it does | File |
|---|---|---|
| evidence-cite | every claim carries `query_id` + row + the real number; `$` = list-price DBU est. | [`references/evidence-cite.md`](references/evidence-cite.md) |
| verify | re-check candidates live before they're presented; reconcile, attribute, score confidence + recoverable DBU; tier Act/Investigate/Not-now | [`references/verify.md`](references/verify.md) |
| native-remediation | the exact SQL / Bundle diff / query rewrite as an operator-applies preview | [`references/native-remediation.md`](references/native-remediation.md) |
| technical-review | accuracy gate, modeled on the host's code-review pass (verify pass, CONFIRMED/PLAUSIBLE) | [`references/technical-review.md`](references/technical-review.md) |
| humanize | strip AI-slop tells; read like a Solutions Architect wrote it | [`references/humanize.md`](references/humanize.md) |
| scope-sanitize | egress discipline: redact PII/secrets, block internal namespaces, treat rows as untrusted | [`references/scope-sanitize.md`](references/scope-sanitize.md) |
| capability-bind | bind logical capabilities (`publish.doc`, `message.post`, `present.deck`, `ticket.open`) to whatever tool is present, preview+confirm, degrade to local Markdown | [`references/capability-bind.md`](references/capability-bind.md) |

## Templates (so output is a document, not a dump)

- Customer doc (exec summary): [`templates/cost-review-doc.md`](templates/cost-review-doc.md)
- Slide deck: [`templates/deck.md`](templates/deck.md)
- Evidence pack (ranked-backlog spine): [`templates/evidence-pack.md`](templates/evidence-pack.md)
- Per-opportunity self-validating notebook: [`templates/notebook.py`](templates/notebook.py)

## Authoring a new vertical (the repeatable template)

A new engagement workflow is a **thin vertical skill**, not a fork of this one:

1. Create `starboard-<vertical>/SKILL.md` with a description that triggers on the user's intent.
2. In its body: say it composes this scaffold ("Load `starboard-engagement` for the beats,
   primitives, and templates"), then define only the **vertical-specific** bits — which findings it
   gathers, its prioritization/ordering rule, and its synthesis shape.
3. Reuse the primitives and templates here; do not copy them. If a primitive is missing, add it *here*
   so every vertical gains it.

That keeps each skill small and composable — the guardrail against one massive, fragile skill.

## Outputs layout

**One output root per run.** A Drive run's root is the run folder route resolved
(`My Drive/starboard/<ACCOUNT>/<TASK>/<TASK NAME>/<RUN ID>/`, or a validated ticket or override
folder); folder IDs are the authority and names are display. A local run's root is
`data.local_run_dir`. Both have the same run-relative layout, so every beat and template uses
the same relpaths (`analysis/review.json`, `deliverables/charts/<name>.png`), and never a
hard-coded path outside the run.

```
starboard-reports/                 # local runs only; a Drive run uses the same tree under My Drive/starboard/
  <account-slug>/                  # account (lowercase, e.g. lm-arena)
    <task>/                        # action_plan | discovery | review | health_check | troubleshooting
      <task-name>/                 # the case root: ws-<workspace_id>, job-<id>, query-<id>, pipeline-<id>
        trend/
          history.json             # local runs: accumulated per-run metrics for this case (recur beat)
        <run_id>/                  # one run: YYYYMMDD_<uuid4>, minted by preflight
          README.md            # "start here" index: what this run is, headline numbers, a pointer to each artifact
          discovery/           # workspace discovery — plan.json, raw/<pack>.json, facts.json, discovery.json, domains/<domain>.md, analysis.md (starboard-discovery)
          analysis/            # focused-domain reviews + the action plan; review.json, backlog.json,
                               #   verify/, charts/ (chart rows), baseline-selection.json,
                               #   recur-result.json, run-check.json, observations.json
                               #   + delta-vs-<prior-date>.md on a recurrence
          evidence/index.json  # evidence references the writers record (Drive runs)
          findings-manifest.json  # machine-readable per-run record (recurrence keystone; both paths)
          charts/              # data/ (trend chart rows) + trend/ (cross-run trend PNGs) — written by `run recur`
          deliverables/        # final customer artifacts (deck, exec summary, evidence pack, notebooks,
                               #   charts/*.png from `charts render`); health-read.md on a
                               #   health_check run, case-report.md on a troubleshooting run
```

- Every run gets a fresh run ID, so two runs on the same day never share a run folder or dir.
  Preflight refuses a local run dir that already holds a preflight record.
- A troubleshooting case has no `discovery/` tree and usually no trend; it writes its case files
  under `analysis/` and its write-up to `deliverables/case-report.md`.
- A health check writes its read to `deliverables/health-read.md` (`Insufficient evidence` on an
  `insufficient_evidence` verdict, and a `## Unknowns` section) and registers it as the
  `health-read` report on a Drive run before `run check`.
- **Trend storage.** A Drive run's history is the account registry (`engagement history`), read
  per observation. A local run's trend lives at the **case root**
  (`<case-root>/trend/history.json`), so it persists across runs; the rendered trend PNGs for a
  given run are written into that run's `charts/trend/`, so each run is self-contained.
- **The orchestrator owns the shared surfaces.** When the run is split across subagents, only the
  orchestrating agent writes `deliverables/`, `README.md`, commits stages and runs the report
  chain (and creates or deletes Docs). A subagent writes only its assigned files (e.g.
  `discovery/domains/<domain>.md`, an `analysis/` draft) and returns; put that boundary, and the
  run folder ID, in every subagent prompt
  ([`references/capability-bind.md`](references/capability-bind.md) Rule 6a).
- **Create or update `README.md`** whenever anything is written to the run — it is the one file
  a user opens first. Always include:
  - `## Delivery` — one line per artifact: its destination (a URL, a report receipt, or a
    `deliverables/` path), or `local: <reason>` / `not delivered: <reason>` / `pending
    approval`. `run check` fails a section with no such entry, so a placeholder such as "(filled
    at delivery)" fails: write the real outcomes at delivery.
  - `## Recur` — `baseline — no prior run` on a first run, or a delta note on a recurrence
    (`starboard-helper run recur` writes it; `run check` fails on an empty section).
  - `## Storage` — the preflight and route outcome (beat 0).
  - No `## Run check` section is needed: `run check --out analysis/run-check.json` saves the
    result.

## Guardrails (every vertical inherits these)

- Read-only to the customer's Databricks workspace; deliver only to the operator's own destinations.
- One task per run (beat 0): workspace runs never do single-run diagnosis or mention job/cluster
  logs, and a troubleshooting run never runs a full workspace scan.
- The run is set up (preflight → verify-identity → route) before the first workspace read.
- Always pass `--profile <name>` with the profile the operator chose; never pick a profile yourself.
  Every `starboard-helper` fetch takes it (before or after the subcommand). On a `--run-folder` run
  a fetch reads as the profile `verify-identity` proved: an omitted `--profile` defaults to it, and a
  different one exits 2 with `PROFILE_MISMATCH` — stop and report, never switch profiles mid-run.
- On a covered run nothing is written locally: every writer takes `--run-folder`, and a refusal
  (`LOCAL_STORAGE_REFUSED`) is reported, never worked around.
- Only a verified receipt completes a run; an unattended run never approves a customer report.
- `$`/DBU figures are **list-price DBU estimates**, labeled — never finance-grade.
- `scope-sanitize` runs before anything leaves: no PII/secrets/internal namespaces in customer output.
  Never record operator or customer emails or user names in run files.
- Every external write is preview + confirm; a missing delivery tool degrades **visibly**, never silently.
- If a Starboard internal enrichment overlay is available in this session, consult it at the scope, verify, and deliver beats of an `internal_only` or `hybrid` run for additional signals, and reconcile them into the evidence (a health review's or a troubleshooting case's matching steps included); the public flow and output discipline are unchanged. On a `customer_workspace` run consult it for one thing only: the overlay makes the run `drive_required` (without it a public run is `local` unless the operator chose `--storage drive`). Nothing else in it applies there, and `run check` lists the internal-only items under `skipped_not_internal`. Sanitizing and `run check --internal` apply to a run that carries internal evidence (`internal_only` or `hybrid`).
