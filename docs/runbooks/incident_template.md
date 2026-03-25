# Incident Response Template

Use this template for all Starboard production incidents. Copy to a new file named `YYYY-MM-DD-<slug>.md`.

---

## Incident Summary

| Field | Value |
|-------|-------|
| **Date** | YYYY-MM-DD |
| **Severity** | P0 / P1 / P2 / P3 |
| **Status** | Investigating / Mitigated / Resolved |
| **Incident Commander** | @handle |
| **Duration** | HH:MM |
| **Services Affected** | starboard-server / frontend / MCP / other |

---

## Timeline

All times in UTC.

| Time | Event |
|------|-------|
| HH:MM | Incident detected (alert / user report / on-call page) |
| HH:MM | Incident commander assigned |
| HH:MM | Initial triage complete |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied |
| HH:MM | Incident resolved |

---

## Impact

**Who was affected?**
- [ ] All users
- [ ] Subset of users (describe: ...)
- [ ] Internal only

**What was broken?**
- [ ] Conversation streaming (SSE)
- [ ] Agent reasoning / tool calls
- [ ] Authentication / authorisation
- [ ] Data reads (Databricks API)
- [ ] Frontend UI
- [ ] Other: ...

**Quantified impact:**
- Estimated users affected: N
- Estimated requests failed: N
- Data loss: yes / no

---

## Root Cause

_Concise technical description of the root cause._

---

## Detection

How was the incident detected?
- [ ] Automated alert (specify alert name)
- [ ] User report
- [ ] On-call engineer noticed
- [ ] Other: ...

---

## Mitigation

Steps taken to stop the bleeding:

1. ...
2. ...

---

## Resolution

Steps taken to fully resolve:

1. ...
2. ...

---

## Contributing Factors

- ...

---

## Action Items

| Action | Owner | Due Date | Issue |
|--------|-------|----------|-------|
| ... | @handle | YYYY-MM-DD | #N |

---

## Lessons Learned

### What went well

- ...

### What could be improved

- ...

### Where we got lucky

- ...

---

## References

- Logs: `trace_id=...`
- PR / commit: ...
- Related incidents: ...
