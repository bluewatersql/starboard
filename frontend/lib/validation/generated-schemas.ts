/**
 * AUTO-GENERATED FILE - DO NOT EDIT
 * 
 * Generated from Pydantic models by scripts/generate_types.py
 * To regenerate: python scripts/generate_types.py
 */

import { z } from "zod";

// Import frontend-only schemas (referenced by generated code but not in backend)
import {
  ToolCallSchema,
} from "./extended-schemas";

// Stub schemas — referenced by generated code but not defined in backend models
export const FileAttachmentSchema = z.object({
  name: z.string(),
  content_type: z.string(),
  content: z.string(),
  size: z.number().optional(),
});

export const DataTableSchema = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.record(z.string(), z.unknown())),
  row_count: z.number().optional(),
});

/**
 * Event types for server-sent events (SSE).
 */
export const EventTypeSchema = z.enum(["thinking", "step.complete", "error", "tool_start", "tool.call.start", "tool.progress", "tool_end", "tool.call.result", "user_input_request", "user_input_response", "final_output", "next_steps", "clarification.request", "handoff", "routing.decision", "friendly_name.update", "agent.transition", "checkpoint", "interrupt.received", "replan", "solicitation", "message.start", "message.delta", "message.end", "step.start"]);
export type EventType = z.infer<typeof EventTypeSchema>;

/**
 * Role of message sender.
 */
export const MessageRoleSchema = z.enum(["user", "assistant", "system", "tool"]);
export type MessageRole = z.infer<typeof MessageRoleSchema>;

/**
 * Status of message processing.
 */
export const MessageStatusSchema = z.enum(["pending", "processing", "completed", "failed"]);
export type MessageStatus = z.infer<typeof MessageStatusSchema>;

/**
 * User feedback rating for agent responses.
 */
export const FeedbackRatingEnumSchema = z.enum(["positive", "negative"]);
export type FeedbackRatingEnum = z.infer<typeof FeedbackRatingEnumSchema>;

/**
 * Categories for negative feedback.
 */
export const FeedbackCategoryEnumSchema = z.enum(["inaccurate", "too_vague", "too_verbose", "irrelevant", "missing_info", "bad_format", "other"]);
export type FeedbackCategoryEnum = z.infer<typeof FeedbackCategoryEnumSchema>;

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
export const DomainModelConfigSchema = z.object({
  /** Human-readable domain name */
  domain: z.string(),
  /** Internal domain key */
  domain_key: z.string(),
  /** LLM model identifier for this domain */
  model: z.string(),
});
export type DomainModelConfig = z.infer<typeof DomainModelConfigSchema>;

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
export const ConversationConfigSchema = z.object({
  /** LLM sampling temperature */
  temperature: z.number(),
  /** Maximum tokens in response */
  max_tokens: z.number().int(),
  /** Automatically use model's maximum output token limit */
  use_max_model_tokens: z.boolean(),
  /** Disable destructive operations if True */
  safe_mode: z.boolean(),
  /** Stream responses via SSE */
  streaming: z.boolean(),
  /** LLM model identifier */
  model: z.string(),
  /** Enforce session token budget limits */
  budget_enforced: z.boolean(),
  /** Maximum reasoning steps allowed */
  max_steps: z.number().int(),
  /** Logging verbosity level */
  logging_level: z.string(),
  /** Per-domain model overrides (domain_key -> model_name) */
  domain_model_overrides: z.record(z.string(), z.string()).nullable().optional(),
  /** Per-domain temperature overrides (domain_key -> temperature) */
  domain_temperature_overrides: z.record(z.string(), z.number()).nullable().optional(),
  /** Force OFFLINE mode - disables tools that require Databricks API calls */
  offline_mode: z.boolean(),
});
export type ConversationConfig = z.infer<typeof ConversationConfigSchema>;

/**
 * API message model.
 */
export const MessageSchema = z.object({
  id: z.string(),
  conversation_id: z.string(),
  role: z.enum(["user", "assistant", "system", "tool"]),
  content: z.string(),
  timestamp: z.string().datetime(),
  status: z.enum(["pending", "processing", "completed", "failed"]),
  metadata: z.record(z.string(), z.any()),
  /** Tool calls executed in this message */
  tool_calls: z.array(ToolCallSchema),
  /** Next step options for interactive conversation flow */
  next_steps: z.array(z.any()).nullable().optional(),
});
export type Message = z.infer<typeof MessageSchema>;

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
export const ConversationResponseSchema = z.object({
  /** Unique conversation identifier */
  conversation_id: z.string(),
  /** User who owns the conversation */
  user_id: z.string().nullable().optional(),
  /** Human-readable conversation title */
  friendly_name: z.string(),
  /** UTC timestamp when conversation was created */
  created_at: z.string().datetime(),
  /** Conversation configuration */
  config: ConversationConfigSchema,
  /** Domain-specific model configurations (non-default models) */
  domain_models: z.array(DomainModelConfigSchema),
});
export type ConversationResponse = z.infer<typeof ConversationResponseSchema>;

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
export const ChatEventSchema = z.object({
  /** Unique event identifier */
  event_id: z.string(),
  /** Type of event */
  type: z.enum(["thinking", "step.complete", "error", "tool_start", "tool.call.start", "tool.progress", "tool_end", "tool.call.result", "user_input_request", "user_input_response", "final_output", "next_steps", "clarification.request", "handoff", "routing.decision", "friendly_name.update", "agent.transition", "checkpoint", "interrupt.received", "replan", "solicitation", "message.start", "message.delta", "message.end", "step.start"]),
  /** Event payload */
  data: z.record(z.string(), z.any()),
  /** UTC timestamp when event was emitted */
  timestamp: z.string().datetime(),
});
export type ChatEvent = z.infer<typeof ChatEventSchema>;

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
export const CreateConversationRequestSchema = z.object({
  /** Initial context for the conversation */
  context: z.record(z.string(), z.any()).nullable().optional(),
  /** Conversation configuration */
  config: ConversationConfigSchema.nullable().optional(),
  /** Optional initial message to send immediately after creation (UX vNext Phase 1) */
  initial_message: z.string().nullable().optional(),
  /** Optional metadata for the conversation */
  metadata: z.record(z.string(), z.any()).nullable().optional(),
});
export type CreateConversationRequest = z.infer<typeof CreateConversationRequestSchema>;

/**
 * Request to send a message in a conversation.
 * 
 * Supports file attachments for artifact analysis. Large files (>50KB)
 * are automatically routed to the diagnostic agent for incremental discovery.
 */
export const SendMessageRequestSchema = z.object({
  /** Message content */
  content: z.string(),
  /** Optional file attachments */
  attachments: z.array(FileAttachmentSchema).nullable().optional(),
  /** Optional metadata */
  metadata: z.record(z.string(), z.any()).nullable().optional(),
});
export type SendMessageRequest = z.infer<typeof SendMessageRequestSchema>;

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
export const SubmitFeedbackRequestSchema = z.object({
  /** ID of the message being rated */
  message_id: z.string(),
  /** User's rating (positive or negative) */
  rating: z.enum(["positive", "negative"]),
  /** Categories for negative feedback (required for negative rating) */
  categories: z.array(z.enum(["inaccurate", "too_vague", "too_verbose", "irrelevant", "missing_info", "bad_format", "other"])).nullable().optional(),
  /** Optional free-text comment */
  comment: z.string().nullable().optional(),
});
export type SubmitFeedbackRequest = z.infer<typeof SubmitFeedbackRequestSchema>;

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
export const RespondToClarificationRequestSchema = z.object({
  /** Clarification ID from the clarification.request event */
  clarification_id: z.string(),
  /** Type of response provided */
  response_type: z.enum(["option_selected", "custom_text"]),
  /** ID of selected option (required if response_type=option_selected) */
  selected_option_id: z.string().nullable().optional(),
  /** Free-form text response (required if response_type=custom_text) */
  custom_text: z.string().nullable().optional(),
  /** Optional additional context */
  metadata: z.record(z.string(), z.any()).nullable().optional(),
});
export type RespondToClarificationRequest = z.infer<typeof RespondToClarificationRequestSchema>;

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
export const RespondToClarificationResponseSchema = z.object({
  /** Unique identifier for this response */
  response_id: z.string(),
  /** ID of the clarification being answered */
  clarification_id: z.string(),
  /** Processing status (accepted, processing, completed, error) */
  status: z.string(),
  /** The original query enriched with clarification response */
  enriched_query: z.string().nullable().optional(),
  /** Status message */
  message: z.string(),
  /** Timestamp of response */
  created_at: z.string().datetime(),
});
export type RespondToClarificationResponse = z.infer<typeof RespondToClarificationResponseSchema>;

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
export const RespondToSolicitationRequestSchema = z.object({
  /** Solicitation ID being answered */
  solicitation_id: z.string(),
  /** User's response/answer */
  content: z.string(),
  /** Additional context */
  metadata: z.record(z.string(), z.any()).nullable().optional(),
});
export type RespondToSolicitationRequest = z.infer<typeof RespondToSolicitationRequestSchema>;

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
export const RespondToSolicitationResponseSchema = z.object({
  /** Unique response identifier */
  response_id: z.string(),
  /** Processing status */
  status: z.string(),
  /** Solicitation that was answered */
  solicitation_id: z.string(),
  /** User response time in milliseconds */
  response_time_ms: z.number(),
});
export type RespondToSolicitationResponse = z.infer<typeof RespondToSolicitationResponseSchema>;

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
export const ClarificationRequestEventDataSchema = z.object({
  /** Unique identifier for this clarification request */
  clarification_id: z.string(),
  /** The clarification question being asked */
  question: z.string(),
  /** Available options (id, label pairs) */
  options: z.array(z.record(z.string(), z.string())).nullable().optional(),
  /** Whether user can provide free-form text instead of selecting option */
  allow_custom_response: z.boolean(),
  /** ID of default/recommended option */
  default_option_id: z.string().nullable().optional(),
});
export type ClarificationRequestEventData = z.infer<typeof ClarificationRequestEventDataSchema>;

/**
 * Code line reference.
 */
export const CodeLineRefSchema = z.object({
  /** Object name */
  object: z.string(),
  /** Line number */
  line: z.number().int(),
});
export type CodeLineRef = z.infer<typeof CodeLineRefSchema>;

/**
 * Reference material link.
 */
export const ReferenceMaterialSchema = z.object({
  /** Reference title */
  title: z.string(),
  /** Reference URL */
  url: z.string(),
  /** Cloud provider */
  cloud: z.string(),
});
export type ReferenceMaterial = z.infer<typeof ReferenceMaterialSchema>;

/**
 * Current system state (supports all domains).
 */
export const CurrentStateSchema = z.object({
  /** Cloud provider */
  cloud_provider: z.string(),
  /** Runtime version */
  runtime_version: z.string(),
  /** Warehouse tier */
  warehouse_tier: z.string(),
  /** Warehouse size */
  warehouse_size: z.string(),
  /** Cluster type */
  cluster_type: z.string(),
  /** Cluster size */
  cluster_size: z.string(),
  /** Table format (Delta, Parquet, etc.) */
  table_format: z.string(),
  /** Resource type (Cluster, Warehouse) */
  resource_type: z.string(),
  /** Resource size configuration */
  resource_size: z.string(),
  /** Key symptoms */
  key_symptoms: z.array(z.string()),
});
export type CurrentState = z.infer<typeof CurrentStateSchema>;

/**
 * Analysis summary.
 */
export const SummarySchema = z.object({
  /** Overview text */
  overview: z.string(),
  /** Current state */
  current_state: CurrentStateSchema,
});
export type Summary = z.infer<typeof SummarySchema>;

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
export const NextStepActionSchema = z.object({
  /** Unique identifier for this step */
  id: z.string(),
  /** Display number for user selection */
  number: z.number().int(),
  /** Short, actionable title */
  title: z.string(),
  /** Longer explanation of the action */
  description: z.string().nullable().optional(),
  /** Type of action (continue, route, tool_call) */
  action_type: z.enum(["continue", "route", "tool_call"]),
  /** Target agent ID for routing */
  target_agent: z.string().nullable().optional(),
  /** Tool name for tool calls */
  tool_name: z.string().nullable().optional(),
  /** Action parameters */
  parameters: z.record(z.string(), z.any()).nullable().optional(),
});
export type NextStepAction = z.infer<typeof NextStepActionSchema>;

/**
 * Effort estimate for a recommendation.
 */
export const EffortEstimateSchema = z.object({
  /** Effort level */
  level: z.enum(["low", "medium", "high"]),
  /** Estimated hours */
  estimate_hours: z.number().nullable().optional(),
});
export type EffortEstimate = z.infer<typeof EffortEstimateSchema>;

/**
 * Impact estimate for a recommendation.
 */
export const ImpactEstimateSchema = z.object({
  /** Query time impact percentage */
  query_time_pct: z.number(),
  /** Data read impact percentage */
  data_read_pct: z.number(),
  /** Shuffle impact percentage */
  shuffle_pct: z.number(),
  /** Cost impact percentage */
  cost_pct: z.number(),
  /** Confidence level */
  confidence: z.enum(["low", "medium", "high"]),
});
export type ImpactEstimate = z.infer<typeof ImpactEstimateSchema>;

/**
 * Fix suggestion (unified for query and job optimization).
 */
export const FixSchema = z.object({
  /** Fix type */
  type: z.enum(["SQL_REWRITE", "DDL_DML", "CONFIG_CHANGE", "PROCESS_CHANGE", "CODE_REWRITE", "CLUSTER_TUNING", "DATA_OPTIMIZATION"]),
  /** Code snippet */
  snippet: z.string(),
  /** Additional notes */
  notes: z.string(),
});
export type Fix = z.infer<typeof FixSchema>;

/**
 * Evidence supporting a finding.
 */
export const ProofsSchema = z.object({
  /** Evidence items */
  evidence: z.array(z.string()),
  /** Code line references */
  code_line_refs: z.array(CodeLineRefSchema),
  /** Reference materials */
  references: z.array(ReferenceMaterialSchema),
});
export type Proofs = z.infer<typeof ProofsSchema>;

/**
 * Query or job optimization finding (unified schema v1/v2).
 * 
 * Supports all agent domains including UC-specific categories:
 * - LINEAGE: Data lineage findings (UC Agent)
 * - POLICY: Access control / governance findings (UC Agent)
 * - STORAGE: Storage optimization findings (UC Agent)
 */
export const FindingSchema = z.object({
  /** Finding identifier */
  id: z.string(),
  /** Category */
  category: z.enum(["QUERY", "TABLE", "WAREHOUSE", "JOB_CONFIG", "CODE", "CLUSTER", "DATA", "RUNTIME", "SCHEMA", "RESOURCE", "LINEAGE", "POLICY", "STORAGE"]),
  /** Finding title */
  title: z.string(),
  /** Recommendation text */
  recommendation: z.string(),
  /** Fix suggestions */
  fixes: z.array(FixSchema),
  /** Supporting evidence (nested structure) */
  proofs: ProofsSchema,
  /** Impact estimate */
  impact_estimate: ImpactEstimateSchema,
  /** Effort estimate */
  effort: EffortEstimateSchema,
  /** Risk items */
  risks: z.array(z.string()),
  /** Priority rank */
  rank: z.number().int(),
});
export type Finding = z.infer<typeof FindingSchema>;

/**
 * Query rewrite suggestion.
 */
export const QueryRewriteSchema = z.object({
  /** Is rewrite applicable */
  applicable: z.boolean(),
  /** Rewritten SQL */
  sql: z.string(),
  /** Rewrite notes */
  notes: z.string(),
});
export type QueryRewrite = z.infer<typeof QueryRewriteSchema>;

/**
 * Complete analysis results.
 */
export const AnalysisSchema = z.object({
  /** Analysis findings */
  findings: z.array(FindingSchema),
  /** Query rewrite suggestion (query domain only) */
  query_rewrite: QueryRewriteSchema.nullable().optional(),
});
export type Analysis = z.infer<typeof AnalysisSchema>;

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
export const TopContributorSchema = z.object({
  /** Resource identifier */
  id: z.string(),
  /** Resource name */
  name: z.string(),
  /** Metric value */
  value: z.number(),
  /** Metric unit (USD, DBU, or other) */
  unit: z.string(),
  /** Additional context or notes */
  notes: z.string(),
});
export type TopContributor = z.infer<typeof TopContributorSchema>;

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
export const CostImpactSchema = z.object({
  /** Current monthly spend for this resource */
  current_monthly_cost: z.number(),
  /** Expected monthly savings if recommendation applied */
  projected_savings_monthly: z.number(),
  /** Cost unit (dollar or dbu) */
  cost_unit: z.enum(["dollar", "dbu"]),
  /** Percentage reduction in cost */
  savings_pct: z.number(),
  /** Confidence level in savings estimate */
  confidence: z.enum(["low", "medium", "high"]),
});
export type CostImpact = z.infer<typeof CostImpactSchema>;

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
export const CostSummarySchema = z.object({
  /** Primary metric column name */
  primary_metric: z.string(),
  /** Primary metric unit (USD or DBU) */
  primary_metric_unit: z.string(),
  /** Total value of primary metric */
  total: z.number(),
  /** Mean value of primary metric */
  mean: z.number(),
  /** Maximum value of primary metric */
  max: z.number(),
  /** Analysis period description (e.g., "30 days", "last month") */
  period: z.string(),
  /** Cost trend direction */
  cost_trend: z.enum(["increasing", "stable", "decreasing"]),
  /** Top cost contributors with detailed information */
  top_contributors: z.array(TopContributorSchema),
});
export type CostSummary = z.infer<typeof CostSummarySchema>;

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
export const VisualizationRecommendationSchema = z.object({
  /** Recommended chart type */
  recommended_chart: z.enum(["line", "bar", "area", "pie", "scatter", "table"]),
  /** Y-axis metric column name */
  primary_metric: z.string(),
  /** X-axis dimension column name */
  primary_dimension: z.string(),
  /** Time column for time-series charts (optional) */
  time_dimension: z.string().nullable().optional(),
  /** Additional metrics to plot */
  secondary_metrics: z.array(z.string()),
  /** Chart-specific configuration for rendering (null for table views) */
  chart_config: z.record(z.string(), z.any()).nullable().optional(),
  /** Visualization guidance notes */
  notes: z.string(),
  /** Cache key for query results (required for frontend data fetching) */
  data_reference: z.string().nullable().optional(),
  /** Whether a chart is available (False for table-only, True for charts) */
  has_visualization: z.boolean(),
});
export type VisualizationRecommendation = z.infer<typeof VisualizationRecommendationSchema>;

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
export const AnalyticsFindingSchema = z.object({
  /** Finding identifier */
  id: z.string(),
  /** Finding category */
  category: z.enum(["COST_OPTIMIZATION", "WASTE_DETECTION", "UTILIZATION", "PERFORMANCE_COST", "ATTRIBUTION", "ANOMALY"]),
  /** Finding title (concise description) */
  title: z.string(),
  /** Cost-saving action to take */
  recommendation: z.string(),
  /** Cost impact estimate */
  cost_impact: CostImpactSchema,
  /** Implementation effort estimate */
  effort: EffortEstimateSchema,
  /** Priority rank by savings percentage (1 = highest) */
  rank: z.number().int(),
});
export type AnalyticsFinding = z.infer<typeof AnalyticsFindingSchema>;

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
export const AgentReportSchema = z.object({
  /** Report type discriminator (advisor, analytics, diagnostic, etc.) */
  report_type: z.string(),
  /** High-level summary */
  summary: SummarySchema,
  /** Suggested next actions for the conversation */
  next_steps: z.array(NextStepActionSchema),
});
export type AgentReport = z.infer<typeof AgentReportSchema>;

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
export const AdvisorReportSchema = AgentReportSchema.extend({
  report_type: z.literal("advisor"),
  /** High-level summary */
  summary: SummarySchema,
  /** Suggested next actions for the conversation */
  next_steps: z.array(NextStepActionSchema),
  /** Optimization findings with impact/effort estimates */
  analysis: AnalysisSchema,
  /** Data table for listing/enumeration requests */
  data_table: DataTableSchema.nullable().optional(),
});
export type AdvisorReport = z.infer<typeof AdvisorReportSchema>;

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
export const AnalyticsReportSchema = AgentReportSchema.extend({
  report_type: z.literal("analytics"),
  /** High-level summary */
  summary: SummarySchema,
  /** Suggested next actions for the conversation */
  next_steps: z.array(NextStepActionSchema),
  /** Cost/usage findings ranked by savings potential */
  findings: z.array(AnalyticsFindingSchema),
  /** Aggregated cost statistics */
  cost_summary: CostSummarySchema,
  /** Chart recommendation for results */
  visualization: VisualizationRecommendationSchema.nullable().optional(),
});
export type AnalyticsReport = z.infer<typeof AnalyticsReportSchema>;
