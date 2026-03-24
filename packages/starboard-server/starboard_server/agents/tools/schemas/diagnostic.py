# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Schema definitions for diagnostic agent tools."""

# =============================================================================
# EXPLORE_ARTIFACT - Intent-aware artifact exploration
# =============================================================================

EXPLORE_ARTIFACT = {
    "name": "explore_artifact",
    "description": (
        "Explore a large uploaded artifact with intent-aware extraction. "
        "Use this to extract specific sections from large files (query profiles, "
        "spark event logs, etc.) based on the user's question. The focus parameter "
        "describes what to look for in natural language."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "attachment_id": {
                "type": "string",
                "description": (
                    "The attachment ID to explore (from available_artifacts context). "
                    "Format: att_<conversation_id>_<hash>"
                ),
            },
            "focus": {
                "type": "string",
                "description": (
                    "Natural language description of what to focus on. Examples:\n"
                    "- 'range join hints, join strategies'\n"
                    "- 'shuffle bottlenecks, data movement'\n"
                    "- 'scan operations, data volumes'\n"
                    "- 'slow operators, execution time'\n"
                    "- 'data skew, partition distribution'"
                ),
            },
            "detail_level": {
                "type": "string",
                "enum": ["summary", "detailed", "exhaustive"],
                "description": (
                    "How much detail to return:\n"
                    "- summary: High-level overview (~2KB)\n"
                    "- detailed: Full relevant sections (~10KB) [default]\n"
                    "- exhaustive: Everything matching focus (~50KB)"
                ),
            },
        },
        "required": ["attachment_id", "focus"],
    },
}
