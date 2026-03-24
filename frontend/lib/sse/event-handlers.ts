/**
 * Event handlers for SSE events.
 *
 * Extracted from useSSE hook for better testability and maintainability.
 * Each handler is a pure function that takes an event and store operations.
 */

import type { StreamingChatEvent, Message, ToolCall, NextStepOption, ToolCallStatus, ToolPosition } from "../types/api";
import { MessageRole, MessageStatus } from "../types/api";
import { debug } from "../utils/debug";
import { logger } from "../utils/logger";
import type { ThinkingStep } from "@/components/chat/thinking";

/**
 * Message update fields (subset of Message for partial updates).
 */
export type MessageUpdate = Partial<Omit<Message, 'message_id' | 'conversation_id'>>;

/**
 * Conversation update fields (for partial updates).
 */
export interface ConversationUpdate {
  friendly_name?: string;
  [key: string]: unknown;
}

/**
 * Message store operations interface.
 */
export interface MessageStoreOperations {
  addMessage: (conversationId: string, message: Message) => void;
  updateMessage: (conversationId: string, messageId: string, updates: MessageUpdate) => void;
  appendToMessage: (conversationId: string, messageId: string, content: string) => void;
  setStreamingMessage: (messageId: string | null) => void;
  getMessages: (conversationId: string) => Message[];
  updateThinkingStep?: (conversationId: string, messageId: string, step: ThinkingStep) => void;
  setThinkingIndicator?: (
    messageId: string,
    state: "idle" | "thinking" | "completed",
    durationSeconds?: number,
    stepTitle?: string
  ) => void;
  getThinkingIndicator?: (messageId: string) => { state: string; startTime?: number };
}

/**
 * Conversation store operations interface.
 */
export interface ConversationStoreOperations {
  updateConversation: (conversationId: string, updates: ConversationUpdate) => void;
}

/**
 * Handle MESSAGE_START event.
 *
 * Creates a new assistant message with initial state.
 */
export function handleMessageStart(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;

  if (!messageId) {
    debug.warn("[handleMessageStart] MESSAGE_START received but no message_id in event data");
    return null;
  }

  debug.log("[handleMessageStart] Creating new message:", messageId);

  const initialToolCalls = (event.data?.tool_calls as ToolCall[]) || [];

  store.addMessage(conversationId, {
    id: messageId,  // Required by GeneratedMessage
    message_id: messageId,
    conversation_id: conversationId,
    trace_id: `trace_${messageId}`,  // Temporary trace ID
    timestamp: new Date().toISOString(),
    role: MessageRole.ASSISTANT,
    content: "",
    status: MessageStatus.PROCESSING,
    tool_calls: initialToolCalls,
  });

  store.setStreamingMessage(messageId);

  debug.log("[handleMessageStart] Message added and streaming started");
}

/**
 * Handle MESSAGE_DELTA event.
 *
 * Appends content to an existing message.
 * Phase 1 P0-3: Also extracts and stores tool_positions for structured rendering.
 */
export function handleMessageDelta(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const delta = event.data?.delta as { content?: string; tool_positions?: ToolPosition[] };
  const content = delta?.content as string;
  const toolPositions = delta?.tool_positions;

  if (!messageId) {
    return null;
  }

  // DEFENSIVE: Check if message exists, if not create it (missed MESSAGE_START)
  const messages = store.getMessages(conversationId);
  const existingMessage = messages.find(m => m.message_id === messageId);

  if (!existingMessage) {
    debug.warn(`[handleMessageDelta] Message ${messageId} not found (missed start), creating placeholder`);
    store.addMessage(conversationId, {
      id: messageId,  // Required by GeneratedMessage
      message_id: messageId,
      conversation_id: conversationId,
      trace_id: `trace_${messageId}`,
      role: MessageRole.ASSISTANT,
      content: "",
      status: MessageStatus.PROCESSING,
      timestamp: new Date().toISOString(),
      tool_calls: [],
    });
    store.setStreamingMessage(messageId);
  }

  // P0-3: Update message with structured tool positions if provided
  if (toolPositions && toolPositions.length > 0) {
    store.updateMessage(conversationId, messageId, {
      tool_positions: toolPositions,
    });
  }

  if (content) {
    // U2: Set thinking indicator to "thinking" when content arrives
    if (store.setThinkingIndicator) {
      store.setThinkingIndicator(messageId, "thinking");
    }
    store.appendToMessage(conversationId, messageId, content);
  }
}

/**
 * Handle MESSAGE_COMPLETE event.
 *
 * Marks message as completed and optionally adds next steps.
 */
export function handleMessageComplete(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;

  if (!messageId) {
    return null;
  }

  const nextSteps = event.data?.next_steps as NextStepOption[] | undefined;
  const updateData: MessageUpdate = {
    status: MessageStatus.COMPLETED,
  };

  if (nextSteps && Array.isArray(nextSteps)) {
    updateData.next_steps = nextSteps;
    debug.log(`[handleMessageComplete] Adding ${nextSteps.length} next steps to message ${messageId}`);
  }

  store.updateMessage(conversationId, messageId, updateData);
  store.setStreamingMessage(null);

  // U2: Reset thinking indicator when message completes
  if (store.setThinkingIndicator) {
    store.setThinkingIndicator(messageId, "idle");
  }
}

/**
 * Handle TOOL_CALL_START event.
 *
 * Phase 2: Adds tool call to message and accumulates streaming positions.
 * No longer inserts markers - positions come from backend.
 */
export function handleToolCallStart(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const toolCallData = event.data?.tool_call as Partial<ToolCall> | undefined;
  const toolPositions = event.data?.tool_positions as ToolPosition[] | undefined;

  if (!messageId || !toolCallData?.tool_name) {
    return null;
  }

  // U2: Mark thinking as completed when tool starts (calculate duration)
  if (store.setThinkingIndicator && store.getThinkingIndicator) {
    const thinkingState = store.getThinkingIndicator(messageId);
    if (thinkingState.state === "thinking" && thinkingState.startTime) {
      const duration = Math.floor((Date.now() - thinkingState.startTime) / 1000);
      store.setThinkingIndicator(messageId, "completed", duration);
    }
  }

  // Get existing message
  const messages = store.getMessages(conversationId);
  let existingMessage = messages.find((m) => m.message_id === messageId);
  
  debug.log(`[handleToolCallStart] Tool: ${toolCallData.tool_name}`);
  debug.log(`[handleToolCallStart] ConversationId: ${conversationId}`);
  debug.log(`[handleToolCallStart] MessageId: ${messageId}`);
  debug.log(`[handleToolCallStart] Total messages in conversation: ${messages.length}`);
  
  // DEFENSIVE: If message doesn't exist (race condition), create a placeholder
  if (!existingMessage) {
    debug.warn(`[handleToolCallStart] Message ${messageId} not found, creating placeholder`);
    store.addMessage(conversationId, {
      id: messageId,  // Required by GeneratedMessage
      message_id: messageId,
      conversation_id: conversationId,
      trace_id: `trace_${messageId}`,
      role: MessageRole.ASSISTANT,
      content: "",
      status: MessageStatus.PROCESSING,
      timestamp: new Date().toISOString(),
      tool_calls: [],
      tool_positions: [],
    });
    
    // Refresh the message reference
    const updatedMessages = store.getMessages(conversationId);
    existingMessage = updatedMessages.find((m) => m.message_id === messageId);
    
    if (!existingMessage) {
      console.error(`[handleToolCallStart] Failed to create message ${messageId} - store.addMessage may have failed`);
      return null;
    }
  }

  const existingToolCalls = existingMessage.tool_calls || [];

  // Extract tool_call_id from event (v2) or generate fallback
  const toolCallId = toolCallData.tool_call_id || `${toolCallData.tool_name}_${Date.now()}`;

  // Check if this specific tool invocation already exists (by tool_call_id)
  const toolExists = existingToolCalls.some((t) => t.tool_call_id === toolCallId);
  if (toolExists) {
    debug.log(`[handleToolCallStart] Tool ${toolCallData.tool_name} already exists, skipping`);
    return null;
  }

  // Build update object
  const updateData: Partial<Message> = {
    tool_calls: [
      ...existingToolCalls,
      {
        tool_call_id: toolCallId,
        tool_name: toolCallData.tool_name,
        friendly_name: toolCallData.friendly_name || toolCallData.tool_name,
        arguments: toolCallData.arguments || {},
        status: "running" as ToolCallStatus,
      } as ToolCall,
    ],
  };

  // Phase 2: Accumulate tool positions as they arrive during streaming
  if (toolPositions && toolPositions.length > 0) {
    // Get existing positions
    const existingPositions = existingMessage?.tool_positions || [];
    
    // Merge new positions (avoid duplicates by tool_call_id)
    const allPositions = [...existingPositions];
    for (const newPos of toolPositions) {
      const exists = allPositions.find(p => p.tool_call_id === newPos.tool_call_id);
      if (!exists) {
        allPositions.push(newPos);
      }
    }
    
    updateData.tool_positions = allPositions;
    
    debug.log('[Streaming Positions] Updated message positions', {
      messageId,
      totalPositions: allPositions.length,
    });
  }

  // Update message with tool call and positions (no markers!)
  store.updateMessage(conversationId, messageId, updateData);
}

/**
 * Handle TOOL_CALL_RESULT event.
 *
 * Updates tool call status and result.
 */
export function handleToolCallResult(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const toolCallData = event.data?.tool_call as Partial<ToolCall> | undefined;

  if (!messageId || !toolCallData?.tool_name) {
    return null;
  }

  // Get existing message
  const messages = store.getMessages(conversationId);
  const existingMessage = messages.find((m) => m.message_id === messageId);
  
  if (!existingMessage) {
    debug.warn(`[handleToolCallResult] Message ${messageId} not found, skipping tool update`);
    return null;
  }
  
  const existingToolCalls = existingMessage.tool_calls || [];

  // Extract tool_call_id from event
  const toolCallId = toolCallData.tool_call_id;

  // Update the specific tool's status by tool_call_id (or fallback to tool_name)
  const updatedToolCalls = existingToolCalls.map((t) => {
    // Match by tool_call_id if available, otherwise by tool_name + running status
    const matches = toolCallId
      ? t.tool_call_id === toolCallId
      : t.tool_name === toolCallData.tool_name && t.status === "running";

    if (matches) {
      return {
        ...t,
        friendly_name: toolCallData.friendly_name || t.friendly_name || t.tool_name,
        status: toolCallData.status || "completed",
        result: toolCallData.result,
        duration_ms: toolCallData.duration_ms,
        error: toolCallData.error,
      } as ToolCall;
    }
    return t;
  });

  // Phase 2: No marker syncing needed - positions are used instead
  store.updateMessage(conversationId, messageId, {
    tool_calls: updatedToolCalls,
  });

  // U3: Update thinking step with call details for 3-level display
  // The step_id corresponds to the tool_name (e.g., "resolve_query")
  if (store.updateThinkingStep) {
    const toolName = toolCallData.tool_name;
    const matchingToolCall = updatedToolCalls.find(t => t.tool_name === toolName);
    
    if (matchingToolCall) {
      // Truncate response if too large for display
      let response = matchingToolCall.result;
      let responseIsTruncated = false;
      
      if (typeof response === 'string' && response.length > 5000) {
        response = response.slice(0, 5000) + '...';
        responseIsTruncated = true;
      } else if (typeof response === 'object' && response !== null) {
        const responseStr = JSON.stringify(response);
        if (responseStr.length > 5000) {
          responseIsTruncated = true;
        }
      }
      
      // Update the thinking step with call details
      store.updateThinkingStep(conversationId, messageId, {
        id: toolName,
        title: matchingToolCall.friendly_name || toolName,
        status: matchingToolCall.status === "completed" ? "completed" : 
                matchingToolCall.status === "failed" ? "failed" : "in_progress",
        callDetails: {
          toolName: toolName,
          parameters: matchingToolCall.arguments || {},
          response: response,
          responseIsTruncated,
          error: matchingToolCall.error,
        },
      });
    }
  }

  // U2: After tool completes, agent will process the result - show "thinking" again
  // Only FINAL_OUTPUT and MESSAGE_COMPLETE should reset to "idle"
  if (store.setThinkingIndicator) {
    store.setThinkingIndicator(messageId, "thinking");
  }
}

/**
 * Handle FINAL_OUTPUT event.
 *
 * Updates message with final report, next steps, and metadata.
 */
interface FinalOutput {
  formatted_report?: string;
  formatted_markdown?: string;
  complete_report?: unknown;
  next_steps?: NextStepOption[];
  tokens_used?: number;
  cost_usd?: number;
  duration_seconds?: number;
  steps_taken?: number;
}

export function handleFinalOutput(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const output = event.data?.output as FinalOutput | undefined;
  const formattedMarkdown = event.data?.formatted_markdown as string | undefined; // Get from top level

  if (!output || !messageId) {
    return null;
  }

  const hasReport = output.complete_report;
  
  // Extract next_steps from output (sent by backend in AgentOutput.to_dict())
  const nextSteps = output.next_steps;

  // Build the update object
  const updateData: MessageUpdate = {
    status: MessageStatus.COMPLETED,
  };

  // Add next_steps if present
  if (nextSteps && Array.isArray(nextSteps) && nextSteps.length > 0) {
    updateData.next_steps = nextSteps;
  }

  if (hasReport) {
    updateData.metadata = {
      complete_report: output.complete_report as Record<string, unknown> | null,
      tokens_used: output.tokens_used,
      cost_usd: output.cost_usd,
      duration_seconds: output.duration_seconds,
      steps_taken: output.steps_taken,
      formatted_markdown: formattedMarkdown,
    };
  } else {
    updateData.metadata = {
      tokens_used: output.tokens_used,
      cost_usd: output.cost_usd,
      duration_seconds: output.duration_seconds,
      steps_taken: output.steps_taken,
    };
  }

  store.updateMessage(conversationId, messageId, updateData);
  store.setStreamingMessage(null);

  // U2: Reset thinking indicator when final output arrives
  if (store.setThinkingIndicator) {
    store.setThinkingIndicator(messageId, "idle");
  }
}

/**
 * Handle ERROR event.
 *
 * Marks message as failed and appends error message.
 */
export function handleError(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;

  if (!messageId) {
    return null;
  }

  // Extract error message from event data
  const errorData = event.data?.error as { message?: string } | undefined;
  const errorMessage = errorData?.message || "An error occurred";

  // Get existing message to append error
  const messages = store.getMessages(conversationId);
  const existingMessage = messages.find((m) => m.message_id === messageId);
  const currentContent = existingMessage?.content || "";

  // Append error message to content (will be displayed in chat)
  const errorSuffix = `\n\n❌ **Error**: ${errorMessage}`;

  store.updateMessage(conversationId, messageId, {
    status: MessageStatus.FAILED,
    content: currentContent + errorSuffix,
  });

  store.setStreamingMessage(null);
}

/**
 * Handle NEXT_STEPS event.
 *
 * Adds next steps to the message for interactive conversation flow.
 * This is sent as a separate event in Phase 1 Conversation Patterns.
 */
export function handleNextSteps(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const nextSteps = event.data?.next_steps as NextStepOption[] | undefined;

  if (!messageId || !nextSteps || !Array.isArray(nextSteps)) {
    debug.warn("[handleNextSteps] Missing message_id or next_steps in event data");
    return null;
  }

  debug.log(`[handleNextSteps] Adding ${nextSteps.length} next steps to message ${messageId}`);

  store.updateMessage(conversationId, messageId, {
    next_steps: nextSteps,
  });
}

/**
 * Handle FRIENDLY_NAME_UPDATE event.
 *
 * Updates conversation friendly name.
 */
export function handleFriendlyNameUpdate(
  event: StreamingChatEvent,
  conversationId: string,
  store: ConversationStoreOperations
): void | null {
  const friendlyName = event.data?.friendly_name as string;

  if (!friendlyName) {
    return null;
  }

  store.updateConversation(conversationId, { friendly_name: friendlyName });
}

/**
 * ThinkingStep data from backend event.
 */
interface ThinkingStepEvent {
  step_id: string;
  title: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  start_time?: number;
  end_time?: number;
  progress?: number;
  sub_tasks?: Array<{
    id: string;
    description: string;
    status: "pending" | "in_progress" | "completed" | "failed";
    value?: string | number;
  }>;
  metadata?: Record<string, unknown>;
}

/**
 * Handle STEP_START event (ThinkingStepUpdate).
 *
 * Updates thinking steps for enhanced UI visualization.
 * These events contain rich progress information including
 * sub-tasks with metrics.
 */
export function handleStepStart(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const thinkingStepData = event.data?.thinking_step as ThinkingStepEvent | undefined;

  if (!thinkingStepData) {
    // Not an enhanced thinking step event
    return null;
  }

  debug.log("[handleStepStart] ThinkingStep received:", thinkingStepData.step_id, thinkingStepData.status);

  // Convert backend format to frontend ThinkingStep format
  const step: ThinkingStep = {
    id: thinkingStepData.step_id,
    title: thinkingStepData.title,
    status: thinkingStepData.status,
    startTime: thinkingStepData.start_time ? thinkingStepData.start_time * 1000 : undefined, // Convert to ms
    endTime: thinkingStepData.end_time ? thinkingStepData.end_time * 1000 : undefined,
    progress: thinkingStepData.progress,
    stepType: thinkingStepData.step_id, // Use step_id as stepType for icon mapping
    subTasks: thinkingStepData.sub_tasks?.map((st) => ({
      id: st.id,
      description: st.description,
      status: st.status,
      value: st.value,
    })),
    metadata: thinkingStepData.metadata,
  };

  // Update store if handler is available
  if (store.updateThinkingStep) {
    store.updateThinkingStep(conversationId, messageId || "current", step);
  }

  // Update thinking indicator with step title for real-time display
  // This shows the current step name (e.g., "Generating Analysis") in the UI
  if (store.setThinkingIndicator && messageId && thinkingStepData.status === "in_progress") {
    store.setThinkingIndicator(
      messageId, 
      "thinking", 
      undefined, 
      thinkingStepData.title
    );
  }
}

/**
 * Handle AGENT_TRANSITION event.
 *
 * Updates the current message with the new agent type so the UI
 * can display which agent is responding.
 */
export function handleAgentTransition(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const toAgent = event.data?.to_agent as string;
  const messageId = event.data?.message_id as string;
  
  // Always log agent transitions for debugging
  logger.debug("[handleAgentTransition] Received:", {
    toAgent,
    messageId,
    eventData: event.data,
  });
  
  if (!toAgent) {
    debug.warn("[handleAgentTransition] Missing to_agent in event data");
    return null;
  }

  debug.log("[handleAgentTransition] Agent transition:", {
    from: event.data?.from_agent,
    to: toAgent,
    messageId,
  });

  // Find the current streaming message or use provided messageId
  const messages = store.getMessages(conversationId);
  
  logger.debug("[handleAgentTransition] Current messages:", messages.map(m => ({
    id: m.message_id,
    role: m.role,
    status: m.status,
    agent_type: m.agent_type,
  })));
  
  // If messageId is provided, use it; otherwise find the latest assistant message
  let targetMessageId: string | undefined = messageId;
  if (!targetMessageId) {
    const streamingMessage = messages.find(
      (m) => m.role === MessageRole.ASSISTANT && m.status === MessageStatus.PROCESSING
    );
    targetMessageId = streamingMessage?.message_id;
    logger.debug("[handleAgentTransition] Found streaming message:", streamingMessage?.message_id);
  }

  if (!targetMessageId) {
    console.warn("[handleAgentTransition] No streaming message found to update!");
    debug.warn("[handleAgentTransition] No streaming message found to update");
    return null;
  }

  // Map backend agent names to frontend AgentType
  // Backend uses names like "query", "job", "table", etc.
  const agentType = toAgent.replace("_agent", "").replace("Agent", "");

  logger.debug("[handleAgentTransition] Updating message", targetMessageId, "with agent_type:", agentType);
  
  store.updateMessage(conversationId, targetMessageId, {
    agent_type: agentType as Message["agent_type"],
  });

  debug.log(`[handleAgentTransition] Updated message ${targetMessageId} with agent_type: ${agentType}`);
}

/**
 * Handle USER_INPUT_REQUEST event.
 *
 * When the agent needs input from the user (e.g., clarification),
 * this updates the message with the question so it can be displayed.
 * The message is already marked complete by MESSAGE_END, this just
 * adds the user input context.
 */
export function handleUserInputRequest(
  event: StreamingChatEvent,
  conversationId: string,
  store: MessageStoreOperations
): void | null {
  const messageId = event.data?.message_id as string;
  const question = event.data?.question as string;
  const requestId = event.data?.request_id as string;
  const context = event.data?.context as string | undefined;

  if (!messageId || !question) {
    debug.warn("[handleUserInputRequest] Missing message_id or question in event data");
    return null;
  }

  debug.log("[handleUserInputRequest] User input requested:", {
    messageId,
    requestId,
    questionPreview: question.slice(0, 50),
  });

  // Update the message with the user input request
  // The UI can use this to display the question prominently
  store.updateMessage(conversationId, messageId, {
    metadata: {
      user_input_request: {
        request_id: requestId,
        question: question,
        context: context,
      },
    },
  });
}

