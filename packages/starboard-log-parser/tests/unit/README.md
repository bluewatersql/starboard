# Log Parser Unit Tests

This directory contains unit tests for the Spark UI log parser.

## Test Organization

```
packages/starboard-log-parser/tests/unit/
├── conftest.py                      # Shared fixtures
├── adapters/                        # Adapter tests
│   └── cloud/
│       └── test_s3_adapter.py       # S3Adapter tests
├── application/
│   └── test_factory_s3.py           # Factory S3 tests
├── auth/                            # Authentication tests
│   ├── test_exceptions.py           # Auth exceptions
│   ├── test_protocols.py            # Credential protocols
│   └── test_providers.py            # Credential providers
├── loaders/                         # Loader tests
│   ├── test_cloud_storage_protocol.py
│   ├── test_dbfs_adapter.py
│   ├── test_dbfs_protocols.py
│   └── test_s3_loaders.py
├── validators/
│   └── test_streaming_validator.py
├── test_application_model.py        # ApplicationModel unit tests
├── test_cloud_storage_exceptions.py # CloudStorageError tests
├── test_log_parser_exceptions.py    # LogParserError tests
├── test_job_model.py                # JobModel unit tests
├── test_no_print_statements.py      # Code quality: no print()
├── test_recursion_limits.py         # Safety: recursion depth limits
├── test_stage_model.py              # StageModel unit tests
├── test_task_model.py               # TaskModel unit tests
└── README.md                        # This file
```

## Running Tests

### Run all log parser unit tests
```bash
cd packages/starboard-log-parser
pytest tests/ -v
```

### Run specific test file
```bash
pytest tests/unit/test_application_model.py -v
```

### Run with coverage
```bash
pytest tests/ --cov=starboard_log_parser --cov-report=html
```

### Run only fast tests (skip slow)
```bash
pytest tests/ -v -m "not slow"
```

## Test Fixtures

The `conftest.py` file provides shared fixtures:

### File Fixtures
- `temp_log_dir`: Temporary directory for log files
- `minimal_spark_log`: Minimal valid Spark log
- `spark_log_with_tasks`: Log with job/stage/task events
- `malformed_spark_log`: Invalid log for error testing

### Data Fixtures
- `deeply_nested_accum_data`: Nested dict for recursion testing
- `sample_task_metrics`: Sample task metrics
- `mock_application_model`: Mock ApplicationModel

## Test Markers

Tests can be marked with custom markers:

- `@pytest.mark.unit`: Unit test
- `@pytest.mark.integration`: Integration test
- `@pytest.mark.slow`: Slow running test
- `@pytest.mark.requires_log_parser`: Requires log parser module

Example:
```python
@pytest.mark.unit
@pytest.mark.requires_log_parser
def test_parse_minimal_log(minimal_spark_log):
    # Test code here
    pass
```

## Test-Driven Development (TDD)

We follow TDD principles:

1. **Red**: Write failing test first
2. **Green**: Make test pass with minimal code
3. **Refactor**: Improve code while keeping tests passing

Example workflow:

```python
# 1. RED: Write failing test
def test_parse_task_metrics():
    metrics = parse_task_metrics(sample_data)
    assert metrics.executor_run_time == 1500
    # Test fails - function doesn't exist yet

# 2. GREEN: Implement minimal code to pass
def parse_task_metrics(data):
    return TaskMetrics(executor_run_time=data["Executor Run Time"])
    # Test passes

# 3. REFACTOR: Improve implementation
def parse_task_metrics(data: Dict[str, Any]) -> TaskMetrics:
    """Parse task metrics from Spark event log."""
    return TaskMetrics(
        executor_run_time=data.get("Executor Run Time", 0),
        # ... other fields
    )
    # Test still passes
```

## Standards Compliance

All tests must comply with repository engineering standards:

### Type Hints
```python
def test_parse_log(log_path: Path) -> None:
    """Test log parsing with proper type hints."""
    result: ApplicationModel = parse_log(log_path)
    assert result.app_name == "TestApp"
```

### Docstrings
```python
def test_parse_invalid_json():
    """
    Test that invalid JSON is handled gracefully.
    
    The parser should log a warning and continue to the next line
    when encountering invalid JSON, rather than crashing.
    """
    # Test code
```

### Naming
- Test functions: `test_<what>_<condition>_<expected>`
- Example: `test_parse_log_with_missing_fields_raises_error`

### Structure
- Arrange: Set up test data
- Act: Execute the code under test
- Assert: Verify results

```python
def test_task_duration_calculation():
    # Arrange
    task = TaskModel(launch_time=1000, finish_time=2000)
    
    # Act
    duration = task.calculate_duration()
    
    # Assert
    assert duration == 1000
```

## Coverage Goals

| Module | Target Coverage | Est. Current Coverage |
|--------|-----------------|----------------------|
| auth/exceptions.py | 85% | ~95% |
| auth/protocols.py | 85% | ~90% |
| auth/providers.py | 85% | ~90% |
| loaders/protocols.py | 80% | ~80% |
| loaders/dbfs_adapter.py | 80% | ~85% |
| parsing_models/event_log_parser.py | 85% | ~60% |
| parsing_models/task_model.py | 85% | ~75% |
| parsing_models/stage_model.py | 85% | ~75% |
| parsing_models/job_model.py | 85% | ~70% |
| validators/streaming_validator.py | 85% | ~85% |
| **Overall** | **75%** | **~50%** |

## Test Priorities

### P0: Critical (Must have)
- ✅ No print statements test
- ✅ Recursion limits test
- ⬜ Parse minimal valid log
- ⬜ Handle invalid JSON
- ⬜ Handle missing required fields
- ⬜ Task metrics parsing

### P1: High (Should have)
- ⬜ Stage aggregation
- ⬜ Job timing calculation
- ⬜ DAG construction
- ⬜ Executor tracking
- ⬜ Memory efficiency tests

### P2: Medium (Nice to have)
- ⬜ Edge cases (empty stages, retries)
- ⬜ Performance benchmarks
- ⬜ Large log handling

## Contributing

When adding new tests:

1. Follow TDD: test first, implementation second
2. Use existing fixtures from conftest.py
3. Add docstrings explaining what and why
4. Mark tests appropriately (@pytest.mark.unit, etc.)
5. Ensure tests are deterministic (no random data)
6. Keep tests focused (one concept per test)
7. Name tests descriptively

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [Package README](../../README.md)
- [Project Testing Guide](../../../../docs/TESTING.md)

