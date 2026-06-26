# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Option selection processor service.

Processes user input to determine if they're selecting a numbered option
or entering free text. Part of Pattern 1: Option Selection.

This service implements multiple matching strategies:
1. Exact numeric match (e.g., "2")
2. Word form match (e.g., "two")
3. Keyword-based match (e.g., "option 2", "choice 3")
4. Semantic matching (optional, requires embedding client)

Examples:
    >>> processor = OptionSelectionProcessor(embedding_client=None)
    >>> result = await processor.process("2", available_options)
    >>> result.selection_type
    'option'
    >>> result.selected_option.number
    2
    >>> result.confidence
    1.0
"""

from __future__ import annotations

import re
from typing import Protocol

from starboard_server.domain.models.conversation_patterns import (
    NextStepOption,
    OptionSelection,
)


class EmbeddingClient(Protocol):
    """Protocol for embedding client (optional dependency for semantic matching)."""

    async def embed(self, text: str) -> list[float]:
        """Embed text into vector representation."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts."""
        ...


class OptionSelectionProcessor:
    """Processes user input to detect option selections.

    Uses multiple strategies to determine if user input is selecting
    a numbered option or is free-form text input.

    Matching Strategies (in order of precedence):
        1. Exact numeric match: "2" → option 2 (confidence: 1.0)
        2. Word form match: "two" → option 2 (confidence: 1.0)
        3. Keyword match: "option 2" → option 2 (confidence: 0.95)
        4. Semantic match: "analyze statistics" → option 2 (confidence: variable)
        5. Free text: No match found (confidence: 1.0)

    Attributes:
        embedding_client: Optional embedding client for semantic matching.
                         If None, semantic matching is disabled.

    Examples:
        >>> processor = OptionSelectionProcessor(embedding_client=None)
        >>>
        >>> # Direct numeric selection
        >>> result = processor.process("2", options)
        >>> assert result.selection_type == "option"
        >>> assert result.confidence == 1.0
        >>>
        >>> # Word form selection
        >>> result = processor.process("two", options)
        >>> assert result.selection_type == "option"
        >>>
        >>> # Keyword selection
        >>> result = processor.process("option 2", options)
        >>> assert result.confidence == 0.95
        >>>
        >>> # Free text
        >>> result = processor.process("Tell me about costs", options)
        >>> assert result.selection_type == "free_text"
    """

    # Word-to-number mapping for options 1-9
    WORD_TO_NUMBER = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
    }

    # Keywords that indicate option selection
    OPTION_KEYWORDS = ["option", "choice", "select"]

    def __init__(self, embedding_client: EmbeddingClient | None = None):
        """Initialize option selection processor.

        Args:
            embedding_client: Optional embedding client for semantic matching.
                            If None, semantic matching is disabled.
        """
        self.embedding_client = embedding_client

    def process(
        self,
        user_input: str,
        available_options: tuple[NextStepOption, ...],
    ) -> OptionSelection:
        """Determine if user input is selecting an option or free text.

        Applies matching strategies in order of precedence until a match
        is found or all strategies are exhausted.

        Args:
            user_input: Raw user message
            available_options: Options from previous agent response

        Returns:
            OptionSelection with detected selection or None if free text

        Examples:
            >>> result = processor.process("2", options)
            >>> assert result.selected_option.number == 2
            >>>
            >>> result = processor.process("What about costs?", options)
            >>> assert result.selection_type == "free_text"
        """
        # Handle empty or whitespace-only input
        if not user_input or not user_input.strip():
            return self._create_free_text_selection(user_input)

        # Handle empty options
        if not available_options:
            return self._create_free_text_selection(user_input)

        user_input_lower = user_input.strip().lower()

        # Strategy 1: Exact numeric match
        if number := self._extract_number(user_input_lower):  # noqa: SIM102
            if option := self._find_option_by_number(number, available_options):
                return OptionSelection(
                    selection_type="option",
                    selected_option=option,
                    original_input=user_input,
                    confidence=1.0,
                )

        # Strategy 2: Keyword-based selection (e.g., "option 2")
        if any(keyword in user_input_lower for keyword in self.OPTION_KEYWORDS):  # noqa: SIM102
            if number := self._extract_number_after_keyword(user_input_lower):  # noqa: SIM102
                if option := self._find_option_by_number(number, available_options):
                    return OptionSelection(
                        selection_type="option",
                        selected_option=option,
                        original_input=user_input,
                        confidence=0.95,  # Slightly lower than direct
                    )

        # No match found - treat as free text
        return self._create_free_text_selection(user_input)

    def _extract_number(self, text: str) -> int | None:
        """Extract single digit or word form from text.

        Handles both numeric ("2") and word form ("two") inputs.
        Only supports 1-9 (no double digits).

        Args:
            text: Lowercased, stripped text

        Returns:
            Number 1-9 if found, None otherwise

        Examples:
            >>> self._extract_number("2")
            2
            >>> self._extract_number("two")
            2
            >>> self._extract_number("10")
            None
        """
        # Check if entire text is a single digit 1-9
        if text.isdigit() and len(text) == 1:
            try:
                number = int(text)
                if 1 <= number <= 9:
                    return number
            except ValueError:
                # Unicode digits or other non-standard digits - treat as free text
                pass

        # Check if entire text is a word form
        return self.WORD_TO_NUMBER.get(text)

    def _extract_number_after_keyword(self, text: str) -> int | None:
        """Extract number after keywords like 'option 2' or 'choice two'.

        Uses regex to find keyword followed by a number (digit or word).

        Args:
            text: Lowercased, stripped text

        Returns:
            Number 1-9 if found after keyword, None otherwise

        Examples:
            >>> self._extract_number_after_keyword("option 2")
            2
            >>> self._extract_number_after_keyword("I'll take choice three")
            3
        """
        # Build pattern for any keyword + number
        word_forms = "|".join(self.WORD_TO_NUMBER.keys())
        pattern = rf"(?:option|choice|select)\s+(\d|{word_forms})"

        if match := re.search(pattern, text):
            number_str = match.group(1)
            return self._extract_number(number_str)

        return None

    def _find_option_by_number(
        self,
        number: int,
        options: tuple[NextStepOption, ...],
    ) -> NextStepOption | None:
        """Find option with matching number.

        Args:
            number: Option number to find (1-9)
            options: Available options

        Returns:
            Matching option or None if not found

        Examples:
            >>> option = self._find_option_by_number(2, options)
            >>> assert option.number == 2
        """
        for option in options:
            if option.number == number:
                return option
        return None

    def _create_free_text_selection(self, user_input: str) -> OptionSelection:
        """Create free text selection result.

        Args:
            user_input: Original user input

        Returns:
            OptionSelection indicating free text with 1.0 confidence
        """
        return OptionSelection(
            selection_type="free_text",
            selected_option=None,
            original_input=user_input,
            confidence=1.0,
        )
