# Debug Session Mode

## Project Status
The project is in DEVELOPMENT and has not been deployed. Avoid incrementing version numbers (i.e. project, package versions, prompt versions, etc), creating techincal debt or other common approaches when debugging and resolving issues in production code.

## Core Principle
**A hasty fix that requires multiple iterations wastes more time than thoughtful troubleshooting upfront. Think deeply, act precisely.**

---

## Activation
**This mode activates ONLY when you explicitly report a bug/error/issue.**

Until then:
- Respond normally to questions and requests
- Do NOT scan files or logs proactively
- Do NOT look for potential issues
- Wait for you to describe the problem

---

## Debugging Workflow

**Investigation Process:**
1. **Check logs FIRST** (`.debug/server` or `.debug/frontend` or `.debug/browser` )
   - Look for: stack traces, timestamps, error codes, request IDs
   - Trace timeline: what happened immediately before the error?
2. **Trace data/execution flow** from source to destination
3. **State hypothesis** about root cause before proposing fix
4. **Outline proposed solution** and why it addresses root cause
5. **Implement minimal fix** only after clear understanding

**Multiple Bugs:**
- Fix sequentially, one at a time
- Before each fix, confirm: "Debugging [X]. Previous changes in this session: [Y, Z]"
- Track interdependencies between fixes

**Logging Strategy:**
- Add comprehensive debug statements upfront (not incrementally)
- Track all debug statements added
- Cleanup after resolution:
  - Remove temporary debug logging
  - Retain if: (a) debug-flag controlled, (b) non-duplicative, (c) future diagnostic value

---

## Operational Requirements

**Environment:**
- Use `.venv` virtual environment exclusively
- Respect all `.env` variables
- Services: `make dev-server-debug` or `make dev-frontend-debug`
- Always use debug commands for start/stop/restart

**Before Making Changes:**
- Verify git status (or note current state)
- State hypothesis and proposed fix
- If unclear after 15min investigation → stop and ask
- If fix requires >3 files → stop and ask
- If fix might break existing functionality → stop and ask

---

## Quality Gates (All Required)

**Pre-Implementation:**
- [ ] Root cause identified (not just symptoms)
- [ ] Hypothesis stated and validated
- [ ] Minimal change scope defined

**Post-Implementation:**
- [ ] Original bug scenario verified fixed
- [ ] **Tests run automatically** (relevant test suite)
- [ ] No regressions in related functionality
- [ ] Shared components/interfaces checked for impacts
- [ ] Data/control flow verified upstream/downstream
- [ ] Logs show no new warnings/errors
- [ ] Services running cleanly
- [ ] Existing tests updated if broken by fix
- [ ] New tests added if fix introduces uncovered paths
- [ ] Debug logging cleaned up per retention rules

---

## Boundaries (STRICT)

❌ **NEVER:**
- Do not take shortcuts
- Invent features or requirements
- Refactor unrelated code
- Add performance optimizations (unless that's the bug)
- Commit code without explicit instruction
- Create documentation/summaries/changelogs unless requested
- Proactively scan for issues when no bug is reported

✅ **ONLY:**
- Minimal changes directly required to fix reported issue

---

## Escalation Triggers (Stop and Ask)

- Hypothesis unclear after reviewing logs/code
- Stuck after 15 minutes of investigation
- Fix requires changes to >3 files
- Fix might break existing functionality
- Need to understand business logic/requirements
- Cannot reproduce the reported issue

---

## Common Pitfalls

- Environment variable not loaded? → Check `.env` and restart service
- Database/state issue? → Consider migrations or cache clearing
- Frontend/backend mismatch? → Verify both services restarted
- Dependency issue? → Check if `.venv` needs refresh

---

**Investigate. Identify root cause. Recommend potential solution.**
**Do not implement or change code until instructed to do so.**
**Standing by for bug reports.**