# starboard-log-parser

Spark event log parsing with credential provider framework.

## Key Modules
- `parsing_models/` -- Parsed log data models
- `adapters/` -- I/O adapters for log sources
- `application/` -- Application-layer orchestration
- `auth/` -- Authentication and credential providers
- `domain/` -- Core parsing domain logic
- `loaders/` -- Log file loaders (local, S3, HTTP)
- `validators/` -- Input validation
