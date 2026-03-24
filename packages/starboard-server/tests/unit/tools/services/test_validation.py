"""Tests for SQL identifier validation (QualifiedTableName + validate_limit).

Covers:
- Valid three-part names
- Injection attack patterns (backticks, semicolons, quotes, comments)
- Edge cases (empty, too long, wrong format)
- Limit validation
"""

import pytest
from starboard_server.tools.services.validation import (
    QualifiedTableName,
    validate_limit,
)


class TestQualifiedTableName:
    """Tests for QualifiedTableName validation and formatting."""

    # --- Valid names ---

    def test_valid_three_part_name(self) -> None:
        name = QualifiedTableName.from_string("catalog.schema.table")
        assert name.catalog == "catalog"
        assert name.schema == "schema"
        assert name.table == "table"

    def test_valid_name_with_underscores(self) -> None:
        name = QualifiedTableName.from_string("my_catalog.my_schema.my_table")
        assert name.catalog == "my_catalog"

    def test_valid_name_with_numbers(self) -> None:
        name = QualifiedTableName.from_string("catalog1.schema2.table3")
        assert name.table == "table3"

    def test_valid_name_starting_with_underscore(self) -> None:
        name = QualifiedTableName.from_string("_catalog._schema._table")
        assert name.catalog == "_catalog"

    def test_to_sql_identifier(self) -> None:
        name = QualifiedTableName.from_string("main.default.users")
        assert name.to_sql_identifier() == "`main`.`default`.`users`"

    def test_immutable(self) -> None:
        name = QualifiedTableName.from_string("catalog.schema.table")
        with pytest.raises(AttributeError):
            name.catalog = "evil"  # type: ignore[misc]

    # --- Injection attack patterns ---

    def test_rejects_backtick_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog`.`schema`.`table; DROP TABLE --")

    def test_rejects_semicolon_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.table; DROP TABLE users")

    def test_rejects_single_quote_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.table'")

    def test_rejects_double_quote_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string('catalog.schema."table"')

    def test_rejects_comment_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.table--comment")

    def test_rejects_space_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.table name")

    def test_rejects_parenthesis_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.table()")

    def test_rejects_hyphen(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog.schema.my-table")

    # --- Format errors ---

    def test_rejects_two_part_name(self) -> None:
        with pytest.raises(ValueError, match="Expected catalog.schema.table format"):
            QualifiedTableName.from_string("schema.table")

    def test_rejects_one_part_name(self) -> None:
        with pytest.raises(ValueError, match="Expected catalog.schema.table format"):
            QualifiedTableName.from_string("table")

    def test_rejects_four_part_name(self) -> None:
        with pytest.raises(ValueError, match="Expected catalog.schema.table format"):
            QualifiedTableName.from_string("a.b.c.d")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError):
            QualifiedTableName.from_string("")

    def test_rejects_empty_component(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("catalog..table")

    # --- Edge cases ---

    def test_rejects_component_starting_with_number(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName.from_string("1catalog.schema.table")

    def test_rejects_component_exceeding_max_length(self) -> None:
        long_name = "a" * 256
        with pytest.raises(ValueError, match="exceeds 255 chars"):
            QualifiedTableName.from_string(f"catalog.schema.{long_name}")

    def test_accepts_component_at_max_length(self) -> None:
        long_name = "a" * 255
        name = QualifiedTableName.from_string(f"catalog.schema.{long_name}")
        assert len(name.table) == 255

    def test_direct_construction(self) -> None:
        name = QualifiedTableName(catalog="cat", schema="sch", table="tbl")
        assert name.to_sql_identifier() == "`cat`.`sch`.`tbl`"

    def test_direct_construction_rejects_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            QualifiedTableName(catalog="cat;", schema="sch", table="tbl")


class TestValidateLimit:
    """Tests for validate_limit."""

    def test_valid_limit(self) -> None:
        assert validate_limit(10) == 10

    def test_valid_limit_at_max(self) -> None:
        assert validate_limit(10000) == 10000

    def test_valid_limit_min(self) -> None:
        assert validate_limit(1) == 1

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            validate_limit(0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            validate_limit(-1)

    def test_rejects_exceeding_max(self) -> None:
        with pytest.raises(ValueError, match="must be at most"):
            validate_limit(10001)

    def test_rejects_float(self) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            validate_limit(10.5)  # type: ignore[arg-type]

    def test_rejects_string(self) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            validate_limit("10")  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            validate_limit(True)  # type: ignore[arg-type]

    def test_custom_max_limit(self) -> None:
        assert validate_limit(50, max_limit=100) == 50
        with pytest.raises(ValueError, match="must be at most"):
            validate_limit(101, max_limit=100)
