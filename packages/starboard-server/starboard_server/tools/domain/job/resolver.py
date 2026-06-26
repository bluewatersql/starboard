# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure job resolution logic."""

from __future__ import annotations

import re

from starboard_core.domain.models.job import (
    AnalysisMode,
    JobResolutionInput,
    JobResolutionResult,
)

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class JobResolver:
    """

    Pure job resolution logic.

    All methods are static and side-effect free.
    """

    @staticmethod
    def is_job_id(target: str) -> bool:
        """
        Check if target looks like a job ID.

        Args:
            target: Input string

        Returns:
            True if target looks like a job ID
        """
        return bool(re.match(r"^\d+$", target))

    @staticmethod
    def is_job_name(target: str) -> bool:
        """
        Check if target looks like a job name.

        Args:
            target: Input string

        Returns:
            True if target looks like a job name
        """
        # Job names are typically short and alphanumeric with some special chars
        return len(target) < 200 and bool(re.match(r"^[\w\-\_\.\ ]+$", target))

    @staticmethod
    def classify_job_input(target: str) -> AnalysisMode:
        """
        Classify job input type.

        Args:
            target: Input string to classify

        Returns:
            AnalysisMode classification
        """
        if JobResolver.is_job_id(target) or JobResolver.is_job_name(target):
            return AnalysisMode.JOB
        else:
            # Assume it's source code for adhoc analysis
            return AnalysisMode.ADHOC

    @staticmethod
    def resolve_from_classification(
        classification: dict | None,
    ) -> JobResolutionResult:
        """
        Resolve job using LLM classification hints.

        Args:
            target: Original target string
            classification: Optional LLM classification result

        Returns:
            JobResolutionResult with partial resolution
        """
        if not classification:
            return JobResolutionResult(
                job_id=None,
                job_name=None,
                source_code=None,
                analysis_mode=AnalysisMode.UNKNOWN,
            )

        confidence = classification.get("confidence", "")
        if confidence not in ["high", "medium"]:
            return JobResolutionResult(
                job_id=None,
                job_name=None,
                source_code=None,
                analysis_mode=AnalysisMode.UNKNOWN,
            )

        input_type = classification.get("input_type", "")
        target_value = classification.get("target")

        match input_type:
            case "job_id":
                logger.debug("LLM resolved job ID from raw input")
                return JobResolutionResult(
                    job_id=target_value,
                    job_name=None,
                    source_code=None,
                    analysis_mode=AnalysisMode.JOB,
                )
            case "job_name":
                logger.debug("LLM resolved job name from raw input")
                return JobResolutionResult(
                    job_id=None,
                    job_name=target_value,
                    source_code=None,
                    analysis_mode=AnalysisMode.JOB,
                )
            case "source_code":
                logger.debug("LLM resolved source code from raw input")
                return JobResolutionResult(
                    job_id=None,
                    job_name=None,
                    source_code=target_value,
                    analysis_mode=AnalysisMode.ADHOC,
                )
            case _:
                logger.debug("unknown_input_type", input_type=input_type)
                return JobResolutionResult(
                    job_id=None,
                    job_name=None,
                    source_code=None,
                    analysis_mode=AnalysisMode.UNKNOWN,
                )

    @staticmethod
    def resolve_job(input_data: JobResolutionInput) -> JobResolutionResult:
        """
        Resolve job from input (classification + fallback).

        Args:
            input_data: Job resolution input

        Returns:
            JobResolutionResult (may be partial)
        """
        # Try classification first
        if input_data.classification:
            result = JobResolver.resolve_from_classification(
                input_data.classification,
            )
            if result.analysis_mode != AnalysisMode.UNKNOWN:
                return result

        # Fallback to manual classification
        mode = JobResolver.classify_job_input(input_data.target)

        if mode == AnalysisMode.JOB:
            if JobResolver.is_job_id(input_data.target):
                logger.debug("resolved_job_id", job_id=input_data.target)
                return JobResolutionResult(
                    job_id=input_data.target,
                    job_name=None,
                    source_code=None,
                    analysis_mode=AnalysisMode.JOB,
                )
            else:
                logger.debug("resolved_job_name", job_name=input_data.target)
                return JobResolutionResult(
                    job_id=None,
                    job_name=input_data.target,
                    source_code=None,
                    analysis_mode=AnalysisMode.JOB,
                )
        else:
            logger.debug("resolved_source_code", target=input_data.target)
            return JobResolutionResult(
                job_id=None,
                job_name=None,
                source_code=input_data.target,
                analysis_mode=AnalysisMode.ADHOC,
            )
