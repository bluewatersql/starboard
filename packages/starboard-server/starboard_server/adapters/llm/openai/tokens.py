"""Token usage aggregation and budget management utilities."""

from __future__ import annotations

import json
from typing import Any

from starboard_server.infra.observability.logging import get_logger

# Try to import tiktoken for accurate token counting

tiktoken: Any = None

try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

logger = get_logger(__name__)

class TokenBudget:
    """

    Manages token budget allocation across different workflow phases.

    Core Categories:
        - planning: Initial and adaptive planning (planning, replanning)
        - critic: Validation and judgment (critic, judge)
        - analysis: Analysis and execution (analysis, execution, table_extract, etc.)
        - synth: Synthesis and finalization (summarization, review, finalization)
    """

    # Phase mapping: maps various phase names to core budget categories
    PHASE_MAPPING = {
        # Planning category
        "planning": "planning",
        "replanning": "planning",
        "planner": "planning",
        "replanner": "planning",
        # Critic category
        "critic": "critic",
        "judge": "critic",
        "validation": "critic",
        "verification": "critic",
        # Analysis category
        "analysis": "analysis",
        "execution": "analysis",
        "table_extract": "analysis",
        "initialization": "analysis",
        "routing": "analysis",
        # Synth category
        "synth": "synth",
        "synthesis": "synth",
        "summarize": "synth",
        "summarization": "synth",
        "review": "synth",
        "finalization": "synth",
    }

    def __init__(
        self,
        session_cap_tokens: int = 1_000_000,
        planning_prompt_cap: int = 128_000,
        planning_output_cap: int = 10_000,
        critic_prompt_cap: int = 128_000,
        critic_output_cap: int = 10_000,
        analysis_prompt_cap: int = 128_000,
        analysis_output_cap: int = 10_000,
        synth_prompt_cap: int = 128_000,
        synth_output_cap: int = 10_000,
        enforced: bool = True,
    ) -> None:
        """
        Initialize token budget.

        Args:
            enforced: Whether to enforce the budget
            session_cap_tokens: Total session token limit
            planning_prompt_cap: Planning phase prompt limit (includes planning, replanning)
            planning_output_cap: Planning phase output limit
            critic_prompt_cap: Critic phase prompt limit (includes critic, judge, validation)
            critic_output_cap: Critic phase output limit
            analysis_prompt_cap: Analysis phase prompt limit (includes analysis, execution, table_extract)
            analysis_output_cap: Analysis phase output limit
            synth_prompt_cap: Synthesis phase prompt limit (includes summarization, review, finalization)
            synth_output_cap: Synthesis phase output limit
        """
        self.enforced = enforced
        self.session_cap = session_cap_tokens
        self.remaining = session_cap_tokens
        self.phase_caps = {
            "planning": {"prompt": planning_prompt_cap, "output": planning_output_cap},
            "critic": {"prompt": critic_prompt_cap, "output": critic_output_cap},
            "analysis": {"prompt": analysis_prompt_cap, "output": analysis_output_cap},
            "synth": {"prompt": synth_prompt_cap, "output": synth_output_cap},
        }
        self.spent: dict[str, int] = {
            "planning": 0,
            "critic": 0,
            "analysis": 0,
            "synth": 0,
        }

        # Log token counting method on first use
        if TIKTOKEN_AVAILABLE:
            logger.debug("[BUDGET] Using tiktoken for accurate token counting")
        else:
            logger.debug(
                "[BUDGET] tiktoken not available, using character-based estimation (1 token ≈ 4 chars)"
            )

    @property
    def total_spent(self) -> int:
        """
        Calculate total tokens spent across all phases.

        Returns:
            Total tokens spent
        """
        return sum(self.spent.values())

    def recalculate_remaining(self) -> None:
        """
        Recalculate remaining tokens from session cap and total spent.

        This ensures consistency in case of any drift between the tracked
        remaining value and the actual spent amounts.
        """
        self.remaining = max(0, self.session_cap - self.total_spent)

    @staticmethod
    def get_encoding_for_model(model: str | None = None) -> Any | None:
        """
        Get tiktoken encoding for a specific model.

        Args:
            model: Model name (e.g., "gpt-4", "gpt-3.5-turbo")

        Returns:
            tiktoken encoding object or None if tiktoken unavailable
        """
        if not TIKTOKEN_AVAILABLE or not tiktoken:
            return None

        try:
            # Try model-specific encoding first
            if model:
                # Handle model variants (e.g., gpt-4-0125-preview -> gpt-4)
                model_parts = model.split("-")[0:2]  # e.g., ["gpt", "4"]
                base_model = "-".join(model_parts) if len(model_parts) > 1 else model

                try:
                    return tiktoken.encoding_for_model(model)
                except KeyError:
                    # Fall back to base model if specific variant not found
                    try:
                        return tiktoken.encoding_for_model(base_model)
                    except KeyError:
                        pass

            # Fall back to cl100k_base (used by gpt-4, gpt-3.5-turbo, etc.)
            return tiktoken.get_encoding("cl100k_base")
        except Exception as e:  # noqa: BLE001 - tiktoken may not be imported
            logger.debug("tiktoken_encoding_failed", error=str(e))
            return None

    @staticmethod
    def count_tokens_accurate(content: Any, model: str | None = None) -> int:
        """
        Count tokens accurately using tiktoken.

        Args:
            content: Content to count tokens for
            model: Optional model name for model-specific encoding

        Returns:
            Accurate token count, or 0 if content is empty
        """
        if not content:
            return 0

        # Convert to string if needed
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        content_str = str(content)

        if not content_str:
            return 0

        # Try tiktoken if available
        if TIKTOKEN_AVAILABLE:
            try:
                encoding = TokenBudget.get_encoding_for_model(model)
                if encoding:
                    return len(encoding.encode(content_str))
            except (ImportError, ValueError) as e:
                logger.debug(
                    f"tiktoken counting failed, falling back to estimation: {e}"
                )

        # Fall back to estimation
        return max(1, len(content_str) // 4)

    @staticmethod
    def approx_tokens(content: Any, model: str | None = None) -> int:
        """
        Count or approximate token count for given input.

        Uses tiktoken for accurate counting when available, falls back to
        character-based estimation (1 token ≈ 4 characters) otherwise.

        Args:
            content: Content to estimate tokens for
            model: Optional model name for model-specific encoding

        Returns:
            Token count (accurate if tiktoken available, estimated otherwise)
        """
        return TokenBudget.count_tokens_accurate(content, model)

    @classmethod
    def map_phase(cls, phase: str) -> str:
        """
        Map a phase name to its core budget category.

        Args:
            phase: Phase name (can be any variant like 'replanning', 'judge', etc.)

        Returns:
            Core category name (planning, critic, analysis, or synth)
        """
        return cls.PHASE_MAPPING.get(phase, "analysis")  # Default to analysis

    def ensure_room(self, phase: str, messages: list[dict]) -> list[dict]:
        """
        Ensure messages fit within phase budget limits.

        Args:
            phase: Phase name (will be mapped to core category)
            messages: List of message dictionaries

        Returns:
            Possibly truncated messages list
        """
        core_phase = self.map_phase(phase)
        cap = self.phase_caps[core_phase]["prompt"]
        combined = "\n".join(json.dumps(msg, ensure_ascii=False) for msg in messages)
        need = self.approx_tokens(combined)

        logger.debug(
            f"[BUDGET] {phase} ({core_phase}) prompt est={need} cap={cap} left={self.remaining}"
        )

        if need <= cap and need <= self.remaining:
            return messages

        # Truncate long user content
        if self.enforced:
            result = []
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 50000:
                        msg = {**msg, "content": content[:50000] + "\n...[truncated]"}
                result.append(msg)
            return result

        # If not enforced, return messages as-is (budget exceeded but allowed to continue)
        logger.debug(
            f"[BUDGET] {phase} ({core_phase}) exceeds budget (need={need}, cap={cap}, remaining={self.remaining}) but enforcement disabled - continuing"
        )
        return messages

    def charge(
        self,
        phase: str,
        prompt: Any,
        output: Any,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        """
        Charge tokens for a phase execution.

        Uses actual token counts from API when available, falls back to estimation.

        Args:
            phase: Phase name (will be mapped to core category)
            prompt: Prompt content (used for estimation if actual tokens not provided)
            output: Output content (used for estimation if actual tokens not provided)
            prompt_tokens: Actual prompt token count from API (optional)
            completion_tokens: Actual completion token count from API (optional)
        """
        core_phase = self.map_phase(phase)

        if prompt_tokens is not None and completion_tokens is not None:
            # Use actual token counts from API
            input_tokens = prompt_tokens
            output_tokens = completion_tokens
            source = "actual"
        else:
            # Fall back to estimation
            input_tokens = self.approx_tokens(prompt)
            output_tokens = self.approx_tokens(output)
            source = "estimated"

        total = input_tokens + output_tokens
        self.remaining = max(0, self.remaining - total)
        self.spent[core_phase] += total
        logger.debug(
            f"[BUDGET] {phase} ({core_phase}) charged={total} ({source}: input={input_tokens}, output={output_tokens}) left={self.remaining}"
        )

        # Warn at 80% usage, log exhaustion at 100%
        usage_ratio = self.total_spent / self.session_cap if self.session_cap > 0 else 0
        if usage_ratio >= 1.0:
            logger.warning(
                f"[BUDGET] budget_exhausted: {self.total_spent}/{self.session_cap} tokens used"
            )
        elif usage_ratio >= 0.8:
            logger.warning(
                f"[BUDGET] budget_warning: {usage_ratio:.0%} of session budget used "
                f"({self.total_spent}/{self.session_cap} tokens, {self.remaining} remaining)"
            )
