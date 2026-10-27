# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SQL identifier validation for safe query construction.

Provides validated, immutable table name types that prevent SQL injection
by ensuring all identifiers conform to Databricks naming rules.
"""

import re
from dataclasses import dataclass

_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_IDENTIFIER_LENGTH = 255

# Databricks SQL warehouse IDs are short alphanumeric tokens. Allowing only
# alphanumerics makes injection through an interpolated warehouse id impossible.
_VALID_WAREHOUSE_ID = re.compile(r"^[A-Za-z0-9]{1,64}$")


@dataclass(frozen=True)
class QualifiedTableName:
    """Validated, immutable three-part Databricks table identifier.

    Ensures each component (catalog, schema, table) is a safe SQL identifier
    that cannot contain injection payloads.

    Args:
        catalog: Catalog name (must match [a-zA-Z_][a-zA-Z0-9_]*)
        schema: Schema name (must match [a-zA-Z_][a-zA-Z0-9_]*)
        table: Table name (must match [a-zA-Z_][a-zA-Z0-9_]*)

    Raises:
        ValueError: If any component is invalid.

    Example:
        >>> name = QualifiedTableName.from_string("main.default.users")
        >>> name.to_sql_identifier()
        '`main`.`default`.`users`'
    """

    catalog: str
    schema: str
    table: str

    def __post_init__(self) -> None:
        for part_name, part_value in [
            ("catalog", self.catalog),
            ("schema", self.schema),
            ("table", self.table),
        ]:
            if not part_value or not _VALID_IDENTIFIER.match(part_value):
                raise ValueError(
                    f"Invalid SQL identifier for {part_name}: {part_value!r}"
                )
            if len(part_value) > _MAX_IDENTIFIER_LENGTH:
                raise ValueError(
                    f"{part_name} identifier exceeds {_MAX_IDENTIFIER_LENGTH} chars"
                )

    @classmethod
    def from_string(cls, full_name: str) -> "QualifiedTableName":
        """Parse a dotted three-part name into a validated QualifiedTableName.

        Args:
            full_name: Dotted name in catalog.schema.table format.

        Returns:
            Validated QualifiedTableName instance.

        Raises:
            ValueError: If format is wrong or any component is invalid.
        """
        parts = full_name.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Expected catalog.schema.table format, got: {full_name!r}"
            )
        return cls(catalog=parts[0], schema=parts[1], table=parts[2])

    def to_sql_identifier(self) -> str:
        """Return backtick-quoted three-part identifier safe for SQL interpolation."""
        return f"`{self.catalog}`.`{self.schema}`.`{self.table}`"

    def to_dotted_name(self) -> str:
        """Return the validated dotted ``catalog.schema.table`` name.

        Use this when the table name is compared as a string literal value
        (e.g. ``source_table_full_name = '<name>'``) rather than referenced as
        a SQL identifier. The components are already validated against
        ``_VALID_IDENTIFIER``, so the result is safe to embed in a string
        literal.
        """
        return f"{self.catalog}.{self.schema}.{self.table}"


def validate_limit(limit: int, max_limit: int = 10000) -> int:
    """Validate a SQL LIMIT parameter.

    Args:
        limit: The limit value to validate.
        max_limit: Maximum allowed limit value.

    Returns:
        The validated limit value.

    Raises:
        ValueError: If limit is not a positive integer within bounds.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an integer, got {type(limit).__name__}")
    if limit < 1:
        raise ValueError(f"limit must be positive, got {limit}")
    if limit > max_limit:
        raise ValueError(f"limit must be at most {max_limit}, got {limit}")
    return limit


def validate_window_days(window_days: int, max_days: int = 3650) -> int:
    """Validate and coerce a day-window value for safe SQL interpolation.

    Databricks SQL cannot bind the day count of an ``INTERVAL <n> DAYS``
    expression as a parameter marker, so the value must be interpolated.
    Coercing to a bounded positive ``int`` guarantees the interpolated text
    is purely numeric and cannot carry an injection payload.

    Args:
        window_days: The look-back window in days. May arrive as a non-int
            (e.g. a numeric string from an external tool call); it is coerced
            via ``int()``.
        max_days: Maximum allowed window (default: 3650 / ~10 years).

    Returns:
        The validated window as a positive ``int``.

    Raises:
        ValueError: If the value cannot be coerced to an int, is not
            positive, or exceeds ``max_days``.
    """
    if isinstance(window_days, bool):
        raise ValueError("window_days must be an integer, got bool")
    try:
        coerced = int(window_days)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"window_days must be an integer, got {window_days!r}"
        ) from exc
    if coerced < 1:
        raise ValueError(f"window_days must be positive, got {coerced}")
    if coerced > max_days:
        raise ValueError(f"window_days must be at most {max_days}, got {coerced}")
    return coerced


def validate_warehouse_id(warehouse_id: str) -> str:
    """Validate a Databricks SQL warehouse identifier for safe interpolation.

    A warehouse id used inside a string-literal filter
    (``compute.warehouse_id = '<id>'``) is not bindable as a SQL parameter
    marker in these system-table queries, so the value is interpolated. A
    warehouse id is an alphanumeric token; rejecting any other character
    (quotes, semicolons, whitespace) makes injection through the id
    impossible.

    Args:
        warehouse_id: The warehouse id to validate.

    Returns:
        The validated warehouse id unchanged.

    Raises:
        ValueError: If the id is empty or contains non-alphanumeric characters.
    """
    if not isinstance(warehouse_id, str) or not _VALID_WAREHOUSE_ID.match(
        warehouse_id
    ):
        raise ValueError(f"Invalid warehouse id: {warehouse_id!r}")
    return warehouse_id
