# 06 – Security & Privacy

---

MUST: Never commit secrets; use .env files and a secret manager (Vault, AWS SSM, GCP Secret Manager, etc.).  
MUST: Add secret scanning in pre-commit (detect-secrets, gitleaks).  
MUST: Validate and sanitize all external inputs; escape or strip unsafe content.  
MUST: Use parameterized queries only; use least privilege for tokens/keys.  

MUST: Redact PII in logs and stored text where possible.
MUST: Avoid logging full prompts/responses that contain sensitive data; prefer hashes or summaries.
MUST: Provide a SAFE_MODE=true or equivalent setting that disables external calls/tools for demos/tests.

**GUIDELINE-009: MUST: Never interpolate user input directly into LLM prompts via f-strings or `.format()`.** User input must be passed as a separate user-role message or through a dedicated template variable with explicit sanitization. Enforced by `tests/architecture/test_prompt_construction.py`.  

MUST: Detect and redact PII at boundaries (inputs before LLM calls, outputs before logging/storage).  
SHOULD: Implement GDPR-style features where applicable (right to deletion, data minimization, audit logs).  

SHOULD: Use moderation and guardrail systems for user inputs and model outputs.  
SHOULD: Use allow-lists and confirmation prompts for high-risk tools and operations.
