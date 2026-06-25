# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Spark event log evidence extractor.

Uses starboard-log-parser to parse Spark event logs and extract
diagnostic evidence for LLM analysis.

This extractor handles:
- Failed jobs with reasons
- Slow stages (duration outliers)
- Executor removals/OOM
- Task failure counts
- Data skew indicators

Design reference: changes/large_files/DESIGN.md Section 4.5
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.diagnostic.models import ArtifactType

logger = get_logger(__name__)

MAX_DISTILLED_SIZE = 8000


# =============================================================================
# EVIDENCE DATACLASS
# =============================================================================


@dataclass
class SparkDiagnosticEvidence:
    """Diagnostic evidence extracted from Spark event log.

    Attributes:
        failed_jobs: List of failed jobs with metadata
        slow_stages: List of stages exceeding duration threshold
        executor_issues: List of executor removal events
        task_failures: Total count of failed tasks
        data_skew_detected: True if significant task duration variance found
        summary: Human-readable summary of findings
    """

    failed_jobs: list[dict[str, Any]]
    slow_stages: list[dict[str, Any]]
    executor_issues: list[dict[str, Any]]
    task_failures: int
    data_skew_detected: bool
    summary: str


# =============================================================================
# PROCESSED ARTIFACT (imported here to avoid circular import)
# =============================================================================


@dataclass(frozen=True)
class ProcessedArtifact:
    """Result of processing a large artifact.

    Note: This is a local copy to avoid circular imports.
    The canonical definition is in large_artifact_processor.py.
    """

    artifact_type: ArtifactType
    distilled_content: str
    evidence_count: int
    original_size: int
    compression_ratio: float
    inferred_goal: str
    metadata: dict[str, Any]


# =============================================================================
# SPARK EVENT LOG EXTRACTOR
# =============================================================================


class SparkEventLogExtractor:
    """Extract diagnostic evidence from Spark event logs.

    Uses starboard-log-parser for parsing, then extracts:
    - Failed jobs with reasons
    - Slow stages (duration outliers)
    - Executor removals/OOM
    - Task failure counts
    - Data skew indicators

    Example:
        >>> extractor = SparkEventLogExtractor()
        >>> result = await extractor.extract(event_log_content, "Analyze performance")
        >>> print(result.distilled_content)

    Attributes:
        _slow_threshold: Duration threshold (seconds) for slow stage detection
    """

    def __init__(self, slow_stage_threshold_sec: float = 60.0) -> None:
        """Initialize extractor.

        Args:
            slow_stage_threshold_sec: Stages longer than this are flagged as slow
        """
        self._slow_threshold = slow_stage_threshold_sec

    async def extract(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Extract diagnostic evidence from Spark event log content.

        Args:
            content: Spark event log (JSON-lines format)
            inferred_goal: User's goal for analysis

        Returns:
            ProcessedArtifact with distilled diagnostic content
        """
        # Parse using starboard-log-parser
        lines_iter = (
            json.loads(line)
            for line in content.splitlines()
            if line.strip() and line.strip().startswith("{")
        )

        try:
            from starboard_log_parser.parsing_models.event_log_parser import (
                ApplicationModel,
            )

            app_model = ApplicationModel(lines_iter, debug=True)
        except (ValueError, KeyError, OSError) as e:
            logger.warning("spark_event_log_parsing_failed", error=str(e))
            return self._fallback_extraction(content, inferred_goal)

        # Extract evidence
        evidence = self._extract_evidence(app_model)

        # Build distilled content
        distilled = self._build_distilled_content(evidence, app_model)

        return ProcessedArtifact(
            artifact_type=ArtifactType.SPARK_EVENT_LOG,
            distilled_content=distilled[:MAX_DISTILLED_SIZE],
            evidence_count=len(evidence.failed_jobs) + len(evidence.slow_stages),
            original_size=len(content),
            compression_ratio=1 - (len(distilled) / len(content)) if content else 0,
            inferred_goal=inferred_goal,
            metadata={
                "jobs_total": len(app_model.jobs),
                "stages_total": len(app_model.stages),
                "tasks_total": len(app_model.tasks),
                "failed_jobs": len(evidence.failed_jobs),
                "slow_stages": len(evidence.slow_stages),
                "executor_issues": len(evidence.executor_issues),
                "data_skew": evidence.data_skew_detected,
            },
        )

    def _extract_evidence(self, app: Any) -> SparkDiagnosticEvidence:
        """Extract diagnostic signals from parsed application.

        Args:
            app: Parsed ApplicationModel from starboard-log-parser

        Returns:
            SparkDiagnosticEvidence with extracted signals
        """
        failed_jobs: list[dict[str, Any]] = []
        slow_stages: list[dict[str, Any]] = []
        executor_issues: list[dict[str, Any]] = []
        task_failures = 0

        # Failed jobs
        for job_id, job in app.jobs.items():
            if job.result and job.result != "JobSucceeded":
                failed_jobs.append(
                    {
                        "job_id": job_id,
                        "result": job.result,
                        "stages": list(job.stages.keys())
                        if hasattr(job, "stages")
                        else [],
                    }
                )

        # Slow stages
        if app.stages:
            stage_durations: list[tuple[int, float, Any]] = []
            for stage_id, stage in app.stages.items():
                if stage.completion_time and stage.submission_time:
                    duration = stage.completion_time - stage.submission_time
                    stage_durations.append((stage_id, duration, stage))

            # Find stages > threshold or > 2x median
            if stage_durations:
                durations = [d[1] for d in stage_durations]
                median_duration = sorted(durations)[len(durations) // 2]
                threshold = max(self._slow_threshold, median_duration * 2)

                for stage_id, duration, stage in stage_durations:
                    if duration > threshold:
                        slow_stages.append(
                            {
                                "stage_id": stage_id,
                                "duration_sec": duration,
                                "name": getattr(stage, "stage_name", "unknown"),
                                "num_tasks": getattr(stage, "num_tasks", 0),
                            }
                        )

        # Executor issues
        for exec_id, executor in app.executors.items():
            if hasattr(executor, "removed_reason") and executor.removed_reason:
                executor_issues.append(
                    {
                        "executor_id": exec_id,
                        "removed_reason": executor.removed_reason,
                        "host": getattr(executor, "host", "unknown"),
                    }
                )

        # Task failures
        for task in app.tasks:
            if hasattr(task, "failed") and task.failed:
                task_failures += 1

        # Data skew detection (task duration variance within a stage)
        data_skew = self._detect_data_skew(app)

        summary = self._generate_summary(
            failed_jobs, slow_stages, executor_issues, task_failures, data_skew, app
        )

        return SparkDiagnosticEvidence(
            failed_jobs=failed_jobs,
            slow_stages=slow_stages,
            executor_issues=executor_issues,
            task_failures=task_failures,
            data_skew_detected=data_skew,
            summary=summary,
        )

    def _detect_data_skew(self, app: Any) -> bool:
        """Detect data skew from task duration variance.

        Args:
            app: Parsed ApplicationModel

        Returns:
            True if significant skew detected (max task > 5x median)
        """
        for _stage_id, stage in app.stages.items():
            tasks = getattr(stage, "tasks", [])
            if len(tasks) >= 10:
                durations = []
                for t in tasks:
                    finish = getattr(t, "finish_time", None)
                    start = getattr(t, "start_time", None)
                    if finish and start:
                        durations.append(finish - start)

                if durations:
                    max_dur = max(durations)
                    median_dur = sorted(durations)[len(durations) // 2]
                    # Skew if max is 5x median
                    if median_dur > 0 and max_dur / median_dur > 5:
                        return True
        return False

    def _generate_summary(
        self,
        failed_jobs: list[dict[str, Any]],
        slow_stages: list[dict[str, Any]],
        executor_issues: list[dict[str, Any]],
        task_failures: int,
        data_skew: bool,
        app: Any,
    ) -> str:
        """Generate a diagnostic summary.

        Args:
            failed_jobs: List of failed jobs
            slow_stages: List of slow stages
            executor_issues: List of executor issues
            task_failures: Total task failure count
            data_skew: Whether data skew was detected
            app: Parsed ApplicationModel

        Returns:
            Human-readable summary string
        """
        parts = []

        # Application overview
        runtime = "unknown"
        if app.finish_time and app.start_time:
            runtime = f"{app.finish_time - app.start_time:.1f}s"
        parts.append(
            f"Spark Application: {len(app.jobs)} jobs, {len(app.stages)} stages, "
            f"{len(app.tasks)} tasks, runtime {runtime}"
        )

        # Issues
        if failed_jobs:
            parts.append(f"❌ {len(failed_jobs)} failed job(s)")
        if slow_stages:
            parts.append(f"🐢 {len(slow_stages)} slow stage(s)")
        if executor_issues:
            parts.append(f"⚠️ {len(executor_issues)} executor issue(s)")
        if task_failures:
            parts.append(f"❌ {task_failures} task failure(s)")
        if data_skew:
            parts.append("📊 Data skew detected")

        if not any(
            [failed_jobs, slow_stages, executor_issues, task_failures, data_skew]
        ):
            parts.append("✅ No significant issues detected")

        return " | ".join(parts)

    def _build_distilled_content(
        self,
        evidence: SparkDiagnosticEvidence,
        app: Any,  # noqa: ARG002
    ) -> str:
        """Build distilled content for LLM context.

        Args:
            evidence: Extracted diagnostic evidence
            app: Parsed ApplicationModel

        Returns:
            Markdown-formatted distilled content
        """
        sections = [f"## Spark Application Analysis\n\n{evidence.summary}"]

        if evidence.failed_jobs:
            sections.append("### Failed Jobs")
            for job in evidence.failed_jobs[:5]:  # Limit to 5
                sections.append(f"- Job {job['job_id']}: {job['result']}")

        if evidence.slow_stages:
            sections.append("### Slow Stages")
            for stage in sorted(evidence.slow_stages, key=lambda s: -s["duration_sec"])[
                :5
            ]:
                sections.append(
                    f"- Stage {stage['stage_id']} ({stage['name']}): "
                    f"{stage['duration_sec']:.1f}s, {stage['num_tasks']} tasks"
                )

        if evidence.executor_issues:
            sections.append("### Executor Issues")
            for exec_info in evidence.executor_issues[:5]:
                sections.append(
                    f"- Executor {exec_info['executor_id']}: {exec_info['removed_reason']}"
                )

        if evidence.data_skew_detected:
            sections.append(
                "### Data Skew\n"
                "Significant task duration variance detected. "
                "Some tasks taking 5x+ longer than median."
            )

        return "\n\n".join(sections)

    def _fallback_extraction(
        self,
        content: str,
        inferred_goal: str,
    ) -> ProcessedArtifact:
        """Fallback when parsing fails - extract key patterns.

        Args:
            content: Original content
            inferred_goal: User's goal

        Returns:
            ProcessedArtifact with pattern-based extraction
        """
        from starboard_server.tools.domain.diagnostic.evidence_extractor import (
            EvidenceWindowExtractor,
        )

        extractor = EvidenceWindowExtractor()
        result = extractor.extract(content)

        return ProcessedArtifact(
            artifact_type=ArtifactType.SPARK_EVENT_LOG,
            distilled_content=f"## Spark Event Log (parse failed)\n\n{result.summary}",
            evidence_count=result.window_count,
            original_size=len(content),
            compression_ratio=0.9,
            inferred_goal=inferred_goal,
            metadata={"parse_failed": True},
        )
