import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import sqlglot
from sqlglot import expressions as exp
from sqlglot.errors import ParseError

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class DateTimeUtils:
    @classmethod
    def last_n_days_epoch_ms(cls, n_days: int, tz: str = "UTC") -> tuple[int, int]:
        """
        Compute [start_ms, end_ms] epoch-millisecond boundaries for the last `n_days`.
        The end boundary is 'now' in the requested timezone.

        Args:
            n_days: Number of days to look back.
            tz: IANA timezone string (e.g., "America/New_York"). Defaults to UTC.

        Returns:
            (start_ms, end_ms) as integers.
        """
        if n_days <= 0:
            raise ValueError("n_days must be >= 1")

        zone = UTC if tz.upper() == "UTC" else ZoneInfo(tz)
        now = datetime.now(zone)
        start = now - timedelta(days=n_days)

        # Convert to epoch ms (timestamp() converts to UTC under the hood for aware datetimes)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        return start_ms, end_ms


class StringUtils:
    __UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )

    @classmethod
    def extract_uuids(cls, text: str, unique: bool = True) -> list[str]:
        """
        Extract UUIDs from a string.

        Args:
            text: String to extract UUIDs from
            unique: Whether to return unique UUIDs only

        Returns:
            List of UUIDs
        """
        matches = cls.__UUID_RE.findall(text)
        if unique:
            return list(set(matches))
        return matches


class SQLUtils:
    DEFAULT_DIALECT = "databricks"
    Category = Literal["DML", "DDL", "DCL", "TCL", "UTILITY", "UNKNOWN", "INVALID"]
    Access = Literal["READ", "WRITE", "READ_WRITE", "NONE", "UNKNOWN"]

    @classmethod
    def is_valid_sql(cls, sql: str, dialect: str = DEFAULT_DIALECT) -> bool:
        """
        Check if a SQL statement is valid.

        Args:
            sql: SQL statement
            dialect: SQL dialect

        Returns:
            True if the SQL statement is valid, False otherwise
        """
        try:
            # parse can handle multiple statements; parse_one for a single statement
            result = cls.classify_sql(sql, dialect=dialect)

            return result.get("category", "UNKNOWN") != "UNKNOWN"

        except ParseError:
            return False

    @classmethod
    def _access_for(cls, expr: exp.Expression) -> Access:
        """
        Determine the access type for a SQL expression.

        Args:
            expr: SQL expression

        Returns:
            Access type
        """
        # Data access intent
        if isinstance(expr, (exp.Select, exp.Show, exp.Describe)):
            return "READ"
        if isinstance(expr, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Copy)):
            # MERGE is both, but in practice it's write-heavy; mark READ_WRITE to be precise
            return "READ_WRITE" if isinstance(expr, exp.Merge) else "WRITE"
        if isinstance(expr, exp.Analyze):
            return "WRITE"
        if isinstance(expr, (exp.Create, exp.Drop, exp.Alter)):
            return "NONE"
        if isinstance(
            expr,
            (
                exp.Grant,
                exp.Revoke,
                exp.Commit,
                exp.Rollback,
                exp.Use,
                exp.Set,
            ),
        ):
            return "NONE"

        # Handle Command types (SHOW TABLES, DESCRIBE, EXPLAIN, etc.)
        if isinstance(expr, exp.Command):
            # Check if it's a read-only command by examining the command name
            sql_text = expr.sql().upper()
            if any(keyword in sql_text for keyword in ["SHOW", "DESCRIBE", "EXPLAIN"]):
                return "READ"
            # Other commands (like TRUNCATE, VACUUM, etc.) are considered writes
            return "WRITE"

        return "UNKNOWN"

    @classmethod
    def _category_for(cls, expr: exp.Expression) -> Category:
        """
        Determine the category for a SQL expression.

        Args:
            expr: SQL expression

        Returns:
            Category
        """
        # High-level SQL family
        if isinstance(
            expr, (exp.Select, exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Copy)
        ):
            return "DML"
        if isinstance(expr, (exp.Create, exp.Drop, exp.Alter, exp.Analyze)):
            return "DDL"
        if isinstance(expr, (exp.Grant, exp.Revoke)):
            return "DCL"
        if isinstance(expr, (exp.Commit, exp.Rollback)):
            return "TCL"
        if isinstance(expr, (exp.Show, exp.Describe, exp.Use, exp.Set, exp.Command)):
            # Command covers engine-specific utilities like REFRESH, MSCK, EXPLAIN, TRUNCATE, OPTIMIZE, VACUUM, BEGIN, etc.
            return "UTILITY"
        return "UNKNOWN"

    @classmethod
    def _root(cls, expr: exp.Expression) -> exp.Expression:
        """
        Determine the root expression for a SQL expression.

        Args:
            expr: SQL expression

        Returns:
            Root expression
        """
        # EXPLAIN is parsed as Command by sqlglot, so no special unwrapping needed
        return expr

    @classmethod
    def classify_sql(cls, sql: str, dialect: str = DEFAULT_DIALECT) -> dict[str, str]:
        """
        Classify a single SQL statement.

        Args:
            sql: SQL statement
            dialect: SQL dialect

        Returns:
            Dictionary with: kind (e.g., SELECT/INSERT/MERGE/...), category (DML/DDL/...), access (READ/WRITE/...).
        """
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
        except ParseError:
            return {"kind": "INVALID", "category": "INVALID", "access": "UNKNOWN"}

        core = cls._root(tree)

        # Kind name
        kind = (
            tree.key.upper()
            if hasattr(tree, "key")
            else tree.__class__.__name__.upper()
        )

        return {
            "kind": kind,  # "SELECT", "INSERT", "MERGE", "CREATE", "EXPLAIN SELECT", ...
            "category": cls._category_for(
                core
            ),  # DML / DDL / DCL / TCL / UTILITY / UNKNOWN
            "access": cls._access_for(
                core
            ),  # READ / WRITE / READ_WRITE / NONE / UNKNOWN
        }

    @classmethod
    def classify_sql_batch(
        cls, sql: str, dialect: str = DEFAULT_DIALECT
    ) -> list[dict[str, str]]:
        """
        Classify 1..N statements in a string. Returns a list of classifications in order.

        Args:
            sql: SQL statements
            dialect: SQL dialect

        Returns:
            List of dictionaries with: kind (e.g., SELECT/INSERT/MERGE/...), category (DML/DDL/...), access (READ/WRITE/...).
        """
        try:
            trees = sqlglot.parse(sql, read=dialect)
        except ParseError:
            return [{"kind": "INVALID", "category": "INVALID", "access": "UNKNOWN"}]

        out: list[dict[str, str]] = []
        for t in trees:
            if t is None:
                continue
            core = cls._root(t)
            kind = t.key.upper() if hasattr(t, "key") else t.__class__.__name__.upper()
            out.append(
                {
                    "kind": kind,
                    "category": cls._category_for(core),
                    "access": cls._access_for(core),
                }
            )
        return out

    @classmethod
    def is_read_only_sql(cls, sql: str, dialect: str = DEFAULT_DIALECT) -> bool:
        """
        Determine if the given SQL statement is read-only.

        Returns True if the statement only reads data (e.g. SELECT, SHOW, DESCRIBE, EXPLAIN SELECT),
        and False if it performs or may perform writes (INSERT/UPDATE/DELETE/MERGE/DDL/...).

        Args:
            sql: SQL statement
            dialect: SQL dialect

        Returns:
            True if the statement is read-only, False otherwise
        """
        info = cls.classify_sql(sql, dialect=dialect)
        return info.get("access") == "READ"

    @classmethod
    def parse_sql_command(cls, sql: str) -> tuple[str | None, str | None]:
        try:
            sql_expression = sqlglot.parse_one(sql, read=cls.DEFAULT_DIALECT)
            sql_type = type(sql_expression).__name__.upper()

            if sql_type == "COMMAND":
                return sql_expression.this, sql_expression.expression.name
            else:
                tables = list(sql_expression.find_all(exp.Table))

            if tables:
                return sql_type, tables[0].name
        except ParseError as e:
            logger.debug("sql_parse_error", sql=sql, error=str(e))

        return None, None
