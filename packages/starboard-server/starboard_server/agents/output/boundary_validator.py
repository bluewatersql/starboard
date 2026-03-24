"""
Boundary validator for agent output.

This module consolidates all LLM output repair logic into a single location.
The validator performs ONE repair pass, then marks the response as partial
if it still doesn't meet the schema requirements.

Key principles:
- Single entry point for all validation/repair
- ONE repair attempt only (no recursive repair)
- Clear logging of what was repaired
- Partial response is valid, not an error

Example:
    >>> validator = BoundaryValidator()
    >>> result = validator.validate_and_repair(raw_output, domain="query")
    >>> if result.is_valid:
    ...     envelope = build_envelope(result.payload)
    >>> elif result.is_partial:
    ...     envelope = build_partial_envelope(result.payload, result.missing_fields)
"""

import json
from dataclasses import dataclass, field
from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.infra.serialization import json_loads

logger = get_logger(__name__)


# Domain to default report type mapping (shared with envelope_translator)
DOMAIN_REPORT_TYPE_MAP: dict[str, str] = {
    "query": "advisor",
    "job": "advisor",
    "uc": "advisor",
    "diagnostic": "advisor",
    "analytics": "analytics",
    "warehouse": "compute",
    "compute": "compute",
}

# Required fields per report type
REQUIRED_FIELDS: dict[str, set[str]] = {
    "advisor": {"summary"},
    "analytics": {"summary"},
    "compute": {"summary"},
}


@dataclass
class ValidationResult:
    """
    Result of validation and repair attempt.

    Attributes:
        is_valid: True if payload meets all requirements
        is_partial: True if payload is usable but incomplete
        payload: The (possibly repaired) payload dict
        repairs_applied: List of repair operations performed
        missing_fields: List of required fields that are missing
        validation_errors: List of validation error messages
    """

    is_valid: bool = False
    is_partial: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    repairs_applied: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


class BoundaryValidator:
    """
    Consolidated validator for agent output boundary.

    This class implements ONE repair pass with the following fixes:
    1. Unwrap OpenAI strict mode {response: {...}}
    2. Unwrap {report: {...}} wrapper
    3. Parse JSON string report/analysis
    4. Move summary from analysis to root
    5. Unwrap double-nested analysis
    6. Infer report_type from domain

    After repair, validates that required fields are present.
    If validation fails, marks response as partial with missing_fields.

    Example:
        >>> validator = BoundaryValidator()
        >>> result = validator.validate_and_repair(raw, domain="query")
        >>> print(f"Valid: {result.is_valid}, Repairs: {result.repairs_applied}")
    """

    def validate_and_repair(
        self,
        raw: dict[str, Any] | list | None,
        domain: str,
    ) -> ValidationResult:
        """
        Validate and repair raw LLM output.

        Performs ONE repair pass, then validates. Does not recurse.

        Args:
            raw: Raw output from LLM (may be None or malformed)
            domain: Agent domain for report_type inference

        Returns:
            ValidationResult with repaired payload and repair log
        """
        result = ValidationResult()

        # Handle None or non-dict input
        if raw is None:
            result.is_partial = True
            result.missing_fields = ["summary"]
            result.payload = {}
            logger.warning(
                "boundary_validation_null_input",
                domain=domain,
            )
            return result

        if not isinstance(raw, dict):
            result.is_partial = True
            result.missing_fields = ["summary"]
            result.payload = {}
            result.validation_errors.append(f"Expected dict, got {type(raw).__name__}")
            logger.warning(
                "boundary_validation_non_dict",
                domain=domain,
                input_type=type(raw).__name__,
            )
            return result

        # Work on a copy to avoid mutating input
        payload = dict(raw)

        # === REPAIR PASS (ONE PASS ONLY) ===

        # 1. Unwrap OpenAI strict mode {response: {...}}
        payload, repair = self._unwrap_response(payload)
        if repair:
            result.repairs_applied.append(repair)

        # 2. Unwrap {report: {...}} wrapper (may be JSON string)
        payload, repair = self._unwrap_report(payload, domain)
        if repair:
            result.repairs_applied.append(repair)

        # 3. Parse JSON string analysis
        payload, repair = self._parse_json_analysis(payload)
        if repair:
            result.repairs_applied.append(repair)

        # 4. Unwrap double-nested analysis {analysis: {analysis: {...}}}
        payload, repair = self._unwrap_double_analysis(payload)
        if repair:
            result.repairs_applied.append(repair)

        # 5. Move summary from analysis to root
        payload, repair = self._move_summary_to_root(payload)
        if repair:
            result.repairs_applied.append(repair)

        # 6. Normalize summary (string -> dict)
        payload, repair = self._normalize_summary(payload)
        if repair:
            result.repairs_applied.append(repair)

        # 7. Infer report_type from domain if missing
        payload, repair = self._infer_report_type(payload, domain)
        if repair:
            result.repairs_applied.append(repair)

        # === VALIDATION ===
        result.payload = payload
        result.missing_fields = self._check_required_fields(payload, domain)

        if not result.missing_fields:
            result.is_valid = True
            result.is_partial = False
        else:
            result.is_valid = False
            result.is_partial = True

        # Log results
        if result.repairs_applied:
            logger.info(
                "boundary_validation_repairs_applied",
                domain=domain,
                repairs=result.repairs_applied,
                is_valid=result.is_valid,
                is_partial=result.is_partial,
            )

        if result.missing_fields:
            logger.warning(
                "boundary_validation_missing_fields",
                domain=domain,
                missing=result.missing_fields,
            )

        return result

    def _unwrap_response(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Unwrap OpenAI strict mode {response: {...}}."""
        if "response" not in payload:
            return payload, None

        response_data = payload.get("response")
        if not isinstance(response_data, dict):
            return payload, None

        # Check if response contains expected report fields
        expected_fields = {"summary", "next_steps", "analysis", "report_type"}
        if expected_fields.intersection(response_data.keys()):
            logger.debug(
                "unwrapping_openai_response",
                found_fields=list(expected_fields.intersection(response_data.keys())),
            )
            return response_data, "unwrap_response"

        return payload, None

    def _unwrap_report(
        self, payload: dict[str, Any], domain: str
    ) -> tuple[dict[str, Any], str | None]:
        """Unwrap {report: {...}} wrapper, handling JSON strings."""
        if "report" not in payload:
            return payload, None

        report_data = payload["report"]
        repair_type = None

        # Case 1: Report is a JSON string
        if isinstance(report_data, str):
            try:
                report_data = json_loads(report_data)
                repair_type = "parse_json_report"
                logger.debug(
                    "parsed_json_string_report",
                    domain=domain,
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "failed_to_parse_json_report",
                    domain=domain,
                    error=str(e),
                )
                return payload, None

        # Case 2: Report is a dict - unwrap it
        if isinstance(report_data, dict):
            expected_fields = {"summary", "analysis", "report_type"}
            if expected_fields.intersection(report_data.keys()):
                # Extract all fields from report to root level
                new_payload = dict(payload)
                del new_payload["report"]

                for key, value in report_data.items():
                    if key not in new_payload:
                        new_payload[key] = value

                return new_payload, repair_type or "unwrap_report"

        return payload, repair_type

    def _parse_json_analysis(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Parse analysis if it's a JSON string."""
        if "analysis" not in payload:
            return payload, None

        analysis = payload.get("analysis")
        if not isinstance(analysis, str):
            return payload, None

        try:
            new_payload = dict(payload)
            new_payload["analysis"] = json_loads(analysis)
            return new_payload, "parse_json_analysis"
        except (json.JSONDecodeError, ValueError):
            return payload, None

    def _unwrap_double_analysis(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Fix {analysis: {analysis: {...}}} double nesting."""
        if "analysis" not in payload:
            return payload, None

        analysis = payload.get("analysis")
        if not isinstance(analysis, dict):
            return payload, None

        if "analysis" not in analysis:
            return payload, None

        inner_analysis = analysis["analysis"]
        if not isinstance(inner_analysis, dict):
            return payload, None

        new_payload = dict(payload)

        # Extract summary and next_steps from outer analysis to root
        if "summary" in analysis and "summary" not in new_payload:
            new_payload["summary"] = analysis["summary"]
        if "next_steps" in analysis and "next_steps" not in new_payload:
            new_payload["next_steps"] = analysis["next_steps"]

        # Use inner analysis
        new_payload["analysis"] = inner_analysis

        return new_payload, "unwrap_double_analysis"

    def _move_summary_to_root(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Move summary from inside analysis to root level."""
        # Only apply if summary is missing at root
        if "summary" in payload:
            return payload, None

        analysis = payload.get("analysis")
        if not isinstance(analysis, dict):
            return payload, None

        if "summary" not in analysis:
            return payload, None

        new_payload = dict(payload)
        new_payload["summary"] = analysis["summary"]

        # Remove summary from analysis
        new_analysis = dict(analysis)
        del new_analysis["summary"]
        new_payload["analysis"] = new_analysis

        return new_payload, "move_summary_to_root"

    def _normalize_summary(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Normalize summary to dict if it's a string."""
        if "summary" not in payload:
            return payload, None

        summary = payload.get("summary")
        if isinstance(summary, dict):
            return payload, None

        if isinstance(summary, str):
            new_payload = dict(payload)
            new_payload["summary"] = {"overview": summary}
            return new_payload, "normalize_summary_string"

        return payload, None

    def _infer_report_type(
        self, payload: dict[str, Any], domain: str
    ) -> tuple[dict[str, Any], str | None]:
        """Infer report_type from domain if missing."""
        if "report_type" in payload:
            return payload, None

        report_type = DOMAIN_REPORT_TYPE_MAP.get(domain, "advisor")
        new_payload = dict(payload)
        new_payload["report_type"] = report_type

        return new_payload, "infer_report_type"

    def _check_required_fields(
        self,
        payload: dict[str, Any],
        domain: str,  # noqa: ARG002
    ) -> list[str]:
        """Check for required fields based on report type."""
        report_type = payload.get("report_type", "advisor")
        required = REQUIRED_FIELDS.get(report_type, {"summary"})

        missing = []
        for field_name in required:
            if field_name not in payload:
                missing.append(field_name)
            elif field_name == "summary":
                # Summary must have overview
                summary = payload.get("summary")
                if not isinstance(summary, dict):
                    missing.append("summary")
                elif "overview" not in summary:
                    missing.append("summary.overview")

        return missing
