/**
 * TypeScript types for Starboard Chat API.
 *
 * This file is now a thin re-export layer that combines:
 * 1. Auto-generated types from backend Pydantic models (generated-api.ts)
 * 2. Frontend-specific extensions and types (extended-api.ts)
 *
 * Migration complete! Types are now auto-generated from:
 * packages/starboard-server/starboard_server/api/models.py
 *
 * To regenerate types after backend changes:
 * ```bash
 * python scripts/generate_types.py
 * ```
 */

// ============================================================================
// Re-export Generated Types (from backend Pydantic models)
// ============================================================================

export type {
  // Configuration
  DomainModelConfig,
  ConversationConfig,
  // Core Models (ToolCall, Message, StreamingChatEvent from extended-api instead)
  ConversationResponse,
  // Request/Response Models
  CreateConversationRequest,
  SendMessageRequest,
  SubmitFeedbackRequest,
  RespondToClarificationRequest,
  RespondToClarificationResponse,
  RespondToSolicitationRequest,
  RespondToSolicitationResponse,
  // Event Data
  ClarificationRequestEventData,
  // LLM Schema Models (used by reports)
  CurrentState,
  Summary,
  // NextStep removed - no longer in generated types
  EffortEstimate,
  ImpactEstimate,
  Finding,
  Fix,
  Analysis,
  // Report Type Models
  AgentReport,
  AdvisorReport,
  AnalyticsReport,
  CostImpact,
  CostSummary,
  VisualizationRecommendation,
  AnalyticsFinding,
} from './generated-api';

export {
  // Enums (must use 'export' not 'export type' for enums)
  EventType,
  MessageRole,
  MessageStatus,
  FeedbackRatingEnum,
  FeedbackCategoryEnum,
} from './generated-api';

// ============================================================================
// Re-export Frontend Extensions
// ============================================================================

export type {
  // Extended Core Types (exported as primary versions)
  Message,  // Extended with debug, retry_count, tool_positions, agent_type fields
  MessageAttachment,  // File attachment in messages (BB-05)
  ToolCall,  // Frontend-specific type for tool execution details
  ToolCallStatus,  // Frontend-specific type for tool status
  ToolPosition,  // Phase 1 P0-3: Structured tool position data
  AgentType,  // Agent indicator: which specialist is responding
  MessageUpdate,
  NewMessage,
  // Frontend-Specific Types
  Attachment,
  NextStepOption,
  ClarificationOption,
  ServerConfig,
  SupportedModel,
  LoggingLevel,
  ConversationMetadata,
  ConversationHistory,
  Conversation,
  MessageResponse,
  ChatEvent,
  ExtendedStreamingChatEvent,
  APIError,
  ClarificationRequest,
  SubmitFeedbackResponse,
  // Warehouse Report Types (SQL Warehouse agent)
  WarehouseReport,
  ComputeReport, // @deprecated - use WarehouseReport
  PortfolioSummary,
  // Diagnostic Report Types (Diagnostic agent)
  DiagnosticReport,
  DiagnosticSummary,
  DiagnosticFinding,
  DiagnosticFingerprint,
  EvidenceWindow,
  MetricsSummary,
  HealthMetrics,
  TopologyAnalysis,
  UserActivitySummary,
  ResourceSummary,
  HealthDistribution,
  MetricScores,
  SLOCompliance,
  WorkloadCluster,
  ConsolidationOpportunity,
  UserActivity,
  WarehouseData,
  DataTable,
} from './extended-api';

// Export ExtendedStreamingChatEvent as StreamingChatEvent for backward compatibility
export type { ExtendedStreamingChatEvent as StreamingChatEvent } from './extended-api';

export {
  // Frontend-Specific Enums
  ActionType,
  ClarificationType,
  // Frontend Constants
  SUPPORTED_MODELS,
  LOGGING_LEVELS,
  // Backward Compatibility
  FeedbackRating,
} from './extended-api';

