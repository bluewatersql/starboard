"""Output management for optimization results."""

import asyncio
import pathlib
from dataclasses import dataclass, field
from typing import Any

import yaml

from starboard_server.infra.io import write_json, write_text
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OutputConfig:
    """
    Configuration for output management.

    Attributes:
        save_to_file: Whether to save outputs to file
        formats: List of output formats (markdown, json, yaml)
        output_dir: Directory to save outputs
        include_raw_context: Whether to include raw context
        include_trace: Whether to include execution trace
        include_budget: Whether to include token budget
    """

    save_to_file: bool = True
    formats: list[str] = field(default_factory=lambda: ["markdown"])
    output_dir: str = "out"
    include_raw_context: bool = False
    include_trace: bool = False
    include_budget: bool = False


class OutputManager:
    """
    Manages flexible output for optimization results.

    Supports multiple output formats:
    - Markdown: Human-readable reports
    - JSON: Structured data for API integration
    - YAML: Configuration-friendly format
    - Raw context: Complete context for reproducibility
    - Execution trace: Task execution graph for debugging
    - Token budget: Token usage breakdown for cost tracking
    """

    def __init__(self, config: OutputConfig):
        """
        Initialize output manager.

        Args:
            config: Output configuration
        """
        self.config = config

    async def save_results(
        self,
        results: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        """
        Save optimization results in multiple formats.

        Uses ``asyncio.gather()`` to write independent files in parallel.

        Args:
            results: Optimization results from workflow
            metadata: Additional metadata (plan, trace, budget)

        Returns:
            Dictionary mapping format to file path
        """
        if not self.config.save_to_file:
            return {}

        # Create output directory
        output_dir = pathlib.Path(self.config.output_dir)
        await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)

        # Extract recommendations
        recommendations = results.get("recommendations", {})

        # Build list of (key, coroutine) pairs for parallel execution
        tasks: list[tuple[str, Any]] = []

        if "markdown" in self.config.formats:
            tasks.append(("markdown", self._save_markdown(output_dir, recommendations)))

        if "json" in self.config.formats:
            tasks.append(
                ("json", self._save_json(output_dir, recommendations, results))
            )

        if "yaml" in self.config.formats:
            tasks.append(
                ("yaml", self._save_yaml(output_dir, recommendations, results))
            )

        if self.config.include_raw_context:
            tasks.append(("raw_context", self._save_raw_context(output_dir, results)))

        if self.config.include_trace and "trace" in metadata:
            tasks.append(
                ("execution_trace", self._save_trace(output_dir, metadata["trace"]))
            )

        if self.config.include_budget and "budget" in metadata:
            tasks.append(
                ("token_budget", self._save_budget(output_dir, metadata["budget"]))
            )

        # Execute all writes in parallel
        paths = await asyncio.gather(*(coro for _, coro in tasks))

        saved_files: dict[str, str] = {}
        for (key, _), path in zip(tasks, paths):
            if path is not None:
                saved_files[key] = str(path)

        logger.debug(
            "output_files_saved", count=len(saved_files), output_dir=str(output_dir)
        )
        return saved_files

    async def _save_markdown(
        self, output_dir: pathlib.Path, recommendations: dict[str, Any]
    ) -> pathlib.Path | None:
        """
        Save recommendations in markdown format.

        Args:
            output_dir: Output directory
            recommendations: Recommendations data

        Returns:
            Path to saved file or None
        """
        try:
            md_path = output_dir / "recommendations.md"

            # Extract markdown content from various formats
            if isinstance(recommendations, str):
                content = recommendations
            elif isinstance(recommendations, dict):
                # Try to extract markdown from structured response
                content = recommendations.get("executive_summary", "")
                if not content:
                    content = recommendations.get("report", "")
                if not content:
                    content = self._format_recommendations_as_markdown(recommendations)
            else:
                content = str(recommendations)

            await write_text(md_path, content)
            logger.debug("markdown_report_saved", path=str(md_path))
            return md_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("markdown_save_failed", error=str(e))
            return None

    async def _save_json(
        self,
        output_dir: pathlib.Path,
        recommendations: dict[str, Any],
        results: dict[str, Any],
    ) -> pathlib.Path | None:
        """
        Save recommendations in JSON format.

        Args:
            output_dir: Output directory
            recommendations: Recommendations data
            results: Full results

        Returns:
            Path to saved file or None
        """
        try:
            json_path = output_dir / "recommendations.json"

            # Build comprehensive JSON output
            output = {
                "recommendations": recommendations,
                "metadata": {
                    "generated_at": results.get("generated_at"),
                    "mode": results.get("mode"),
                },
            }

            # Add additional context if available
            if "job_id" in results:
                output["job_id"] = results["job_id"]
            if "job_name" in results:
                output["job_name"] = results["job_name"]

            await write_json(json_path, output)
            logger.debug("json_report_saved", path=str(json_path))
            return json_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("json_save_failed", error=str(e))
            return None

    async def _save_yaml(
        self,
        output_dir: pathlib.Path,
        recommendations: dict[str, Any],
        results: dict[str, Any],
    ) -> pathlib.Path | None:
        """
        Save recommendations in YAML format.

        Args:
            output_dir: Output directory
            recommendations: Recommendations data
            results: Full results

        Returns:
            Path to saved file or None
        """
        try:
            yaml_path = output_dir / "recommendations.yaml"

            # Build YAML output
            output = {
                "recommendations": recommendations,
                "metadata": {
                    "generated_at": str(results.get("generated_at", "")),
                    "mode": results.get("mode", ""),
                },
            }

            if "job_id" in results:
                output["job_id"] = results["job_id"]
            if "job_name" in results:
                output["job_name"] = results["job_name"]

            content = yaml.dump(output, default_flow_style=False, sort_keys=False)
            await write_text(yaml_path, content)
            logger.debug("yaml_report_saved", path=str(yaml_path))
            return yaml_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("yaml_save_failed", error=str(e))
            return None

    async def _save_raw_context(
        self, output_dir: pathlib.Path, results: dict[str, Any]
    ) -> pathlib.Path | None:
        """
        Save raw context for reproducibility.

        Args:
            output_dir: Output directory
            results: Full results with context

        Returns:
            Path to saved file or None
        """
        try:
            ctx_path = output_dir / "raw_context.json"

            await write_json(ctx_path, results)
            logger.debug("raw_context_saved", path=str(ctx_path))
            return ctx_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("raw_context_save_failed", error=str(e))
            return None

    async def _save_trace(
        self, output_dir: pathlib.Path, trace: list[dict[str, Any]]
    ) -> pathlib.Path | None:
        """
        Save execution trace.

        Args:
            output_dir: Output directory
            trace: Execution trace

        Returns:
            Path to saved file or None
        """
        try:
            trace_path = output_dir / "execution_trace.json"

            await write_json(trace_path, trace)
            logger.debug("execution_trace_saved", path=str(trace_path))
            return trace_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("execution_trace_save_failed", error=str(e))
            return None

    async def _save_budget(
        self, output_dir: pathlib.Path, budget: dict[str, Any]
    ) -> pathlib.Path | None:
        """
        Save token budget information.

        Args:
            output_dir: Output directory
            budget: Token budget data

        Returns:
            Path to saved file or None
        """
        try:
            budget_path = output_dir / "token_budget.json"

            await write_json(budget_path, budget)
            logger.debug("token_budget_saved", path=str(budget_path))
            return budget_path

        except Exception as e:  # noqa: BLE001 - output handler boundary
            logger.error("token_budget_save_failed", error=str(e))
            return None

    def _format_recommendations_as_markdown(
        self, recommendations: dict[str, Any]
    ) -> str:
        """
        Format recommendations dictionary as markdown.

        Args:
            recommendations: Recommendations dictionary

        Returns:
            Markdown-formatted string
        """
        lines = ["# Job Optimization Recommendations\n"]

        # Add summary if available
        if "summary" in recommendations:
            lines.append("## Summary\n")
            lines.append(f"{recommendations['summary']}\n")

        # Add opportunities if available
        if "opportunities" in recommendations:
            lines.append("## Optimization Opportunities\n")
            for i, opp in enumerate(recommendations["opportunities"], 1):
                lines.append(f"### {i}. {opp.get('title', 'Opportunity')}\n")
                if "description" in opp:
                    lines.append(f"{opp['description']}\n")
                if "recommendation" in opp:
                    lines.append(f"**Recommendation:** {opp['recommendation']}\n")

        # Add any other keys
        for key, value in recommendations.items():
            if key not in ["summary", "opportunities"]:
                lines.append(f"## {key.replace('_', ' ').title()}\n")
                lines.append(f"{value}\n")

        return "\n".join(lines)
