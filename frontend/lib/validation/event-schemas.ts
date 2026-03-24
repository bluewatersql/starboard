/**
 * Zod schemas for runtime validation of SSE events.
 *
 * These schemas provide:
 * 1. Runtime validation to catch type mismatches before they reach UI logic
 * 2. Single source of truth for types (inferred from schemas)
 * 3. Clear error messages for debugging
 *
 * Related: packages/starboard-server/starboard_server/api/models.py
 */

import { z } from "zod";

// ============================================================================
// Enums
// ============================================================================

export const MessageStatusSchema = z.enum([
  "queued",
  "processing",
  "completed",
  "failed",
]);

export const MessageRoleSchema = z.enum(["user", "assistant", "system"]);

export const ToolCallStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
]);

export const EventTypeSchema = z.enum([
  // Core message events
  "message.start",
  "message.delta",
  "message.complete",
  "message.end",
  
  // Tool execution events
  "tool.call.start",
  "tool.progress",
  "tool.call.result",
  
  // Output and error events
  "final_output",
  "error",
  "heartbeat",
  
  // Phase 3: Interruptible Reasoning Events
  "checkpoint",
  "interrupt.received",
  "replan",
  "solicitation",
  "user_input_request",
  "user_input_response",
  
  // Phase 4: Multi-Agent Routing Events
  "routing.decision",
  "agent.transition",
  "clarification.request",
  "thinking",
  "step.start",
  "step.complete",
  
  // Metadata events
  "friendly_name.update",
  
  // Phase 1: Conversation Patterns
  "next_steps",
]);

export const ActionTypeSchema = z.enum(["continue", "route", "tool_call"]);

export const FeedbackRatingSchema = z.enum(["positive", "negative"]);

export const ClarificationTypeSchema = z.enum([
  "ambiguous_entity",
  "missing_parameter",
  "vague_reference",
  "insufficient_context",
]);

// ============================================================================
// Configuration Schemas
// ============================================================================

export const ConversationConfigSchema = z.object({
  temperature: z.number().min(0).max(2).optional(),
  max_tokens: z.number().positive().optional(),
  use_max_model_tokens: z.boolean().optional(),
  safe_mode: z.boolean().optional(),
  streaming: z.boolean().optional(),
  model: z.string().optional(),
  budget_enforced: z.boolean().optional(),
  max_steps: z.number().positive().optional(),
  logging_level: z.string().optional(),
  domain_model_overrides: z.record(z.string(), z.string()).optional(),
  domain_temperature_overrides: z.record(z.string(), z.number()).optional(),
});

// ============================================================================
// Core Data Structures
// ============================================================================

export const AttachmentSchema = z.object({
  attachment_id: z.string(),
  filename: z.string(),
  content_type: z.string(),
  size_bytes: z.number().nonnegative(),
  url: z.string().url().optional(),
});

export const ToolCallSchema = z.object({
  tool_call_id: z.string().optional(),
  tool_name: z.string().min(1),
  friendly_name: z.string().optional(),
  arguments: z.object({}).catchall(z.any()),
  result: z.any().optional(),
  status: ToolCallStatusSchema,
  error: z.string().optional(),
  duration_ms: z.number().nonnegative().optional(),
});

export const NextStepOptionSchema = z.object({
  id: z.string(),
  number: z.number().int().min(1).max(9),
  title: z.string(),
  description: z.string().nullable().optional(),
  action_type: z.enum(["continue", "route", "tool_call"]),
  target_agent: z.string().nullable().optional(),
  tool_name: z.string().nullable().optional(),
  parameters: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const ClarificationOptionSchema = z.object({
  option_id: z.string(),
  display_text: z.string(),
  value: z.any(),
  description: z.string().optional(),
});

// ============================================================================
// SSE Event Data Schemas
// ============================================================================

/**
 * Base schema for all SSE events
 */
const BaseEventSchema = z.object({
  event_id: z.string(),
  type: EventTypeSchema,
  timestamp: z.string().datetime(),
  data: z.object({}).catchall(z.any()),
});

/**
 * MESSAGE_START event - signals start of new assistant message
 */
const MessageStartDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  conversation_id: z.string().optional(),
});

export const MessageStartEventSchema = BaseEventSchema.extend({
  type: z.literal("message.start"),
  data: MessageStartDataSchema,
});

/**
 * MESSAGE_DELTA event - streaming content updates
 */
const DeltaObjectSchema = z.object({
  content: z.string(),
});

const MessageDeltaDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  delta: DeltaObjectSchema,
});

export const MessageDeltaEventSchema = BaseEventSchema.extend({
  type: z.literal("message.delta"),
  data: MessageDeltaDataSchema,
});

/**
 * MESSAGE_COMPLETE event - signals end of message
 * Backend may include next_steps for interactive conversations
 */
const MessageCompleteDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  status: MessageStatusSchema.optional(),
  final_content: z.string().optional(),
  next_steps: z.array(NextStepOptionSchema).optional(),
});

export const MessageCompleteEventSchema = BaseEventSchema.extend({
  type: z.literal("message.complete"),
  data: MessageCompleteDataSchema,
});

/**
 * MESSAGE_END event - signals end of message processing
 */
const MessageEndDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
});

export const MessageEndEventSchema = BaseEventSchema.extend({
  type: z.literal("message.end"),
  data: MessageEndDataSchema,
});

/**
 * TOOL_CALL_START event - tool execution begins
 */
const ToolCallRunningSchema = z.object({
  tool_call_id: z.string().optional(),
  tool_name: z.string().min(1),
  friendly_name: z.string().optional(),
  arguments: z.union([z.string(), z.object({}).catchall(z.any()), z.any()]).optional(),
  status: z.literal("running"),
  error: z.string().optional(),
  duration_ms: z.number().nonnegative().optional(),
});

/**
 * Tool position schema for inline rendering (Phase 2 Streaming Positions).
 */
const ToolPositionSchema = z.object({
  tool_call_id: z.string(),
  position: z.number().nonnegative(),
  display: z.enum(["inline", "group", "hidden"]).default("inline"),
});

const ToolCallStartDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  tool_call: ToolCallRunningSchema,
  // Phase 2: Streaming positions sent during streaming
  tool_positions: z.array(ToolPositionSchema).optional(),
});

export const ToolCallStartEventSchema = BaseEventSchema.extend({
  type: z.literal("tool.call.start"),
  data: ToolCallStartDataSchema,
});

/**
 * TOOL_PROGRESS event - tool execution progress update
 */
const ToolProgressDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  tool_call_id: z.string(),
  progress_message: z.string(),
  progress_percentage: z.number().min(0).max(100).optional(),
});

export const ToolProgressEventSchema = BaseEventSchema.extend({
  type: z.literal("tool.progress"),
  data: ToolProgressDataSchema,
});

/**
 * TOOL_CALL_RESULT event - tool execution completes
 */
const ToolCallCompletedSchema = z.object({
  tool_call_id: z.string().optional(),
  tool_name: z.string().min(1),
  friendly_name: z.string().optional(),
  arguments: z.union([z.string(), z.object({}).catchall(z.any()), z.any()]).optional(),
  result: z.any().optional().nullable(),
  status: z.enum(["completed", "failed"]),
  success: z.boolean().optional(),
  error: z.string().nullable().optional(),
  duration_ms: z.number().nonnegative().optional(),
});

const ToolCallResultDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  tool_call: ToolCallCompletedSchema,
});

export const ToolCallResultEventSchema = BaseEventSchema.extend({
  type: z.literal("tool.call.result"),
  data: ToolCallResultDataSchema,
});

/**
 * FINAL_OUTPUT event - agent completes with final report
 */
const OutputObjectSchema = z.object({
  status: z.enum(["success", "error", "budget_exceeded", "max_steps_reached", "unknown"]),
  formatted_report: z.string().nullable().optional(),
  complete_report: z.union([z.object({}).catchall(z.any()), z.null()]).optional(),
  next_steps: z.array(NextStepOptionSchema).nullable().optional(), // Next steps for user interaction
  tokens_used: z.number().nonnegative().optional(),
  cost_usd: z.number().nonnegative().optional(),
  duration_seconds: z.number().nonnegative().optional(),
  steps_taken: z.number().nonnegative().optional(),
});

const FinalOutputDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  output: OutputObjectSchema,
  formatted_markdown: z.string().nullable().optional(), // Formatted report markdown
});

export const FinalOutputEventSchema = BaseEventSchema.extend({
  type: z.literal("final_output"),
  data: FinalOutputDataSchema,
});

/**
 * ERROR event - error occurred during processing
 */
const ErrorObjectSchema = z.object({
  message: z.string(),
  code: z.string().optional(),
  details: z.object({}).catchall(z.any()).optional(),
});

const ErrorDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).optional(),
  error: ErrorObjectSchema,
});

export const ErrorEventSchema = BaseEventSchema.extend({
  type: z.literal("error"),
  data: ErrorDataSchema,
});

/**
 * HEARTBEAT event - keep-alive signal
 */
const HeartbeatDataSchema = z.object({
  timestamp: z.string().datetime(),
  message: z.string().optional(),
});

export const HeartbeatEventSchema = BaseEventSchema.extend({
  type: z.literal("heartbeat"),
  data: HeartbeatDataSchema,
});

/**
 * THINKING event - agent reasoning/thinking content
 */
const ThinkingDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  content: z.string(),
  step: z.number().nonnegative().optional(),
});

export const ThinkingEventSchema = BaseEventSchema.extend({
  type: z.literal("thinking"),
  data: ThinkingDataSchema,
});

/**
 * STEP_START event - enhanced thinking step with sub-tasks
 * Backend sends ThinkingStepUpdate with rich progress info
 */
const ThinkingStepSubTaskSchema = z.object({
  id: z.string(),
  description: z.string(),
  status: z.enum(["pending", "in_progress", "completed", "failed"]),
  value: z.union([z.string(), z.number()]).optional().nullable(),
});

const ThinkingStepSchema = z.object({
  step_id: z.string(),
  title: z.string(),
  status: z.enum(["pending", "in_progress", "completed", "failed"]),
  start_time: z.number().optional().nullable(),
  end_time: z.number().optional().nullable(),
  progress: z.number().min(0).max(100).optional().nullable(),
  sub_tasks: z.array(ThinkingStepSubTaskSchema).optional(),
  metadata: z.record(z.string(), z.any()).optional(),
});

const StepStartDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).optional().nullable(),
  thinking_step: ThinkingStepSchema,
});

export const StepStartEventSchema = BaseEventSchema.extend({
  type: z.literal("step.start"),
  data: StepStartDataSchema,
});

/**
 * STEP_COMPLETE event - agent completes reasoning step
 * Backend sends: reasoning, tools_called (list of tool names)
 * Note: 'step' is in the base StreamingEvent, not in data
 */
const StepCompleteDataSchema = z.object({
  reasoning: z.string().nullable().optional(),
  tools_called: z.array(z.string()).optional().default([]),
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).optional(),
});

export const StepCompleteEventSchema = BaseEventSchema.extend({
  type: z.literal("step.complete"),
  data: StepCompleteDataSchema,
});

/**
 * ROUTING_DECISION event - agent router makes routing decision
 * Backend sends: domain, confidence, reasoning, clarification_needed
 */
const RoutingDecisionDataSchema = z.object({
  domain: z.string(),
  confidence: z.number().min(0).max(1),
  reasoning: z.string(),
  clarification_needed: z.boolean(),
});

export const RoutingDecisionEventSchema = BaseEventSchema.extend({
  type: z.literal("routing.decision"),
  data: RoutingDecisionDataSchema,
});

/**
 * AGENT_TRANSITION event - conversation transitions to different agent
 * Backend sends: from_agent, to_agent, reason, context_passed
 */
const AgentTransitionDataSchema = z.object({
  from_agent: z.string(),
  to_agent: z.string(),
  reason: z.string(),
  context_passed: z.record(z.string(), z.any()).optional(),
});

export const AgentTransitionEventSchema = BaseEventSchema.extend({
  type: z.literal("agent.transition"),
  data: AgentTransitionDataSchema,
});

/**
 * CLARIFICATION_REQUEST event - agent requests clarification from user
 * Backend sends all clarification fields flattened in the data object
 */
const ClarificationRequestEventDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).optional(),
  conversation_id: z.string().optional(),
  clarification_id: z.string(),
  clarification_type: z.string(),
  question: z.string(),
  options: z.array(z.record(z.string(), z.unknown())).nullable().optional(),
  allow_custom_response: z.boolean().default(true),
  is_required: z.boolean().default(true),
  target_tool: z.string().nullable().optional(),
});

export const ClarificationRequestEventSchema = BaseEventSchema.extend({
  type: z.literal("clarification.request"),
  data: ClarificationRequestEventDataSchema,
});

/**
 * NEXT_STEPS event - agent provides next step options
 */
const NextStepsDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  next_steps: z.array(NextStepOptionSchema).min(1).max(9),
});

export const NextStepsEventSchema = BaseEventSchema.extend({
  type: z.literal("next_steps"),
  data: NextStepsDataSchema,
});

/**
 * FRIENDLY_NAME_UPDATE event - updates conversation friendly name
 * Backend sends: friendly_name
 */
const FriendlyNameUpdateDataSchema = z.object({
  friendly_name: z.string(),
});

export const FriendlyNameUpdateEventSchema = BaseEventSchema.extend({
  type: z.literal("friendly_name.update"),
  data: FriendlyNameUpdateDataSchema,
});

/**
 * USER_INPUT_REQUEST event - agent requests user input
 * Backend sends: message_id, request_id, question, context, suggestions, timeout_seconds
 */
const UserInputRequestDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).nullable().optional(),
  request_id: z.string(),
  question: z.string(),
  context: z.string().nullable().optional(),
  suggestions: z.array(z.string()).optional(),
  timeout_seconds: z.number().nullable().optional(),
});

export const UserInputRequestEventSchema = BaseEventSchema.extend({
  type: z.literal("user_input_request"),
  data: UserInputRequestDataSchema,
});

/**
 * USER_INPUT_RESPONSE event - user provides requested input
 * Backend sends: message_id, request_id, user_response, timed_out
 */
const UserInputResponseDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/).nullable().optional(),
  request_id: z.string(),
  user_response: z.string(),
  timed_out: z.boolean().optional(),
});

export const UserInputResponseEventSchema = BaseEventSchema.extend({
  type: z.literal("user_input_response"),
  data: UserInputResponseDataSchema,
});

/**
 * CHECKPOINT event - agent creates checkpoint
 */
const CheckpointDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  checkpoint_id: z.string(),
  description: z.string().optional(),
});

export const CheckpointEventSchema = BaseEventSchema.extend({
  type: z.literal("checkpoint"),
  data: CheckpointDataSchema,
});

/**
 * INTERRUPT_RECEIVED event - agent received interrupt signal
 */
const InterruptReceivedDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  reason: z.string().optional(),
});

export const InterruptReceivedEventSchema = BaseEventSchema.extend({
  type: z.literal("interrupt.received"),
  data: InterruptReceivedDataSchema,
});

/**
 * REPLAN event - agent replanning reasoning
 */
const ReplanDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  new_plan: z.string(),
  reason: z.string().optional(),
});

export const ReplanEventSchema = BaseEventSchema.extend({
  type: z.literal("replan"),
  data: ReplanDataSchema,
});

/**
 * SOLICITATION event - agent soliciting information
 */
const SolicitationDataSchema = z.object({
  message_id: z.string().regex(/^msg_[a-zA-Z0-9_]+$/),
  solicitation_type: z.string(),
  prompt: z.string(),
  options: z.array(z.string()).optional(),
});

export const SolicitationEventSchema = BaseEventSchema.extend({
  type: z.literal("solicitation"),
  data: SolicitationDataSchema,
});

// ============================================================================
// Union Schema for All Event Types
// ============================================================================

/**
 * Discriminated union of all possible SSE event types.
 * This enables type-safe event handling based on event.type.
 */
export const StreamingChatEventSchema = z.discriminatedUnion("type", [
  MessageStartEventSchema,
  MessageDeltaEventSchema,
  MessageCompleteEventSchema,
  MessageEndEventSchema,
  ToolCallStartEventSchema,
  ToolProgressEventSchema,
  ToolCallResultEventSchema,
  FinalOutputEventSchema,
  ErrorEventSchema,
  HeartbeatEventSchema,
  ThinkingEventSchema,
  StepStartEventSchema,
  StepCompleteEventSchema,
  RoutingDecisionEventSchema,
  AgentTransitionEventSchema,
  ClarificationRequestEventSchema,
  NextStepsEventSchema,
  FriendlyNameUpdateEventSchema,
  UserInputRequestEventSchema,
  UserInputResponseEventSchema,
  CheckpointEventSchema,
  InterruptReceivedEventSchema,
  ReplanEventSchema,
  SolicitationEventSchema,
]);

// ============================================================================
// Type Inference
// ============================================================================

/**
 * Infer TypeScript types from Zod schemas (single source of truth)
 */
export type MessageStatus = z.infer<typeof MessageStatusSchema>;
export type MessageRole = z.infer<typeof MessageRoleSchema>;
export type ToolCallStatus = z.infer<typeof ToolCallStatusSchema>;
export type EventType = z.infer<typeof EventTypeSchema>;
export type ActionType = z.infer<typeof ActionTypeSchema>;
export type FeedbackRating = z.infer<typeof FeedbackRatingSchema>;
export type ClarificationType = z.infer<typeof ClarificationTypeSchema>;

export type ConversationConfig = z.infer<typeof ConversationConfigSchema>;
export type Attachment = z.infer<typeof AttachmentSchema>;
export type ToolCall = z.infer<typeof ToolCallSchema>;
export type NextStepOption = z.infer<typeof NextStepOptionSchema>;
export type ClarificationOption = z.infer<typeof ClarificationOptionSchema>;
export type ClarificationRequestData = z.infer<typeof ClarificationRequestEventDataSchema>;

export type StreamingChatEvent = z.infer<typeof StreamingChatEventSchema>;
export type MessageStartEvent = z.infer<typeof MessageStartEventSchema>;
export type MessageDeltaEvent = z.infer<typeof MessageDeltaEventSchema>;
export type MessageCompleteEvent = z.infer<typeof MessageCompleteEventSchema>;
export type MessageEndEvent = z.infer<typeof MessageEndEventSchema>;
export type ToolCallStartEvent = z.infer<typeof ToolCallStartEventSchema>;
export type ToolProgressEvent = z.infer<typeof ToolProgressEventSchema>;
export type ToolCallResultEvent = z.infer<typeof ToolCallResultEventSchema>;
export type FinalOutputEvent = z.infer<typeof FinalOutputEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
export type HeartbeatEvent = z.infer<typeof HeartbeatEventSchema>;
export type ThinkingEvent = z.infer<typeof ThinkingEventSchema>;
export type StepStartEvent = z.infer<typeof StepStartEventSchema>;
export type StepCompleteEvent = z.infer<typeof StepCompleteEventSchema>;
export type RoutingDecisionEvent = z.infer<typeof RoutingDecisionEventSchema>;
export type AgentTransitionEvent = z.infer<typeof AgentTransitionEventSchema>;
export type ClarificationRequestEvent = z.infer<typeof ClarificationRequestEventSchema>;
export type NextStepsEvent = z.infer<typeof NextStepsEventSchema>;
export type FriendlyNameUpdateEvent = z.infer<typeof FriendlyNameUpdateEventSchema>;
export type UserInputRequestEvent = z.infer<typeof UserInputRequestEventSchema>;
export type UserInputResponseEvent = z.infer<typeof UserInputResponseEventSchema>;
export type CheckpointEvent = z.infer<typeof CheckpointEventSchema>;
export type InterruptReceivedEvent = z.infer<typeof InterruptReceivedEventSchema>;
export type ReplanEvent = z.infer<typeof ReplanEventSchema>;
export type SolicitationEvent = z.infer<typeof SolicitationEventSchema>;

// ============================================================================
// Validation Utilities
// ============================================================================

/**
 * Validate and parse SSE event data.
 * Returns validated data or throws descriptive error.
 */
export function validateStreamingEvent(data: unknown): {
  success: true;
  data: StreamingChatEvent;
} | {
  success: false;
  error: z.ZodError;
} {
  const result = StreamingChatEventSchema.safeParse(data);
  return result.success
    ? { success: true, data: result.data }
    : { success: false, error: result.error };
}

/**
 * Validate event with custom error handler.
 * Useful for logging/monitoring integration.
 */
export function validateStreamingEventWithHandler(
  data: unknown,
  onError?: (error: z.ZodError, rawData: unknown) => void
): StreamingChatEvent | null {
  const result = validateStreamingEvent(data);
  
  if (!result.success) {
    onError?.(result.error, data);
    return null;
  }
  
  return result.data;
}

/**
 * Type guard for specific event types.
 * Enables type-safe narrowing in event handlers.
 */
export function isEventType<T extends EventType>(
  event: StreamingChatEvent,
  type: T
): event is Extract<StreamingChatEvent, { type: T }> {
  return event.type === type;
}

/**
 * Format validation error for debugging.
 * Returns human-readable error message.
 */
export function formatValidationError(error: z.ZodError): string {
  const formatted = error.format();
  return JSON.stringify(formatted, null, 2);
}

/**
 * Extract error path from validation error.
 * Useful for identifying which field failed validation.
 */
export function getValidationErrorPath(error: z.ZodError): string[] {
  const firstIssue = error.issues[0];
  return firstIssue ? firstIssue.path.map(String) : [];
}

