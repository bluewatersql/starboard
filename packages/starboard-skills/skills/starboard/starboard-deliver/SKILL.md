---
name: starboard-deliver
description: "The delivery vertical of the Starboard engagement workflow: deliver a finished plan or report to where the user wants it — a doc, a message, a deck outline, a ticket — by binding LOGICAL capabilities to whatever tools are present (Google Docs/Slack/Jira, by availability), rendered native to the destination, with preview+confirm, degrading visibly (on a local run to local Markdown; on a Drive run the artifact is marked not delivered and stays in the run folder) when nothing is bound. The deck is a local Markdown outline (no Slides build). Read-only to the customer workspace. Use when the user wants to publish/share/hand off a plan or report, or asks to put it in a Doc/Slack/deck/ticket."
allowed-tools: Bash(starboard-helper:*), Read, Write, mcp__google__docs_*, mcp__google__drive_*
---

# Starboard: Deliver (engagement vertical)

This is a **thin vertical** of the Starboard engagement workflow. **Load
[`starboard-engagement`](../starboard-engagement/SKILL.md) first** — delivery is its
[`capability-bind`](../starboard-engagement/references/capability-bind.md) primitive plus
[`scope-sanitize`](../starboard-engagement/references/scope-sanitize.md). This skill just applies them
to a finished artifact.

## What it does

Take the finished plan or report (from `starboard-action-plan` or any synthesized output) and deliver
the **confirmed artifact set** to the user's chosen destinations. You (the host) are the binder; there
is no rendering script and no second LLM.

Follow the **capability-bind** primitive for the full contract. The key points for this vertical:

1. **Artifact-selection model.** The `present` beat produced a confirmed list of artifacts. Deliver
   exactly those — no more, no less. **Artifact selection** (which deliverables) is separate from
   **delivery destination** (where they go): selecting "exec summary doc" means **build the actual
   Google Doc**; selecting "deck" means **produce the local Markdown outline** (there is no Slides
   deck-build path). The Markdown working copy is always saved (on a Drive run put into the run
   folder with `starboard-helper engagement put --run-folder $RUN_FOLDER --path
   deliverables/<file>`, the Markdown on stdin, before the analysis commit; under
   `<run-dir>/deliverables/` on a local run). On a local run it is the fallback **only** when a
   tool is genuinely unavailable; on a Drive run there is no local fallback (the working copy stays
   in the run folder and the artifact is `not delivered: <reason>`). Any degradation must be stated
   **visibly** (name the missing tool); never silently emit a Markdown outline as the *doc* when the
   Docs tool could have been used.
   - **Deck** (`present.deck`) — the deliverable is the **local Markdown outline** (per the
     [`../starboard-engagement/templates/deck.md`](../starboard-engagement/templates/deck.md)
     spec) plus chart PNGs under `deliverables/charts/`. There is **no Slides/Drive deck-build
     path**: the outline is what ships, and the operator adapts it into their own presentation tool
     with their own branding. Nothing to preflight, nothing that can hard-fail.
   - **Exec summary / doc** (`publish.doc`) — **build the actual Google Doc** using the **Google
     MCP Docs tools** (`mcp__google__docs_document_create_from_markdown` or the Docs API
     structurally). If the Docs MCP is unavailable, say so: on a local run fall back to the local
     Markdown; on a Drive run record `not delivered: <reason>` and keep the revision as it is.
   - **Evidence pack + notebooks** — delivered as **files**. On a Drive run the writers already
     streamed them into the run folder (`--run-folder $RUN_FOLDER`); there is no upload step. On a
     local run they stay under `<run-dir>/deliverables/`. Notebooks are never imported into the
     customer workspace.
   - **Slack message** (`message.post`) — bound to Slack MCP; without it, content-only (the local
     Markdown on a local run, `not delivered: <reason>` on a Drive run).
   - **CRM draft** (`ticket.open`) — Salesforce MCP, draft only; never auto-submitted.
2. **Drive run folder and the publication chain.** On a Drive run (`storage_decision`
   `drive_required`, `drive_default` or `drive_optional`) the engagement's setup already resolved
   the folder with
   `starboard-helper engagement route --run-id $RUN_ID` and kept its `run_folder_id`:
   `My Drive/starboard/<ACCOUNT>/<TASK>/<TASK NAME>/<RUN ID>/`, or a validated ticket folder on the
   internal overlay. Every file is already there and nothing is written locally. Deliver after
   `starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json` and
   `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check`,
   in this order: **report → approve → deliver | receipt**.
   - **Register:** `starboard-helper engagement report --run-folder $RUN_FOLDER --report-id <report-id> --audience <internal|customer> --path deliverables/<file>`.
     Derive `--audience` from the destination: an internal destination is `internal`, a
     customer-facing one is `customer`. The output names `allowed_audiences` and
     `derived_from_revision`; offer a customer version only when `allowed_audiences` includes
     `customer`. With no answer (an unattended or scripted run), write none and record
     `customer version offered, no answer: not written`.
     A customer version of an internal report is a new report derived from it:
     `starboard-helper engagement report --run-folder $RUN_FOLDER --report-id <customer-report-id> --audience customer --path deliverables/<file> --derived-from <internal-report-id>@<n> --cite-evidence <evidence_id>`
     (or `--cite-observation <observation_id>` for an observation in `analysis/observations.json`;
     both repeat, and a customer report needs at least one).
     A `customer` report that cites internal-only evidence is `blocked_audience`
     (`internal_only_run`, `derivative_required` or `derivative_source_not_internal`): rewrite it
     from customer-shareable evidence as such a derivative. `REPORT_REFUSED` (exit 2) means the
     body is under `raw/` or `evidence/`, a `customer` report has no `--cite-evidence` /
     `--cite-observation`, a `customer` body is internal-sourced evidence, or `--derived-from`
     names the report itself or a revision that does not exist;
     `UNCOMMITTED_ARTIFACT` means commit the body's stage first.
   - **Approve (customer audience):** show the operator the exact revision, and on yes run
     `starboard-helper engagement approve --run-folder $RUN_FOLDER --report-id <report-id> --revision <n>`.
     An unattended run can't approve (`can_approve` is false): leave it pending. Any edit needs a
     new revision and a new approval.
   - **Deliver or record:** `starboard-helper engagement deliver --run-folder $RUN_FOLDER --report-id <report-id> --revision <n> --destination-folder-id <folder_id>`
     copies it to an internal-only Drive destination (any other folder is `DELIVERY_REFUSED`);
     after publishing it yourself through a host tool, record it
     with `starboard-helper engagement receipt --run-folder $RUN_FOLDER --report-id <report-id> --revision <n> --external-object-id <object_id> --channel <google_doc|slides|slack> --destination-id <folder_or_channel_id>`
     (`--destination-id` is required unless a verified `deliver` of that revision is recorded).
   - **Only a verified receipt completes the run.** A Doc or Slides receipt is verified only when
     the object sits directly in the destination, outside the run folder and staging, is not a run
     artifact, matches the revision's md5 when Drive reports one, and was created after the
     approval; otherwise it returns `warnings` and the run stays pending. **A Slack receipt never
     completes** a customer delivery (it is recorded unverified). Until then the run is
     `publication_pending`: say so, never "delivered".
   - **Filling a Doc from a Drive run.** `markdown_file_path` needs a local file, which a Drive run
     never has. Read the registered revision with
     `starboard-helper engagement read --run-folder $RUN_FOLDER --path deliverables/<file>` (only
     when `truncated` is false; if it is true, stop and report) and pass that text as the Docs
     tool's `file_content`, unchanged. A Doc has no md5, so check it by exporting it with
     `docs_document_export_as_markdown` (no `output_file_path`) and comparing its headings and
     numbers with the text you read; fix a difference by re-creating the Doc from the same text.
   - **Customer-version Doc destination.** Put it where the operator names. With no destination
     named, use the owner-only case folder (the run folder's parent), say in README `## Delivery`
     that the Doc is not shared with the customer, and share it only on the operator's word.
   - **`publication: skipped`.** `engagement report` / `receipt` and the manifest report
     `publication: skipped` when no report in the run needs delivery: only `customer` reports do,
     because an internal report's delivery is the run folder itself. It is not a failure and not a
     delivery; the run completes without a receipt. `pending` means a customer report still awaits
     its receipt, `complete` means every one has a verified receipt.
   - **Docs:** create with the Docs MCP, then move each Doc into its delivery destination folder,
     outside the run folder (`drive_file_get` its parent, `drive_file_update` with
     `add_parents`/`remove_parents`, and confirm a single parent), then record its receipt
     (`--channel google_doc --destination-id <that folder_id>`) before calling it delivered.
   - Repeat any `fallback_warning` (the ticket or chosen folder wasn't writable, so the run went to the
     `My Drive` account route) and `ticket_warning` in the delivery confirmation.
   - **Record the outcomes in the README.** After the receipts, fill README `## Delivery`: read the
     README with `engagement read --path README.md`, only when `truncated` is false; if it is true, stop and report, and never put back an excerpt (it would replace the file with the excerpt). Put the whole file back,
     then commit the check stage again so the manifest records the new md5 (without it a later
     `engagement read` of the README returns `committed: false`):
     ```bash
     starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
     <the whole README, with the ## Delivery lines filled in>
     EOF
     starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
     ```
   - If the folder's sharing changed since route, the helper stops with `blocked_access`: restore
     the folder's previous sharing and re-run the step, or start a new run with preflight.
   - **No local fallback on a Drive run** (`drive_required`, `drive_default`, or `drive_optional`
     — a public install where the operator chose `--storage drive`). When a destination tool is missing or fails, write
     `not delivered: <reason>` for that artifact in README `## Delivery`, leave its revision as it
     is (`ready`, `approved` or `pending_delivery`), and quote the run's publication state:
     `data.states.publication` of `starboard-helper engagement status --run-folder $RUN_FOLDER`
     (`pending` until every due revision has a verified receipt). The manifest is a versioned
     record, not a run file: `engagement read --path manifest.json` exits `NOT_FOUND`. Never write the
     artifact to a local folder instead.

   See [`capability-bind`](../starboard-engagement/references/capability-bind.md) Rule 6. On a
   local run (public install, `local`; never `drive_optional`, which is a Drive run) there is no
   report chain: write each
   artifact under `<run-dir>/deliverables/` (`<run-dir>` is preflight's `data.local_run_dir`, see
   the engagement scaffold's Outputs layout) and record its outcome in the run's `README.md`
   `## Delivery`.
3. **Render native to the destination** — styled headings and real code blocks in a Doc (not a raw
   Markdown paste that leaks `\~`/`\+`/`\#`), one idea per slide in a deck (never a pasted table).
4. **Preview + confirm before every external write.** Email/CRM are draft-only unless the user
   confirms a send and a write path exists.
5. **Preflight auth before building, then degrade visibly.** Before building each selected
   artifact, confirm its primary tool is present AND authenticated: run a cheap read call (e.g.
   `mcp__google__drive_file_list` or `mcp__google__docs_document_list` for Google MCP; a
   `channels.list` for Slack). If the call fails or returns unauthenticated: for **attended runs**
   **STOP and prompt the user** with the exact re-auth step — name the tool and the concrete fix
   (Google MCP: workspace connections page for that connector; Starboard Drive storage: the
   sign-in step named in the helper's `error` text; Slack MCP: connect the Slack app). Ask:
   **fix-and-retry / skip this artifact / local-Markdown fallback** on a local run, or
   **fix-and-retry / skip this artifact (`not delivered: <reason>`)** on a Drive run, which has no
   local fallback. Do not build the degraded version until the user has chosen —
   never silently emit a Markdown outline as the doc because auth was down, never a
   false "delivered" (the deck is always a local Markdown outline). For **unattended runs**:
   apply per-artifact degrade-and-record instead — on a local run mark `local: <reason>` in
   `README.md ## Delivery` and keep the file; on a Drive run mark `not delivered: <reason>` and
   leave the revision pending; continue either way and never pause for a confirmation. See
   [`capability-bind`](../starboard-engagement/references/capability-bind.md) Rule 3 and the
   Unattended path for the full preflight contract.
6. **Guardrails** — run `scope-sanitize` on the payload; read-only to the customer's Databricks
   workspace; `$`/DBU figures are labeled list-price estimates. Deliver only to the operator's own
   destinations (Docs/Slack/Drive/CRM by availability) plus the run folder (or the local run dir on
   a local run) —
   **never publish deliverables to any external hosting surface the operator did not choose**:
   deliver only to the operator's own tools and to local files. A self-contained HTML deck, if
   built, is a local working file under `deliverables/`.
