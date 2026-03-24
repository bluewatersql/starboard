# ADR-001: Databricks Auth Session Validation

**Status:** Accepted
**Date:** 2026-03-01
**Context:** Phase 01 Security Hardening (Finding M12)

## Decision

`DatabricksAuthProvider.validate_session()` intentionally returns `True` without performing explicit session validation.

## Context

The Starboard application is deployed as a Databricks App, which runs inside the Databricks workspace infrastructure. The Databricks platform provides:

1. **Reverse proxy authentication** — Every HTTP request reaching the application has already been authenticated by the Databricks workspace proxy.
2. **Platform-managed sessions** — Session lifecycle (creation, expiration, revocation) is handled by the Databricks platform, not by downstream applications.
3. **User identity extraction** — `get_current_user()` calls the Databricks `current_user.me()` API, which returns the authenticated user. If the session were invalid, this API call would fail with a 401.

Implementing custom session validation would require:
- Maintaining a separate session store (Redis/DB)
- Duplicating session lifecycle management the platform already provides
- Risk of inconsistency between platform sessions and application sessions

## Consequences

### Positive
- No redundant session state to manage
- No risk of session store drift vs. platform sessions
- Simpler deployment model — the app trusts its host platform

### Negative
- If the application is deployed **outside** Databricks (e.g., standalone), `validate_session()` must be replaced with real validation
- No application-level session revocation capability (relies on platform)

### Mitigations
- `get_current_user()` validates the user identity on every request via the Databricks API
- The auth middleware runs on all non-excluded paths
- If deployment context changes, the `AuthenticationService` protocol requires implementing `validate_session()`, so any new provider must address this explicitly

## Alternatives Considered

1. **JWT-based session validation** — Rejected: would duplicate platform auth, adds complexity, requires secret management
2. **Redis session cache** — Rejected: adds infrastructure dependency for no security benefit in Databricks context
3. **Call Databricks API in validate_session()** — Rejected: `get_current_user()` already does this; calling it twice per request is wasteful
