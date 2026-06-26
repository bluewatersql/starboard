# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Next-step generator service for cross-domain suggestions.

Generates NextStepOptions from domain agent outputs and service catalog.
Part of Phase 9: Service Catalog & Next-Step Suggestions

Examples:
    >>> generator = NextStepGenerator(catalog_tool)
    >>> options = generator.generate(domain_output, current_agent="query_optimizer")
    >>> len(options)
    3
"""

from __future__ import annotations

from starboard_server.domain.models.agent_output import DomainAgentOutput
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.service_catalog_tool import ServiceCatalogTool

logger = get_logger(__name__)


class NextStepGenerator:
    """Generates NextStepOptions from domain agent output and catalog.

    Combines in-domain next steps with cross-domain handoff recommendations
    to create a unified set of options for the user.

    Attributes:
        catalog: Service catalog tool for agent lookup

    Examples:
        >>> catalog = ServiceCatalogTool()
        >>> generator = NextStepGenerator(catalog)
        >>> options = generator.generate(domain_output, "query_optimizer")
    """

    MAX_OPTIONS = 9

    def __init__(self, catalog: ServiceCatalogTool) -> None:
        """Initialize next-step generator.

        Args:
            catalog: Service catalog tool for agent discovery

        Examples:
            >>> generator = NextStepGenerator(catalog_tool)
        """
        self.catalog = catalog

    async def generate_next_steps(
        self,
        domain_output: DomainAgentOutput,
        current_agent: str,
    ) -> tuple[NextStepOption, ...]:
        """Generate next-step options from domain agent output.

        Priority order:
        1. In-domain next steps (CONTINUE action)
        2. Cross-domain handoffs (ROUTE action), sorted by confidence

        Args:
            domain_output: Output from domain agent
            current_agent: ID of current agent

        Returns:
            Tuple of NextStepOptions, numbered 1-9, prioritized and limited

        Examples:
            >>> options = generator.generate(output, "query_optimizer")
            >>> options[0].number
            1
            >>> options[0].action_type
            <ActionType.CONTINUE: 'continue'>
        """
        all_options: list[NextStepOption] = []

        # 1. Convert in-domain steps to options (CONTINUE action)
        if domain_output.in_domain_next_steps:
            for step in domain_output.in_domain_next_steps:
                option = NextStepOption(
                    id=f"in_domain_{step.id}",
                    number=0,  # Will be renumbered later
                    title=step.title,
                    description=step.description,
                    action_type=ActionType.CONTINUE,
                    target_agent=None,
                    tool_name=None,
                    parameters={"suggested_prompt": step.suggested_prompt},
                )
                all_options.append(option)

        # 2. Convert handoff recommendations to options (ROUTE action)
        if domain_output.handoff_recommendations:
            # Sort handoffs by confidence (HIGH → MEDIUM → LOW)
            sorted_handoffs = sorted(
                domain_output.handoff_recommendations,
                key=lambda h: h.confidence,
                reverse=True,
            )

            for handoff in sorted_handoffs:
                # Lookup target agent in catalog
                catalog_entries = self.catalog.get_entries(domain=handoff.target_domain)

                if not catalog_entries:
                    # Domain not found in catalog, skip this handoff
                    logger.warning(
                        "handoff_domain_not_found",
                        target_domain=handoff.target_domain,
                        current_agent=current_agent,
                    )
                    continue

                # Use first active agent for this domain
                target_entry = catalog_entries[0]

                option = NextStepOption(
                    id=f"handoff_{handoff.target_domain}",
                    number=0,  # Will be renumbered later
                    title=f"{target_entry.name}",
                    description=handoff.reason,
                    action_type=ActionType.ROUTE,
                    target_agent=target_entry.service_id,
                    tool_name=None,
                    parameters=(
                        {"handoff_context": handoff.context_to_pass}
                        if handoff.context_to_pass
                        else None
                    ),
                )
                all_options.append(option)

        # 3. Limit to MAX_OPTIONS
        limited_options = all_options[: self.MAX_OPTIONS]

        # 4. Renumber sequentially
        numbered_options = tuple(
            NextStepOption(
                id=opt.id,
                number=idx + 1,
                title=opt.title,
                description=opt.description,
                action_type=opt.action_type,
                target_agent=opt.target_agent,
                tool_name=opt.tool_name,
                parameters=opt.parameters,
            )
            for idx, opt in enumerate(limited_options)
        )

        logger.debug(
            "next_steps_generated",
            current_agent=current_agent,
            in_domain_count=(
                len(domain_output.in_domain_next_steps)
                if domain_output.in_domain_next_steps
                else 0
            ),
            handoff_count=(
                len(domain_output.handoff_recommendations)
                if domain_output.handoff_recommendations
                else 0
            ),
            total_options=len(numbered_options),
        )

        return numbered_options
