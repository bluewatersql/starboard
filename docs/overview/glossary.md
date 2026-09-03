# Glossary

Definitions of key terms used throughout Starboard documentation.

---

## Starboard Terms

**Agent**
: An AI assistant specialized in a specific Databricks domain. Each agent has its own system prompt, tool set, and output format. Starboard has 8 domain agents plus an Intent Router.

**Agent Handoff**
: The process by which one agent transfers control to another, passing context such as resource IDs and partial findings. Handoffs enable cross-domain analysis without losing context.

**Complete (tool)**
: A core tool available to all agents that signals the end of reasoning and delivers the final structured report to the user.

**Continuous Reasoning**
: The agent architecture pattern where agents reason step-by-step, evaluating data before deciding next actions, rather than following a predefined workflow graph.

**Conversation**
: A persistent interaction session between a user and the agent system. Conversations store message history and working memory.

**ConversationSession**
: In the SDK, a handle to a single multi-turn conversation that maintains context across successive `ask()` calls.

**Discovery Agent**
: A domain agent that performs workspace-wide health assessments using a 4-phase pipeline: product audit, query pack execution, domain analysis, and report synthesis.

**Domain Agent**
: A specialized agent that handles a specific category of Databricks optimization tasks (e.g., Query, Job, UC, Cluster, Analytics, Warehouse, Discovery, Diagnostic).

**Episode**
: A unit of working memory that captures a summary of an interaction segment within a conversation.

**Fact**
: A piece of long-term memory extracted from conversations, stored with a confidence score.

**Finding**
: A specific issue or observation identified during analysis, backed by evidence from tool outputs. In Workload Review, each finding carries a severity, an impact/effort priority score, a suggested fix, and an evidence citation (the query-pack `query_id` + the row that triggered it).

**Intent Router**
: The framework agent that classifies user requests and dispatches them to the appropriate domain specialist using a hybrid pattern-matching and LLM classification approach.

**List-Price Estimate**
: The basis for all `$` figures on Starboard's public path — DBU consumption valued at published list prices. These are directional estimates, not finance-grade billing numbers.

**Interruptible Reasoning**
: The ability for users to provide additional context, corrections, or redirections to an agent during mid-analysis without restarting the workflow.

**Offline Mode**
: An operating mode where agents perform static analysis without calling Databricks APIs. Useful for testing, demonstrations, and environments without connectivity.

**Optimization Mode**
: The execution mode for agent analysis: `online` (full API access), `offline` (static analysis only), or `diagnostic` (focused troubleshooting).

**Proof**
: Evidence cited by an agent to support a finding, typically drawn from tool outputs such as execution plans, table metadata, or runtime metrics.

**Query Pack**
: A curated, versioned set of SQL queries over public `system.*` tables. Discovery and Workload Review run query packs to gather evidence; findings cite the pack `query_id` and the row that triggered them.

**Reference Files (RAG)**
: The analytics-context source — curated on-disk domain reference files (`starboard_core/rag/knowledge/domains/*.md`) plus query packs. No embeddings or vector database are used.

**Reasoning Loop**
: The iterative cycle where an agent calls the LLM, evaluates the response, executes a tool, and decides whether to continue or complete.

**Report**
: The structured output produced by an agent at the end of analysis, containing findings, recommendations, proofs, and next steps.

**Report Type**
: The schema category for agent output. Types include `advisor` (optimization recommendations), `analytics` (cost analysis and charts), and `compute` (resource health and portfolio views).

**Request User Input (tool)**
: A core tool that pauses agent reasoning and asks the user for clarification or additional information.

**Safe Mode**
: A configuration option (`SAFE_MODE=true`) that disables all external API calls, useful for testing and controlled environments.

**Starboard Client**
: The in-package SDK class (`from starboard.sdk import StarboardClient`) that bootstraps the agent stack and creates conversation sessions for programmatic access — used by the `examples/` notebooks. It ships inside the `starboard` package; there is no separate `starboard-sdk` package.

**Tool**
: A function available to agents that performs a specific operation, such as fetching query metadata, analyzing a cluster configuration, or executing a SQL query. Tools follow a three-layer architecture (Domain, Service, Adapter).

**Tool Budget**
: The token limit allocated to an agent for completing its analysis. Agents are designed to complete within a target number of tool calls to stay efficient.

**Tool Sharing**
: The 80/20 strategy where agents get strategic overlap in tools (80% independent completion) while delegating complex operations to domain specialists (20%).

---

## Databricks Terms

**Cluster**
: A set of Databricks compute resources used to run notebooks, jobs, and interactive workloads. Clusters can be all-purpose or job-specific.

**DBSQL**
: Databricks SQL — the SQL analytics service for running queries against data in Unity Catalog using SQL warehouses.

**DBU**
: Databricks Unit — the unit of measure for Databricks compute consumption used in billing.

**Job**
: A Databricks workflow that runs one or more tasks on a schedule or trigger. Jobs can contain notebooks, JARs, Python scripts, and SQL tasks.

**Statement ID**
: A unique identifier for a SQL query execution in Databricks SQL, used to retrieve query text, execution plans, and runtime metrics.

**Unity Catalog (UC)**
: The unified governance layer for Databricks that manages data assets (catalogs, schemas, tables, volumes, functions) with access control, lineage, and auditing.

**Warehouse (SQL Warehouse)**
: A Databricks SQL compute resource optimized for running SQL queries. Can be serverless, pro, or classic type.

**Workspace**
: A Databricks deployment environment that contains notebooks, jobs, clusters, warehouses, and Unity Catalog assets.

---

## Architecture Terms

**Adapter**
: The outermost layer in the three-layer tool architecture, responsible for I/O operations such as Databricks API calls, database queries, and file access.

**Circuit Breaker**
: A reliability pattern that fails fast when an external dependency is unavailable, preventing cascading failures and reducing unnecessary retries.

**Domain Layer**
: The innermost layer in the three-layer tool architecture, containing pure business logic with no I/O dependencies. Fully deterministic and testable.

**EventEmitter**
: The component that publishes streaming events (thinking, tool start, tool end, final output) to the CLI / SDK during agent execution — an in-process stream.

**Golden Test**
: A snapshot test that captures LLM prompts and outputs to detect unintended changes in agent behavior across code modifications.

**Hexagonal Architecture**
: The architectural pattern where pure domain logic sits at the core, surrounded by adapters for external I/O, enabling clean separation of concerns.

**Pydantic**
: The Python validation library (V2) used at all system boundaries to enforce type safety on user inputs, LLM outputs, and API payloads.

**Repository Pattern**
: The data access pattern used for state management, providing abstract interfaces with pluggable backends. The active state backend is memory-only (`database_backend="memory"`); Redis is an opt-in cache backend (`starboard[redis]`).

**Cache**
: Starboard's response cache. It runs **TTL-only** (exact-key) with no vector dependency. In-memory by default; Redis is an opt-in cache backend (`starboard[redis]`).

**Workload Review**
: The `starboard review` flagship — a ranked, evidence-cited review of a workspace's jobs, SQL, and warehouses over public `system.*` data only. Findings are scored against a rule registry and filtered by the **severity gate** (`--min-severity` / `--min-score`). The review is read-only: it never writes back to your workspace.

**Service Layer**
: The middle layer in the three-layer tool architecture, responsible for orchestrating adapters, composing operations, and handling errors.

---

## Abbreviations

| Abbreviation | Full Term |
|-------------|-----------|
| **CLI** | Command-Line Interface |
| **DBU** | Databricks Unit |
| **DBSQL** | Databricks SQL |
| **FinOps** | Financial Operations (cloud cost management) |
| **LLM** | Large Language Model |
| **PII** | Personally Identifiable Information |
| **RBAC** | Role-Based Access Control |
| **SDK** | Software Development Kit |
| **SLO** | Service Level Objective |
| **TTL** | Time To Live |
| **UC** | Unity Catalog |

---

## See also

- [What is Starboard?](what-is-starboard.md)
- [Agent Catalog](agents.md)
- [Contributing](../contributing.md)
