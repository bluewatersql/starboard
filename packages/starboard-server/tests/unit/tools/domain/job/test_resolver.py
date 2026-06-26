# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for job domain resolver."""

from starboard_core.domain.models.job import (
    AnalysisMode,
    JobResolutionInput,
)
from starboard_server.tools.domain.job.resolver import JobResolver


class TestJobResolver:
    """Tests for JobResolver."""

    def test_is_job_id_with_numeric_string(self):
        """Test job ID detection with numeric string."""
        assert JobResolver.is_job_id("12345") is True
        assert JobResolver.is_job_id("abc123") is False

    def test_is_job_name_with_valid_name(self):
        """Test job name detection."""
        assert JobResolver.is_job_name("my_job_name") is True
        assert JobResolver.is_job_name("Job With Spaces") is True
        assert JobResolver.is_job_name("a" * 300) is False  # Too long

    def test_classify_job_input_with_job_id(self):
        """Test classification of job ID."""
        mode = JobResolver.classify_job_input("12345")
        assert mode == AnalysisMode.JOB

    def test_classify_job_input_with_job_name(self):
        """Test classification of job name."""
        mode = JobResolver.classify_job_input("my_job")
        assert mode == AnalysisMode.JOB

    def test_classify_job_input_with_source_code(self):
        """Test classification of source code."""
        code = "def my_function():\\n    pass"
        mode = JobResolver.classify_job_input(code)
        assert mode == AnalysisMode.ADHOC

    def test_resolve_job_with_job_id(self):
        """Test resolving job with job ID."""
        input_data = JobResolutionInput(target="12345", classification=None)
        result = JobResolver.resolve_job(input_data)

        assert result.job_id == "12345"
        assert result.job_name is None
        assert result.analysis_mode == AnalysisMode.JOB

    def test_resolve_job_with_job_name(self):
        """Test resolving job with job name."""
        input_data = JobResolutionInput(target="my_job", classification=None)
        result = JobResolver.resolve_job(input_data)

        assert result.job_id is None
        assert result.job_name == "my_job"
        assert result.analysis_mode == AnalysisMode.JOB

    def test_resolve_job_with_llm_classification(self):
        """Test resolving job with LLM classification."""
        input_data = JobResolutionInput(
            target="Find job abc",
            classification={
                "input_type": "job_id",
                "target": "123",
                "confidence": "high",
            },
        )
        result = JobResolver.resolve_job(input_data)

        assert result.job_id == "123"
        assert result.analysis_mode == AnalysisMode.JOB

    def test_resolve_from_classification_with_low_confidence(self):
        """Test that low confidence classification is ignored."""
        result = JobResolver.resolve_from_classification(
            {"input_type": "job_id", "target": "123", "confidence": "low"}
        )

        assert result.analysis_mode == AnalysisMode.UNKNOWN

    def test_resolve_from_classification_with_source_code_type(self):
        """Test classification with source code type."""
        result = JobResolver.resolve_from_classification(
            {
                "input_type": "source_code",
                "target": "print('hello')",
                "confidence": "high",
            }
        )

        assert result.analysis_mode == AnalysisMode.ADHOC
        assert result.source_code == "print('hello')"
