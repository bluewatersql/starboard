"""Unit tests for StreamingValidator.

Tests the streaming validation functionality for Spark event logs,
ensuring fail-fast behavior and minimal memory usage.
"""

import pytest
from starboard_log_parser.parsing_models.exceptions import (
    UrgentEventValidationException,
)
from starboard_log_parser.validators.streaming_validator import (
    StreamingValidator,
    ValidationRules,
    ValidationState,
)


class TestValidationState:
    """Test ValidationState dataclass."""

    def test_initial_state(self):
        """ValidationState initializes with correct defaults."""
        state = ValidationState()

        assert state.event_count == 0
        assert state.required_events_seen == set()
        assert state.start_time is None
        assert state.end_time is None
        assert state.application_name is None
        assert state.application_id is None
        assert state.spark_version is None
        assert state.stages_seen == set()
        assert state.jobs_seen == set()
        assert state.executors_seen == set()
        assert state.platform_detected is None
        assert state.has_errors is False

    def test_state_is_mutable(self):
        """ValidationState can be updated."""
        state = ValidationState()

        state.event_count = 10
        state.application_name = "TestApp"
        state.jobs_seen.add(1)

        assert state.event_count == 10
        assert state.application_name == "TestApp"
        assert 1 in state.jobs_seen


class TestValidationRules:
    """Test ValidationRules constants."""

    def test_required_events_defined(self):
        """ValidationRules defines required events."""
        assert "SparkListenerLogStart" in ValidationRules.REQUIRED_EVENTS
        assert "SparkListenerApplicationStart" in ValidationRules.REQUIRED_EVENTS

    def test_event_required_fields_defined(self):
        """ValidationRules defines required fields per event type."""
        app_start_fields = ValidationRules.EVENT_REQUIRED_FIELDS[
            "SparkListenerApplicationStart"
        ]
        assert "App Name" in app_start_fields
        assert "App ID" in app_start_fields
        assert "Timestamp" in app_start_fields

    def test_platform_indicators_defined(self):
        """ValidationRules defines platform detection indicators."""
        assert "databricks" in ValidationRules.PLATFORM_INDICATORS
        assert "emr" in ValidationRules.PLATFORM_INDICATORS


class TestStreamingValidatorBasics:
    """Test basic StreamingValidator functionality."""

    def test_initialization_default(self):
        """StreamingValidator initializes with defaults."""
        validator = StreamingValidator()

        assert validator.expected_platform is None
        assert validator.strict is True
        assert validator.state.event_count == 0
        assert len(validator.errors) == 0
        assert len(validator.warnings) == 0

    def test_initialization_with_platform(self):
        """StreamingValidator accepts expected platform."""
        validator = StreamingValidator(expected_platform="databricks")

        assert validator.expected_platform == "databricks"

    def test_initialization_non_strict(self):
        """StreamingValidator can be initialized in non-strict mode."""
        validator = StreamingValidator(strict=False)

        assert validator.strict is False


class TestEventStructureValidation:
    """Test validation of basic event structure."""

    def test_validates_valid_event(self):
        """StreamingValidator accepts valid event."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        validator.validate_event(event, line_number=1)

        assert validator.state.event_count == 1

    def test_rejects_non_dict_event(self):
        """StreamingValidator rejects non-dictionary event."""
        validator = StreamingValidator()

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event("invalid", line_number=42)

        assert "Line 42" in str(exc_info.value)
        assert "dict" in str(exc_info.value).lower()

    def test_rejects_empty_event(self):
        """StreamingValidator rejects empty event."""
        validator = StreamingValidator()

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event({}, line_number=42)

        assert "Line 42" in str(exc_info.value)
        assert "empty" in str(exc_info.value).lower()

    def test_rejects_missing_event_type(self):
        """StreamingValidator rejects event without Event field."""
        validator = StreamingValidator()
        event = {"App Name": "TestApp"}  # Missing "Event" field

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(event, line_number=42)

        assert "Event type field" in str(exc_info.value)
        assert "Line 42" in str(exc_info.value)


class TestRequiredFieldsValidation:
    """Test validation of required fields per event type."""

    def test_validates_application_start_with_all_fields(self):
        """Validates ApplicationStart with all required fields."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        validator.validate_event(event, line_number=1)

        assert validator.state.event_count == 1

    def test_rejects_application_start_missing_app_name(self):
        """Rejects ApplicationStart without App Name."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            # Missing "App Name"
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(event, line_number=10)

        assert "App Name" in str(exc_info.value)
        assert "Line 10" in str(exc_info.value)

    def test_rejects_job_start_missing_job_id(self):
        """Rejects JobStart without Job ID."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerJobStart",
            # Missing "Job ID"
            "Submission Time": 1000000,
            "Stage IDs": [0, 1],
        }

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(event, line_number=20)

        assert "Job ID" in str(exc_info.value)
        assert "Line 20" in str(exc_info.value)


class TestEventSpecificValidation:
    """Test event-specific validation logic."""

    def test_validates_application_start_details(self):
        """Validates ApplicationStart event details."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1500000000000,
            "User": "test",
        }

        validator.validate_event(event, line_number=1)

        assert validator.state.application_name == "TestApp"
        assert validator.state.application_id == "app-001"
        assert validator.state.start_time == 1500000000.0

    def test_rejects_application_start_invalid_timestamp(self):
        """Rejects ApplicationStart with invalid timestamp."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 0,  # Invalid
            "User": "test",
        }

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(event, line_number=5)

        assert "timestamp" in str(exc_info.value).lower()
        assert "Line 5" in str(exc_info.value)

    def test_warns_on_empty_application_name(self):
        """Warns when ApplicationStart has empty App Name."""
        validator = StreamingValidator(strict=False)
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "",  # Empty
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        validator.validate_event(event, line_number=5)

        assert len(validator.warnings) == 1
        assert "Line 5" in validator.warnings[0]
        assert "application name" in validator.warnings[0].lower()

    def test_validates_job_start_details(self):
        """Validates JobStart event details."""
        validator = StreamingValidator()
        # First add ApplicationStart to satisfy early checks
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=1,
        )

        event = {
            "Event": "SparkListenerJobStart",
            "Job ID": 5,
            "Submission Time": 1001000,
            "Stage IDs": [0, 1, 2],
        }

        validator.validate_event(event, line_number=10)

        assert 5 in validator.state.jobs_seen

    def test_rejects_job_start_invalid_job_id(self):
        """Rejects JobStart with invalid Job ID."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerJobStart",
            "Job ID": -1,  # Invalid
            "Submission Time": 1000000,
            "Stage IDs": [0],
        }

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(event, line_number=15)

        assert "Job ID" in str(exc_info.value)
        assert "Line 15" in str(exc_info.value)

    def test_warns_on_job_with_no_stages(self):
        """Warns when JobStart has no Stage IDs."""
        validator = StreamingValidator(strict=False)
        # First add ApplicationStart
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=1,
        )

        event = {
            "Event": "SparkListenerJobStart",
            "Job ID": 3,
            "Submission Time": 1001000,
            "Stage IDs": [],  # Empty
        }

        validator.validate_event(event, line_number=10)

        assert len(validator.warnings) == 1
        assert "Line 10" in validator.warnings[0]
        assert "no stages" in validator.warnings[0].lower()


class TestStateTracking:
    """Test validation state tracking."""

    def test_tracks_event_count(self):
        """Tracks event count correctly."""
        validator = StreamingValidator()

        for i in range(5):
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=i + 1,
            )

        assert validator.state.event_count == 5

    def test_tracks_required_events(self):
        """Tracks required events seen."""
        validator = StreamingValidator()

        validator.validate_event(
            {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
            line_number=1,
        )
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=2,
        )

        assert "SparkListenerLogStart" in validator.state.required_events_seen
        assert "SparkListenerApplicationStart" in validator.state.required_events_seen

    def test_tracks_jobs_seen(self):
        """Tracks job IDs seen."""
        validator = StreamingValidator()
        # Add ApplicationStart first
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=1,
        )

        for job_id in [0, 1, 5, 10]:
            validator.validate_event(
                {
                    "Event": "SparkListenerJobStart",
                    "Job ID": job_id,
                    "Submission Time": 1000000,
                    "Stage IDs": [0],
                },
                line_number=job_id + 10,
            )

        assert validator.state.jobs_seen == {0, 1, 5, 10}


class TestEarlyErrorDetection:
    """Test fail-fast error detection."""

    def test_detects_missing_app_start_early(self):
        """Fails fast if ApplicationStart not seen in first 100 events."""
        validator = StreamingValidator()

        # Add 100 events without ApplicationStart
        for i in range(100):
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=i + 1,
            )

        # 101st event should trigger early detection
        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=101,
            )

        assert "ApplicationStart" in str(exc_info.value)
        assert "first 100 events" in str(exc_info.value)

    def test_allows_app_start_within_100_events(self):
        """Allows ApplicationStart seen within first 100 events."""
        validator = StreamingValidator()

        # Add 50 log start events
        for i in range(50):
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=i + 1,
            )

        # Add ApplicationStart
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=51,
        )

        # Should succeed
        assert validator.state.event_count == 51
        assert "SparkListenerApplicationStart" in validator.state.required_events_seen


class TestFinalization:
    """Test final validation after all events."""

    def test_finalize_with_required_events(self):
        """Finalize succeeds when required events present."""
        validator = StreamingValidator()

        validator.validate_event(
            {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
            line_number=1,
        )
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=2,
        )

        validator.finalize()  # Should not raise

    def test_finalize_fails_without_app_start(self):
        """Finalize fails if ApplicationStart missing."""
        validator = StreamingValidator()

        validator.validate_event(
            {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
            line_number=1,
        )

        with pytest.raises(UrgentEventValidationException) as exc_info:
            validator.finalize()

        assert "ApplicationStart" in str(exc_info.value)


class TestValidationSummary:
    """Test validation summary generation."""

    def test_get_summary_returns_dict(self):
        """get_summary returns dictionary with metrics."""
        validator = StreamingValidator()

        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=1,
        )

        summary = validator.get_summary()

        assert isinstance(summary, dict)
        assert "event_count" in summary
        assert "validation_time" in summary
        assert "errors_found" in summary
        assert "warnings_found" in summary

    def test_summary_reflects_state(self):
        """Summary reflects actual validation state."""
        validator = StreamingValidator()

        for i in range(10):
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=i + 1,
            )

        summary = validator.get_summary()

        assert summary["event_count"] == 10
        assert summary["errors_found"] == 0


class TestPerformance:
    """Test validation performance requirements."""

    def test_validation_is_fast(self):
        """Validation has minimal per-event overhead."""
        import time

        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        iterations = 10_000
        start = time.perf_counter()
        for _ in range(iterations):
            validator.validate_event(event, 1)
        elapsed = time.perf_counter() - start

        per_event_us = (elapsed / iterations) * 1_000_000
        assert per_event_us < 100, f"Validation too slow: {per_event_us:.1f}µs/event"

    def test_memory_usage_constant(self):
        """Memory usage is O(1) per event."""
        validator = StreamingValidator()

        # Add ApplicationStart first to avoid early detection
        validator.validate_event(
            {
                "Event": "SparkListenerApplicationStart",
                "App Name": "TestApp",
                "App ID": "app-001",
                "Timestamp": 1000000,
                "User": "test",
            },
            line_number=1,
        )

        # Process many events
        for i in range(999):
            validator.validate_event(
                {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
                line_number=i + 2,
            )

        # State should not grow unboundedly
        assert validator.state.event_count == 1000
        # These sets should be small for this test
        assert len(validator.state.required_events_seen) < 10
        assert len(validator.state.jobs_seen) < 100


class TestNonStrictMode:
    """Test non-strict validation mode."""

    def test_non_strict_collects_warnings(self):
        """Non-strict mode collects warnings instead of failing."""
        validator = StreamingValidator(strict=False)

        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "",  # Would warn in non-strict
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        validator.validate_event(event, line_number=5)

        assert len(validator.warnings) > 0
        assert validator.state.event_count == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_validates_event_without_line_number(self):
        """Validates event without line number."""
        validator = StreamingValidator()
        event = {
            "Event": "SparkListenerApplicationStart",
            "App Name": "TestApp",
            "App ID": "app-001",
            "Timestamp": 1000000,
            "User": "test",
        }

        validator.validate_event(event)  # No line_number

        assert validator.state.event_count == 1

    def test_handles_unknown_event_types(self):
        """Handles unknown event types gracefully."""
        validator = StreamingValidator()
        event = {"Event": "SparkListenerUnknownEvent"}

        # Should not raise for unknown event type
        validator.validate_event(event, line_number=10)

        assert validator.state.event_count == 1

    def test_handles_very_large_event_count(self):
        """Handles very large event counts."""
        validator = StreamingValidator()

        # Simulate many events with ApplicationStart already seen
        validator.state.event_count = 1000000
        validator.state.required_events_seen.add("SparkListenerApplicationStart")

        # Should still function normally
        validator.validate_event(
            {"Event": "SparkListenerLogStart", "Spark Version": "3.0.0"},
            line_number=1000001,
        )

        assert validator.state.event_count == 1000001
