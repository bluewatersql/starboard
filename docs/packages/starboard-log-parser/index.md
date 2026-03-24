# starboard-log-parser

High-performance Spark event log parser with multi-cloud support.

## Overview

`starboard-log-parser` provides flexible, protocol-based parsing of Spark event logs from multiple sources (local, DBFS, Unity Catalog, HTTP/S, S3).

![Parsing Pipeline](../../diagrams/generated/packages/starboard-log-parser-pipeline.png)

## Quick Links

- **[Complete Architecture](./architecture.md)** - Detailed architecture guide
- **[S3 Guide](../../S3_CONNECTOR_GUIDE.md)** - S3 integration
- **[Cloud Auth](../../CLOUD_AUTHENTICATION.md)** - Authentication setup

## Key Features

### Multi-Cloud Support

Parse logs from anywhere:
- **Local files**: `/path/to/eventlog.gz`
- **DBFS**: `dbfs:/cluster-logs/eventlog`
- **Unity Catalog Volumes**: `/Volumes/catalog/schema/volume/logs/`
- **HTTP/S**: `https://example.com/logs/eventlog.gz`
- **S3**: `s3://bucket/logs/eventlog.gz`

### Archive Handling

Automatic decompression and extraction:
- `.gz` - gzip compression
- `.zip` - zip archives
- `.tar.gz` - tar archives
- Nested archives (`.zip.gz`)
- Auto-detection

### Protocol-Based Architecture

Flexible implementations via Python protocols:
- **DBFSClient**: DBFS operations
- **CredentialProvider**: Authentication

## Architecture Highlights

### Layered Design

1. **Application Layer**: Factory function (`create_spark_application`)
2. **Domain Layer**: Immutable models (SparkApplication, Jobs, Stages)
3. **Parsing Layer**: Event parser (30+ event types)
4. **Loader Layer**: Storage backends (5 implementations)
5. **Auth Layer**: Credential management (pluggable providers)

### Streaming Processing

Memory-efficient streaming parser:
- O(1) memory usage
- ~50,000 events/second
- Handles multi-GB logs

### Data Models

**SparkApplication** (immutable):
- Job data (job → stages → tasks)
- Stage metrics and timelines
- Task execution details
- Executor information
- DAG structure
- Application metadata

## Quick Start

```python
from starboard_log_parser import create_spark_application

# Parse any source
app = create_spark_application("path/to/eventlog.gz")

# Access parsed data
print(f"Jobs: {len(app.job_data)}")
print(f"Stages: {len(app.stage_data)}")
print(f"Tasks: {len(app.task_data)}")
```

## Extension Points

### Custom DBFS Client

Implement `DBFSClient` protocol:
```python
class MyDBFSClient:
    def dbfs_path_exists(self, path: str) -> bool: ...
    def read_dbfs_chunk(self, path: str, offset: int, length: int) -> bytes: ...
    def list_dbfs_files(self, path: str, recursive: bool = True): ...
```

### Custom Credential Provider

Implement `CredentialProvider` protocol:
```python
class MyCredentialProvider:
    def get_credentials(self) -> Credentials: ...
    def refresh_credentials(self) -> Credentials: ...
```

See [Complete Architecture](./architecture.md) for detailed information.

