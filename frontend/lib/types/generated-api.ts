/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * AUTO-GENERATED FILE - DO NOT EDIT
 * 
 * Generated from Pydantic models by scripts/generate_types.py
 * To regenerate: python scripts/generate_types.py
 */

// ============================================================================
// Frontend-Only Types (referenced by generated code but not in backend)
// These types are frontend-specific and defined here to resolve references.
// ============================================================================

/**
 * File attachment for sending files with messages.
 * Stub type — defined here because it is referenced by generated SendMessageRequest.
 * Fields match the FileUploadButton.FileAttachment shape used throughout the UI.
 */
export interface FileAttachment {
  /** Original filename */
  filename?: string;
  /** File name (alias) */
  name?: string;
  /** MIME type */
  content_type?: string;
  /** File content */
  content?: string;
  /** File size in bytes */
  size?: number;
  /** First 500 chars for display */
  contentPreview?: string;
  /** True if file exceeds large file threshold */
  isLargeFile?: boolean;
  /** Allow additional properties for flexibility */
  [key: string]: unknown;
}

/**
 * Data table for listing/enumeration results.
 * Stub type — defined here because it is referenced by generated AdvisorReport.
 */
export interface DataTable {
  /** Column names */
  columns: string[];
  /** Row data */
  rows: Array<Record<string, unknown>>;
  /** Optional row count */
  row_count?: number;
}

/**
 * Tool call information (frontend-only type).
 * Used for displaying tool execution details in the UI.
 */
export interface ToolCall {
  /** Unique tool call identifier */
  tool_call_id?: string;
  /** Tool name (e.g., "fetch_table_metadata") */
  tool_name: string;
  /** Human-readable tool name */
  friendly_name?: string;
  /** Tool execution status */
  status?: "completed" | "failed" | "running" | "pending";
  /** Tool arguments/parameters */
  arguments?: Record<string, unknown>;
  /** Tool execution result */
  result?: unknown;
  /** Error message if tool failed */
  error?: string;
  /** Execution duration in milliseconds */
  duration_ms?: number;
}

// ============================================================================
// End Frontend-Only Types
// ============================================================================

/**
 * Event types for server-sent events (SSE).
 */
export enum EventType {
  THINKING = "thinking",
  STEP_COMPLETE = "step.complete",
  ERROR = "error",
  TOOL_START = "tool_start",
  TOOL_CALL_START = "tool.call.start",
  TOOL_PROGRESS = "tool.progress",
  TOOL_END = "tool_end",
  TOOL_CALL_RESULT = "tool.call.result",
  USER_INPUT_REQUEST = "user_input_request",
  USER_INPUT_RESPONSE = "user_input_response",
  FINAL_OUTPUT = "final_output",
  NEXT_STEPS = "next_steps",
  CLARIFICATION_REQUEST = "clarification.request",
  HANDOFF = "handoff",
  ROUTING_DECISION = "routing.decision",
  FRIENDLY_NAME_UPDATE = "friendly_name.update",
  AGENT_TRANSITION = "agent.transition",
  CHECKPOINT = "checkpoint",
  INTERRUPT_RECEIVED = "interrupt.received",
  REPLAN = "replan",
  SOLICITATION = "solicitation",
  MESSAGE_START = "message.start",
  MESSAGE_DELTA = "message.delta",
  MESSAGE_END = "message.end",
  STEP_START = "step.start",
}

/**
 * Role of message sender.
 */
export enum MessageRole {
  USER = "user",
  ASSISTANT = "assistant",
  SYSTEM = "system",
  TOOL = "tool",
}

/**
 * Status of message processing.
 */
export enum MessageStatus {
  PENDING = "pending",
  PROCESSING = "processing",
  COMPLETED = "completed",
  FAILED = "failed",
}

/**
 * User feedback rating for agent responses.
 */
export enum FeedbackRatingEnum {
  POSITIVE = "positive",
  NEGATIVE = "negative",
}

/**
 * Categories for negative feedback.
 */
export enum FeedbackCategoryEnum {
  INACCURATE = "inaccurate",
  TOO_VAGUE = "too_vague",
  TOO_VERBOSE = "too_verbose",
  IRRELEVANT = "irrelevant",
  MISSING_INFO = "missing_info",
  BAD_FORMAT = "bad_format",
  OTHER = "other",
}

/**
 * Domain-specific model configuration.
 * 
 * Args:
 *     domain: Domain name (e.g., "Query Optimization", "Job Analysis").
 *     domain_key: Internal domain key (e.g., "query", "job").
 *     model: LLM model identifier for this domain.
 * 
 * Examples:
 *     >>> config = DomainModelConfig(
 *     ...     domain="Query Optimization",
 *     ...     domain_key="query",
 *     ...     model="databricks-gpt-5-1"
 *     ... )
 */
export interface DomainModelConfig {
  /** Human-readable domain name */
  domain: string;
  /** Internal domain key */
  domain_key: string;
  /** LLM model identifier for this domain */
  model: string;
}

/**
 * Configuration for a conversation session.
 * 
 * Args:
 *     temperature: LLM sampling temperature (0.1-1.0). Lower is more deterministic.
 *     max_tokens: Maximum tokens in response (10,000-200,000).
 *     use_max_model_tokens: If True, automatically use model's max output tokens.
 *     safe_mode: If True, disable destructive operations and external calls.
 *     streaming: If True, stream responses via SSE; else return complete response.
 *     model: LLM model identifier (supported models from Databricks).
 *     budget_enforced: If True, enforce session token budget limits.
 *     max_steps: Maximum reasoning steps allowed (5-25).
 *     logging_level: Logging verbosity level.
 *     domain_model_overrides: Per-domain model overrides (domain_key -> model_name).
 *     domain_temperature_overrides: Per-domain temperature overrides (domain_key -> temperature).
 * 
 * Examples:
 *     >>> config = ConversationConfig(temperature=0.4, max_tokens=120000)
 *     >>> config.temperature
 *     0.4
 *     >>> config.budget_enforced
 *     False
 *     >>> config_with_overrides = ConversationConfig(
 *     ...     domain_model_overrides={"query": "databricks-gpt-5"},
 *     ...     domain_temperature_overrides={"diagnostic": 0.7}
 *     ... )
 */
export interface ConversationConfig {
  /** LLM sampling temperature */
  temperature?: number;
  /** Maximum tokens in response */
  max_tokens?: number;
  /** Automatically use model's maximum output token limit */
  use_max_model_tokens?: boolean;
  /** Disable destructive operations if True */
  safe_mode?: boolean;
  /** Stream responses via SSE */
  streaming?: boolean;
  /** LLM model identifier */
  model?: string;
  /** Enforce session token budget limits */
  budget_enforced?: boolean;
  /** Maximum reasoning steps allowed */
  max_steps?: number;
  /** Logging verbosity level */
  logging_level?: string;
  /** Per-domain model overrides (domain_key -> model_name) */
  domain_model_overrides?: Record<string, string> | null;
  /** Per-domain temperature overrides (domain_key -> temperature) */
  domain_temperature_overrides?: Record<string, number> | null;
  /** Force OFFLINE mode - disables tools that require Databricks API calls */
  offline_mode?: boolean;
}

/**
 * API message model.
 */
export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  timestamp?: string;
  status?: MessageStatus;
  metadata?: Record<string, any>;
  /** Tool calls executed in this message */
  tool_calls?: Array<ToolCall>;
  /** Next step options for interactive conversation flow */
  next_steps?: Array<any> | null;
}

/**
 * Response after creating a conversation.
 * 
 * Args:
 *     conversation_id: Unique conversation identifier.
 *     friendly_name: Human-readable conversation title.
 *     created_at: UTC timestamp when conversation was created.
 *     config: Conversation configuration.
 * 
 * Examples:
 *     >>> response = ConversationResponse(
 *     ...     conversation_id="conv_abc123",
 *     ...     friendly_name="New Conversation 2025-11-17 02:30PM",
 *     ...     created_at=datetime.utcnow(),
 *     ...     config=ConversationConfig()
 *     ... )
 */
export interface ConversationResponse {
  /** Unique conversation identifier */
  conversation_id: string;
  /** User who owns the conversation */
  user_id?: string | null;
  /** Human-readable conversation title */
  friendly_name: string;
  /** UTC timestamp when conversation was created */
  created_at: string;
  /** Conversation configuration */
  config: ConversationConfig;
  /** Domain-specific model configurations (non-default models) */
  domain_models?: Array<DomainModelConfig>;
}

/**
 * A single Server-Sent Event in a conversation stream.
 * 
 * Args:
 *     event_id: Unique event identifier (for resumption with Last-Event-ID).
 *     type: Type of event (message.start, message.delta, etc.).
 *     data: Event payload (varies by event type).
 *     timestamp: UTC timestamp when event was emitted.
 * 
 * Examples:
 *     >>> event = ChatEvent(
 *     ...     event_id="evt_001",
 *     ...     type=EventType.MESSAGE_DELTA,
 *     ...     data={"message_id": "msg_abc", "delta": {"content": "Hello"}},
 *     ...     timestamp=datetime.utcnow()
 *     ... )
 */
export interface ChatEvent {
  /** Unique event identifier */
  event_id: string;
  /** Type of event */
  type: EventType;
  /** Event payload */
  data: Record<string, any>;
  /** UTC timestamp when event was emitted */
  timestamp: string;
}

/**
 * Request to create a new conversation session.
 * 
 * Note: user_id is now extracted from authentication middleware,
 * not from the request body.
 * 
 * Args:
 *     context: Initial context for the conversation (job_id, workspace, etc.).
 *     config: Conversation configuration (temperature, model, etc.).
 *     initial_message: Optional message to send immediately after creation.
 *     metadata: Optional metadata for the conversation.
 * 
 * Examples:
 *     >>> # Minimal request
 *     >>> request = CreateConversationRequest()
 * 
 *     >>> # With initial message (UX vNext)
 *     >>> request = CreateConversationRequest(
 *     ...     initial_message="Analyze job performance for job 12345",
 *     ...     context={"job_id": "12345"},
 *     ...     metadata={"source": "homepage"}
 *     ... )
 * 
 *     >>> # Traditional request
 *     >>> request = CreateConversationRequest(
 *     ...     context={"workspace_id": "ws_abc"},
 *     ...     config=ConversationConfig(temperature=0.4)
 *     ... )
 */
export interface CreateConversationRequest {
  /** Initial context for the conversation */
  context?: Record<string, any> | null;
  /** Conversation configuration */
  config?: ConversationConfig | null;
  /** Optional initial message to send immediately after creation (UX vNext Phase 1) */
  initial_message?: string | null;
  /** Optional metadata for the conversation */
  metadata?: Record<string, any> | null;
}

/**
 * Request to send a message in a conversation.
 * 
 * Supports file attachments for artifact analysis. Large files (>50KB)
 * are automatically routed to the diagnostic agent for incremental discovery.
 */
export interface SendMessageRequest {
  /** Message content */
  content: string;
  /** Optional file attachments */
  attachments?: Array<FileAttachment> | null;
  /** Optional metadata */
  metadata?: Record<string, any> | null;
}

/**
 * Request to submit user feedback on an agent response.
 * 
 * Args:
 *     message_id: ID of the message being rated
 *     rating: User's rating (positive/negative)
 *     categories: Optional categories for negative feedback
 *     comment: Optional free-text comment
 * 
 * Examples:
 *     >>> request = SubmitFeedbackRequest(
 *     ...     message_id="msg_123",
 *     ...     rating="positive"
 *     ... )
 *     >>> request_negative = SubmitFeedbackRequest(
 *     ...     message_id="msg_456",
 *     ...     rating="negative",
 *     ...     categories=["inaccurate", "too_vague"],
 *     ...     comment="Not specific enough"
 *     ... )
 */
export interface SubmitFeedbackRequest {
  /** ID of the message being rated */
  message_id: string;
  /** User's rating (positive or negative) */
  rating: FeedbackRatingEnum;
  /** Categories for negative feedback (required for negative rating) */
  categories?: Array<FeedbackCategoryEnum> | null;
  /** Optional free-text comment */
  comment?: string | null;
}

/**
 * Request to respond to a clarification question.
 * 
 * When the framework detects an ambiguous query and asks for clarification,
 * use this endpoint to provide the requested information.
 * 
 * Args:
 *     clarification_id: ID of the clarification request (from event)
 *     response_type: Type of response (option_selected, custom_text)
 *     selected_option_id: ID of selected option (if choosing from options)
 *     custom_text: Free-form text response (if allow_custom_response=true)
 *     metadata: Optional additional context
 * 
 * Examples:
 *     >>> # User selects option 2 (Medium warehouse size)
 *     >>> request = RespondToClarificationRequest(
 *     ...     clarification_id="clar_abc123",
 *     ...     response_type="option_selected",
 *     ...     selected_option_id="2",
 *     ... )
 * 
 *     >>> # User provides custom text
 *     >>> request = RespondToClarificationRequest(
 *     ...     clarification_id="clar_abc123",
 *     ...     response_type="custom_text",
 *     ...     custom_text="my-custom-warehouse",
 *     ... )
 */
export interface RespondToClarificationRequest {
  /** Clarification ID from the clarification.request event */
  clarification_id: string;
  /** Type of response provided */
  response_type: "option_selected" | "custom_text";
  /** ID of selected option (required if response_type=option_selected) */
  selected_option_id?: string | null;
  /** Free-form text response (required if response_type=custom_text) */
  custom_text?: string | null;
  /** Optional additional context */
  metadata?: Record<string, any> | null;
}

/**
 * Response after responding to clarification.
 * 
 * Args:
 *     response_id: Unique identifier for this response
 *     clarification_id: ID of the clarification being answered
 *     status: Processing status (accepted, processing, completed, error)
 *     enriched_query: The original query enriched with clarification response
 *     message: Status message
 *     created_at: Timestamp of response
 * 
 * Examples:
 *     >>> response = RespondToClarificationResponse(
 *     ...     response_id="resp_xyz789",
 *     ...     clarification_id="clar_abc123",
 *     ...     status="accepted",
 *     ...     enriched_query="create warehouse my-wh size Medium",
 *     ...     message="Clarification accepted, continuing with execution",
 *     ...     created_at=datetime.now(timezone.utc),
 *     ... )
 */
export interface RespondToClarificationResponse {
  /** Unique identifier for this response */
  response_id: string;
  /** ID of the clarification being answered */
  clarification_id: string;
  /** Processing status (accepted, processing, completed, error) */
  status: string;
  /** The original query enriched with clarification response */
  enriched_query?: string | null;
  /** Status message */
  message: string;
  /** Timestamp of response */
  created_at: string;
}

/**
 * Request to respond to an agent solicitation.
 * 
 * When the agent asks a question (solicitation), use this to provide
 * the requested information.
 * 
 * Args:
 *     solicitation_id: ID of the solicitation being answered
 *     content: User's response/answer
 *     metadata: Optional additional context
 * 
 * Examples:
 *     >>> request = RespondToSolicitationRequest(
 *     ...     solicitation_id="sol_abc123",
 *     ...     content="Service principal: sp-prod-databricks",
 *     ...     metadata={"confidence": "high"}
 *     ... )
 */
export interface RespondToSolicitationRequest {
  /** Solicitation ID being answered */
  solicitation_id: string;
  /** User's response/answer */
  content: string;
  /** Additional context */
  metadata?: Record<string, any> | null;
}

/**
 * Response after responding to solicitation.
 * 
 * Args:
 *     response_id: Unique identifier for this response
 *     status: Processing status
 *     solicitation_id: Solicitation that was answered
 *     response_time_ms: Time taken by user to respond (milliseconds)
 * 
 * Examples:
 *     >>> response = RespondToSolicitationResponse(
 *     ...     response_id="resp_xyz789",
 *     ...     status="accepted",
 *     ...     solicitation_id="sol_abc123",
 *     ...     response_time_ms=12345.6
 *     ... )
 */
export interface RespondToSolicitationResponse {
  /** Unique response identifier */
  response_id: string;
  /** Processing status */
  status: string;
  /** Solicitation that was answered */
  solicitation_id: string;
  /** User response time in milliseconds */
  response_time_ms: number;
}

/**
 * Event data for clarification requests.
 * 
 * Args:
 *     clarification_id: Unique identifier for this clarification request
 *     question: The clarification question being asked
 *     options: Available options (if multiple choice)
 *     allow_custom_response: Whether user can provide free-form text
 *     default_option_id: ID of default/recommended option
 * 
 * Examples:
 *     >>> data = ClarificationRequestEventData(
 *     ...     clarification_id="clar_abc123",
 *     ...     question="What size warehouse would you like?",
 *     ...     options=[
 *     ...         {"id": "1", "label": "Small (X-Small)"},
 *     ...         {"id": "2", "label": "Medium (Small)"},
 *     ...         {"id": "3", "label": "Large (Medium/Large)"},
 *     ...     ],
 *     ...     allow_custom_response=True,
 *     ...     default_option_id="2",
 *     ... )
 */
export interface ClarificationRequestEventData {
  /** Unique identifier for this clarification request */
  clarification_id: string;
  /** The clarification question being asked */
  question: string;
  /** Available options (id, label pairs) */
  options?: Array<Record<string, string>> | null;
  /** Whether user can provide free-form text instead of selecting option */
  allow_custom_response?: boolean;
  /** ID of default/recommended option */
  default_option_id?: string | null;
}

/**
 * Code line reference.
 */
export interface CodeLineRef {
  /** Object name */
  object: string;
  /** Line number */
  line: number;
}

/**
 * Reference material link.
 */
export interface ReferenceMaterial {
  /** Reference title */
  title: string;
  /** Reference URL */
  url?: string;
  /** Cloud provider */
  cloud?: string;
}

/**
 * Current system state (supports all domains).
 */
export interface CurrentState {
  /** Cloud provider */
  cloud_provider: string;
  /** Runtime version */
  runtime_version?: string;
  /** Warehouse tier */
  warehouse_tier?: string;
  /** Warehouse size */
  warehouse_size?: string;
  /** Cluster type */
  cluster_type?: string;
  /** Cluster size */
  cluster_size?: string;
  /** Table format (Delta, Parquet, etc.) */
  table_format?: string;
  /** Resource type (Cluster, Warehouse) */
  resource_type?: string;
  /** Resource size configuration */
  resource_size?: string;
  /** Key symptoms */
  key_symptoms?: Array<string>;
}

/**
 * Analysis summary.
 */
export interface Summary {
  /** Overview text */
  overview: string;
  /** Current state */
  current_state: CurrentState;
}

/**
 * Detailed next step action for interactive conversation flow.
 * 
 * Used by all agent types to present structured, actionable options to users.
 * This format enables the routing system to handle cross-domain handoffs,
 * tool calls, and continuation within the same agent.
 * 
 * Attributes:
 *     id: Unique identifier for this step
 *     number: Display number for user selection (1-9)
 *     title: Short, actionable title (3-7 words)
 *     description: Longer explanation of what this action does
 *     action_type: Type of action (continue, route, tool_call)
 *     target_agent: Target agent ID for routing (if action_type=route)
 *     tool_name: Tool name for tool calls (if action_type=tool_call)
 *     parameters: Parameters to pass to target agent/tool
 * 
 * Example:
 *     >>> step = NextStepAction(
 *     ...     id="analyze_table_1",
 *     ...     number=1,
 *     ...     title="Analyze table optimization opportunities",
 *     ...     description="Deep dive into table partitioning and statistics",
 *     ...     action_type="route",
 *     ...     target_agent="uc",
 *     ...     tool_name=None,
 *     ...     parameters={"table_names": ["sales", "customers"]}
 *     ... )
 */
export interface NextStepAction {
  /** Unique identifier for this step */
  id: string;
  /** Display number for user selection */
  number: number;
  /** Short, actionable title */
  title: string;
  /** Longer explanation of the action */
  description?: string | null;
  /** Type of action (continue, route, tool_call) */
  action_type: "continue" | "route" | "tool_call";
  /** Target agent ID for routing */
  target_agent?: string | null;
  /** Tool name for tool calls */
  tool_name?: string | null;
  /** Action parameters */
  parameters?: Record<string, any> | null;
}

/**
 * Effort estimate for a recommendation.
 */
export interface EffortEstimate {
  /** Effort level */
  level: "low" | "medium" | "high";
  /** Estimated hours */
  estimate_hours?: number | null;
}

/**
 * Impact estimate for a recommendation.
 */
export interface ImpactEstimate {
  /** Query time impact percentage */
  query_time_pct: number;
  /** Data read impact percentage */
  data_read_pct?: number;
  /** Shuffle impact percentage */
  shuffle_pct?: number;
  /** Cost impact percentage */
  cost_pct?: number;
  /** Confidence level */
  confidence: "low" | "medium" | "high";
}

/**
 * Fix suggestion (unified for query and job optimization).
 */
export interface Fix {
  /** Fix type */
  type: "SQL_REWRITE" | "DDL_DML" | "CONFIG_CHANGE" | "PROCESS_CHANGE" | "CODE_REWRITE" | "CLUSTER_TUNING" | "DATA_OPTIMIZATION";
  /** Code snippet */
  snippet: string;
  /** Additional notes */
  notes?: string;
}

/**
 * Evidence supporting a finding.
 */
export interface Proofs {
  /** Evidence items */
  evidence?: Array<string>;
  /** Code line references */
  code_line_refs?: Array<CodeLineRef>;
  /** Reference materials */
  references?: Array<ReferenceMaterial>;
}

/**
 * Query or job optimization finding (unified schema v1/v2).
 * 
 * Supports all agent domains including UC-specific categories:
 * - LINEAGE: Data lineage findings (UC Agent)
 * - POLICY: Access control / governance findings (UC Agent)
 * - STORAGE: Storage optimization findings (UC Agent)
 */
export interface Finding {
  /** Finding identifier */
  id: string;
  /** Category */
  category: "QUERY" | "TABLE" | "WAREHOUSE" | "JOB_CONFIG" | "CODE" | "CLUSTER" | "DATA" | "RUNTIME" | "SCHEMA" | "RESOURCE" | "LINEAGE" | "POLICY" | "STORAGE";
  /** Finding title */
  title: string;
  /** Recommendation text */
  recommendation: string;
  /** Fix suggestions */
  fixes?: Array<Fix>;
  /** Supporting evidence (nested structure) */
  proofs: Proofs;
  /** Impact estimate */
  impact_estimate: ImpactEstimate;
  /** Effort estimate */
  effort: EffortEstimate;
  /** Risk items */
  risks?: Array<string>;
  /** Priority rank */
  rank: number;
}

/**
 * Query rewrite suggestion.
 */
export interface QueryRewrite {
  /** Is rewrite applicable */
  applicable: boolean;
  /** Rewritten SQL */
  sql?: string;
  /** Rewrite notes */
  notes?: string;
}

/**
 * Complete analysis results.
 */
export interface Analysis {
  /** Analysis findings */
  findings: Array<Finding>;
  /** Query rewrite suggestion (query domain only) */
  query_rewrite?: QueryRewrite | null;
}

/**
 * Top cost contributor detail.
 * 
 * Attributes:
 *     id: Resource identifier (job_id, warehouse_id, cluster_id)
 *     name: Resource name
 *     value: Metric value (cost, DBUs, etc.)
 *     unit: Metric unit (USD, DBU, or other)
 *     notes: Additional context or notes
 * 
 * Example:
 *     >>> contributor = TopContributor(
 *     ...     id="job_123",
 *     ...     name="ETL Pipeline",
 *     ...     value=844.65,
 *     ...     unit="USD",
 *     ...     notes="31 runs in period"
 *     ... )
 */
export interface TopContributor {
  /** Resource identifier */
  id: string;
  /** Resource name */
  name: string;
  /** Metric value */
  value: number;
  /** Metric unit (USD, DBU, or other) */
  unit: string;
  /** Additional context or notes */
  notes?: string;
}

/**
 * Cost impact estimate for a finding.
 * 
 * Attributes:
 *     current_monthly_cost: Current monthly spend for this resource
 *     projected_savings_monthly: Expected monthly savings if recommendation applied
 *     cost_unit: Cost unit (dollar | dbu)
 *     savings_pct: Percentage reduction in cost
 *     confidence: Confidence level (low, medium, high)
 * 
 * Example:
 *     >>> impact = CostImpact(
 *     ...     current_monthly_cost=2400.00,
 *     ...     projected_savings_monthly=2040.00,
 *     ...     cost_unit="dollar",
 *     ...     savings_pct=85.0,
 *     ...     confidence="high"
 *     ... )
 */
export interface CostImpact {
  /** Current monthly spend for this resource */
  current_monthly_cost: number;
  /** Expected monthly savings if recommendation applied */
  projected_savings_monthly: number;
  /** Cost unit (dollar or dbu) */
  cost_unit: "dollar" | "dbu";
  /** Percentage reduction in cost */
  savings_pct: number;
  /** Confidence level in savings estimate */
  confidence: "low" | "medium" | "high";
}

/**
 * Aggregated cost statistics for the analysis period.
 * 
 * Attributes:
 *     primary_metric: Primary metric column name (e.g., "list_cost", "run_dbus")
 *     primary_metric_unit: Primary metric unit (USD or DBU)
 *     total: Total value of primary metric
 *     mean: Mean value of primary metric
 *     max: Maximum value of primary metric
 *     period: Analysis period description (e.g., "30 days", "last month")
 *     cost_trend: Cost trend direction (increasing, stable, decreasing)
 *     top_contributors: Top cost contributors with details
 * 
 * Example:
 *     >>> summary = CostSummary(
 *     ...     primary_metric="list_cost",
 *     ...     primary_metric_unit="USD",
 *     ...     total=45000.00,
 *     ...     mean=1500.00,
 *     ...     max=5000.00,
 *     ...     period="30 days",
 *     ...     cost_trend="increasing",
 *     ...     top_contributors=[TopContributor(...)]
 *     ... )
 */
export interface CostSummary {
  /** Primary metric column name */
  primary_metric: string;
  /** Primary metric unit (USD or DBU) */
  primary_metric_unit: string;
  /** Total value of primary metric */
  total: number;
  /** Mean value of primary metric */
  mean: number;
  /** Maximum value of primary metric */
  max: number;
  /** Analysis period description (e.g., "30 days", "last month") */
  period: string;
  /** Cost trend direction */
  cost_trend: "increasing" | "stable" | "decreasing";
  /** Top cost contributors with detailed information */
  top_contributors?: Array<TopContributor>;
}

/**
 * Chart/visualization recommendation for query results.
 * 
 * Provides frontend with metadata to render appropriate chart types
 * for the data returned by analytics queries.
 * 
 * Attributes:
 *     recommended_chart: Recommended chart type (line, bar, area, pie, scatter, table)
 *     primary_metric: Y-axis metric column name
 *     primary_dimension: X-axis dimension column name
 *     time_dimension: Time column for time-series charts (optional)
 *     secondary_metrics: Additional metrics to plot (optional)
 *     chart_config: Chart-specific configuration for rendering (optional)
 *     notes: Visualization guidance notes
 *     data_reference: Cache key for query results (for frontend chart rendering)
 *     has_visualization: Whether a chart is available (False for table-only)
 * 
 * Example:
 *     >>> viz = VisualizationRecommendation(
 *     ...     recommended_chart="line",
 *     ...     primary_metric="total_cost",
 *     ...     primary_dimension="usage_date",
 *     ...     time_dimension="usage_date",
 *     ...     notes="Use line chart to show cost trends over time",
 *     ...     data_reference="data_ref_abc123",
 *     ...     has_visualization=True,
 *     ... )
 */
export interface VisualizationRecommendation {
  /** Recommended chart type */
  recommended_chart: "line" | "bar" | "area" | "pie" | "scatter" | "table";
  /** Y-axis metric column name */
  primary_metric: string;
  /** X-axis dimension column name */
  primary_dimension: string;
  /** Time column for time-series charts (optional) */
  time_dimension?: string | null;
  /** Additional metrics to plot */
  secondary_metrics?: Array<string>;
  /** Chart-specific configuration for rendering (null for table views) */
  chart_config: Record<string, any> | null;
  /** Visualization guidance notes */
  notes?: string;
  /** Cache key for query results (required for frontend data fetching) */
  data_reference: string | null;
  /** Whether a chart is available (False for table-only, True for charts) */
  has_visualization: boolean;
}

/**
 * Cost/usage finding for analytics reports.
 * 
 * Represents a cost optimization opportunity with estimated savings
 * and implementation details.
 * 
 * Attributes:
 *     id: Finding identifier (e.g., "finops_001")
 *     category: Finding category (cost optimization, waste detection, etc.)
 *     title: Finding title (concise description)
 *     recommendation: Cost-saving action to take
 *     cost_impact: Cost impact estimate
 *     effort: Implementation effort estimate
 *     rank: Priority rank by savings percentage (1 = highest)
 * 
 * Example:
 *     >>> finding = AnalyticsFinding(
 *     ...     id="finops_001",
 *     ...     category="WASTE_DETECTION",
 *     ...     title="Idle warehouse consuming $2,400/month",
 *     ...     recommendation="Enable auto-stop after 10 minutes",
 *     ...     cost_impact=CostImpact(...),
 *     ...     effort=EffortEstimate(level="low", estimate_hours=0.5),
 *     ...     rank=1
 *     ... )
 */
export interface AnalyticsFinding {
  /** Finding identifier */
  id: string;
  /** Finding category */
  category: "COST_OPTIMIZATION" | "WASTE_DETECTION" | "UTILIZATION" | "PERFORMANCE_COST" | "ATTRIBUTION" | "ANOMALY";
  /** Finding title (concise description) */
  title: string;
  /** Cost-saving action to take */
  recommendation: string;
  /** Cost impact estimate */
  cost_impact: CostImpact;
  /** Implementation effort estimate */
  effort: EffortEstimate;
  /** Priority rank by savings percentage (1 = highest) */
  rank: number;
}

/**
 * Base class for all agent reports.
 * 
 * Common fields present in every agent response regardless of specialization.
 * Subclasses add domain-specific fields.
 * 
 * Attributes:
 *     report_type: Report type discriminator (advisor, analytics, diagnostic, etc.)
 *     summary: High-level summary with overview and current state
 *     next_steps: Suggested next actions (1-5 steps)
 * 
 * Design:
 *     - Extra fields allowed for subclass extensions
 *     - Frozen for immutability
 *     - report_type used for runtime type discrimination
 */
export interface AgentReport {
  /** Report type discriminator (advisor, analytics, diagnostic, etc.) */
  report_type: string;
  /** High-level summary */
  summary: Summary;
  /** Suggested next actions for the conversation */
  next_steps: Array<NextStepAction>;
}

/**
 * Optimization advisor report for performance-focused agents.
 * 
 * Used by: query, job, table, compute agents
 * Focus: Performance optimization, configuration tuning, resource efficiency
 * 
 * Attributes:
 *     report_type: Always "advisor"
 *     summary: Analysis summary with current state
 *     analysis: Optimization findings with impact/effort estimates
 *     next_steps: Suggested actions
 *     query_rewrite: Optional SQL rewrite (query agent only)
 * 
 * Example:
 *     >>> report = AdvisorReport(
 *     ...     summary=Summary(
 *     ...         overview="Query is slow due to missing index",
 *     ...         current_state=CurrentState(cloud_provider="AWS")
 *     ...     ),
 *     ...     analysis=Analysis(findings=[...]),
 *     ...     next_steps=[NextStepAction(
 *     ...         id="add_index_1",
 *     ...         number=1,
 *     ...         title="Add index to table",
 *     ...         description="Create index on user_id column",
 *     ...         action_type="continue",
 *     ...         target_agent=None,
 *     ...         tool_name=None,
 *     ...         parameters=None
 *     ...     )]
 *     ... )
 *     >>> assert report.report_type == "advisor"
 */
export interface AdvisorReport extends AgentReport {
  report_type: "advisor";
  /** High-level summary */
  summary: Summary;
  /** Suggested next actions for the conversation */
  next_steps: Array<NextStepAction>;
  /** Optimization findings with impact/effort estimates */
  analysis: Analysis;
  /** Data table for listing/enumeration requests */
  data_table?: DataTable | null;
}

/**
 * Analytics report for cost/usage-focused agents.
 * 
 * Used by: analytics (FinOps) agent
 * Focus: Cost analysis, usage trends, resource attribution, waste detection
 * 
 * Attributes:
 *     report_type: Always "analytics"
 *     summary: Cost analysis summary
 *     findings: Cost/usage findings ranked by savings potential
 *     cost_summary: Aggregated cost statistics
 *     visualization: Chart recommendation (optional)
 *     next_steps: Suggested actions
 * 
 * Example:
 *     >>> report = AnalyticsReport(
 *     ...     summary=Summary(overview="Total spend: $45k/month"),
 *     ...     findings=[AnalyticsFinding(...)],
 *     ...     cost_summary=CostSummary(...),
 *     ...     visualization=VisualizationRecommendation(...),
 *     ...     next_steps=[NextStepAction(
 *     ...         id="implement_savings_1",
 *     ...         number=1,
 *     ...         title="Implement top cost savings",
 *     ...         description="Apply configuration changes to reduce spending",
 *     ...         action_type="continue",
 *     ...         target_agent=None,
 *     ...         tool_name=None,
 *     ...         parameters=None
 *     ...     )]
 *     ... )
 *     >>> assert report.report_type == "analytics"
 */
export interface AnalyticsReport extends AgentReport {
  report_type: "analytics";
  /** High-level summary */
  summary: Summary;
  /** Suggested next actions for the conversation */
  next_steps: Array<NextStepAction>;
  /** Cost/usage findings ranked by savings potential */
  findings: Array<AnalyticsFinding>;
  /** Aggregated cost statistics */
  cost_summary: CostSummary;
  /** Chart recommendation for results */
  visualization?: VisualizationRecommendation | null;
}
