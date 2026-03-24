"""SQL identifier validation for safe query construction.

Provides validated, immutable table name types that prevent SQL injection
by ensuring all identifiers conform to Databricks naming rules.
"""

import re
from dataclasses import dataclass

_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_MAX_IDENTIFIER_LENGTH = 255


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
