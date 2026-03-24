# Web Interface Guide

> Last verified: 2026-03-24

The Starboard AI web interface provides a real-time chat experience for interacting with
domain-specialist agents. This guide walks through every aspect of the interface so you
can get the most out of each conversation.

---

## Accessing the Web UI

| Component | URL |
|-----------|-----|
| **Frontend (Web UI)** | [http://localhost:3000](http://localhost:3000) |
| **Backend (API)** | [http://localhost:8000](http://localhost:8000) |
| **API Documentation** | [http://localhost:8000/docs](http://localhost:8000/docs) (dev environments only) |

**Browser requirements**: Any modern browser with JavaScript enabled (Chrome, Firefox,
Safari, Edge). The UI uses Server-Sent Events (SSE) for real-time streaming, so browser
extensions that block EventSource connections may interfere.

---

## Starting the Server

### Method 1: Make (Recommended)

The simplest way to start both the backend and frontend together:

```bash
make dev
```

You can also start them individually:

```bash
make dev-server    # Backend only  (http://localhost:8000)
make dev-frontend  # Frontend only (http://localhost:3000)
```

**Expected output** (backend):

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     server_starting
```

### Method 2: Manual Uvicorn

If you prefer to run the backend manually:

```bash
# Backend (from repository root)
uvicorn starboard_server.main:create_app --factory --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend
npm install   # first time only
npm run dev
# Runs on http://localhost:3000
```

!!! warning "Use the --factory flag"
    The backend uses an application factory pattern. You must pass both
    `starboard_server.main:create_app` and `--factory` to Uvicorn. Using
    `starboard_server.main:app` without `--factory` may also work but bypasses
    the factory entry point.

### Method 3: Docker (Coming Soon)

Docker Compose support is planned but not yet available. For now, use `make dev` or
the manual Uvicorn method above.

!!! note "Backend must be running"
    The frontend connects to the backend API at `http://localhost:8000` by default.
    If you see connection errors, verify the backend is healthy:
    ```bash
    curl http://localhost:8000/health/ready
    ```
    You can override the API URL with the `NEXT_PUBLIC_API_URL` environment variable.

---

## Interface Overview

### Homepage

When you open `http://localhost:3000`, you land on the **Welcome** screen. It contains
three main elements:

**Hero Prompt** -- The large text area in the center of the page is where you type your
first question. It supports:

- **Enter** to submit and start a new conversation.
- **Shift+Enter** to insert a new line without submitting.
- A character counter (limit: 10,000 characters).
- **File upload** -- click the attachment button to the left of the text area to upload
  SQL files, notebooks, log files, or other text artifacts for analysis.
- **Offline mode toggle** -- a switch below the text area that lets you run without
  live Databricks API access (useful for reviewing cached data or code-only analysis).

**Example Query Cards** -- Below the prompt you will find clickable example queries
organized by domain:

| Domain | Example Query |
|--------|---------------|
| **Job** | "Analyze job performance for job 12345 and suggest optimizations" |
| **Job** | "Why did job 67890 fail in the last run?" |
| **Query** | "Why is query q_abc123 running slowly?" |
| **Query** | "Optimize this query: SELECT * FROM large_table WHERE date > '2024-01-01'" |
| **Unity Catalog** | "Show me the schema and statistics for table sales.customer_orders" |
| **Unity Catalog** | "What is the lineage for table analytics.daily_metrics?" |
| **Analytics** | "Analyze cost trends for the last 30 days" |
| **Analytics** | "Which warehouse is consuming the most credits?" |

Clicking a card copies its text into the Hero Prompt so you can customize it or submit
it directly.

### Conversation Sidebar

The left-hand sidebar provides conversation management:

| Control | Description |
|---------|-------------|
| **Starboard logo / title** | Click to return to the homepage. |
| **Theme toggle** (sun/moon icon) | Switch between light and dark mode. |
| **Menu toggle** (hamburger icon) | Collapse or expand the sidebar. |
| **New Conversation** button | Start a fresh conversation. |
| **Search** | Filter conversations by name, ID, or query ID. |
| **Filter tabs** (All / Advisor / Analytics) | Narrow the list by conversation type. |
| **Configuration** button | Open the settings page. |
| **Clear All** button | Delete all conversations (with confirmation). |

Conversations are grouped chronologically (Today, Yesterday, Last 7 Days, Older).
Each entry shows a friendly name generated from your first message, an agent icon
indicating which domain agent handled the conversation, and a timestamp for the
last activity. Click any conversation to resume it.

---

## Starting a Conversation

1. **Open the web UI** at [http://localhost:3000](http://localhost:3000).
2. **Type your question** in the Hero Prompt or click an example query card.
3. **Press Enter** or click the **Send** button.

The system automatically routes your question to the best specialist agent. You can
help the router by including specific identifiers in your question.

### Example Prompts by Domain

| Agent Domain | Example Prompt |
|--------------|---------------|
| **Query** | "Why is statement `01234abc-...` running slowly?" |
| **Job** | "Analyze job 98765 -- it's been timing out this week" |
| **Unity Catalog** | "Show lineage for `prod.analytics.daily_revenue`" |
| **Cluster** | "Review cluster `0123-456789-abc` configuration for cost savings" |
| **Analytics (FinOps)** | "What are our top 10 most expensive warehouses this month?" |
| **Warehouse** | "Compare SLO compliance across all SQL warehouses" |
| **Diagnostic** | "Job 55555 failed with OOM -- help me troubleshoot" |
| **Discovery** | "Run a health assessment of our Databricks workspace" |

!!! tip "Be specific with identifiers"
    Including job IDs, query statement IDs, table names, or warehouse names helps the
    router select the right specialist agent instantly, without needing a clarification
    step.

---

## Understanding Agent Responses

### Agent Badges

Each assistant message displays a small colored badge on the avatar indicating which
domain agent produced the response:

| Badge Color | Agent | Specialty |
|-------------|-------|-----------|
| Blue | **Query Expert** | SQL optimization and execution plans |
| Green | **Job Expert** | Databricks job performance tuning |
| Violet | **Unity Catalog Expert** | Metadata, lineage, governance, storage |
| Pink | **Cluster Expert** | Cluster configuration and optimization |
| Emerald | **FinOps Expert** | Cost analysis, billing, budget forecasting |
| Cyan | **Warehouse Expert** | SQL warehouse portfolio optimization |
| Amber | **Diagnostic Expert** | Troubleshooting and root cause analysis |
| Teal | **Discovery Expert** | Workspace health assessments |
| Indigo | **Router** | Routes your query to the right specialist |

Hover over a badge to see the agent name and a short description.

### Streaming Responses

Responses stream in real time via Server-Sent Events (SSE). While the agent is
working, you will see:

- **Thinking indicator** -- An animated ellipsis with a timer (e.g., "Thinking (3s)")
  while the agent reasons about your request. When the agent finishes a reasoning step,
  the indicator transitions to "Thought for Xs".
- **Inline tool calls** -- As the agent invokes tools, each call appears as a
  de-emphasized italic line (e.g., `-> Resolve Job`, `-> Analyze Job History`). This
  lets you follow the agent's investigation in real time.
- **Connection indicator** -- A small colored dot at the top of the chat area shows
  connection status:

| Color | Meaning |
|-------|---------|
| **Green** | Connected -- real-time streaming is active. |
| **Yellow** | Connecting -- establishing the SSE stream. |
| **Red** | Disconnected -- check your network or restart the backend. |
| **Blue** | New conversation -- not yet connected (normal). |

### Structured Reports

When an agent completes its analysis, it produces a structured report. The type of
report depends on the domain:

- **Advisor Report** -- Findings, recommendations, and implementation plans (Query,
  Job, UC, Cluster agents).
- **Analytics Report** -- Cost summaries, trend charts, and FinOps findings (Analytics
  agent).
- **Warehouse Report** -- Portfolio overview, health gauges, topology cards, and
  chargeback tables (Warehouse agent).
- **Diagnostic Report** -- Root-cause timeline, error stack traces, and remediation
  steps (Diagnostic agent).

Each report can be **downloaded** in Markdown or JSON format using the icons in the
report header.

### Next Steps

After a report, the agent may present a **"What would you like to do next?"** card
with numbered options. Each option has a type badge:

| Badge | Meaning |
|-------|---------|
| **Continue** | Continue the conversation with the current agent. |
| **Expert** | Hand off to a different specialist agent. |
| **Action** | Execute a specific follow-up action. |

Click an option or ignore it and type your own follow-up question.

### Clarification Requests

Sometimes an agent needs more information before it can proceed. A clarification
dialog will appear with specific options or a free-text input. Required
clarifications cannot be dismissed; optional ones can.

### Feedback

After a completed report (when no next-step options are pending), a feedback widget
appears allowing you to rate the response. This helps improve agent quality over time.

---

## Providing Follow-up Context

Starboard agents use **interruptible reasoning** -- you can provide additional context
or corrections at any point during a conversation.

1. **Refine your question.** If the agent asks a clarification question, answer it
   directly in the message input. The agent will incorporate your response and continue.
2. **Correct course.** If the agent is investigating the wrong resource, type a
   correction like "Actually, I meant job 12345, not 12346." The agent will adjust.
3. **Add context mid-conversation.** You can upload files or paste additional details
   at any time. The agent will incorporate the new information into its analysis.
4. **Switch domains.** If you want a different specialist, rephrase your question with
   domain-specific keywords. For example, "Now analyze the cluster configuration for
   this job" will route to the Cluster Expert.

---

## File Uploads

You can attach files to any message -- from the homepage Hero Prompt or from the
in-conversation message input.

### Supported Workflow

1. **Click the paperclip** button.
2. **Select a file** (SQL, Python, JSON, log files, notebooks, etc.).
3. **Review the attachment** -- the file appears as a chip above the text input showing
   the filename and size.
4. **Add an optional message** describing what you want done with the file (e.g.,
   "Optimize this query" or "Debug this notebook").
5. **Press Enter** or click **Send**.

If you do not type a message, the agent automatically generates a prompt like
"Analyze the attached file: filename.sql".

!!! tip "Small vs. large files"
    Small files are embedded directly in the message. Larger files are sent as
    attachments with a preview. In both cases, the agent receives the full file
    content for analysis.

---

## Configuration Page

Navigate to `/config` via the **Configuration** button in the sidebar. The settings
page lets you tune the agent's behavior for new conversations.

### Model Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **LLM Model** | Choose the underlying language model. | `databricks-claude-sonnet-4-5` |
| **Temperature** | Controls response randomness (0.1 = deterministic, 1.0 = creative). | 0.4 |
| **Max Tokens** | Maximum tokens per response. | 75,000 |
| **Use Max Model Tokens** | Automatically use the model's maximum output limit. | Off |

### Agent Settings

| Setting | Description | Default |
|---------|-------------|---------|
| **Budget Enforcement** | Enforce session token budget limits. | On |
| **Max Steps** | Maximum reasoning steps per conversation turn (5--25). | 20 |
| **Logging Level** | Control backend log verbosity. | INFO |

### Domain-Specific Overrides

The **Domain Model Selector** at the bottom of the page lets you assign different
models and temperatures to individual domain agents. For example, you might use a
cheaper model for the Router while keeping a more capable model for the Query Expert.

!!! note "Settings apply to new conversations"
    Changes take effect for conversations created after you save. Existing
    conversations retain their original settings.

---

## Keyboard Shortcuts

| Shortcut | Context | Action |
|----------|---------|--------|
| **Enter** | Message input | Send message |
| **Shift+Enter** | Message input | Insert new line |
| **/** | Message input (empty) | Show slash command suggestions |

---

## Dark Mode

Starboard supports both light and dark themes. Toggle the theme using the sun/moon
icon in the sidebar header. Your preference is saved in local storage and persists
across sessions. The application also respects your operating system's color scheme
preference on first visit.

---

## Troubleshooting

### Connection error -- "Please refresh the page"

The SSE connection to the backend was lost.

1. **Check that the backend is running:**
   ```bash
   curl http://localhost:8000/health/ready
   ```
   Expected response: `{"status": "ok", ...}` with HTTP 200.
2. **Refresh the browser.**
3. **Restart the backend** if the problem persists:
   ```bash
   make dev-server
   ```

### "This conversation no longer exists"

The conversation was deleted or the server was restarted (in-memory storage does not
persist across restarts).

- You will be redirected to the homepage automatically.
- Start a new conversation.

!!! tip "Use persistent storage for production"
    Configure `DATABASE_BACKEND=postgres` or `DATABASE_BACKEND=databricks` for
    conversation persistence across restarts. The default `sqlite` backend persists
    locally but is not recommended for production.

### Messages are not streaming

1. **Verify the connection indicator** is **green** at the top of the chat area.
2. **Check the browser console** (F12) for SSE or network errors.
3. **Ensure no browser extensions** are blocking EventSource connections.
4. **Verify backend health:**
   ```bash
   curl http://localhost:8000/health/live
   ```

### Agent times out or seems stuck

1. **Wait up to 60 seconds** -- complex analyses (job history, warehouse portfolios)
   may take time.
2. **Check the backend logs** for rate-limit or timeout errors.
3. **Reduce max steps** in the Configuration page if the agent is performing too many
   reasoning iterations.

### File upload fails

- Confirm the file is a text-based format (SQL, Python, JSON, YAML, log, CSV).
- Binary files (images, compiled binaries) are not supported.
- Check the file size -- the default maximum request size is 10 MB.

### Wrong agent handles my question

- Check the **agent badge** on the response to see which agent was selected.
- Rephrase your question with more specific keywords or identifiers. For example,
  include a job ID to route to the Job Expert, or mention "warehouse" to route to
  the Warehouse Expert.

---

## Tips and Best Practices

1. **Be specific.** Include job IDs, query IDs, table names, or warehouse names in
   your questions. The router uses these identifiers to select the right specialist
   agent instantly.

2. **Use example queries as templates.** The homepage cards are great starting points.
   Click one, then customize it with your actual identifiers.

3. **Follow the next steps.** After a report, the suggested next steps are tailored to
   your specific situation. They often reveal deeper insights.

4. **Attach files for code review.** Upload SQL files or notebooks and ask the agent
   to optimize or debug them -- this gives the agent the full context it needs.

5. **Use offline mode for sensitive environments.** If you cannot connect to
   Databricks from your current network, toggle offline mode to work with cached
   data and code analysis tools.

6. **Adjust the temperature for your use case.** Lower temperatures (0.1--0.3)
   produce more consistent, deterministic analysis. Higher temperatures (0.5--0.8)
   can yield more creative optimization suggestions.

7. **Review the agent badge.** If a response seems off-topic, check which agent
   handled it. You can rephrase your question with more specific keywords to route
   to the correct specialist.
