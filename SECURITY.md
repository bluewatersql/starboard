# Security Policy

**Copyright 2024 Databricks, Inc.**

---

## Supported Versions

The following versions of Starboard AI Agent receive security fixes:

| Version | Supported |
|---------|-----------|
| 0.1.x (latest) | Yes |
| Earlier releases | No |

Once a `1.0.0` stable release is published, this table will be updated to reflect the support window (typically the two most recent minor releases).

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

We use GitHub's private vulnerability-reporting feature. To report a vulnerability:

1. Navigate to the **Security** tab of this repository.
2. Click **"Report a vulnerability"** to open a private advisory draft.
3. Provide as much detail as possible:
   - A description of the vulnerability and its potential impact.
   - Steps to reproduce or a proof-of-concept (no live exploits against production systems, please).
   - The affected version(s) and component(s).
   - Any suggested mitigations you are aware of.

If you cannot use GitHub Security Advisories, you may contact the maintainers by email at **<security-contact-email>**. Please encrypt sensitive details using the public key listed in the advisory page when available.

---

## Response Expectations

| Stage | Target time |
|-------|-------------|
| Acknowledgement of report | Within 3 business days |
| Initial triage and severity classification | Within 7 business days |
| Status update to reporter | Every 14 days until resolved |
| Patch release for Critical / High severity | Within 30 days of confirmed severity |
| Patch release for Medium severity | Within 90 days |
| Low / Informational | Addressed in next scheduled release |

These are best-effort targets for a community project. We will communicate promptly if a timeline cannot be met.

---

## Disclosure Policy

We follow **coordinated disclosure**:

- We ask reporters to keep vulnerability details private until a patch is available.
- We aim to publish a GitHub Security Advisory alongside the patch release.
- We credit reporters by name (or pseudonym) in the advisory unless they prefer to remain anonymous.
- We request a **90-day maximum embargo** from the date of our acknowledgement; if a patch is not available by then we will discuss the situation openly with the reporter.

---

## Scope

This policy covers the Starboard AI Agent source code in this repository, including:

- `packages/starboard-core`
- `packages/starboard-server`
- `packages/starboard-log-parser`
- `packages/starboard-cli`
- `packages/starboard-sdk`
- `frontend/`

**Out of scope**: third-party dependencies (report those to the respective upstream projects), hosted demo environments, and infrastructure operated by Databricks outside this repository.

---

## Security Best Practices for Deployers

- Rotate API keys and Databricks tokens regularly.
- Run the server behind authentication; the default configuration has no auth middleware enabled.
- Set `SAFE_MODE=true` to disable outbound calls to external services during evaluation.
- Keep Python and Node.js runtimes up to date; pinned versions in `pyproject.toml` and `package.json` reflect minimum tested versions, not maximums.
- Never commit `.env` files or credential files; use environment variables or a secrets manager.

---

*This policy was last reviewed: 2026-06-25.*
