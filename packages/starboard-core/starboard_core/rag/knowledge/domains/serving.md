---
domain: serving
system_tables:
- system.serving.endpoint_usage
- system.serving.served_entities
---

# Reference: serving

> Curated Databricks system-table knowledge for the `serving` RAG resource domain. SQL corpus lives in `discovery/query_packs/*` (reused in place, not duplicated here).

## Tables

### system.serving.endpoint_usage
System table in the `serving` domain. See query packs for vetted SQL over this table.

### system.serving.served_entities
System table in the `serving` domain. See query packs for vetted SQL over this table.

## Nuance

_No curated nuance entries for this domain yet._

## Codebook

### system.serving.served_entities.entity_type
DOC_TYPE: codebook
CODE_KEY: system.serving.served_entities.entity_type
SUMMARY: Served entity category behind an endpoint.
VALUES:
- FEATURE_SPEC
- EXTERNAL_MODEL
- FOUNDATION_MODEL
- CUSTOM_MODEL
SQL_HINT: Use entity_type to split platform costs/usage patterns (foundation vs custom vs external). Join endpoint_usage -> served_entities on served_entity_id for attribution.

### system.serving.served_entities.task
DOC_TYPE: codebook
CODE_KEY: system.serving.served_entities.task
SUMMARY: Serving request API shape for the served entity.
VALUES:
- llm/v1/chat
- llm/v1/completions
- llm/v1/embeddings
SQL_HINT: Use task to segment token-heavy workloads (chat/completions) vs embedding throughput. Pair with endpoint_usage token counts for cost/latency analysis.

### system.serving.served_entities.custom_model_config.compute_type
DOC_TYPE: codebook
CODE_KEY: system.serving.served_entities.custom_model_config.compute_type
SUMMARY: Compute type for custom models/features (non-exhaustive, depends on platform).
PATTERNS/EXAMPLES (non-exhaustive):
- CPU
- GPU
SQL_HINT: Use compute_type to split infra needs; corroborate with SKU/billing where available.

## Facets

### system.serving.served_entities.entity_type
FEATURE_SPEC,EXTERNAL_MODEL,FOUNDATION_MODEL,CUSTOM_MODEL

### system.serving.served_entities.task
llm/v1/chat,llm/v1/completions,llm/v1/embeddings

### system.serving.served_entities.custom_model_config.compute_type
CPU,GPU
