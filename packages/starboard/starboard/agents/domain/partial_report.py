# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Partial report generation for budget-exhausted domain agents.

This module handles the generation of partial reports when an agent's
token budget is exhausted before completing analysis. It also builds
context summaries for continuation.

Responsibilities:
- Generate structured partial reports from gathered data
- Build context summaries for analysis continuation
- Extract findings from tool results in conversation history
- Create next steps for budget-exhausted sessions

Does NOT:
- Execute reasoning or tools (that's ReasoningEngine/ToolExecutor)
- Emit events (that's EventStreamer)
- Build final output for completed agents (that's OutputBuilder)
"""

from __future__ import annotations

from typing import Any

from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.state.agent_state import AgentState
from starboard.infra.observability.logging import get_logger

logger = get_logger(__name__)


def build_context_summary(
    state: AgentState,
    tools_used: list[str],
    discovered: dict[str, Any],
) -> str:
    """
    Build a context summary for continuation that captures what was done.

    This creates a summary that can be injected into the next agent run
    to provide continuity.

    Args:
        state: Current agent state
        tools_used: List of tool names that were executed
        discovered: Dict of discovered entities from working memory

    Returns:
        Formatted context string for continuation
    """
    # Extract original user request from messages
    original_request = "Unknown request"
    for msg in state.conversation_history:
        if msg.role == "user":
            original_request = msg.content[:500]  # Truncate long requests
            break

    lines = [
        "=== PREVIOUS ANALYSIS CONTEXT (budget exhausted) ===",
        f"Original request: {original_request}",
        f"Steps completed: {state.current_step}",
        f"Tokens remaining: {state.budget_remaining}",
        "",
    ]

    if tools_used:
        lines.append("Tools executed:")
        for tool in tools_used:
            lines.append(f"  - {tool}")
        lines.append("")

    # Extract and summarize tool results from messages
    tool_results_summary = []
    for msg in state.conversation_history:
        if msg.role == "tool" and msg.metadata and msg.content:
            tool_name = msg.metadata.get("tool_name", "unknown")
            # Truncate to first 300 chars for summary
            result_preview = msg.content[:300]
            if len(msg.content) > 300:
                result_preview += "..."
            tool_results_summary.append(f"  {tool_name}: {result_preview}")

    if tool_results_summary:
        lines.append("Tool results summary:")
        for summary in tool_results_summary[:5]:  # Limit to 5 tools
            lines.append(summary)
        if len(tool_results_summary) > 5:
            lines.append(f"  ... and {len(tool_results_summary) - 5} more")
        lines.append("")

    if discovered:
        lines.append("Data gathered:")
        for entity_type, entities in discovered.items():
            if entities:
                entity_preview = ", ".join(str(e) for e in entities[:5])
                if len(entities) > 5:
                    entity_preview += f"... (+{len(entities) - 5} more)"
                lines.append(f"  - {entity_type}: {entity_preview}")
        lines.append("")

    # Include key facts from working memory if available
    if state.working_memory.facts:
        lines.append("Key facts discovered:")
        for fact in state.working_memory.facts[:5]:
            lines.append(f"  - {str(fact)[:150]}")
        lines.append("")

    lines.append("=== CONTINUE FROM HERE ===")
    lines.append(
        "Please continue the analysis using the context above. "
        "Focus on generating actionable recommendations based on the data already gathered."
    )

    return "\n".join(lines)


def generate_partial_report(
    state: AgentState,
    config: AgentConfig,
) -> dict[str, Any]:
    """
    Generate a partial report when budget is exhausted.

    This creates a valid report structure that includes:
    - Summary explaining budget exhaustion
    - Actual findings from tool results in conversation history
    - Facts discovered during analysis
    - Next steps for user to continue

    Args:
        state: Current agent state with working memory
        config: Agent configuration (for domain)

    Returns:
        Partial report dict with actual gathered data for UI rendering
    """
    tools_used = list(state.working_memory.tools_used)
    discovered = state.working_memory.metrics.get("discovered_entities", {})
    facts = state.working_memory.facts  # Discovered facts

    # Extract tool results from conversation history messages
    # Tool results are stored in "tool" role messages, not in working_memory.summaries
    tool_results: dict[str, str] = {}
    for msg in state.conversation_history:
        if msg.role == "tool" and msg.metadata:
            tool_name = msg.metadata.get("tool_name", "unknown")
            # Get the content (tool result)
            if msg.content and len(msg.content) > 10:
                tool_results[tool_name] = msg.content

    # Build summary explaining the partial status
    summary_text = (
        f"Analysis was interrupted due to token budget constraints after gathering data. "
        f"Tools executed: {', '.join(tools_used) if tools_used else 'none'}. "
        f"The analysis can be continued by asking a follow-up question."
    )

    # Build findings from actual tool results extracted from messages
    findings = []
    rank = 1

    # Create findings from tool results - these contain the actual analysis data
    for tool_name, result_content in tool_results.items():
        if result_content and len(str(result_content)) > 20:  # Skip trivial results
            # Truncate long results for display but keep enough to be useful
            display_content = str(result_content)[:800]
            if len(str(result_content)) > 800:
                display_content += "...\n[Result truncated for display]"

            findings.append(
                {
                    "id": f"data_{tool_name}",
                    "category": "DATA_GATHERED",
                    "title": f"Data from {tool_name.replace('_', ' ').title()}",
                    "recommendation": display_content,
                    "fixes": [],
                    "proofs": {
                        "evidence": [f"Retrieved via {tool_name}"],
                        "code_line_refs": [],
                        "references": [],
                    },
                    "impact_estimate": {
                        "query_time_pct": 0,
                        "data_read_pct": 0,
                        "shuffle_pct": 0,
                        "cost_pct": 0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low", "estimate_hours": 0},
                    "risks": ["Partial analysis - recommendations pending"],
                    "rank": rank,
                }
            )
            rank += 1

    # Add discovered facts as a finding if present
    if facts:
        fact_list = "\n".join(f"\u2022 {fact}" for fact in facts[:10])
        if len(facts) > 10:
            fact_list += f"\n\u2022 ... and {len(facts) - 10} more"

        findings.append(
            {
                "id": "discovered_facts",
                "category": "OBSERVATIONS",
                "title": f"Key Observations ({len(facts)} discovered)",
                "recommendation": fact_list,
                "fixes": [],
                "proofs": {
                    "evidence": facts[:5],
                    "code_line_refs": [],
                    "references": [],
                },
                "impact_estimate": {
                    "query_time_pct": 0,
                    "data_read_pct": 0,
                    "shuffle_pct": 0,
                    "cost_pct": 0,
                    "confidence": "medium",
                },
                "effort": {"level": "low", "estimate_hours": 0},
                "risks": [],
                "rank": rank,
            }
        )
        rank += 1

    # Add discovered entities as findings
    if discovered:
        for entity_type, entities in discovered.items():
            if entities:
                entity_list = ", ".join(str(e) for e in entities[:5])
                if len(entities) > 5:
                    entity_list += f"... (+{len(entities) - 5} more)"

                findings.append(
                    {
                        "id": f"entities_{entity_type}",
                        "category": "ENTITIES",
                        "title": f"Discovered {entity_type.replace('_', ' ').title()}",
                        "recommendation": entity_list,
                        "fixes": [],
                        "proofs": {
                            "evidence": [f"Found {len(entities)} {entity_type}"],
                            "code_line_refs": [],
                            "references": [],
                        },
                        "impact_estimate": {
                            "query_time_pct": 0,
                            "data_read_pct": 0,
                            "shuffle_pct": 0,
                            "cost_pct": 0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0},
                        "risks": [],
                        "rank": rank,
                    }
                )
                rank += 1

    # If still no findings, add a generic one
    if not findings:
        findings.append(
            {
                "id": "partial_analysis",
                "category": "STATUS",
                "title": "Partial analysis - budget exhausted",
                "recommendation": "Continue the analysis by asking a follow-up question to get full recommendations.",
                "fixes": [],
                "proofs": {
                    "evidence": [
                        f"Tools used: {', '.join(tools_used) if tools_used else 'none'}"
                    ],
                    "code_line_refs": [],
                    "references": [],
                },
                "impact_estimate": {
                    "query_time_pct": 0,
                    "data_read_pct": 0,
                    "shuffle_pct": 0,
                    "cost_pct": 0,
                    "confidence": "low",
                },
                "effort": {"level": "low", "estimate_hours": 0},
                "risks": [],
                "rank": 1,
            }
        )

    # Build context summary for continuation
    context_summary = build_context_summary(state, tools_used, discovered)

    # Build next steps for continuation with embedded context
    next_steps = [
        {
            "id": "continue_analysis",
            "number": 1,
            "title": "Continue the analysis",
            "description": f"Resume analysis with the data already gathered ({len(tools_used)} tools used)",
            "action_type": "continue",
            "target_agent": config.domain,
            "tool_name": None,
            "parameters": {
                "continuation_context": context_summary,
                "resume_from": "partial_analysis",
            },
        },
        {
            "id": "narrow_scope",
            "number": 2,
            "title": "Ask a more specific question",
            "description": "Try a more focused question to stay within token limits",
            "action_type": "continue",
            "target_agent": None,
            "tool_name": None,
            "parameters": None,
        },
    ]

    # Determine report type based on domain
    report_type = "analytics" if config.domain == "analytics" else "advisor"

    return {
        "report_type": report_type,
        "budget_exhausted": True,  # Flag for UI to show warning banner
        "summary": {
            "overview": summary_text,
            "current_state": {
                "cloud_provider": "unknown",
                "key_symptoms": ["Budget exhausted before completion"],
            },
        },
        "analysis": {"findings": findings},
        "testing_validation": {
            "plan": ["Continue analysis to generate testing plan"],
            "metrics_to_track": [],
            "success_criteria": [],
        },
        "next_steps": next_steps,
    }
