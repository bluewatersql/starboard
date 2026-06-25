# starboard-log-parser Architecture

**Package**: `starboard-log-parser`  
**Version**: 0.1.0  
**Purpose**: High-performance Spark event log parser  
**Last Updated**: 2025-12-02

---

## Overview

`starboard-log-parser` is a flexible, protocol-based Spark event log parser supporting multiple cloud storage backends. It parses Spark event logs into structured Python objects for analysis and optimization.

### Key Features

- **Streaming Parser**: Memory-efficient processing of large event logs
- **Multi-Cloud Support**: Local files, DBFS, Unity Catalog Volumes, HTTP/S, S3
- **Archive Handling**: .zip, .tar.gz, .gz compression support
- **Protocol-Based**: Flexible architecture using Python protocols (PEP 544)
- **Credential Management**: Pluggable authentication framework
- **Validation**: Streaming validation of Spark event data

### Design Philosophy

- **Protocol-oriented**: Use Python protocols for flexibility
- **Streaming-first**: Process logs without loading entire file into memory
- **Cloud-agnostic**: Abstract storage backends behind protocols
- **Credential-aware**: Separate authentication concerns from parsing logic

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────┐
│              Application Layer                        │
│  ┌────────────────────────────────────────────────┐ │
│  │  create_spark_application()                     │ │
│  │  Factory function coordinating all layers       │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│               Domain Layer                            │
│  ┌────────────────────────────────────────────────┐ │
│  │  SparkApplication (Pure Data)                   │ │
│  │  - Jobs, Stages, Tasks                          │ │
│  │  - Executors, DAG                               │ │
│  │  - Metadata, Metrics                            │ │
│  └────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│              Parsing Layer                            │
│  ┌────────────────────────────────────────────────┐ │
│  │  EventLogParser                                 │ │
│  │  - Stream JSON events                           │ │
│  │  - Build domain models                          │ │
│  │  - Validate data                                │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│              Loader Layer                             │
│  ┌────────────────────────────────────────────────┐ │
│  │  Protocol: DBFSClient                           │ │
│  │  ├── LocalFileLoader                            │ │
│  │  ├── DBFSLoader (Unity Catalog Volumes)       │ │
│  │  ├── HTTPSLoader                                │ │
│  │  └── S3Loader                                   │ │
│  └────────────┬───────────────────────────────────┘ │
└───────────────┼──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│           Authentication Layer                        │
│  ┌────────────────────────────────────────────────┐ │
│  │  Protocol: CredentialProvider                   │ │
│  │  ├── DatabricksCredentialProvider               │ │
│  │  ├── AWSCredentialProvider                      │ │
│  │  └── StaticCredentialProvider                   │ │
│  └────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

---

## Package Structure

```
starboard-log-parser/
├── starboard_log_parser/
│   ├── application/            # Factory patterns
│   │   └── factory.py          # create_spark_application()
│   │
│   ├── domain/                 # Pure domain models (no I/O)
│   │   ├── models/             # Immutable domain entities
│   │   │   ├── application.py  # SparkApplication
│   │   │   ├── info.py         # SparkApplicationInfo
│   │   │   └── metadata.py     # SparkApplicationMetadata
│   │   └── services/           # Pure business logic (future)
│   │
│   ├── adapters/               # I/O adapters
│   │   ├── cloud/              # Cloud storage adapters
│   │   │   └── s3.py           # S3 storage support
│   │   └── parsers/            # Event parsers
│   │       └── parsed_log.py   # Pre-parsed JSON logs
│   │
│   ├── parsing_models/         # Parsing-specific models
│   │   ├── event_log_parser.py # Main event parser
│   │   ├── application/        # Application-level parsing (9 files)
│   │   ├── computers/          # Executor/driver parsing (10 files)
│   │   ├── dag_model.py        # DAG structure
│   │   ├── executor_model.py   # Executor tracking
│   │   ├── job_model.py        # Job parsing
│   │   ├── stage_model.py      # Stage parsing
│   │   └── task_model.py       # Task parsing
│   │
│   ├── loaders/                # Data loaders (protocol implementations)
│   │   ├── protocols.py        # DBFSClient protocol
│   │   ├── dbfs_adapter.py     # Databricks SDK adapter
│   │   ├── dbfs.py             # DBFS loader
│   │   ├── https.py            # HTTP/S loader
│   │   ├── json.py             # JSON loader
│   │   ├── local_file.py       # Local file loader
│   │   └── s3.py               # S3 loader
│   │
│   ├── auth/                   # Authentication framework
│   │   ├── protocols.py        # CredentialProvider protocol
│   │   ├── providers.py        # Concrete providers
│   │   └── exceptions.py       # Auth-specific exceptions
│   │
│   ├── validators/             # Data validation
│   │   └── streaming_validator.py  # Stream-based validation
│   │
│   └── exceptions.py           # Package exceptions
│
└── tests/
    └── unit/                   # Unit tests (100% coverage goal)
```

---

## Key Components

### 1. Application Factory (`application/factory.py`)

Main entry point for creating SparkApplication instances:

```python
def create_spark_application(
    path: str,
    dbfs_client: DBFSClient | None = None,
    credential_provider: CredentialProvider | None = None,
) -> SparkApplication:
    """
    Create SparkApplication from various sources.
    
    Supports:
    - Local files: /path/to/eventlog.gz
    - DBFS: dbfs:/cluster-logs/eventlog
    - Unity Catalog: /Volumes/catalog/schema/volume/logs/
    - HTTP/S: https://example.com/logs/eventlog.gz
    - S3: s3://bucket/logs/eventlog.gz
    """
    # Auto-detect format
    # Select appropriate loader
    # Parse events
    # Return SparkApplication
```

**Features**:
- Auto-detection of source type
- Automatic decompression
- Archive extraction
- Format detection (raw events vs pre-parsed JSON)

---

### 2. Domain Models (`domain/models/`)

Immutable representations of Spark application data.

#### SparkApplication

```python
@dataclass(frozen=True)
class SparkApplication:
    """Complete parsed Spark application."""
    metadata: SparkApplicationMetadata
    job_data: dict[int, JobData]
    stage_data: dict[int, StageData]
    task_data: dict[int, TaskData]
    executor_data: dict[str, ExecutorData]
    dag: DAG
```

**Key Characteristics**:
- Frozen (immutable)
- Type-safe
- Rich metadata
- Relationships preserved

#### SparkApplicationInfo

```python
@dataclass(frozen=True)
class SparkApplicationInfo:
    """Application metadata."""
    application_id: str
    application_name: str
    spark_version: str
    start_time: datetime
    end_time: datetime | None
    user: str
```

#### SparkApplicationMetadata

```python
@dataclass(frozen=True)
class SparkApplicationMetadata:
    """Extended metadata."""
    application_info: SparkApplicationInfo
    configuration: dict[str, str]
    environment: dict[str, str]
    runtime_info: dict[str, Any]
```

---

### 3. Loader System (`loaders/`)

Protocol-based loading from multiple sources.

#### DBFSClient Protocol

```python
class DBFSClient(Protocol):
    """Abstract interface for DBFS operations."""
    
    def dbfs_path_exists(self, dbfs_path: str) -> bool:
        """Check if path exists."""
        ...
    
    def list_dbfs_files(
        self,
        dbfs_path: str,
        recursive: bool = True,
    ) -> list[FileInfo]:
        """List files in directory."""
        ...
    
    def read_dbfs_chunk(
        self,
        dbfs_path: str,
        offset: int,
        length: int,
    ) -> bytes:
        """Read chunk of file."""
        ...
```

**Implementations**:

1. **DatabricksSDKAdapter** (`loaders/dbfs_adapter.py`):
   - Uses Databricks SDK
   - Supports Unity Catalog Volumes
   - OAuth authentication

2. **DatabricksAPIAdapter** (`loaders/dbfs_adapter.py`):
   - Direct REST API calls
   - Token authentication
   - Manual credential management

#### Loader Implementations

**LocalFileLoader** (`loaders/local_file.py`):
```python
class LocalFileLinesDataLoader:
    """Load from local filesystem."""
    def load_lines(self, path: str) -> Iterator[str]:
        # Handle compression
        # Stream lines
        ...
```

**DBFSLoader** (`loaders/dbfs.py`):
```python
class DBFSFileLinesDataLoader:
    """Load from DBFS/Unity Catalog."""
    def __init__(self, dbfs_client: DBFSClient):
        self._client = dbfs_client
    
    def load_lines(self, path: str) -> Iterator[str]:
        # Use protocol
        # Stream chunks
        ...
```

**HTTPSLoader** (`loaders/https.py`):
```python
class HTTPSFileLinesDataLoader:
    """Load from HTTP/S URLs."""
    def load_lines(self, url: str) -> Iterator[str]:
        # Stream HTTP response
        # Handle redirects
        ...
```

**S3Loader** (`loaders/s3.py`):
```python
class S3FileLinesDataLoader:
    """Load from AWS S3."""
    def __init__(self, credential_provider: CredentialProvider):
        self._provider = credential_provider
    
    def load_lines(self, s3_path: str) -> Iterator[str]:
        # Use credentials
        # Stream S3 object
        ...
```

---

### 4. Authentication Framework (`auth/`)

Pluggable credential management.

#### CredentialProvider Protocol

```python
class CredentialProvider(Protocol):
    """Abstract interface for credential management."""
    
    def get_credentials(self) -> Credentials:
        """Retrieve current credentials."""
        ...
    
    def refresh_credentials(self) -> Credentials:
        """Refresh expired credentials."""
        ...
```

**Implementations**:

1. **DatabricksCredentialProvider**:
   - Token-based auth
   - Automatic refresh
   - Environment variable support

2. **AWSCredentialProvider**:
   - AWS access keys
   - IAM role support
   - Session tokens

3. **StaticCredentialProvider**:
   - Fixed credentials
   - Testing/development

**Design Benefits**:
- Separate authentication from loading
- Easy to add new providers
- Testable (fake providers)
- Secure (no hardcoded credentials)

---

### 5. Parsing System (`parsing_models/`)

Stream-based event parsing.

#### EventLogParser

```python
class ApplicationModel:
    """Main event parser."""
    
    def parse_line(self, line: str) -> None:
        """Parse single event line."""
        event = json.loads(line)
        event_type = event.get("Event")
        
        # Route to appropriate handler
        if event_type == "SparkListenerJobStart":
            self._handle_job_start(event)
        elif event_type == "SparkListenerStageSubmitted":
            self._handle_stage_submitted(event)
        # ... 30+ event types
    
    def finalize(self) -> SparkApplication:
        """Build final SparkApplication."""
        return SparkApplication(
            metadata=self._metadata,
            job_data=self._jobs,
            stage_data=self._stages,
            # ...
        )
```

**Event Types Handled** (30+):
- Application events (start, end)
- Job events (start, end)
- Stage events (submitted, completed)
- Task events (start, end, metrics)
- Executor events (added, removed, metrics)
- Block manager events
- Environment updates

**Parsing Strategy**:
1. Stream events one at a time
2. Build incremental state
3. Validate as we go
4. Finalize into immutable models

---

### 6. Validation System (`validators/`)

Streaming validation of event data.

#### StreamingValidator

```python
class StreamingValidator:
    """Validate events during parsing."""
    
    def validate_event(self, event: dict) -> list[ValidationError]:
        """Validate single event."""
        errors = []
        
        # Check required fields
        if "Event" not in event:
            errors.append(MissingFieldError("Event"))
        
        # Type-specific validation
        if event.get("Event") == "SparkListenerJobStart":
            errors.extend(self._validate_job_start(event))
        
        return errors
```

**Validation Levels**:
- **Critical**: Must be valid (raises exception)
- **Warning**: Logged but doesn't fail
- **Info**: Informational only

---

## Data Flow

### Parsing Pipeline

```
1. Source Path
   └─> Format detection (file ext, magic bytes)

2. Loader Selection
   ├─> Local: LocalFileLoader
   ├─> DBFS: DBFSLoader
   ├─> HTTP/S: HTTPSLoader
   └─> S3: S3Loader

3. Decompression (if needed)
   ├─> .gz: gzip
   ├─> .zip: zipfile
   └─> .tar.gz: tarfile

4. Stream Events
   └─> Line-by-line JSON parsing

5. Event Parsing
   ├─> ApplicationModel.parse_line()
   ├─> Validate event
   ├─> Update internal state
   └─> Build relationships

6. Finalization
   └─> Create immutable SparkApplication

7. Return
   └─> Fully parsed application
```

### Archive Handling Flow

```
Compressed File (.gz, .zip, .tar.gz)
     │
     ▼
Detect Archive Type
     │
     ├─> Single File Archive
     │   └─> Extract → Parse
     │
     ├─> Multi-File Archive
     │   ├─> List entries
     │   ├─> Find event log
     │   └─> Extract → Parse
     │
     └─> Nested Archive (.zip.gz)
         ├─> Extract outer
         ├─> Extract inner
         └─> Parse
```

**Safety Limits**:
- Max archive size: 10 GB (configurable)
- Max entries: 10,000 (prevents zip bombs)
- Timeout: 5 minutes (configurable)

---

## Design Patterns

### 1. Protocol-Oriented Programming

Use protocols (PEP 544) instead of inheritance:

```python
# Define interface
class DBFSClient(Protocol):
    def read_dbfs_chunk(...): ...

# Implement without inheritance
class MyClient:
    def read_dbfs_chunk(...):
        # Implementation
        ...

# Works via structural typing
loader = DBFSLoader(MyClient())  # ✓ Type checks
```

**Benefits**:
- No inheritance required
- Testable (easy to fake)
- Flexible implementations

### 2. Streaming Processing

Process data incrementally:

```python
# BAD: Load entire file
data = open(path).read()  # Memory spike!
events = [json.loads(line) for line in data.split('\n')]

# GOOD: Stream line by line
for line in load_lines(path):
    event = json.loads(line)
    parser.parse_line(event)
```

**Benefits**:
- Constant memory usage
- Early failure detection
- Interruptible processing

### 3. Immutable Domain Models

```python
@dataclass(frozen=True)
class SparkApplication:
    """Cannot be modified after creation."""
    metadata: SparkApplicationMetadata
    job_data: dict[int, JobData]
```

**Benefits**:
- Thread-safe
- Cacheable
- Predictable

### 4. Factory Pattern

```python
# Single entry point
app = create_spark_application(path)

# Hides complexity:
# - Format detection
# - Loader selection
# - Credential management
# - Parsing
# - Validation
```

---

## Usage Examples

### Basic Usage

```python
from starboard_log_parser import create_spark_application

# Parse any supported format
app = create_spark_application("/path/to/eventlog.gz")

# Access data
print(f"App: {app.metadata.application_info.name}")
print(f"Jobs: {len(app.job_data)}")
print(f"Duration: {app.metadata.application_info.end_time - app.metadata.application_info.start_time}")
```

### With Custom DBFS Client

```python
from starboard_log_parser import create_spark_application
from starboard_log_parser.loaders.protocols import DBFSClient

class MyDBFSClient:
    """Custom implementation."""
    def dbfs_path_exists(self, path: str) -> bool:
        # Your logic
        return True
    
    def read_dbfs_chunk(self, path: str, offset: int, length: int) -> bytes:
        # Your logic
        return b"..."
    
    def list_dbfs_files(self, path: str, recursive: bool = True):
        # Your logic
        return []

client = MyDBFSClient()
app = create_spark_application(
    "dbfs:/logs/eventlog",
    dbfs_client=client,
)
```

### With AWS S3

```python
from starboard_log_parser import create_spark_application
from starboard_log_parser.auth.providers import AWSCredentialProvider

# Create credential provider
creds = AWSCredentialProvider(
    access_key_id="...",
    secret_access_key="...",
)

# Parse from S3
app = create_spark_application(
    "s3://my-bucket/logs/eventlog.gz",
    credential_provider=creds,
)
```

---

## Testing Strategy

### Unit Tests

- All loaders have fake implementations
- Parsers tested with synthetic events
- Validators tested with invalid data
- 100% coverage target

### Integration Tests

- Real Databricks connection (optional)
- Real S3 connection (optional)
- Sample event logs included
- Performance benchmarks

---

## Performance Characteristics

### Memory Usage

- **Streaming**: O(1) memory (constant)
- **Non-streaming**: O(n) where n = file size

### Parsing Speed

- ~50,000 events/second (single core)
- ~500 MB/minute for compressed logs
- Scales linearly with file size

### Optimization Tips

1. **Use streaming**: Default behavior
2. **Disable validation**: Set `validate=False` for trusted logs
3. **Parallel parsing**: Split logs by application_id

---

## Related Documentation

- [S3 Connector Guide](../../S3_CONNECTOR_GUIDE.md) - S3 setup
- [S3 Connector Guide](../../S3_CONNECTOR_GUIDE.md) - Auth setup

---

## Future Enhancements

Potential improvements:
- Parallel parsing of multiple logs
- Incremental parsing (resume from checkpoint)
- Custom event handlers
- Real-time log tailing
- Query DSL for filtering events

---

**Last Updated**: 2025-12-02

