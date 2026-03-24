# Call the API in 5 Minutes

Get up and running with the Starboard AI Agent API. This guide walks through creating a conversation, sending messages, and receiving streaming AI responses using `curl` and Python `httpx`.

---

## Prerequisites

Before starting, ensure the backend is running:

```bash
make dev-server
```

!!! info "Verify the server is healthy"
    ```bash
    curl http://localhost:8000/health/live
    ```
    You should receive an `HTTP 200` response.

| Requirement | Detail |
|---|---|
| **Backend URL** | `http://localhost:8000` |
| **API prefix** | `/api/chat` (conversations, messages, streaming) |
| **Content-Type** | `application/json` |
| **Python version** | 3.8+ (for `httpx` examples) |

---

## Authentication

### Development Mode

In local development, the `AuthMiddleware` extracts user identity from the request. No API key or OAuth token is required. The middleware creates a default user automatically.

### Production (Databricks Reverse Proxy)

In production deployments behind a Databricks reverse proxy, user identity is extracted from platform-injected headers:

| Header | Purpose |
|---|---|
| `X-Forwarded-User` | Authenticated user email |
| `X-Forwarded-Groups` | User group memberships |

```bash
# Production request with auth headers
curl -X POST http://your-deployment/api/chat/conversations \
  -H "Content-Type: application/json" \
  -H "X-Forwarded-User: user@example.com" \
  -d '{}'
```

!!! warning "Health endpoints skip authentication"
    The paths `/health`, `/health/live`, and `/health/ready` are excluded from authentication middleware and can be called without any headers.

---

## Step 1: Create a Conversation

A conversation is a persistent session that maintains context across multiple messages. You must create one before sending any messages.

### Request

**Endpoint:** `POST /api/chat/conversations`
**Status:** `201 Created`

| Field | Type | Required | Description |
|---|---|---|---|
| `initial_message` | `string` | No | Send a first message immediately on creation (max 10,000 chars) |
| `context` | `object` | No | Initial context (e.g., `{"workspace_id": "ws_abc"}`) |
| `config` | `object` | No | Session configuration (temperature, model, max_tokens) |
| `metadata` | `object` | No | Arbitrary metadata (e.g., `{"source": "api"}`) |

### Response Schema

```json
{
  "conversation_id": "conv_abc123def456",
  "user_id": "user_123",
  "friendly_name": "New Conversation 2026-03-01 10:30AM",
  "created_at": "2026-03-01T10:30:00Z",
  "config": {
    "temperature": 0.4,
    "max_tokens": 120000,
    "safe_mode": false,
    "streaming": true,
    "model": "databricks-claude-sonnet-4-5",
    "max_steps": 20
  },
  "domain_models": []
}
```

### Examples

=== "curl"

    ```bash
    # Minimal -- just create an empty conversation
    curl -s -X POST http://localhost:8000/api/chat/conversations \
      -H "Content-Type: application/json" \
      -d '{}' | jq .

    # With an initial message (starts processing immediately)
    curl -s -X POST http://localhost:8000/api/chat/conversations \
      -H "Content-Type: application/json" \
      -d '{
        "initial_message": "Analyze job 12345 for performance issues",
        "context": {"workspace_id": "ws_prod"},
        "config": {"temperature": 0.4, "max_tokens": 120000}
      }' | jq .
    ```

=== "Python (httpx)"

    ```python
    import httpx

    BASE_URL = "http://localhost:8000"

    response = httpx.post(
        f"{BASE_URL}/api/chat/conversations",
        json={
            "initial_message": "Analyze job 12345 for performance issues",
            "context": {"workspace_id": "ws_prod"},
        },
    )
    response.raise_for_status()
    conversation = response.json()
    conversation_id = conversation["conversation_id"]
    print(f"Created conversation: {conversation_id}")
    ```

!!! tip "Save the `conversation_id`"
    Every subsequent call -- sending messages, streaming events, retrieving history -- requires the `conversation_id` returned in this response.

---

## Step 2: Send a Message (with Streaming)

Sending a message is a two-part process:

1. **POST** the message -- the server accepts it asynchronously (HTTP 202).
2. **GET** the SSE stream -- receive real-time thinking, tool calls, and final output.

### 2a. Post the Message

**Endpoint:** `POST /api/chat/conversations/{conversation_id}/messages`
**Status:** `202 Accepted`
**Rate limit:** 30 requests per minute per user

| Field | Type | Required | Description |
|---|---|---|---|
| `content` | `string` | Yes | The user message (min 1 char) |
| `attachments` | `array` | No | File attachments for analysis |
| `metadata` | `object` | No | Arbitrary metadata |

=== "curl"

    ```bash
    CONV_ID="conv_abc123def456"  # from Step 1

    curl -s -X POST "http://localhost:8000/api/chat/conversations/${CONV_ID}/messages" \
      -H "Content-Type: application/json" \
      -d '{"content": "Show me the top 10 most expensive jobs this month"}' | jq .
    ```

=== "Python (httpx)"

    ```python
    msg_response = httpx.post(
        f"{BASE_URL}/api/chat/conversations/{conversation_id}/messages",
        json={"content": "Show me the top 10 most expensive jobs this month"},
    )
    msg_response.raise_for_status()
    message = msg_response.json()
    print(f"Message queued: {message['message_id']} (status: {message['status']})")
    ```

**Response:**

```json
{
  "message_id": "msg_xyz789abc",
  "conversation_id": "conv_abc123def456",
  "status": "processing",
  "trace_id": "trace_def456ghi"
}
```

### 2b. Stream the Response (SSE)

Open a long-lived connection to receive events as the agent reasons, calls tools, and produces output.

**Endpoint:** `GET /api/chat/conversations/{conversation_id}/stream`
**Content-Type:** `text/event-stream`

=== "curl"

    ```bash
    # Stream events (Ctrl+C to stop)
    curl -N "http://localhost:8000/api/chat/conversations/${CONV_ID}/stream"
    ```

    Example output:

    ```
    retry: 3000

    event: message.start
    data: {"event_id":"evt_a1b2c3","type":"message.start","data":{"message_id":"msg_xyz789abc"},"timestamp":"2026-03-01T10:30:05Z"}

    event: tool.call.start
    data: {"event_id":"evt_d4e5f6","type":"tool.call.start","data":{"message_id":"msg_xyz789abc","tool_call":{"tool_name":"resolve_query","friendly_name":"Resolving Query","status":"running"}},"timestamp":"2026-03-01T10:30:06Z"}

    event: tool.call.result
    data: {"event_id":"evt_g7h8i9","type":"tool.call.result","data":{"message_id":"msg_xyz789abc","tool_call":{"tool_name":"resolve_query","status":"completed","duration_ms":1200}},"timestamp":"2026-03-01T10:30:07Z"}

    event: message.delta
    data: {"event_id":"evt_j0k1l2","type":"message.delta","data":{"message_id":"msg_xyz789abc","delta":{"content":"Based on my analysis..."}},"timestamp":"2026-03-01T10:30:08Z"}

    event: final_output
    data: {"event_id":"evt_m3n4o5","type":"final_output","data":{"message_id":"msg_xyz789abc","output":{"status":"success","formatted_report":"...","tokens_used":1523,"cost_usd":0.023}},"timestamp":"2026-03-01T10:30:12Z"}
    ```

=== "Python (httpx)"

    ```python
    import json
    import httpx

    async def stream_response(base_url: str, conversation_id: str) -> None:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "GET",
                f"{base_url}/api/chat/conversations/{conversation_id}/stream",
            ) as response:
                event_type = None
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        print(f"[{event_type}] {json.dumps(data, indent=2)[:200]}")

                        # Stop after final output
                        if event_type == "final_output":
                            break
                    # Empty line = end of event block (ignored)

    # Usage:
    # import asyncio
    # asyncio.run(stream_response(BASE_URL, conversation_id))
    ```

!!! note "Streaming is the primary response mechanism"
    The `POST /messages` endpoint returns immediately with `202 Accepted`. The actual AI response is delivered exclusively through the SSE stream. Always open the stream **before or immediately after** posting a message.

For full details on every SSE event type and its schema, see the [SSE Streaming Guide](sse-streaming.md).

---

## Step 3: List Conversations

Retrieve all conversations for the authenticated user, ordered by most recent first.

**Endpoint:** `GET /api/chat/conversations`
**Status:** `200 OK`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | `int` | 20 | Max results (1-100) |
| `offset` | `int` | 0 | Pagination offset |

=== "curl"

    ```bash
    curl -s "http://localhost:8000/api/chat/conversations?limit=10" | jq .
    ```

=== "Python (httpx)"

    ```python
    response = httpx.get(
        f"{BASE_URL}/api/chat/conversations",
        params={"limit": 10},
    )
    conversations = response.json()
    for conv in conversations:
        print(f"  {conv['conversation_id']}  {conv['friendly_name']}")
    ```

**Response:**

```json
[
  {
    "conversation_id": "conv_abc123def456",
    "user_id": "user_123",
    "friendly_name": "Job Performance Analysis",
    "created_at": "2026-03-01T10:30:00Z",
    "config": {
      "temperature": 0.4,
      "max_tokens": 120000,
      "model": "databricks-claude-sonnet-4-5"
    },
    "domain_models": []
  }
]
```

---

## Step 4: Continue a Conversation

Send follow-up messages to the same conversation to maintain context. The agent remembers everything from previous turns.

=== "curl"

    ```bash
    # Follow-up question in the same conversation
    curl -s -X POST "http://localhost:8000/api/chat/conversations/${CONV_ID}/messages" \
      -H "Content-Type: application/json" \
      -d '{"content": "Can you drill into the most expensive job and show me its cluster config?"}' \
      | jq .

    # Stream the response
    curl -N "http://localhost:8000/api/chat/conversations/${CONV_ID}/stream"
    ```

=== "Python (httpx)"

    ```python
    # Send follow-up
    httpx.post(
        f"{BASE_URL}/api/chat/conversations/{conversation_id}/messages",
        json={"content": "Drill into the most expensive job and show cluster config"},
    ).raise_for_status()

    # Stream response (reuse the stream_response function from Step 2)
    # asyncio.run(stream_response(BASE_URL, conversation_id))
    ```

### Retrieve Conversation History

To fetch all messages exchanged so far (useful for restoring UI state after a page refresh):

**Endpoint:** `GET /api/chat/conversations/{conversation_id}/history`

=== "curl"

    ```bash
    curl -s "http://localhost:8000/api/chat/conversations/${CONV_ID}/history" | jq .
    ```

=== "Python (httpx)"

    ```python
    history = httpx.get(
        f"{BASE_URL}/api/chat/conversations/{conversation_id}/history"
    ).json()

    for msg in history["messages"]:
        role = msg["role"].upper()
        preview = msg["content"][:80]
        print(f"  [{role}] {preview}...")

    meta = history["metadata"]
    print(f"\nTotal: {meta['total_messages']} messages, "
          f"{meta['total_tokens']} tokens, ${meta['total_cost']:.4f}")
    ```

**Response:**

```json
{
  "conversation_id": "conv_abc123def456",
  "messages": [
    {
      "id": "msg_001",
      "conversation_id": "conv_abc123def456",
      "role": "user",
      "content": "Show me the top 10 most expensive jobs",
      "timestamp": "2026-03-01T10:30:05Z",
      "status": "completed",
      "tool_calls": []
    },
    {
      "id": "msg_002",
      "conversation_id": "conv_abc123def456",
      "role": "assistant",
      "content": "Based on my analysis of your Databricks workspace...",
      "timestamp": "2026-03-01T10:30:12Z",
      "status": "completed",
      "tool_calls": [
        {
          "tool_call_id": "call_abc",
          "tool_name": "resolve_query",
          "friendly_name": "Resolving Query",
          "status": "completed",
          "duration_ms": 1200
        }
      ],
      "metadata": {
        "tokens": 1523,
        "cost": 0.023,
        "latency_ms": 7000
      }
    }
  ],
  "metadata": {
    "total_messages": 2,
    "total_tokens": 1523,
    "total_cost": 0.023,
    "created_at": "2026-03-01T10:30:00Z",
    "updated_at": "2026-03-01T10:30:12Z",
    "friendly_name": "Job Performance Analysis"
  }
}
```

---

## Common Request/Response Schemas

### ConversationConfig

Configuration passed during conversation creation. All fields are optional and have sensible defaults.

| Field | Type | Default | Description |
|---|---|---|---|
| `temperature` | `float` | `0.4` | LLM sampling temperature (0.1 -- 1.0) |
| `max_tokens` | `int` | `120000` | Max tokens in response (10,000 -- 200,000) |
| `safe_mode` | `bool` | `false` | Disable destructive operations |
| `streaming` | `bool` | `true` | Enable SSE streaming |
| `model` | `string` | `databricks-claude-sonnet-4-5` | LLM model identifier |
| `max_steps` | `int` | `20` | Max reasoning steps (5 -- 25) |
| `budget_enforced` | `bool` | `false` | Enforce session token budget |
| `offline_mode` | `bool` | `false` | Disable Databricks API calls |
| `domain_model_overrides` | `object` | `null` | Per-domain model overrides |
| `domain_temperature_overrides` | `object` | `null` | Per-domain temperature overrides |

### MessageResponse

Returned after posting a message.

| Field | Type | Description |
|---|---|---|
| `message_id` | `string` | Unique message identifier (e.g., `msg_xyz789abc`) |
| `conversation_id` | `string` | Parent conversation ID |
| `status` | `string` | One of: `pending`, `processing`, `completed`, `failed` |
| `trace_id` | `string` | Distributed tracing ID for debugging |

---

## Error Handling

All errors follow a consistent JSON format:

```json
{
  "error": {
    "type": "ValidationError",
    "message": "Invalid conversation_id format",
    "details": {
      "field": "conversation_id",
      "constraint": "must be UUID"
    },
    "request_id": "req_abc123",
    "timestamp": "2026-03-01T10:30:00Z"
  }
}
```

### HTTP Status Codes

| Code | Meaning | When |
|---|---|---|
| `200` | OK | Successful read/update |
| `201` | Created | Conversation created |
| `202` | Accepted | Message queued for async processing |
| `204` | No Content | Successful deletion |
| `400` | Bad Request | Invalid request syntax |
| `404` | Not Found | Conversation or resource not found |
| `422` | Unprocessable Entity | Validation error (e.g., empty message) |
| `429` | Too Many Requests | Rate limit exceeded |
| `500` | Internal Server Error | Server-side failure |

### Retry Strategy

For **5xx errors**, use exponential backoff:

```
Attempt 1: wait 1s
Attempt 2: wait 2s
Attempt 3: wait 4s (max 3 retries)
Add +/- 25% jitter to each delay.
```

**Do not retry** 4xx errors -- fix the request instead.

---

## Rate Limiting

| Scope | Limit |
|---|---|
| Conversation creation | 10 per minute per user |
| Message sending | 30 per minute per user |
| General API | 100 per minute per IP |
| Concurrent SSE streams | 10 per user |

Rate limit headers are included in responses:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1709290800
```

When rate-limited, you receive a `429` response with a `retry_after_seconds` field:

```json
{
  "error": {
    "type": "RateLimitError",
    "message": "Rate limit exceeded",
    "retry_after_seconds": 60
  }
}
```

---

## Complete End-to-End Script

=== "Bash"

    ```bash
    #!/usr/bin/env bash
    set -euo pipefail

    BASE="http://localhost:8000"

    # 1. Create conversation
    CONV=$(curl -s -X POST "${BASE}/api/chat/conversations" \
      -H "Content-Type: application/json" \
      -d '{"initial_message": "What are my top 5 most expensive Databricks jobs?"}')
    CONV_ID=$(echo "$CONV" | jq -r '.conversation_id')
    echo "Conversation: ${CONV_ID}"

    # 2. Stream events (runs for ~30s depending on analysis)
    echo "--- Streaming events ---"
    curl -N "${BASE}/api/chat/conversations/${CONV_ID}/stream" &
    STREAM_PID=$!

    # Wait for stream to finish (or timeout after 60s)
    sleep 60 && kill $STREAM_PID 2>/dev/null

    # 3. Retrieve full history
    echo ""
    echo "--- Conversation history ---"
    curl -s "${BASE}/api/chat/conversations/${CONV_ID}/history" | jq '.messages[] | {role, content: .content[:100]}'
    ```

=== "Python (async)"

    ```python
    #!/usr/bin/env python3
    """End-to-end Starboard API example."""

    import asyncio
    import json
    import httpx

    BASE_URL = "http://localhost:8000"


    async def main() -> None:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # 1. Create conversation with initial message
            resp = await client.post(
                "/api/chat/conversations",
                json={
                    "initial_message": "What are my top 5 most expensive Databricks jobs?",
                },
            )
            resp.raise_for_status()
            conv = resp.json()
            conv_id = conv["conversation_id"]
            print(f"Created conversation: {conv_id}")

            # 2. Stream events
            print("\n--- Streaming events ---")
            async with client.stream(
                "GET", f"/api/chat/conversations/{conv_id}/stream"
            ) as stream:
                event_type = None
                async for line in stream.aiter_lines():
                    if line.startswith("event: "):
                        event_type = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        nested = data.get("data", {})

                        if event_type == "tool.call.start":
                            tool = nested.get("tool_call", {})
                            print(f"  [TOOL] {tool.get('friendly_name', tool.get('tool_name'))} started")
                        elif event_type == "tool.call.result":
                            tool = nested.get("tool_call", {})
                            ms = tool.get("duration_ms", "?")
                            print(f"  [TOOL] {tool.get('tool_name')} completed ({ms}ms)")
                        elif event_type == "message.delta":
                            delta = nested.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                print(content, end="", flush=True)
                        elif event_type == "final_output":
                            output = nested.get("output", {})
                            print(f"\n\n  [DONE] status={output.get('status')}, "
                                  f"tokens={output.get('tokens_used')}, "
                                  f"cost=${output.get('cost_usd', 0):.4f}")
                            break

            # 3. Get history
            print("\n--- Conversation history ---")
            hist = (await client.get(f"/api/chat/conversations/{conv_id}/history")).json()
            for msg in hist["messages"]:
                print(f"  [{msg['role'].upper()}] {msg['content'][:100]}...")


    if __name__ == "__main__":
        asyncio.run(main())
    ```

---

## Next Steps

- **[SSE Streaming Guide](sse-streaming.md)** -- Deep dive into every event type, schema, and parsing strategy
- **[API Reference](../api/API_REFERENCE.md)** -- Complete reference for all 22 endpoints
- **[Interruptible Reasoning](../INTERRUPTIBLE_REASONING.md)** -- How to inject input and interrupt agent reasoning mid-execution
- **[Quickstart](../QUICKSTART.md)** -- Full project setup including frontend
