# Security & Privacy Standards

Security and privacy rules for the Starboard AI Agent project. These apply to all code that handles user data, credentials, LLM interactions, or external service calls.

!!! info "Source of truth"
    These standards are mirrored from `.cursor/06_security_and_privacy.md`.

---

## Secrets Management

| Rule | Level |
|------|-------|
| Never commit secrets; use `.env` files and secret managers | MUST |
| Add secret scanning in pre-commit (`detect-secrets`, `gitleaks`) | MUST |
| Use least privilege for tokens and API keys | MUST |

Supported secret managers: Vault, AWS SSM, GCP Secret Manager, or environment variables.

---

## Input Validation

| Rule | Level |
|------|-------|
| Validate and sanitize all external inputs | MUST |
| Escape or strip unsafe content | MUST |
| Use parameterized queries only (no SQL injection risk) | MUST |
| Pydantic V2 validation at all boundaries | MUST |

---

## PII & Data Protection

| Rule | Level |
|------|-------|
| Redact PII in logs and stored text | MUST |
| Avoid logging full prompts/responses with sensitive data | MUST |
| Prefer hashes or summaries over raw sensitive content in logs | MUST |
| Detect and redact PII at boundaries (before LLM calls, before logging) | MUST |
| GDPR-style features: right to deletion, data minimization, audit logs | SHOULD |

---

## Safe Mode

| Rule | Level |
|------|-------|
| Provide `SAFE_MODE=true` setting that disables external calls | MUST |

Safe mode is used for demos, testing, and development without Databricks connectivity. When enabled, all external API calls are disabled and mock data is returned.

---

## LLM Security

| Rule | Level |
|------|-------|
| Use moderation and guardrail systems for inputs and outputs | SHOULD |
| Use allow-lists and confirmation prompts for high-risk tools | SHOULD |
| Validate LLM-generated SQL is read-only (SELECT only, no DDL/DML) | MUST |
| Log and alert on suspicious prompt patterns | MUST |

---

## Authentication

The application supports multiple auth modes:

| Mode | Context | Mechanism |
|------|---------|-----------|
| **Platform (Databricks App)** | Production | Reverse proxy headers (`X-Forwarded-User`, `X-Forwarded-Groups`) |
| **Databricks OAuth** | Development | OAuth2 token flow |
| **Personal Access Token** | Development | `DATABRICKS_TOKEN` env var |

All conversation endpoints must verify user ownership before returning data.
