"""Report generation utilities.

File write helpers (``write_text_file``, ``write_json_file``) are async to
avoid blocking the event loop — they may be called during request handling.
"""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

from starboard_server.infra.io import write_json, write_text
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)

# Constants
REPORT_WIDTH = 100
SECTION_SEPARATOR_WIDTH = 70
DEFAULT_INDENT = "   "


class Utils:
    """Utility functions for report formatting."""

    @staticmethod
    def confidence_indicator(val: str) -> str:
        """
        Return visual indicator for confidence level.

        Args:
            val: Confidence level (low, medium, high)

        Returns:
            Emoji indicator for confidence level
        """
        match val:
            case "low":
                return "🔴"
            case "medium":
                return "🟠"
            case "high":
                return "🟢"
            case _:
                logger.warning("unknown_confidence_level", value=val)
                return "⚪"

    @staticmethod
    def effort_indicator(val: str) -> str:
        """
        Return visual indicator for effort level.

        Args:
            val: Effort level (low, medium, high)

        Returns:
            Emoji indicator for effort level (low=green/good, high=red/warning)
        """
        match val:
            case "low":
                return "🟢"  # Low effort = good
            case "medium":
                return "🟠"
            case "high":
                return "🔴"  # High effort = warning
            case _:
                logger.warning("unknown_effort_level", value=val)
                return "⚪"


class AnalystReports:
    @staticmethod
    def build_llm_usage_summary(results: dict[str, Any]) -> None:
        """
        Build a report from the LLM usage summary.

        Args:
            results: The results from the LLM usage summary

        Returns:
            None
        """
        print("\n" + "=" * 70)
        print("=== LLM Summary ===")
        print("=" * 70)

        # Token usage (actual from API responses)
        if "token_usage" in results:
            usage = results["token_usage"]
            print("\n💰 Token Usage (Actual from API):")
            total = usage.get("total_tokens", "N/A")
            prompt = usage.get("prompt_tokens", "N/A")
            completion = usage.get("completion_tokens", "N/A")
            print(
                f"   Total: {total:,}"
                if isinstance(total, int)
                else f"   Total: {total}"
            )
            print(
                f"   Prompt: {prompt:,}"
                if isinstance(prompt, int)
                else f"   Prompt: {prompt}"
            )
            print(
                f"   Completion: {completion:,}"
                if isinstance(completion, int)
                else f"   Completion: {completion}"
            )

        # Execution
        if "completed_tasks" in results:
            completed_tasks = results["completed_tasks"]
            print("\n⚙️  Execution:")
            print(f"   Tasks completed: {len(completed_tasks)}")
            if completed_tasks:
                print(f"   Task IDs: {', '.join(completed_tasks)}")

        print()

    @staticmethod
    def build_advisor_report(results: dict[str, Any]) -> None:
        """
        Build and print a report from the advisor results.

        This is a convenience wrapper that prints the report to stdout.
        For testing or programmatic access, use build_advisor_report_string().

        Args:
            results: The results from the advisor

        Returns:
            None
        """
        report = AnalystReports.build_advisor_report_string(results)
        if report:
            print(report)

    @staticmethod
    def build_advisor_report_string(results: dict[str, Any]) -> str:
        """
        Build a report from the advisor results as a string.

        Args:
            results: The results from the advisor

        Returns:
            Formatted report string, or empty string if no advice available
        """
        advice = results.get("results", {}).get("final_advisor_advice", {})
        if not advice:
            return ""

        lines = []
        summary = advice.get("summary", {})
        analysis = advice.get("analysis", {})
        next_steps = advice.get("next_steps", [])

        # Build report sections
        lines.append(_format_overview_section(summary))

        current_state = _format_current_state_section(summary)
        if current_state:
            lines.append(current_state)

        lines.append(_format_findings_section(analysis))

        next_steps_section = _format_next_steps_section(next_steps)
        if next_steps_section:
            lines.append(next_steps_section)

        return "\n".join(lines)

    @staticmethod
    def build_advisor_report_markdown(results: dict[str, Any]) -> str:
        """
        Build a report from the advisor results in Markdown format.

        Args:
            results: The results from the advisor

        Returns:
            Markdown-formatted report string, or empty string if no advice available
        """
        from starboard_server.infra.observability.logging import get_logger

        logger = get_logger(__name__)

        advice = results.get("results", {}).get("final_advisor_advice", {})

        if not advice:
            logger.warning("no_advice_found_in_results")
            return ""

        lines = []
        summary = advice.get("summary", {})
        analysis = advice.get("analysis", {})
        next_steps = advice.get("next_steps", [])

        # Defensive: Handle case where LLM returns JSON string instead of dict
        if isinstance(analysis, str):
            try:
                analysis = json.loads(analysis)
                logger.debug("parsed_analysis_from_string")
            except json.JSONDecodeError as e:
                logger.warning(
                    "failed_to_parse_analysis_string",
                    error=str(e),
                    preview=analysis[:100],
                )
                analysis = {}

        if isinstance(next_steps, str):
            try:
                next_steps = json.loads(next_steps)
                logger.debug("parsed_next_steps_from_string")
            except json.JSONDecodeError as e:
                logger.warning(
                    "failed_to_parse_next_steps_string",
                    error=str(e),
                    preview=next_steps[:100],
                )
                next_steps = []

        # Build markdown report sections
        lines.append(_format_overview_section_markdown(summary))

        current_state = _format_current_state_section_markdown(summary)
        if current_state:
            lines.append(current_state)

        lines.append(_format_findings_section_markdown(analysis))

        next_steps_section = _format_next_steps_section_markdown(next_steps)
        if next_steps_section:
            lines.append(next_steps_section)

        final_report = "\n".join(lines)
        logger.debug(
            "report_markdown_generated",
            sections=len(lines),
            length=len(final_report),
        )

        return final_report


# Private helper functions for text format


def _format_section_header(title: str, width: int = SECTION_SEPARATOR_WIDTH) -> str:
    """Format a section header with separator lines."""
    return f"\n{'=' * width}\n=== {title} ===\n{'=' * width}"


def _create_text_wrapper() -> textwrap.TextWrapper:
    """Create a consistent text wrapper for report formatting."""
    return textwrap.TextWrapper(
        width=REPORT_WIDTH,
        initial_indent="",
        subsequent_indent=DEFAULT_INDENT,
    )


def _format_overview_section(summary: dict[str, Any]) -> str:
    """Format the overview section."""
    wrapper = _create_text_wrapper()
    lines = []
    lines.append(_format_section_header("Optimizer Advisor Overview"))
    lines.append("")
    overview = summary.get("overview", "")
    if overview:
        lines.append(f"{DEFAULT_INDENT}{wrapper.fill(overview)}")
    else:
        lines.append(f"{DEFAULT_INDENT}No overview available.")
    lines.append("")
    return "\n".join(lines)


def _format_current_state_section(summary: dict[str, Any]) -> str:
    """Format the current state issues section."""
    key_symptoms = summary.get("current_state", {}).get("key_symptoms", [])
    if not key_symptoms:
        return ""

    lines = []
    lines.append(_format_section_header("Current State Issues"))
    for symptom in key_symptoms:
        lines.append(f"  ℹ️  {symptom}")
    return "\n".join(lines)


def _format_findings_section(analysis: dict[str, Any]) -> str:
    """Format the findings section."""
    findings = analysis.get("findings", [])
    if not findings:
        lines = []
        lines.append(_format_section_header("Findings"))
        lines.append("")
        lines.append(f"{DEFAULT_INDENT}No findings available.")
        return "\n".join(lines)

    # Sort findings by rank before displaying
    sorted_findings = sorted(findings, key=lambda x: x.get("rank", 999))

    lines = []
    lines.append(_format_section_header("Findings"))

    wrapper = _create_text_wrapper()

    for finding in sorted_findings:
        lines.append("")
        rank = finding.get("rank", "?")
        title = finding.get("title", "Untitled")
        lines.append(f" ✅ RANK {rank} - {title}")

        recommendation = finding.get("recommendation", "")
        if recommendation:
            lines.append(f"{DEFAULT_INDENT}{wrapper.fill(recommendation)}")
        lines.append("")

        # Impact estimate
        impact = finding.get("impact_estimate", {})
        if impact and isinstance(impact, dict):
            impact_parts = []
            for k, v in impact.items():
                if k != "confidence" and v != 0.0:
                    impact_parts.append(f"{k.replace('_pct', '')}: {v}%")

            confidence = impact.get("confidence", "")
            if impact_parts:
                lines.append(
                    f"{DEFAULT_INDENT}=== 💥 IMPACT === Confidence: {Utils.confidence_indicator(confidence)} ({' | '.join(impact_parts)})"
                )

        # Effort estimate
        effort = finding.get("effort", {})
        if effort and isinstance(effort, dict):
            level = effort.get("level", "")
            hours = effort.get("estimate_hours", "")
            lines.append(
                f"{DEFAULT_INDENT}=== 🎯 EFFORT === Level: {Utils.effort_indicator(level)} (hours: {hours})"
            )

        lines.append("")

        # Code references
        proofs = finding.get("proofs", {})
        if proofs and isinstance(proofs, dict):
            code_refs = proofs.get("code_line_refs", [])
            if code_refs:
                lines.append(f"{DEFAULT_INDENT} === CODE REFERENCES ===")
                for ref in code_refs:
                    # Handle both dict and string formats from LLM
                    if isinstance(ref, dict):
                        obj_name = ref.get("object", "Unknown")
                        line_num = ref.get("line", "?")
                        lines.append(
                            f"{DEFAULT_INDENT} 📜 {obj_name} @ Line {line_num}"
                        )
                    elif isinstance(ref, str):
                        lines.append(f"{DEFAULT_INDENT} 📜 {ref}")
                lines.append("")

        # Fixes
        fixes = finding.get("fixes", [])
        if fixes:
            for fix in fixes:
                fix_type = fix.get("type", "unknown")
                lines.append(f"{DEFAULT_INDENT} === 👉 FIX: {fix_type} ===")
                snippet = fix.get("snippet", "")
                if snippet:
                    formatted_snippet = snippet.replace("\n", "\n      ")
                    lines.append(f"      {formatted_snippet}")
        lines.append("")

    return "\n".join(lines)


def _format_next_steps_section(next_steps: list[dict[str, Any]]) -> str:
    """Format the next steps section."""
    if not next_steps:
        return ""

    # Sort by rank to ensure proper ordering
    sorted_steps = sorted(next_steps, key=lambda x: x.get("rank", 999))

    lines = []
    lines.append(_format_section_header("🎯 Suggested Next Actions"))
    lines.append("")

    for step in sorted_steps:
        rank = step.get("rank", "?")
        action = step.get("action", "")

        lines.append(f" 🚀 {rank}. {action}")
        lines.append("")

    return "\n".join(lines)


# Private helper functions for markdown format


def _format_overview_section_markdown(summary: dict[str, Any]) -> str:
    """Format the overview section in Markdown."""
    lines = []
    lines.append("")
    lines.append("# Optimizer Advisor Overview")
    lines.append("")
    overview = summary.get("overview", "")
    if overview:
        lines.append(overview)
    else:
        lines.append("*No overview available.*")
    lines.append("")
    return "\n".join(lines)


def _format_current_state_section_markdown(summary: dict[str, Any]) -> str:
    """Format the current state issues section in Markdown."""
    key_symptoms = summary.get("current_state", {}).get("key_symptoms", [])
    if not key_symptoms:
        return ""

    lines = []
    lines.append("## Current State Issues")
    lines.append("")
    for symptom in key_symptoms:
        lines.append(f"- ℹ️ {symptom}")
    lines.append("")
    return "\n".join(lines)


def _format_findings_section_markdown(analysis: dict[str, Any]) -> str:
    """Format the findings section in Markdown."""
    # Defensive: Handle case where analysis might be a string
    if isinstance(analysis, str):
        try:
            analysis = json.loads(analysis)
            logger.debug("parsed_analysis_from_string_in_findings")
        except json.JSONDecodeError as e:
            logger.warning(
                "failed_to_parse_analysis_in_findings",
                error=str(e),
                preview=analysis[:100],
            )
            analysis = {}

    findings = analysis.get("findings", [])

    if not findings:
        lines = []
        lines.append("## Findings")
        lines.append("")
        lines.append("*No findings available.*")
        lines.append("")
        return "\n".join(lines)

    # Sort findings by rank before displaying
    sorted_findings = sorted(findings, key=lambda x: x.get("rank", 999))

    lines = []
    lines.append("## Findings")
    lines.append("")

    for finding in sorted_findings:
        rank = finding.get("rank", "?")
        title = finding.get("title", "Untitled")
        lines.append(f"### ✅ Finding {rank}: {title}")
        lines.append("")

        recommendation = finding.get("recommendation", "")
        if recommendation:
            lines.append(recommendation)
            lines.append("")

        # Impact estimate
        impact = finding.get("impact_estimate", {})
        if impact and isinstance(impact, dict):
            impact_parts = []
            for k, v in impact.items():
                if k != "confidence" and v != 0.0:
                    impact_parts.append(f"**{k.replace('_pct', '')}**: {v}%")

            confidence = impact.get("confidence", "")
            if impact_parts or confidence:
                lines.append("**💥 Impact:**")
                if confidence:
                    lines.append(
                        f"- Confidence: {Utils.confidence_indicator(confidence)} {confidence}"
                    )
                if impact_parts:
                    lines.append(f"- {' | '.join(impact_parts)}")
                lines.append("")

        # Effort estimate
        effort = finding.get("effort", {})
        if effort and isinstance(effort, dict):
            level = effort.get("level", "")
            hours = effort.get("estimate_hours", "")
            lines.append("**🎯 Effort:**")
            lines.append(f"- Level: {Utils.effort_indicator(level)} {level}")
            if hours:
                lines.append(f"- Estimated hours: {hours}")
            lines.append("")

        # Code references
        proofs = finding.get("proofs", {})
        if proofs and isinstance(proofs, dict):
            code_refs = proofs.get("code_line_refs", [])
            if code_refs:
                lines.append("**Code References:**")
                for ref in code_refs:
                    obj_name = ref.get("object", "Unknown")
                    line_num = ref.get("line", "?")
                    lines.append(f"- 📜 `{obj_name}` @ Line {line_num}")
                lines.append("")

        # Fixes
        fixes = finding.get("fixes", [])
        if fixes:
            lines.append("**Proposed Fixes:**")
            for fix in fixes:
                fix_type = fix.get("type", "unknown")
                lines.append(f"- **{fix_type}:**")
                snippet = fix.get("snippet", "")
                if snippet:
                    lines.append("```")
                    lines.append(snippet)
                    lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _format_next_steps_section_markdown(next_steps: list[dict[str, Any]]) -> str:
    """Format the next steps section in Markdown."""
    # Defensive: Handle case where next_steps might be a string
    if isinstance(next_steps, str):
        import json

        from starboard_server.infra.observability.logging import get_logger

        logger = get_logger(__name__)
        try:
            next_steps = json.loads(next_steps)
            logger.debug("parsed_next_steps_from_string_in_formatting")
        except json.JSONDecodeError as e:
            logger.warning(
                "failed_to_parse_next_steps_in_formatting",
                error=str(e),
                preview=next_steps[:100],
            )
            next_steps = []

    if not next_steps:
        return ""

    # Sort by rank to ensure proper ordering
    sorted_steps = sorted(next_steps, key=lambda x: x.get("rank", 999))

    lines = []
    lines.append("## 🎯 Suggested Next Actions")
    lines.append("")

    for step in sorted_steps:
        rank = step.get("rank", "?")
        action = step.get("action", "")

        lines.append(f"{rank}. {action}")
        lines.append("")

    return "\n".join(lines)


async def write_text_file(path: Path, content: str) -> None:
    """Write text content to a file asynchronously with UTF-8 encoding.

    This function creates or overwrites the file at the specified path.
    The parent directory must exist; this function does not create directories.

    Uses ``starboard_server.infra.io.write_text`` for non-blocking I/O.

    Args:
        path: Path object pointing to the target file location.
        content: Text content to write. Will be encoded as UTF-8.

    Raises:
        OSError: If the file cannot be written (permissions, disk space, etc.)
    """
    await write_text(path, content)


async def write_json_file(
    file_path: str | Path, data: dict, *, indent: int = 2
) -> None:
    """Write dictionary to JSON file asynchronously with pretty formatting.

    This function serializes a dictionary to JSON with indentation for readability.
    The output uses UTF-8 encoding and preserves Unicode characters (ensure_ascii=False).
    The parent directory must exist; this function does not create directories.

    Uses ``starboard_server.infra.io.write_json`` for non-blocking I/O.

    Args:
        file_path: Path to the target file. Can be a string or Path object.
        data: Dictionary to serialize to JSON. Must be JSON-serializable.
        indent: Number of spaces for indentation in the output. Default is 2.

    Raises:
        TypeError: If data contains non-serializable types
        OSError: If the file cannot be written
    """
    path = Path(file_path) if isinstance(file_path, str) else file_path
    await write_json(path, data, indent=indent)


def generate_markdown_report(content: str) -> str:
    """
    Generate cleaned markdown report with normalized spacing.

    This function performs lightweight cleanup on markdown content:
    - Trims leading and trailing whitespace
    - Collapses sequences of 3+ newlines into exactly 2 newlines
    - Ensures the content ends with a single newline

    The cleanup improves readability without altering the markdown structure
    or semantic content.

    Args:
        content: Raw markdown content string to clean

    Returns:
        Cleaned markdown string with normalized spacing and trailing newline
    """
    # Normalize spacing (optional cleanup)
    decoded = re.sub(r"\n{3,}", "\n\n", content.strip()) + "\n"
    return decoded
