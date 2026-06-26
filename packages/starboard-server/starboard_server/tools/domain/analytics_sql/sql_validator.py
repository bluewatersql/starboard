# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Analytics SQL - SQL Validator.

Validates SQL queries using two gates:
- Gate 1: SQLglot syntax validation (always)
- Gate 2: EXPLAIN plan validation (runtime/schema validation)

Ensures queries are read-only and free from injection risks.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp, serde
from sqlglot.optimizer.canonicalize import canonicalize
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from starboard_server.exceptions import AdapterError, QueryExecutionError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.analytics_sql.models import ValidationResult

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncSQLExecutor

logger = get_logger(__name__)


# =============================================================================
# Databricks Error Pattern Definitions
# =============================================================================


@dataclass(frozen=True)
class ErrorPattern:
    """Databricks error pattern definition."""

    code: str
    sqlstate: str
    category: str
    severity: str
    regex_pattern: str | None
    reflexion_hint: str


# Known Databricks EXPLAIN error patterns (ordered by frequency/priority)
DATABRICKS_ERROR_PATTERNS: dict[str, ErrorPattern] = {
    "UNRESOLVED_COLUMN.WITH_SUGGESTION": ErrorPattern(
        code="UNRESOLVED_COLUMN.WITH_SUGGESTION",
        sqlstate="42703",
        category="column_resolution",
        severity="high",
        regex_pattern=r"with name `([^`]+)` cannot be resolved.*Did you mean one of the following\? \[([^\]]+)\]",
        reflexion_hint="Use one of the suggested column names",
    ),
    "UNRESOLVED_COLUMN": ErrorPattern(
        code="UNRESOLVED_COLUMN",
        sqlstate="42703",
        category="column_resolution",
        severity="high",
        regex_pattern=r"cannot resolve ['\"`]([^'\"` ]+)['\"`]",
        reflexion_hint="Search codebook/tables for correct column name",
    ),
    "AMBIGUOUS_REFERENCE": ErrorPattern(
        code="AMBIGUOUS_REFERENCE",
        sqlstate="42702",
        category="column_resolution",
        severity="high",
        regex_pattern=r"Column ['\"`]([^'\"` ]+)['\"`] is ambiguous",
        reflexion_hint="Add table alias prefix (e.g., table_alias.column_name)",
    ),
    "TABLE_OR_VIEW_NOT_FOUND": ErrorPattern(
        code="TABLE_OR_VIEW_NOT_FOUND",
        sqlstate="42P01",
        category="object_resolution",
        severity="high",
        regex_pattern=r"Table ['\"`]?([^'\"` ]+)['\"`]? (not found|does not exist)",
        reflexion_hint="Verify fully qualified table name (catalog.schema.table)",
    ),
    "PARSE_SYNTAX_ERROR": ErrorPattern(
        code="PARSE_SYNTAX_ERROR",
        sqlstate="42601",
        category="syntax",
        severity="high",
        regex_pattern=r"Syntax error at or near",
        reflexion_hint="Fix SQL syntax near indicated position",
    ),
    "PERMISSION_DENIED": ErrorPattern(
        code="PERMISSION_DENIED",
        sqlstate="42501",
        category="access_control",
        severity="critical",
        regex_pattern=r"(PERMISSION_DENIED|permission denied|not authorized|insufficient privileges)",
        reflexion_hint="Cannot fix - missing database permissions",
    ),
    "DATATYPE_MISMATCH": ErrorPattern(
        code="DATATYPE_MISMATCH",
        sqlstate="42804",
        category="type_compatibility",
        severity="medium",
        regex_pattern=r"Cannot (compare|cast|convert) (\w+) (to|with) (\w+)",
        reflexion_hint="Add explicit CAST() to convert data types",
    ),
    "INVALID_PARAMETER_VALUE": ErrorPattern(
        code="INVALID_PARAMETER_VALUE",
        sqlstate="22023",
        category="function_args",
        severity="medium",
        regex_pattern=r"Invalid (parameter|argument) value",
        reflexion_hint="Check function documentation for valid parameter values",
    ),
    "DIVIDE_BY_ZERO": ErrorPattern(
        code="DIVIDE_BY_ZERO",
        sqlstate="22012",
        category="arithmetic",
        severity="medium",
        regex_pattern=r"(Division by zero|divide by zero)",
        reflexion_hint="Use NULLIF(divisor, 0) or add WHERE clause to filter zeros",
    ),
    "UNSUPPORTED_FEATURE": ErrorPattern(
        code="UNSUPPORTED_FEATURE",
        sqlstate="0A000",
        category="feature_support",
        severity="medium",
        regex_pattern=r"(not supported|is not supported|unsupported)",
        reflexion_hint="Use alternative SQL pattern supported by Databricks",
    ),
    "INVALID_SCHEMA_OR_CATALOG": ErrorPattern(
        code="INVALID_SCHEMA_OR_CATALOG",
        sqlstate="3F000",
        category="object_resolution",
        severity="high",
        regex_pattern=r"(Schema|Catalog) ['\"`]?(\w+)['\"`]? (not found|does not exist)",
        reflexion_hint="Verify catalog and schema names are correct",
    ),
}


@dataclass
class ParsedError:
    """Parsed error components from EXPLAIN output."""

    error_code: str | None  # e.g., "UNRESOLVED_COLUMN.WITH_SUGGESTION"
    error_message: str  # Full error message (without query plan)
    sqlstate: str | None  # e.g., "42703"
    line: int | None  # Line number where error occurred
    position: int | None  # Column position where error occurred
    suggestions: list[str]  # Suggested fixes (if available)
    matched_pattern: ErrorPattern | None  # Matched error pattern (if known)


class SQLValidator:
    """Validates SQL queries using two-gate validation.

    Gate 1: SQLglot syntax validation (always)
    - Syntax correctness (can SQL be parsed?)
    - Safety (no DROP, DELETE, UPDATE, INSERT, etc.)
    - Read-only (only SELECT statements)
    - Single statement (no multiple statements separated by ;)

    Gate 2: EXPLAIN plan validation (optional, requires SQL executor)
    - Runtime validation via EXPLAIN on Databricks
    - Verifies columns and tables exist
    - Checks for optimization opportunities

    Example:
        >>> validator = SQLValidator(sql_executor=executor)
        >>> result = await validator.validate("SELECT * FROM table")
        >>> result.is_valid
        True
    """

    # Dangerous SQL statement types (not allowed)
    DANGEROUS_STATEMENTS = {
        exp.Drop,
        exp.Delete,
        exp.Update,
        exp.Insert,
        exp.Merge,
        exp.Create,
        exp.Alter,
    }

    SQL_DIALECT: str = "databricks"

    def __init__(self, sql_executor: AsyncSQLExecutor | None = None):
        """Initialize SQL validator.

        Args:
            sql_executor: Optional SQL executor for EXPLAIN validation (Gate 2)
                         If None, only Gate 1 (syntax) validation is performed.
        """
        self.sql_executor = sql_executor

    async def validate(
        self, sql: str, runtime_validation: bool = False
    ) -> ValidationResult:
        """Validate SQL query using two-gate validation.

        Gate 1: SQLglot syntax validation (always)
        Gate 2: EXPLAIN plan validation (if sql_executor provided)

        Args:
            sql: SQL query string to validate
            runtime_validation: Whether to perform runtime validation (Gate 2)
            If True, will perform runtime validation using EXPLAIN.
            If False, will only perform syntax validation (Gate 1).

        Returns:
            ValidationResult with validation status and details

        Example:
            >>> validator = SQLValidator(sql_executor=executor)
            >>> result = await validator.validate("SELECT warehouse_id FROM system.billing.usage")
            >>> result.is_valid
            True
            >>> result.validation_method
            'sqlglot+explain'
        """
        # GATE 1: SQLglot syntax validation
        syntax_result = self._validate_syntax(sql)

        if not syntax_result.is_valid:
            logger.debug("syntax_validation_failed")
            return syntax_result

        # GATE 2: EXPLAIN plan validation (if executor provided)
        if self.sql_executor and runtime_validation:
            explain_result = await self._validate_explain(sql)

            if not explain_result.is_valid:
                logger.debug("explain_validation_failed")
                # Merge warnings from both gates
                all_warnings = syntax_result.warnings + explain_result.warnings
                return ValidationResult(
                    is_valid=False,
                    errors=explain_result.errors,
                    warnings=all_warnings,
                    validation_method="sqlglot+explain",
                )

            # Both gates passed
            all_warnings = syntax_result.warnings + explain_result.warnings
            logger.debug("explain_validation_passed")

            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=all_warnings,
                validation_method="sqlglot+explain",
            )
        else:
            logger.debug(
                "explain_validation_skipped",
                extra={
                    "runtime_validation": runtime_validation,
                    "sql_preview": sql[:100],
                },
            )

        # Only syntax validation performed
        return syntax_result

    @staticmethod
    def generate_sql_cache_key(sql: str) -> str:
        """
        Deterministic cache key for a SQL statement.

        Notes:
        - Includes sqlglot version in the key so upgrades don't create accidental collisions
        if normalization/canonicalization behavior changes.
        - Uses serde.dump + json.dumps(sort_keys=True) for stable serialization.
        """

        # Normalize identifiers (case/casing semantics) and canonicalize structure
        tree = sqlglot.parse_one(sql, read="databricks")
        tree = normalize_identifiers(tree, dialect="databricks")
        tree = canonicalize(tree, dialect="databricks")

        payload = serde.dump(tree)
        stable = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()

        # Make cache invalidation safe across versions
        return f"v1|{digest}"

    def _validate_syntax(self, sql: str) -> ValidationResult:
        warnings: list[str] = []

        # Check for empty SQL
        if not sql or not sql.strip():
            return ValidationResult(
                is_valid=False,
                errors=["SQL query cannot be empty"],
                warnings=[],
                validation_method="sqlglot",
            )

        sql = sql.strip()

        # Check for multiple statements (semicolon-separated)
        if self._contains_multiple_statements(sql):
            return ValidationResult(
                is_valid=False,
                errors=[
                    "Multiple SQL statements not allowed. Only single SELECT queries are permitted."
                ],
                warnings=[],
                validation_method="sqlglot",
            )

        # Try to parse SQL
        try:
            parsed = sqlglot.parse_one(sql, read=self.SQL_DIALECT)
        except sqlglot.ParseError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"SQL syntax error: {str(e)}"],
                warnings=[],
                validation_method="sqlglot",
            )

        # Check if parsed result is None (comment-only SQL)
        if parsed is None:
            return ValidationResult(
                is_valid=False,
                errors=["SQL contains no valid statement"],
                warnings=[],
                validation_method="sqlglot",
            )

        # Check for dangerous statements
        dangerous_check = self._check_dangerous_statements(parsed)
        if dangerous_check:
            return ValidationResult(
                is_valid=False,
                errors=[dangerous_check],
                warnings=[],
                validation_method="sqlglot",
            )

        # Check that it's a SELECT statement
        if not isinstance(parsed, exp.Select):
            return ValidationResult(
                is_valid=False,
                errors=[
                    "Only SELECT queries are allowed. Other statement types are not permitted."
                ],
                warnings=[],
                validation_method="sqlglot",
            )

        # Validation passed
        return ValidationResult(
            is_valid=True,
            errors=[],
            warnings=warnings,
            validation_method="sqlglot",
        )

    async def _validate_explain(self, sql: str) -> ValidationResult:
        """Validate SQL using EXPLAIN plan (Gate 2).

        Runs EXPLAIN on Databricks to verify:
        - Columns exist
        - Tables exist
        - Query can be optimized
        - Runtime errors

        Args:
            sql: SQL query to validate

        Returns:
            ValidationResult with EXPLAIN validation results
        """
        if not self.sql_executor:
            # Should not happen (caller checks), but be safe
            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=["EXPLAIN validation skipped - no SQL executor"],
                validation_method="explain_skipped",
            )

        explain_sql = f"EXPLAIN {sql}"

        try:
            # Execute EXPLAIN (should be fast, doesn't run actual query)
            logger.debug(
                "explain_validation_starting", extra={"sql_preview": sql[:100]}
            )

            df = await self.sql_executor.execute_sql(
                sql=explain_sql,
                use_cache=False,  # Don't cache EXPLAIN results
            )

            # Check if EXPLAIN output contains error text
            if hasattr(df, "to_dicts"):
                rows = df.to_dicts()
                for row in rows:
                    for val in row.values():
                        if (
                            isinstance(val, str)
                            and "error occurred during query planning:" in val.lower()
                        ):
                            formatted_error = self._format_explain_error(val)
                            raise RuntimeError(formatted_error)

            # EXPLAIN succeeded - query is valid
            logger.debug("explain_validation_passed")

            return ValidationResult(
                is_valid=True,
                errors=[],
                warnings=[],
                validation_method="explain",
            )

        except (QueryExecutionError, AdapterError) as e:
            # EXPLAIN failed - capture error for reflexion
            error_msg = str(e)

            logger.warning(
                "explain_validation_failed",
                extra={
                    "error": error_msg,
                    "error_type": type(e).__name__,
                    "sql_preview": sql[:100],
                },
            )

            return ValidationResult(
                is_valid=False,
                errors=[self._format_explain_error(error_msg)],
                warnings=[],
                validation_method="explain",
            )

    def _format_explain_error(self, error_msg: str) -> str:
        """Format EXPLAIN error message for agent reflexion.

        Args:
            error_msg: Error message from EXPLAIN

        Returns:
            Formatted error message with actionable guidance
        """
        if (
            isinstance(error_msg, str)
            and "error occurred during query planning:" in error_msg.lower()
        ):
            # Parse error message and raise with clean error text
            parsed_error = self._parse_explain_error(error_msg)
            return self._format_validation_error(parsed_error)
        else:
            return error_msg

    def _contains_multiple_statements(self, sql: str) -> bool:
        """Check if SQL contains multiple statements (separated by semicolons).

        Args:
            sql: SQL string to check

        Returns:
            True if multiple statements detected
        """
        # Remove string literals to avoid false positives from semicolons in strings
        sql_without_strings = self._remove_string_literals(sql)

        # Check for semicolons (excluding trailing semicolon)
        sql_stripped = sql_without_strings.rstrip().rstrip(";")
        return ";" in sql_stripped

    def _remove_string_literals(self, sql: str) -> str:
        """Remove string literals from SQL to avoid false positives.

        Args:
            sql: SQL string

        Returns:
            SQL with string literals replaced by empty strings
        """

        # Remove single-quoted strings
        sql = re.sub(r"'[^']*'", "''", sql)
        # Remove double-quoted strings
        sql = re.sub(r'"[^"]*"', '""', sql)

        return sql

    def _check_dangerous_statements(self, parsed: exp.Expression) -> str | None:
        """Check if parsed SQL contains dangerous statements.

        Args:
            parsed: Parsed SQL expression

        Returns:
            Error message if dangerous statement found, None otherwise
        """
        # Check the top-level statement
        for dangerous_type in self.DANGEROUS_STATEMENTS:
            if isinstance(parsed, dangerous_type):
                stmt_name = dangerous_type.__name__.upper()
                return f"{stmt_name} statements are not allowed. Only read-only SELECT queries are permitted."

        # Recursively check all child nodes
        for node in parsed.walk():
            for dangerous_type in self.DANGEROUS_STATEMENTS:
                if isinstance(node, dangerous_type):
                    stmt_name = dangerous_type.__name__.upper()
                    return f"{stmt_name} statements are not allowed. Only read-only SELECT queries are permitted."

        return None

    def _parse_explain_error(self, explain_output: str) -> ParsedError:
        """Parse error message from EXPLAIN output.

        EXPLAIN errors follow this format:
        ```
        Error occurred during query planning:
        [ERROR_CODE{.SUBTYPE}] Error message. {Optional: Did you mean...?}. SQLSTATE: 12345; line X pos Y;
        'QueryPlanTree
        +- ...
        ```

        Args:
            explain_output: Full EXPLAIN output text with embedded error

        Returns:
            ParsedError with structured error components
        """
        # Split at the query plan tree marker (lines starting with ', +-, or :-)
        lines = explain_output.split("\n")

        error_lines = []
        for output_line in lines:
            # Stop when we hit the query plan tree
            stripped = output_line.strip()
            if (
                stripped.startswith("'")
                or stripped.startswith("+-")
                or stripped.startswith(":-")
            ):
                break
            error_lines.append(output_line)

        # Join error lines and clean up
        error_text = "\n".join(error_lines).strip()

        # Remove the "Error occurred during query planning:" prefix
        if error_text.startswith("Error occurred during query planning:"):
            error_text = error_text.replace(
                "Error occurred during query planning:", ""
            ).strip()

        # Extract error code (e.g., [UNRESOLVED_COLUMN.WITH_SUGGESTION])
        error_code_match = re.search(r"\[([^\]]+)\]", error_text)
        error_code = error_code_match.group(1) if error_code_match else None

        # Extract SQLSTATE (e.g., SQLSTATE: 42703)
        sqlstate_match = re.search(r"SQLSTATE:\s*(\w+)", error_text)
        sqlstate = sqlstate_match.group(1) if sqlstate_match else None

        # Extract line and position (e.g., line 8 pos 25)
        line_match = re.search(r"line\s+(\d+)", error_text)
        pos_match = re.search(r"pos\s+(\d+)", error_text)
        error_line: int | None = int(line_match.group(1)) if line_match else None
        position: int | None = int(pos_match.group(1)) if pos_match else None

        # Extract suggestions (e.g., Did you mean one of the following? [`col1`, `col2`])
        suggestions = []
        suggestions_match = re.search(
            r"Did you mean one of the following\? \[([^\]]+)\]", error_text
        )
        if suggestions_match:
            suggestions_text = suggestions_match.group(1)
            # Split by comma and clean up
            suggestions = [s.strip().strip("`'\"") for s in suggestions_text.split(",")]

        # Match against known error patterns
        matched_pattern = None
        if error_code:
            # Try exact match first
            matched_pattern = DATABRICKS_ERROR_PATTERNS.get(error_code)

            # Try base code without subtype (e.g., UNRESOLVED_COLUMN from UNRESOLVED_COLUMN.WITH_SUGGESTION)
            if not matched_pattern and "." in error_code:
                base_code = error_code.split(".")[0]
                matched_pattern = DATABRICKS_ERROR_PATTERNS.get(base_code)

        # If no direct match, try regex patterns
        if not matched_pattern:
            for pattern_def in DATABRICKS_ERROR_PATTERNS.values():
                if pattern_def.regex_pattern and re.search(
                    pattern_def.regex_pattern, error_text, re.IGNORECASE
                ):
                    matched_pattern = pattern_def
                    break

        return ParsedError(
            error_code=error_code,
            error_message=error_text,
            sqlstate=sqlstate,
            line=error_line,
            position=position,
            suggestions=suggestions,
            matched_pattern=matched_pattern,
        )

    def _format_validation_error(self, parsed_error: ParsedError) -> str:
        """Format validation error message for agent reflexion.

        Converts parsed error into actionable feedback with reflexion hints.

        Args:
            parsed_error: Parsed error components

        Returns:
            Formatted error message with actionable guidance
        """
        # Build location string
        location_parts = []
        if parsed_error.line:
            location_parts.append(f"line {parsed_error.line}")
        if parsed_error.position:
            location_parts.append(f"position {parsed_error.position}")
        location_str = f" at {' '.join(location_parts)}" if location_parts else ""

        # Handle known error patterns with typed formatting
        if parsed_error.matched_pattern:
            pattern = parsed_error.matched_pattern
            category = pattern.category

            if category == "column_resolution":
                # Extract column name
                column_match = re.search(
                    r"with name `([^`]+)` cannot be resolved",
                    parsed_error.error_message,
                )
                if not column_match:
                    column_match = re.search(
                        r"cannot resolve ['\"`]([^'\"` ]+)['\"`]",
                        parsed_error.error_message,
                    )
                column_name = column_match.group(1) if column_match else "unknown"

                # Build message with suggestions if available
                if parsed_error.suggestions:
                    suggestions_str = ", ".join(parsed_error.suggestions)
                    return (
                        f"Column '{column_name}' not found{location_str}. "
                        f"Available alternatives: {suggestions_str}. "
                        f"Hint: {pattern.reflexion_hint}"
                    )
                else:
                    return (
                        f"Column '{column_name}' not found{location_str}. "
                        f"Hint: {pattern.reflexion_hint}"
                    )

            elif category == "object_resolution":
                # Extract table/catalog/schema name
                object_match = re.search(
                    r"(Table|Schema|Catalog) ['\"`]?([^'\"` ]+)['\"`]?",
                    parsed_error.error_message,
                )
                if object_match:
                    object_type = object_match.group(1)
                    object_name = object_match.group(2)
                    return (
                        f"{object_type} '{object_name}' not found{location_str}. "
                        f"Hint: {pattern.reflexion_hint}"
                    )

            elif category == "access_control":
                # Permission errors cannot be fixed by agent
                return (
                    f"Permission denied{location_str}. "
                    f"This cannot be fixed through SQL changes. "
                    f"User lacks database permissions for this operation."
                )

            elif category == "type_compatibility":
                # Extract type mismatch details
                type_match = re.search(
                    r"Cannot (compare|cast|convert) (\w+) (to|with) (\w+)",
                    parsed_error.error_message,
                )
                if type_match:
                    operation = type_match.group(1)
                    type1 = type_match.group(2)
                    type2 = type_match.group(4)
                    return (
                        f"Type mismatch: cannot {operation} {type1} with {type2}{location_str}. "
                        f"Hint: {pattern.reflexion_hint}"
                    )

            elif category == "syntax":
                return f"SQL syntax error{location_str}. Hint: {pattern.reflexion_hint}"

            # Generic formatted message for other known patterns
            return (
                f"{pattern.code} error{location_str}: {parsed_error.error_message}. "
                f"Hint: {pattern.reflexion_hint}"
            )

        # Unknown error type - return full error message with metadata
        error_type = parsed_error.error_code or "UNKNOWN_ERROR"
        logger.warning(
            "unknown_explain_error_type",
            extra={
                "error_code": error_type,
                "sqlstate": parsed_error.sqlstate,
                "error_message_preview": parsed_error.error_message[:200],
            },
        )

        return (
            f"Query validation failed ({error_type}){location_str}: "
            f"{parsed_error.error_message}"
        )
