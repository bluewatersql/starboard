# Rollback Runbook Template

## Overview
Use this template when a deployment must be reverted due to critical issues.

## Pre-Rollback Checklist
- [ ] Confirm the issue is caused by the new deployment (not an external dependency)
- [ ] Notify stakeholders (engineering lead, on-call, affected teams)
- [ ] Identify the last known-good version/commit

## Rollback Procedure

### 1. Identify Target Version
```bash
# Find the last known-good deployment tag or commit
git log --oneline -10
```

### 2. Execute Rollback
```bash
# Revert to previous version
git checkout <known-good-commit>

# Rebuild and redeploy
make build
# Follow standard deployment procedure (see DEPLOYMENT.md)
```

### 3. Verify Rollback
- [ ] Application starts without errors
- [ ] Health check endpoints return 200
- [ ] Core user flows work (send a test query, verify agent response)
- [ ] No elevated error rates in logs

### 4. Database Rollback (if applicable)
- [ ] Check if the deployment included database migrations
- [ ] If yes, apply reverse migration or restore from backup
- [ ] Verify data integrity after rollback

## Post-Rollback
- [ ] Update incident channel with rollback status
- [ ] Create a post-incident ticket to investigate root cause
- [ ] Schedule a blameless post-mortem within 48 hours
- [ ] Document what went wrong and update this runbook if needed

## Escalation
If rollback fails or the issue persists after rollback:
1. Page the engineering lead
2. Consider restoring from the last database backup
3. Engage infrastructure team if the issue is platform-level
