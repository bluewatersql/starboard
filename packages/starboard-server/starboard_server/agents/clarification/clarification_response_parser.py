"""
Clarification response parser for multi-agent routing.

Parses user responses to clarification prompts, detecting numeric choices
(1-5) or keyword matches (sql, job, uc/catalog/lineage, cluster, debug).

Follows Python AI Agent Engineering Standards:
- Single responsibility (response parsing only)
- Pure logic (stateless, deterministic)
- Explicit configuration
- Type hints on all functions
"""

from __future__ import annotations

from starboard_server.agents.clarification.clarification_handler import DomainOption


class ClarificationResponseParser:
    """
    Parses user responses to clarification prompts.

    Supports two input formats:
    1. Numeric choice (1-5) matching the numbered options
    2. Keyword match (sql, job, uc/catalog/lineage, cluster, troubleshoot, etc.)

    Design:
    - Stateless (no instance state beyond configuration)
    - Pure functions (deterministic output for given input)
    - Reuses DomainOption from ClarificationHandler
    - Filters disabled domains automatically

    Example:
        ```python
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["compute"],
        )

        # Parse numeric choice
        domain = parser.parse("2")  # Returns "job"

        # Parse keyword
        domain = parser.parse("I need help with SQL")  # Returns "query"

        # Invalid/unclear response
        domain = parser.parse("hello")  # Returns None
        ```
    """

    # Keyword to domain mapping for flexible parsing
    KEYWORD_MAPPING = {
        "query": "query",
        "sql": "query",
        "statement": "query",
        "job": "job",
        "databricks job": "job",
        "workflow": "job",
        "table": "uc",
        "metadata": "uc",
        "lineage": "uc",
        "schema": "uc",
        "catalog": "uc",
        "unity catalog": "uc",
        "governance": "uc",
        "grant": "uc",
        "permission": "uc",
        "cluster": "cluster",
        "autoscaling": "cluster",
        "spark config": "cluster",
        "warehouse": "warehouse",
        "sql warehouse": "warehouse",
        "diagnostic": "diagnostic",
        "troubleshoot": "diagnostic",
        "debug": "diagnostic",
        "error": "diagnostic",
        "issue": "diagnostic",
    }

    def __init__(
        self,
        domain_options: list[DomainOption],
        disabled_domains: list[str] | None = None,
    ) -> None:
        """
        Initialize clarification response parser.

        Args:
            domain_options: Available domain options (must match order in clarification prompt)
            disabled_domains: List of domain keys to exclude from parsing
        """
        self.domain_options = domain_options
        self.disabled_domains = set(disabled_domains or [])

        # Build filtered options list (enabled only)
        self._enabled_options = [
            opt.domain_key
            for opt in domain_options
            if opt.domain_key not in self.disabled_domains
        ]

    def parse(self, user_response: str) -> str | None:
        """
        Parse user response to clarification prompt.

        Tries to detect:
        1. Numeric choice (1-N where N is number of enabled options)
        2. Keyword match (sql, job, uc/catalog/lineage, cluster, troubleshoot, etc.)

        Args:
            user_response: User's input message

        Returns:
            Domain key (query, job, uc, compute, diagnostic) if parsed successfully,
            None if response is unclear or doesn't match any option

        Example:
            >>> parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)
            >>> parser.parse("1")
            'query'
            >>> parser.parse("help with sql")
            'query'
            >>> parser.parse("3")
            'uc'
            >>> parser.parse("troubleshoot issue")
            'diagnostic'
            >>> parser.parse("hello")
            None
        """
        user_input_lower = user_response.strip().lower()

        # Try to parse as numeric choice (1-N)
        if user_input_lower.isdigit():
            choice_num = int(user_input_lower)
            if 1 <= choice_num <= len(self._enabled_options):
                return self._enabled_options[choice_num - 1]

        # Try to match keywords
        for keyword, domain in self.KEYWORD_MAPPING.items():
            if keyword in user_input_lower and domain in self._enabled_options:
                return domain

        # Could not parse - caller should handle as normal query
        return None

    def is_valid_numeric_choice(self, choice: str) -> bool:
        """
        Check if string is a valid numeric choice.

        Args:
            choice: Input string to validate

        Returns:
            True if valid numeric choice (1-N), False otherwise
        """
        if not choice.isdigit():
            return False

        choice_num = int(choice)
        return 1 <= choice_num <= len(self._enabled_options)

    def get_enabled_domain_count(self) -> int:
        """
        Get count of enabled domain options.

        Returns:
            Number of enabled (non-disabled) domain options
        """
        return len(self._enabled_options)

    def get_domain_for_number(self, choice_num: int) -> str | None:
        """
        Get domain key for a numeric choice.

        Args:
            choice_num: Numeric choice (1-based indexing)

        Returns:
            Domain key if valid choice, None otherwise

        Example:
            >>> parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)
            >>> parser.get_domain_for_number(1)
            'query'
            >>> parser.get_domain_for_number(99)
            None
        """
        if 1 <= choice_num <= len(self._enabled_options):
            return self._enabled_options[choice_num - 1]
        return None
