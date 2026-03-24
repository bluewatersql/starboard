/**
 * Frontend extensions to generated API types.
 * 
 * This file extends the auto-generated types from generated-api.ts
 * with frontend-specific fields that don't exist in the backend.
 * 
 * DO NOT modify generated-api.ts directly - it will be overwritten.
 * Add frontend-only extensions here instead.
 */

import type {
  Message as GeneratedMessage,
  ConversationResponse as GeneratedConversationResponse,
  ChatEvent as GeneratedStreamingChatEvent,
  DomainModelConfig,
} from './generated-api';

// Import and re-export ALL enums from generated types
import {
  EventType,
  MessageRole,
  MessageStatus,
  FeedbackRatingEnum,
  FeedbackCategoryEnum,
} from './generated-api';

export { 
  EventType, 
  MessageRole, 
  MessageStatus, 
  FeedbackRatingEnum,
  FeedbackCategoryEnum,
};

/**
 * Tool call status - frontend-only type.
 */
export type ToolCallStatus = "completed" | "failed" | "running" | "pending";

/**
 * Agent type - identifies which specialized agent is responding.
 * Maps to backend agent domains.
 */
export type AgentType = 
  | "router"      // IntentRouter - routes queries
  | "query"       // QueryAgent - SQL optimization
  | "job"         // JobAgent - Databricks job analysis
  | "table"       // TableAgent - Schema/lineage (deprecated, use "uc")
  | "uc"          // Unity Catalog Agent - Metadata/lineage/governance
  | "warehouse"   // WarehouseAgent - SQL warehouse analysis
  | "analytics"   // AnalyticsAgent - FinOps/cost analysis
  | "diagnostic"  // DiagnosticAgent - Troubleshooting
  | "cluster"     // ClusterAgent - Databricks cluster configuration
  | "compute"     // ComputeAgent - Legacy (kept for backward compatibility)
  | "discovery"   // DiscoveryAgent - Workspace health assessment
  | "general";    // Default/unknown agent

/**
 * Tool position information for inline display (Phase 1 P0-3).
 * 
 * Defines where a tool call should appear within the thinking text content.
 * Used for structured rendering without regex parsing.
 */
export interface ToolPosition {
  /** ID of the tool call to display */
  tool_call_id: string;
  /** Character position in content where tool should appear */
  position: number;
  /** Display mode for this tool */
  display: "inline" | "group" | "hidden";
}

/**
 * Tool call information - frontend-only type.
 * Used for displaying tool execution details in the UI.
 */
export interface ToolCall {
  /** Unique tool call identifier */
  tool_call_id?: string;
  /** Tool name (e.g., "fetch_table_metadata") */
  tool_name: string;
  /** Human-readable tool name (e.g., "Fetch Table Metadata") */
  friendly_name?: string;
  /** Tool execution status */
  status?: ToolCallStatus;
  /** Tool arguments/parameters */
  arguments?: Record<string, unknown>;
  /** Tool execution result */
  result?: unknown;
  /** Error message if tool failed */
  error?: string;
  /** Execution duration in milliseconds */
  duration_ms?: number;
}

/**
 * Extended Message type with frontend-specific fields.
 */
/**
 * Thinking step sub-task for enhanced visualization.
 */
export interface ThinkingSubTask {
  id: string;
  description: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  value?: string | number;
}

/**
 * Call details for tool execution (3-level display).
 */
export interface MessageToolCallDetails {
  toolName: string;
  parameters?: Record<string, unknown>;
  response?: unknown;
  responseIsTruncated?: boolean;
  error?: string;
}

/**
 * Enhanced thinking step for UI visualization.
 */
export interface MessageThinkingStep {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  startTime?: number;
  endTime?: number;
  progress?: number;
  subTasks?: ThinkingSubTask[];
  metadata?: Record<string, unknown>;
  /** Call details for accordion expansion (U3) */
  callDetails?: MessageToolCallDetails;
}

/**
 * File attachment for messages (BB-05).
 */
export interface MessageAttachment {
  /** Attachment ID */
  id?: string;
  /** Filename */
  filename: string;
  /** Size in bytes */
  size?: number;
  /** Content preview (first 500 chars) */
  content_preview?: string;
  /** Full content (for small files) */
  content?: string;
  /** Whether this is a large file stored in cache */
  is_large_file?: boolean;
}

export interface Message extends GeneratedMessage {
  /**
   * Message ID (alternative to 'id' from GeneratedMessage).
   */
  message_id?: string;
  
  /**
   * Trace ID for distributed tracing.
   */
  trace_id?: string;
  
  /**
   * File attachments included with this message (BB-05).
   */
  attachments?: MessageAttachment[];
  
  /**
   * Tool calls executed during this message.
   * Populated via SSE events or history API.
   */
  tool_calls?: ToolCall[];
  
  /**
   * Structured tool position data for inline display (Phase 1 P0-3).
   * 
   * When present, content should be clean text without {{TOOL:...}} markers.
   * Tools are rendered at specified positions using structured data.
   * 
   * This eliminates regex parsing and improves performance.
   */
  tool_positions?: ToolPosition[];
  
  /**
   * Next step options for user to choose from.
   */
  next_steps?: NextStepOption[];
  
  /**
   * Complete report data (for advisor/analytics reports).
   */
  complete_report?: unknown;
  
  /**
   * Enhanced thinking steps for UI visualization.
   * Populated via STEP_START events during streaming.
   */
  thinking_steps?: MessageThinkingStep[];
  
  /**
   * Debug mode flag - shows hidden tools and extra debugging info.
   * Frontend-only field, not persisted to backend.
   */
  debug?: boolean;
  
  /**
   * Agent type that generated this message.
   * Populated via agent.transition events during streaming.
   */
  agent_type?: AgentType;
  
  /**
   * Retry count for failed messages.
   * Frontend-only field for UI state management.
   */
  retry_count?: number;
}

/**
 * Extended ConversationResponse (currently same as generated).
 * Placeholder for future frontend-specific extensions.
 */
export type ConversationResponse = GeneratedConversationResponse;

/**
 * Extended StreamingChatEvent (currently same as generated).
 * Placeholder for future frontend-specific extensions.
 */
export type StreamingChatEvent = GeneratedStreamingChatEvent;

/**
 * Helper type for partial message updates.
 * Used when updating existing messages with new data.
 */
export type MessageUpdate = Partial<Message>;

/**
 * Helper type for new messages being created.
 * Some fields have defaults and don't need to be provided.
 */
export type NewMessage = Omit<Message, 'timestamp' | 'metadata'> & {
  timestamp?: string;
  metadata?: Record<string, unknown>;
};

// ============================================================================
// Frontend-Specific Types (Not in Backend)
// ============================================================================

/**
 * UI file attachment handling.
 * Frontend manages file uploads/downloads.
 */
export interface Attachment {
  attachment_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  url?: string;
}

/**
 * Action types for next step options.
 * Frontend-only enum for UI decision tree.
 */
export enum ActionType {
  CONTINUE = "continue",
  ROUTE = "route",
  TOOL_CALL = "tool_call",
}

/**
 * Next step option for interactive conversations.
 * Structured fields for frontend UI rendering.
 */
export interface NextStepOption {
  id: string;
  number: number;  // 1-9 for keyboard shortcuts
  title: string;
  description: string | null;
  action_type: ActionType;
  target_agent: string | null;
  tool_name: string | null;
  parameters: Record<string, unknown> | null;
}

/**
 * Clarification type categories.
 * Frontend-only enum for UI categorization.
 */
export enum ClarificationType {
  AMBIGUOUS_ENTITY = "ambiguous_entity",
  MISSING_PARAMETER = "missing_parameter",
  VAGUE_REFERENCE = "vague_reference",
  INSUFFICIENT_CONTEXT = "insufficient_context",
}

/**
 * Clarification option for user selection.
 * Structured fields for frontend UI rendering.
 */
export interface ClarificationOption {
  option_id: string;
  display_text: string;
  value: unknown;
  description?: string;
}

/**
 * Frontend server configuration.
 * UI-specific config, not persisted to backend.
 */
export interface ServerConfig {
  default_model: string;
  default_temperature: number;
  default_max_tokens: number;
  domain_model_overrides: Record<string, string>;
  domain_temperature_overrides: Record<string, number>;
}

/**
 * Supported LLM models.
 * Frontend constant for UI model selection.
 */
export const SUPPORTED_MODELS = [
  "databricks-claude-sonnet-4-5",
  "databricks-gpt-5",
  "databricks-gpt-5-1",
  "databricks-gpt-5-mini",
  "databricks-gemini-2.5-pro",
  "databricks-gemini-2.5-flash",
  "databricks-qwen3-next-80b-a3b-instruct",
  "databricks-llama-4-maverick",
  "databricks-meta-llama-3-1-405b-instruct",
  "databricks-meta-llama-3-1-70b-instruct",
] as const;

export type SupportedModel = typeof SUPPORTED_MODELS[number];

/**
 * Logging levels.
 * Frontend constant for UI log level selection.
 */
export const LOGGING_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"] as const;
export type LoggingLevel = typeof LOGGING_LEVELS[number];

/**
 * Conversation metadata aggregation.
 * Frontend-computed statistics, not stored in backend.
 */
export interface ConversationMetadata {
  total_messages: number;
  user_messages: number;
  assistant_messages: number;
  tool_calls: number;
  tokens_used: number;
  cost_usd: number;
  friendly_name?: string;
}

/**
 * Conversation history with messages.
 * Frontend wrapper for rendering conversation view.
 */
export interface ConversationHistory {
  conversation_id: string;
  messages: Message[];
  metadata: ConversationMetadata;
  domain_models?: DomainModelConfig[];
}

/**
 * Conversation with frontend extensions.
 * Extends backend ConversationResponse with UI-specific fields.
 */
export interface Conversation extends ConversationResponse {
  /**
   * User ID who owns this conversation.
   * Frontend-tracked field for multi-user scenarios.
   */
  user_id: string;
  
  /**
   * Updated timestamp for last message.
   * Frontend-computed field.
   */
  updated_at?: string;
  
  /**
   * Conversation context (shared state).
   * Frontend field for UI state management.
   */
  context?: Record<string, unknown>;
  
  /**
   * Additional metadata.
   * Frontend field for extensibility.
   */
  metadata?: Record<string, unknown>;
}

/**
 * Message response from send message API.
 * Response when submitting a message to the conversation.
 * 
 * Backend schema: packages/starboard-server/starboard_server/api/models/messages.py
 */
export interface MessageResponse {
  message_id: string;
  conversation_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  trace_id?: string | null;
}

/**
 * Base chat event structure.
 * Frontend wrapper for SSE events with 'type' alias for 'event_type'.
 */
export interface ChatEvent {
  event_id: string;
  type: EventType;  // Alias for event_type
  data: Record<string, unknown>;
  timestamp: string;
}

/**
 * Extended streaming chat event.
 * Frontend adds convenience fields for UI rendering.
 * This extends the backend StreamingChatEvent with UI-specific shortcuts.
 * 
 * Note: Backend uses 'event_type', frontend prefers 'type' as alias.
 */
export interface ExtendedStreamingChatEvent extends Omit<StreamingChatEvent, 'event_type'> {
  /** Event type (alias for backend's event_type) */
  type: EventType;
  /** Event type in backend format (for compatibility) */
  event_type?: string;
  /** Convenience: Message ID from data */
  message_id?: string;
  /** Convenience: Content from data */
  content?: string;
  /** Convenience: Tool call from data */
  tool_call?: ToolCall;
  /** Convenience: Metadata from data */
  metadata?: Record<string, unknown>;
  /** Convenience: Error from data */
  error?: string;
}

/**
 * API error response.
 * Frontend error handling structure.
 */
export interface APIError {
  detail: string;
  status_code: number;
}

/**
 * Clarification request wrapper.
 * Frontend combines backend event data with UI fields.
 */
export interface ClarificationRequest {
  clarification_id: string;
  conversation_id: string;
  message_id: string;
  clarification_type: ClarificationType;
  question: string;
  options?: ClarificationOption[];
  allow_custom_response: boolean;
  is_required: boolean;
  target_tool?: string;
}

/**
 * Feedback submission response.
 * Frontend-specific response type for feedback API.
 */
export interface SubmitFeedbackResponse {
  feedback_id: string;
  message_id: string;
  rating: FeedbackRatingEnum;
  created_at: string;
}

// ============================================================================
// Compute Report Types (Warehouse/Cluster Agents)
// ============================================================================

/**
 * Resource metrics for a compute resource.
 */
export interface ResourceMetrics {
  p50_latency_ms?: number;
  p95_latency_ms?: number;
  avg_queue_time_ms?: number;
  query_count?: number;
  dbu_usage?: number;
}

/**
 * Summary of a single compute resource.
 */
export interface ResourceSummary {
  id: string;
  name: string;
  resource_type: "warehouse" | "cluster";
  health_score: number;
  health_status: "healthy" | "warning" | "critical" | "inactive";
  metrics?: ResourceMetrics;
}

/**
 * Distribution of resources by health status.
 */
export interface HealthDistribution {
  healthy: number;
  warning: number;
  critical: number;
  inactive: number;
}

/**
 * Portfolio-level overview of compute resources.
 */
export interface PortfolioSummary {
  total_count: number;
  health_distribution: HealthDistribution;
  top_resources?: Array<ResourceSummary>;
}

/**
 * Individual SLO target compliance detail.
 */
export interface SLODetail {
  metric: string;
  target: number;
  actual: number;
  met: boolean;
}

/**
 * SLO compliance summary.
 */
export interface SLOCompliance {
  targets_met: number;
  targets_total: number;
  details?: Array<SLODetail>;
}

/**
 * Individual metric health scores (0-100).
 * Supports both warehouse metrics and cluster metrics.
 */
export interface MetricScores {
  // Warehouse metrics
  latency?: number;
  availability?: number;
  queue_time?: number;
  error_rate?: number;
  // Cluster metrics
  cpu_utilization?: number;
  memory_utilization?: number;
  disk_io?: number;
  network_io?: number;
}

/**
 * Health metrics for a compute resource.
 */
export interface HealthMetrics {
  overall_score: number;
  metric_scores?: MetricScores;
  slo_compliance?: SLOCompliance;
  risk_factors?: Array<string>;
}

/**
 * Group of resources with similar workloads.
 */
export interface WorkloadCluster {
  id: string;
  name: string;
  resources: Array<string>;
  similarity_score: number;
}

/**
 * Potential consolidation recommendation.
 */
export interface ConsolidationOpportunity {
  source_resources: Array<string>;
  target_resource?: string;
  estimated_savings_pct: number;
  confidence: "low" | "medium" | "high";
  recommendation: string;
}

/**
 * Cross-resource topology analysis.
 */
export interface TopologyAnalysis {
  clusters?: Array<WorkloadCluster>;
  consolidation_opportunities?: Array<ConsolidationOpportunity>;
}

/**
 * User activity on compute resources.
 */
export interface UserActivity {
  user_email: string;
  query_count: number;
  total_runtime_seconds: number;
  bytes_scanned: number;
  cost_attribution_pct?: number;
}

/**
 * Summary of user activity across resources.
 */
export interface UserActivitySummary {
  period: string;
  top_users?: Array<UserActivity>;
  allocation_method?: "runtime" | "queries" | "bytes";
}

// Import Analysis type from generated-api for ComputeReport
import type { Analysis, Summary, NextStepAction } from './generated-api';

/**
 * Warehouse data from portfolio tool.
 * Agent includes this when user requests data listing (e.g., "show me all warehouses").
 */
export interface WarehouseData {
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string;
  state: string;
  total_queries: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  p99_duration_ms: number;
  avg_queue_time_ms: number;
  queued_query_pct: number;
  unique_users: number;
  error_rate_pct: number;
  health_score: number;
  health_status: "healthy" | "warning" | "critical" | "inactive";
}

/**
 * Generic data table for report outputs.
 * 
 * Used when user expects to see tabular data (reports, lists, breakdowns).
 * Signal words: "report", "show me", "list", "breakdown", "chargeback"
 */
export interface DataTable {
  /** Table title (e.g., "Warehouse Chargeback Report") */
  title: string;
  /** Brief description of what the table shows */
  description?: string;
  /** Column headers with units (e.g., "Cost ($)") */
  columns: string[];
  /** Data rows - values in column order */
  rows: Array<Array<string | number | null>>;
  /** Total row count for display */
  total_rows?: number;
  /** Summary/aggregate values */
  summary?: Record<string, string | number>;
}

/**
 * Warehouse report for SQL Warehouse agent.
 * 
 * Used by: warehouse agent
 * Focus: Resource health, portfolio metrics, topology analysis
 * 
 * The warehouse report supports multiple optional sections based on analysis type:
 * - portfolio_summary: Fleet-level overview
 * - health_metrics: Individual resource health
 * - topology_analysis: Consolidation recommendations
 * - user_activity: Chargeback reporting
 * - warehouses: Full warehouse list (agent decides when to include)
 * - data_table: Generic tabular data for reports (agent decides when to include)
 * - analysis: Technical findings (agent decides when to include)
 */
export interface WarehouseReport {
  report_type: "warehouse";
  summary: Summary;
  next_steps: Array<NextStepAction>;
  portfolio_summary?: PortfolioSummary;
  health_metrics?: HealthMetrics;
  topology_analysis?: TopologyAnalysis;
  user_activity?: UserActivitySummary;
  /** Full warehouse list - agent includes when user requests data listing */
  warehouses?: Array<WarehouseData>;
  /** Generic data table - agent includes when user expects tabular data (reports, chargeback, etc.) */
  data_table?: DataTable;
  /** Technical findings - agent includes when optimization analysis is relevant */
  analysis?: Analysis;
}

// ============================================================================
// Diagnostic Report Types (DiagnosticAgent)
// ============================================================================

/**
 * Evidence window - a specific piece of evidence from the artifact.
 */
export interface EvidenceWindow {
  /** Evidence ID for citation (e.g., "EV001") */
  id: string;
  /** Type of evidence (exception, error, metric, etc.) */
  type: string;
  /** The actual content/snippet */
  content: string;
  /** Line numbers in original artifact (if available) */
  line_start?: number;
  line_end?: number;
  /** Confidence that this is relevant evidence (0-1) */
  confidence?: number;
}

/**
 * Diagnostic finding - a specific issue identified in the analysis.
 */
export interface DiagnosticFinding {
  /** Unique finding ID */
  id: string;
  /** Category (MEMORY, NETWORK, DATA, CONFIG, SQL, etc.) */
  category: string;
  /** Short title */
  title: string;
  /** Confidence level (high, medium, low) */
  confidence: "high" | "medium" | "low";
  /** Detailed explanation */
  explanation: string;
  /** Evidence references (IDs from evidence_windows) */
  evidence_refs: string[];
  /** Recommended actions */
  recommendations: string[];
  /** Pattern ID that matched (if any) */
  pattern_id?: string;
}

/**
 * Diagnostic fingerprint for handoffs to other agents.
 */
export interface DiagnosticFingerprint {
  /** Primary symptom identified */
  primary_symptom: string;
  /** Likely root causes */
  likely_root_causes: string[];
  /** Extracted Databricks context */
  extracted_context: Record<string, string | number>;
  /** Evidence snippets */
  evidence_snippets: string[];
  /** Recommended handoff target */
  recommended_handoff_target?: string;
}

/**
 * Diagnostic report summary.
 */
export interface DiagnosticSummary {
  /** 2-3 sentence overview */
  overview: string;
  /** Artifact type detected */
  artifact_type: string;
  /** Analysis mode (online, offline, hybrid) */
  mode: "online" | "offline" | "hybrid";
  /** Overall confidence (0-1) */
  confidence: number;
}

/**
 * Diagnostic report from DiagnosticAgent.
 * 
 * Evidence-based troubleshooting report with findings and recommendations.
 * BB-09: Enhanced with metrics_summary and optimized_code sections.
 */
export interface DiagnosticReport {
  report_type: "diagnostic";
  /** Summary overview */
  summary: DiagnosticSummary;
  /** Evidence windows extracted from artifact */
  evidence_windows?: EvidenceWindow[];
  /** Diagnostic findings */
  findings?: DiagnosticFinding[];
  /** 
   * Metrics summary for query profiles, Spark logs, etc.
   * BB-09: null/undefined for simple error messages or code snippets.
   */
  metrics_summary?: MetricsSummary | null;
  /**
   * Optimized query or code suggestion.
   * BB-09: Include when a specific rewrite is suggested.
   */
  optimized_code?: string | null;
  /** Next steps for user */
  next_steps?: NextStepAction[];
  /** Handoff fingerprint (if recommending specialist) */
  fingerprint?: DiagnosticFingerprint;
  /** Whether budget was exhausted */
  budget_exhausted?: boolean;
}

/**
 * Structured metrics summary for diagnostic reports.
 * BB-09: Context-specific metrics for query profiles, Spark logs, etc.
 */
export interface MetricsSummary {
  /** Execution timing metrics */
  execution?: {
    total_time_ms?: number;
    compilation_time_ms?: number;
    execution_time_ms?: number;
    result_fetch_time_ms?: number;
    rows_produced?: number;
  };
  /** I/O statistics */
  io?: {
    bytes_read?: number;
    bytes_pruned?: number;
    rows_scanned?: number;
    rows_output?: number;
    files_read?: number;
    files_pruned?: number;
    cache_hit_pct?: number;
  };
  /** Processing efficiency */
  processing?: {
    photon_enabled?: boolean;
    photon_coverage_pct?: number;
    peak_memory?: number;
    spill_to_disk?: number;
  };
}

/**
 * @deprecated Use WarehouseReport instead. ComputeReport is maintained for backward compatibility
 * with cluster agent reports that may still use report_type: "compute".
 */
export interface ComputeReport {
  report_type: "compute" | "cluster";
  summary: Summary;
  next_steps: Array<NextStepAction>;
  portfolio_summary?: PortfolioSummary;
  health_metrics?: HealthMetrics;
  topology_analysis?: TopologyAnalysis;
  user_activity?: UserActivitySummary;
  warehouses?: Array<WarehouseData>;
  data_table?: DataTable;
  analysis?: Analysis;
}

// ============================================================================
// Backward Compatibility Aliases
// ============================================================================

/**
 * Alias for FeedbackRatingEnum.
 * Maintains backward compatibility with existing code.
 */
export const FeedbackRating = FeedbackRatingEnum;
export type FeedbackRating = FeedbackRatingEnum;

