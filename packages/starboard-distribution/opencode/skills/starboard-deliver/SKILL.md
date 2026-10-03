---
name: starboard-deliver
description: 'The delivery vertical of the Starboard engagement workflow: deliver a finished plan or report to where the user wants it — a doc, a message, a deck outline, a ticket — by binding LOGICAL capabilities to whatever tools are present (Google Docs/Slack/Jira, by availability), rendered native to the destination, with preview+confirm, degrading visibly to local Markdown when nothing is bound. The deck is a local Markdown outline (no Slides build). Read-only to the customer workspace. Use when the user wants to publish/share/hand off a plan or report, or asks to put it in a Doc/Slack/deck/ticket.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-deliver/SKILL.md
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
   deck-build path). Local Markdown is the always-saved working copy and the fallback **only** when a
   tool is genuinely unavailable — any degradation must be stated **visibly** (name the missing tool);
   never silently emit a Markdown outline as the *doc* when the Docs tool could have been used.
   - **Deck** (`present.deck`) — the deliverable is the **local Markdown outline** (per the
     [`../starboard-engagement/templates/deck.md`](../starboard-engagement/templates/deck.md)
     spec) plus chart PNGs under `deliverables/charts/`. There is **no Slides/Drive deck-build
     path**: the outline is what ships, and the operator adapts it into their own presentation tool
     with their own branding. Nothing to preflight, nothing that can hard-fail.
   - **Exec summary / doc** (`publish.doc`) — **build the actual Google Doc** using the **Google
     MCP Docs tools** (`mcp__google__docs_document_create_from_markdown` or the Docs API
     structurally). If the Docs MCP is unavailable, say so and fall back to local Markdown.
   - **Evidence pack + notebooks** — delivered as **files** to the Drive folder and
     `<run-dir>/deliverables/`; notebooks are never imported into the customer workspace.
     Byte uploads (notebooks, PNGs) need an **authenticated uploader** (gcloud/curl) — the Google MCP
     can't upload bytes. If none is authenticated, these files **degrade to local-only** under
     `deliverables/`; say so at preflight, before promising them in Drive.
   - **Slack message** (`message.post`) — bound to Slack MCP; fall back to local Markdown / content-only.
   - **CRM draft** (`ticket.open`) — Salesforce MCP, draft only; never auto-submitted.
2. **Drive folder target.** Upload all artifacts to `My Drive/starboard/<Workspace Name>/<YYYY_MM_DD>/`
   (create the full path first). Folder naming is **find-or-create**, resolved by **listing each
   parent's child folders** (`'<parentId>' in parents`) and matching the name client-side — a name
   query can miss an existing folder: reuse an existing customer/account folder under `starboard/`,
   else `<Workspace Name>`; reuse an existing same-day folder (even empty) instead of duplicating;
   create only after the parent-scoped listing confirms absence. A created Google Doc lands in
   **My Drive root** (no parent-folder argument) — read its parent (`drive_file_get`), move it with
   `drive_file_update` (`add_parents=<folder id>`, `remove_parents=<the parent you read>`), and confirm
   it has a single parent before calling it delivered. See [`capability-bind`](../starboard-engagement/references/capability-bind.md) Rule 6. Mirror every artifact locally under `<run-dir>/deliverables/`
   (`<run-dir>` is defined in the engagement scaffold's Outputs layout) before attempting any remote write. The local run dir mirrors the Drive folder; update the run's `README.md` index with links to what you delivered. The user may override the root path.
3. **Render native to the destination** — styled headings and real code blocks in a Doc (not a raw
   Markdown paste that leaks `\~`/`\+`/`\#`), one idea per slide in a deck (never a pasted table).
4. **Preview + confirm before every external write.** Email/CRM are draft-only unless the user
   confirms a send and a write path exists.
5. **Preflight auth before building, then degrade visibly.** Before building each selected
   artifact, confirm its primary tool is present AND authenticated: run a cheap read call (e.g.
   `mcp__google__drive_file_list` or `mcp__google__docs_document_list` for Google MCP; a
   `channels.list` for Slack). If the call fails or returns unauthenticated: for **attended runs**
   **STOP and prompt the user** with the exact re-auth step — name the tool and the concrete fix
   (Google MCP: workspace connections page for that connector; gcloud/curl: `gcloud auth login` or
   token refresh; Slack MCP: connect the Slack app). Ask: **fix-and-retry / skip this artifact /
   local-Markdown fallback**. Do not build the degraded version until the user has chosen —
   never silently emit a Markdown outline as the doc because auth was down, never a
   false "delivered" (the deck is always a local Markdown outline). For **unattended runs**:
   apply per-artifact degrade-and-record instead — mark `local: <reason>` in `README.md
   ## Delivery`, keep the local file, and continue; never pause for a confirmation. See
   [`capability-bind`](../starboard-engagement/references/capability-bind.md) Rule 3 and the
   Unattended path for the full preflight contract.
6. **Guardrails** — run `scope-sanitize` on the payload; read-only to the customer's Databricks
   workspace; `$`/DBU figures are labeled list-price estimates. Deliver only to the operator's own
   destinations (Docs/Slack/Drive/CRM by availability) plus local files under the run dir —
   **never publish deliverables to any external hosting surface the operator did not choose**:
   deliver only to the operator's own tools and to local files. A self-contained HTML deck, if
   built, is a local working file under `deliverables/`.
