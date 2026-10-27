# Case report — <task_name>

<!-- The write-up of a `troubleshooting` run: deliverables/case-report.md. One question, one
     target. Name every case_id; keep the Unknowns section even when it is short.
     `$` figures are list-price DBU estimates. -->

**Run:** `<run_id>` · **Workspace:** `<workspace_id>` · **Window:** <YYYY-MM-DD> – <YYYY-MM-DD>

## Question

`<case_id>` — <the operator's one question>

## Symptom

<what failed or slowed down, when it started, how often — from the cited evidence>

## Evidence

| File | What it shows |
|---|---|
| `raw/<file>.json` | <the fact it establishes> |

## Cause

<the cause> — `cause_confidence`: `hypothesis` | `supported`

| Hypothesis | Status | Cited evidence |
|---|---|---|
| <statement> | `untested` / `supported` / `refuted` | `raw/<file>.json` |

## Next step

- `<action_id>`, or `no action: <reason>` — <the change, its owner and how it will be verified>
  (acceptance: `pending` | `accepted` | `executed`)

## Unknowns

- <what was not read, and why>
<!-- Only on an internal_only run started because the customer or hybrid leg had no customer
     profile: -->
- customer workspace: not acquired (no customer profile)
