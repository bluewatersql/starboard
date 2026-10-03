# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""User interaction and intent resolution tool schemas."""

RESOLVE_USER_INTENT = {
    "name": "resolve_user_intent",
    "description": (
        "Analyze user input to determine optimization intent and extract key parameters.\n"
        "WHEN TO USE: User input is ambiguous, unclear, or lacks specific identifiers (job IDs, statement IDs, table names).\n"
        "Returns: Intent classification (query/job/pipeline optimization), confidence score, extracted parameters (IDs, names), reasoning.\n"
        "Cost: ~50 tokens | Prerequisites: None\n"
        "→ Next: Use extracted parameters to call appropriate tools (resolve_query, resolve_job, fetch_table_metadata)\n"
        "Best practice: Call this FIRST when user intent is not immediately clear from the input\n"
        "Examples:\n"
        "  - 'optimize this' → detects intent, extracts context\n"
        "  - 'why is it slow?' → classifies as query/job optimization\n"
        "  - 'job 12345 is taking forever' → extracts job_id=12345, intent=optimize_job"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_input": {
                "type": "string",
                "description": "The user's natural language input to analyze",
            },
            "conversation_history": {
                "type": "array",
                "description": "Optional: Previous messages for context (not required for simple cases)",
                "items": {"type": "object"},
            },
        },
        "required": ["user_input"],
    },
}

REQUEST_USER_INPUT = {
    "name": "request_user_input",
    "description": (
        "Request user input when critical information is missing. Pauses execution and waits for response.\n"
        "Cost: FREE but SLOW (waits up to 5 minutes for human response)\n"
        "When to use: Missing required IDs (job_id, warehouse_id, cluster_id), multiple ambiguous matches\n"
        "When NOT: Info can be inferred, searched with tools, or has defaults (dates, limits)\n"
        "Best practice: FIRST try resolve_user_intent and resolve_* tools, THEN use this if necessary\n"
        "CRITICAL: Always provide 'context' parameter explaining what you're trying to do\n"
        "Timeout: If user doesn't respond in 5 minutes, tool returns error\n"
        "Example: User says 'my query' but resolve_query finds 10 matches → request_user_input('Which query?', context='Optimizing query', suggestions=[...])"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Clear, specific question for the user",
            },
            "context": {
                "type": "string",
                "description": "IMPORTANT: Brief context explaining what you're trying to do (e.g., 'Optimizing query performance'). This helps maintain context after receiving the response.",
            },
            "suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional: Up to 5 suggested answers to help user respond quickly",
            },
            "timeout": {
                "type": "number",
                "description": "Optional: Timeout in seconds (default: 300 = 5 minutes)",
            },
        },
        "required": ["question"],
    },
}
