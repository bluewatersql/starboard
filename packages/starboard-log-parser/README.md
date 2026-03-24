# Starboard Log Parser

High-performance Spark event log parser with multi-cloud support.

## Features

- 🚀 **Streaming Parser**: Memory-efficient processing of large event logs
- ☁️ **Multi-Cloud**: Support for local files, DBFS, Unity Catalog Volumes, HTTP/S
- 📦 **Archive Support**: Handles .zip, .tar.gz, .gz compressed logs
- 🔌 **Protocol-Based**: Flexible architecture using Python protocols
- ✅ **100% Tested**: Comprehensive test coverage

## Installation

```bash
# Basic installation
pip install starboard-log-parser

# With Databricks support
pip install starboard-log-parser[databricks]

# With HTTP support
pip install starboard-log-parser[http]

# With all cloud providers
pip install starboard-log-parser[all-clouds]
```

## Quick Start

### Parse from Local File

```python
from starboard_log_parser.application import create_spark_application

# Parse event log
app = create_spark_application(path="/path/to/eventlog.gz")

# Access parsed data
print(f"Application: {app.metadata.application_info.name}")
print(f"Jobs: {len(app.job_data)}")
print(f"Stages: {len(app.stage_data)}")
print(f"Tasks: {len(app.task_data)}")
```

### Parse from DBFS

```python
from databricks.sdk import WorkspaceClient
from starboard_log_parser.application import create_spark_application
from starboard_log_parser.loaders.dbfs_adapter import DatabricksSDKAdapter

# Create DBFS client
sdk_client = WorkspaceClient()
dbfs_client = DatabricksSDKAdapter(sdk_client)

# Parse from DBFS
app = create_spark_application(
    path="dbfs:/cluster-logs/eventlog",
    dbfs_client=dbfs_client
)
```

### Parse from Unity Catalog Volumes

```python
from starboard_log_parser.application import create_spark_application

# Unity Catalog Volume path
app = create_spark_application(
    path="/Volumes/catalog/schema/volume/logs/eventlog.json.gz"
)
```

### Parse from HTTP

```python
from starboard_log_parser.application import create_spark_application

# Public HTTPS URL
app = create_spark_application(
    path="https://example.com/logs/eventlog.gz"
)
```

## Architecture

### Protocol-Based Design

The log parser uses Python protocols (PEP 544) for flexible implementations:

```python
from starboard_log_parser.loaders.protocols import DBFSClient

class CustomDBFSClient:
    """Your custom implementation."""
    
    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        ...
    
    def list_dbfs_files(self, dbfs_path: str, recursive: bool = True):
        ...
    
    def read_dbfs_chunk(self, dbfs_path: str, offset: int, length: int):
        ...

# Use with loaders
from starboard_log_parser.loaders.dbfs import DBFSFileLinesDataLoader

client = CustomDBFSClient()
loader = DBFSFileLinesDataLoader(dbfs_client=client)
```

### Supported File Formats

- ✅ Raw event logs (JSON Lines)
- ✅ Pre-parsed JSON
- ✅ Compressed: .gz, .zip, .tar.gz
- ✅ Nested archives: .zip.gz, .json.gz
- ✅ Auto-detection of format

## Development

### Setup

```bash
cd packages/starboard-log-parser
pip install -e ".[test,databricks,http]"
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# With coverage
pytest --cov=starboard_log_parser --cov-report=html
```

### Code Quality

```bash
# Format
ruff format starboard_log_parser/ tests/

# Lint
ruff check starboard_log_parser/ tests/

# Type check
mypy starboard_log_parser/
```

## License

MIT

