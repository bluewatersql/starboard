# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for pattern YAML schema validation.

Tests cover:
- Valid pattern loading
- Invalid regex detection
- Missing required fields
- Duplicate pattern IDs
- Schema validation edge cases
"""

import pytest
from pydantic import ValidationError
from starboard.tools.domain.diagnostic.patterns.schema import (
    Category,
    ConfidenceFactorsYAML,
    EvidenceChecklistYAML,
    PatternCatalogYAML,
    PatternYAML,
    RecommendationYAML,
    ResponsibilityScope,
    Severity,
)

# =============================================================================
# VALID PATTERN TESTS
# =============================================================================


class TestValidPatternYAML:
    """Tests for valid pattern definitions."""

    def test_minimal_valid_pattern(self) -> None:
        """Minimal valid pattern with required fields only."""
        pattern = PatternYAML(
            id="test_pattern",
            name="Test Pattern",
            category=Category.MEMORY,
            severity=Severity.HIGH,
            responsibility=ResponsibilityScope.CONFIGURATION,
            keywords=["error", "test"],
            exit_code=137,
            root_cause="Test root cause",
        )

        assert pattern.id == "test_pattern"
        assert pattern.category == Category.MEMORY
        assert pattern.severity == Severity.HIGH

    def test_full_pattern_with_all_fields(self) -> None:
        """Pattern with all optional fields populated."""
        pattern = PatternYAML(
            id="full_pattern",
            name="Full Pattern",
            category=Category.SQL,
            severity=Severity.CRITICAL,
            responsibility=ResponsibilityScope.USER_CODE,
            keywords=["AnalysisException", "cannot resolve"],
            regex_patterns=[r"cannot resolve '\w+'"],
            exception_class=r"AnalysisException",
            message_pattern=r"cannot resolve",
            captures={"column_name": "The missing column"},
            root_cause="Column not found in schema",
            symptoms=["Query fails", "AnalysisException thrown"],
            root_causes=["Typo in column name", "Schema changed"],
            remediation=["Check column spelling", "Verify schema"],
            recommendations=[
                RecommendationYAML(
                    id="check_schema",
                    priority="high",
                    action="Verify schema",
                    implementation="df.printSchema()",
                    verification="Column exists",
                )
            ],
            docs=["https://docs.databricks.com/"],
            evidence_checklist=EvidenceChecklistYAML(
                required=["AnalysisException in logs"],
                supporting=["Column list in error"],
            ),
            confidence_factors=ConfidenceFactorsYAML(
                increase=["Clear column name"],
                decrease=["Ambiguous error"],
            ),
            related_patterns=["permission_denied"],
            version="1.0.0",
            databricks_runtimes=["13.3", "14.0"],
        )

        assert len(pattern.recommendations) == 1
        assert pattern.recommendations[0].priority == "high"

    def test_pattern_with_multiple_regex(self) -> None:
        """Pattern with multiple regex patterns."""
        pattern = PatternYAML(
            id="multi_regex",
            name="Multi Regex",
            category=Category.NETWORK,
            severity=Severity.MEDIUM,
            responsibility=ResponsibilityScope.INFRASTRUCTURE,
            keywords=["timeout", "connection"],
            regex_patterns=[
                r"connection timed out",
                r"Connection reset",
                r"java\.net\.SocketTimeoutException",
            ],
            root_cause="Network connectivity issues",
        )

        assert len(pattern.regex_patterns) == 3


# =============================================================================
# INVALID PATTERN TESTS
# =============================================================================


class TestInvalidPatternYAML:
    """Tests for pattern validation failures."""

    def test_invalid_pattern_id_format(self) -> None:
        """Pattern ID must match ^[a-z][a-z0-9_]*$."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="Invalid-Pattern",  # Contains uppercase and hyphen
                name="Test",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                exit_code=1,
                root_cause="Test",
            )

        assert "id" in str(exc_info.value)

    def test_invalid_regex_pattern(self) -> None:
        """Invalid regex should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="bad_regex",
                name="Bad Regex",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                regex_patterns=["[invalid(regex"],  # Unclosed bracket
                root_cause="Test",
            )

        assert "Invalid regex" in str(exc_info.value)

    def test_invalid_exception_class_regex(self) -> None:
        """Invalid exception_class regex should fail."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="bad_exception_regex",
                name="Bad Exception Regex",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                exception_class="[unclosed",
                root_cause="Test",
            )

        assert "Invalid exception_class regex" in str(exc_info.value)

    def test_invalid_message_pattern_regex(self) -> None:
        """Invalid message_pattern regex should fail."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="bad_message_regex",
                name="Bad Message Regex",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                message_pattern="(unclosed",
                root_cause="Test",
            )

        assert "Invalid message_pattern regex" in str(exc_info.value)

    def test_no_matching_criteria(self) -> None:
        """Pattern must have at least one matching criterion."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="no_criteria",
                name="No Criteria",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                # No regex_patterns, exit_code, exception_class, or message_pattern
                root_cause="Test",
            )

        assert "must have at least one matching criterion" in str(exc_info.value)

    def test_empty_keywords(self) -> None:
        """Keywords list cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="empty_keywords",
                name="Empty Keywords",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=[],  # Empty
                exit_code=1,
                root_cause="Test",
            )

        assert "keywords" in str(exc_info.value).lower()

    def test_invalid_recommendation_priority(self) -> None:
        """Recommendation priority must be high/medium/low."""
        with pytest.raises(ValidationError) as exc_info:
            PatternYAML(
                id="bad_priority",
                name="Bad Priority",
                category=Category.MEMORY,
                severity=Severity.HIGH,
                responsibility=ResponsibilityScope.CONFIGURATION,
                keywords=["test"],
                exit_code=1,
                root_cause="Test",
                recommendations=[
                    RecommendationYAML(
                        id="rec1",
                        priority="urgent",  # Invalid
                        action="Do something",
                    )
                ],
            )

        assert "priority" in str(exc_info.value).lower()


# =============================================================================
# CATALOG VALIDATION TESTS
# =============================================================================


class TestPatternCatalogYAML:
    """Tests for pattern catalog validation."""

    def test_valid_catalog(self) -> None:
        """Valid catalog with multiple patterns."""
        catalog = PatternCatalogYAML(
            version="1.0.0",
            patterns=[
                PatternYAML(
                    id="pattern_one",
                    name="Pattern One",
                    category=Category.MEMORY,
                    severity=Severity.HIGH,
                    responsibility=ResponsibilityScope.CONFIGURATION,
                    keywords=["one"],
                    exit_code=1,
                    root_cause="Test one",
                ),
                PatternYAML(
                    id="pattern_two",
                    name="Pattern Two",
                    category=Category.SQL,
                    severity=Severity.MEDIUM,
                    responsibility=ResponsibilityScope.USER_CODE,
                    keywords=["two"],
                    message_pattern="two",
                    root_cause="Test two",
                ),
            ],
        )

        assert len(catalog.patterns) == 2

    def test_duplicate_pattern_ids(self) -> None:
        """Catalog with duplicate pattern IDs should fail."""
        with pytest.raises(ValidationError) as exc_info:
            PatternCatalogYAML(
                version="1.0.0",
                patterns=[
                    PatternYAML(
                        id="duplicate_id",
                        name="First",
                        category=Category.MEMORY,
                        severity=Severity.HIGH,
                        responsibility=ResponsibilityScope.CONFIGURATION,
                        keywords=["one"],
                        exit_code=1,
                        root_cause="First",
                    ),
                    PatternYAML(
                        id="duplicate_id",  # Same ID
                        name="Second",
                        category=Category.SQL,
                        severity=Severity.MEDIUM,
                        responsibility=ResponsibilityScope.USER_CODE,
                        keywords=["two"],
                        exit_code=2,
                        root_cause="Second",
                    ),
                ],
            )

        assert "Duplicate pattern IDs" in str(exc_info.value)

    def test_empty_patterns_list(self) -> None:
        """Catalog must have at least one pattern."""
        with pytest.raises(ValidationError) as exc_info:
            PatternCatalogYAML(
                version="1.0.0",
                patterns=[],
            )

        assert "patterns" in str(exc_info.value).lower()


# =============================================================================
# ENUM TESTS
# =============================================================================


class TestEnums:
    """Tests for enum values."""

    def test_all_categories(self) -> None:
        """All category values are valid."""
        categories = [
            Category.MEMORY,
            Category.EXECUTION,
            Category.SHUFFLE,
            Category.NETWORK,
            Category.SQL,
            Category.STORAGE,
            Category.DELTA,
            Category.UC,
            Category.STREAMING,
            Category.DATA_QUALITY,
            Category.CLUSTER,
            Category.PERFORMANCE,
        ]

        assert len(categories) == 12

    def test_all_severities(self) -> None:
        """All severity values are valid."""
        severities = [
            Severity.CRITICAL,
            Severity.HIGH,
            Severity.MEDIUM,
            Severity.LOW,
        ]

        assert len(severities) == 4

    def test_all_responsibility_scopes(self) -> None:
        """All responsibility scope values are valid."""
        scopes = [
            ResponsibilityScope.USER_CODE,
            ResponsibilityScope.CONFIGURATION,
            ResponsibilityScope.INFRASTRUCTURE,
        ]

        assert len(scopes) == 3


# =============================================================================
# FROZEN MODEL TESTS
# =============================================================================


class TestFrozenModels:
    """Tests for model immutability."""

    def test_pattern_is_frozen(self) -> None:
        """PatternYAML should be immutable."""
        pattern = PatternYAML(
            id="frozen_test",
            name="Frozen Test",
            category=Category.MEMORY,
            severity=Severity.HIGH,
            responsibility=ResponsibilityScope.CONFIGURATION,
            keywords=["test"],
            exit_code=1,
            root_cause="Test",
        )

        with pytest.raises(ValidationError):
            pattern.name = "Modified"  # type: ignore[misc]
