# AWS S3 Connector Guide

**Package**: `starboard-log-parser`  
**Version**: 0.2.0+  
**Status**: Production-Ready

---

## Overview

The S3 connector enables memory-efficient streaming of Spark event logs stored in AWS S3 buckets. It supports automatic decompression of `.gz` files and handles multi-GB logs without running out of memory.

---

## Quick Start

### 1. Install with S3 Support

```bash
pip install boto3  # Required for S3 access
```

### 2. Configure AWS Credentials

Set AWS credentials via environment variables:

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-west-2"
```

### 3. Use S3Adapter

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.s3 import S3Adapter

# Create credential provider
provider = EnvironmentCredentialProvider(cloud="aws")

# Create S3 adapter
s3 = S3Adapter(credential_provider=provider)

# Check if file exists
if s3.path_exists("s3://my-bucket/spark-logs/eventlog.gz"):
    # Get file size
    size = s3.get_file_size("s3://my-bucket/spark-logs/eventlog.gz")
    
    # Stream file in chunks
    offset = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    
    while offset < size:
        chunk = s3.read_chunk(
            "s3://my-bucket/spark-logs/eventlog.gz",
            offset,
            chunk_size
        )
        if not chunk:
            break
        
        # Process chunk (decompress, parse, analyze)
        process_spark_events(chunk)
        offset += len(chunk)
```

---

## S3Adapter API

### path_exists(path: str) -> bool

Check if an S3 file or prefix exists.

```python
exists = s3.path_exists("s3://bucket/path/to/file.gz")
```

### list_files(path: str, recursive: bool = False, pattern: str = "*") -> list[dict]

List files in an S3 path with optional glob pattern filtering.

```python
# List all JSON files in a directory
files = s3.list_files(
    "s3://bucket/logs/",
    recursive=True,
    pattern="*.json"
)

for file in files:
    print(f"{file['path']} - {file['size']} bytes")
```

**Returns**: List of dicts with keys: `path`, `size`, `last_modified`

**Note**: Currently returns max 1,000 objects. Use more specific paths for large directories.

### read_chunk(path: str, offset: int, length: int) -> bytes

Read a byte range from an S3 file using HTTP Range requests.

```python
# Read first 1MB
chunk = s3.read_chunk("s3://bucket/file.gz", 0, 1024*1024)
```

**Memory-efficient**: Reads only requested bytes, not entire file.

### get_file_size(path: str) -> int

Get file size via HEAD request (no data download).

```python
size = s3.get_file_size("s3://bucket/large-file.gz")
print(f"File size: {size:,} bytes")
```

---

## Authentication Methods

### Environment Variables (Recommended)

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider

provider = EnvironmentCredentialProvider(cloud="aws")
```

**Reads**:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_SESSION_TOKEN` (optional)
- `AWS_REGION` (optional, default: us-east-1)

### Static Credentials (Development Only)

```python
from starboard_log_parser.auth.providers import StaticCredentialProvider

provider = StaticCredentialProvider(
    access_key="MY_AWS_ACCESS_KEY_ID",
    secret_key="MY_AWS_SECRET_KEY",
    region="us-west-2"
)
```

⚠️ **Not recommended for production**: Use environment variables or IAM roles instead.

---

## Best Practices

### 1. Use Chunked Reading for Large Files

```python
# ✅ Good: Memory-efficient streaming
size = s3.get_file_size(s3_path)
chunk_size = 1024 * 1024  # 1MB

offset = 0
while offset < size:
    chunk = s3.read_chunk(s3_path, offset, chunk_size)
    if not chunk:
        break
    process(chunk)
    offset += len(chunk)

# ❌ Bad: Don't read entire file at once (for large files)
# all_data = s3.read_chunk(s3_path, 0, size)  # May run out of memory
```

### 2. Check File Existence Before Reading

```python
if s3.path_exists(s3_path):
    size = s3.get_file_size(s3_path)
    # ... read file
else:
    print(f"File not found: {s3_path}")
```

### 3. Use Specific Paths for Listing

```python
# ✅ Good: Specific path
files = s3.list_files("s3://bucket/year=2024/month=11/", pattern="*.json")

# ⚠️ May be slow: Very broad path with many objects
# files = s3.list_files("s3://bucket/", recursive=True)
```

### 4. Handle Errors Gracefully

```python
from starboard_log_parser.exceptions import CloudStorageError

try:
    size = s3.get_file_size("s3://bucket/file.gz")
except CloudStorageError as e:
    print(f"S3 error: {e}")
    # Handle error (log, retry, etc.)
```

---

## IAM Permissions Required

Your AWS credentials need these S3 permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name/*",
        "arn:aws:s3:::your-bucket-name"
      ]
    }
  ]
}
```

**Minimal permissions**: Read-only access to specific buckets.

---

## Limitations

1. **No write support**: Read-only operations
2. **No pagination**: `list_files()` returns max 1,000 objects
3. **No automatic retry**: Transient errors fail immediately

**Future enhancements**: Write support, pagination, retry logic with exponential backoff.

---

## Troubleshooting

### ImportError: No module named 'boto3'

**Solution**: Install boto3:
```bash
pip install boto3
```

### CloudStorageError: Access Denied

**Causes**:
- Invalid credentials
- Insufficient IAM permissions
- Bucket does not exist
- File does not exist

**Solution**: Verify credentials and IAM permissions.

### CloudStorageError: Bucket not found

**Solution**: Check bucket name and region. If bucket is in a different region, specify it:

```python
provider = StaticCredentialProvider(
    access_key="...",
    secret_key="...",
    region="us-east-1"  # Specify correct region
)
```

---

## Examples

### Example 1: Parse Spark Event Log from S3

```python
from starboard_log_parser.auth.providers import EnvironmentCredentialProvider
from starboard_log_parser.adapters.cloud.s3 import S3Adapter

provider = EnvironmentCredentialProvider(cloud="aws")
s3 = S3Adapter(credential_provider=provider)

s3_path = "s3://spark-logs/app-20241129-123456/eventlog.gz"

# Stream and parse in chunks
size = s3.get_file_size(s3_path)
offset = 0
chunk_size = 1024 * 1024

while offset < size:
    chunk = s3.read_chunk(s3_path, offset, chunk_size)
    if not chunk:
        break
    
    # Process Spark events from chunk
    for event in parse_spark_events(chunk):
        analyze_event(event)
    
    offset += len(chunk)
```

### Example 2: List and Process Multiple Files

```python
# List all event logs for a specific date
files = s3.list_files(
    "s3://spark-logs/year=2024/month=11/day=29/",
    recursive=True,
    pattern="eventlog*.gz"
)

print(f"Found {len(files)} event logs")

for file_info in files:
    path = file_info['path']
    size = file_info['size']
    
    print(f"Processing {path} ({size:,} bytes)")
    
    # Process each file
    process_event_log(path, s3)
```

---

## See Also

- [Log Parser Architecture](packages/starboard-log-parser/architecture.md) - System overview
- [API Reference](api/API_REFERENCE.md) - Complete API documentation

---

**Last Updated**: 2025-11-29  
**Version**: 1.0

