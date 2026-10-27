# Primitive: humanize — the de-AI-slop voice gate

Run this on every customer-facing artifact after technical-review and before deliver. The goal: it
reads like a Solutions Architect wrote it, not like a model emitted it. Accurate content poured out
raw is still slop.

## The checklist

- **Cut meta-narration and process talk.** No "Let me…", "I'll now…", "As we can see". The reader
  wants findings, not the agent's journey.
- **No hype or filler openers.** Delete "In today's data-driven world", "It's important to note",
  "It's worth noting that".
- **Lead with the point.** Conclusion first; evidence supports it, doesn't precede it.
- **Concrete over hedged.** "Auto-stop is off on 3 running clusters" — not "there may be opportunities
  to review cluster configurations."
- **Active voice, real subject.** "The platform team sets auto-termination" — not "auto-termination
  should be set."
- **Stop bolding everything.** At most one emphasized phrase per paragraph; if all is bold, none is.
- **Kill the confidence-theater tic.** Not "Why confidence 8, not 10:" — state confidence once, plainly.
- **Vary sentence rhythm.** Avoid the parallel-triple habit ("faster, cheaper, better") and identical
  sentence openings.
- **No emoji or ✅/🛑 in customer output.** Fine in the internal console; never in the Doc/Deck/CRM.
- **Tables for data, prose for reasoning.** Don't render an argument as a table.
- **One voice, third-person-neutral.** Strip first-person agent ("I validated…") → "Validated against
  the live API."
- **Units and the estimate label once.** Label list-price DBU at the top; don't repeat "(est.)" in
  every cell.

## Record the pass

After completing the checklist, note it in the `## Humanize` section of `analysis/technical-review.md`:
one line stating which artifacts were reviewed and that the pass is complete (e.g. "Humanize pass
complete — reviewed: deliverables/exec-summary.md, deliverables/evidence-pack.md, deliverables/action-plan.md,
deliverables/slack-post.md, and 7 notebooks."). This is the completion record that `run check` verifies.

## Delivery-format note

When the artifact lands in a Doc/Deck, it must be **native** to that surface — styled headings, real
code blocks, real tables — not raw Markdown pasted in (which leaks `\~`, `\+`, `\#` escapes and renders
code as flat text). See [`capability-bind.md`](capability-bind.md).
