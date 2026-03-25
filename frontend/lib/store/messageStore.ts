/**
 * Zustand store for message state management.
 *
 * Phase 2: Uses structured tool_positions for rendering (no markers).
 * Manages messages within conversations, including streaming updates.
 */

import { create } from "zustand";
import type { Message } from "../types/api";
import { MessageStatus } from "../types/api";
import { logger } from "../utils/logger";

/**
 * Clean and filter message content.
 * Removes LLM annotations and normalizes whitespace in thinking text.
 * Preserves markdown formatting in report sections (after ---).
 */
function cleanMessageContent(content: string): string {
  // Split at --- separator to handle thinking vs markdown sections separately
  const parts = content.split(/\n---\n/);
  
  if (parts.length > 1) {
    // Has both thinking and markdown sections
    // Clean only the thinking part (before ---), preserve markdown formatting after
    const thinkingPart = addThinkingLineBreaks(parts[0])
      // Remove [Calling...] patterns
      .replace(/\[Calling[^\]]*\]/g, ' ')
      // Collapse multiple spaces
      .replace(/  +/g, ' ')
      // Collapse multiple newlines
      .replace(/\n{3,}/g, '\n\n')
      // Clean up spaces around newlines
      .replace(/ \n/g, '\n')
      .replace(/\n /g, '\n');
    
    // Keep markdown parts unchanged (they need specific formatting)
    const markdownParts = parts.slice(1);
    
    return [thinkingPart, ...markdownParts].join('\n---\n');
  }
  
  // No markdown section yet, clean as thinking text and add line breaks
  return addThinkingLineBreaks(content)
    // Remove [Calling...] patterns
    .replace(/\[Calling[^\]]*\]/g, ' ')
    // Collapse multiple spaces
    .replace(/  +/g, ' ')
    // Collapse multiple newlines
    .replace(/\n{3,}/g, '\n\n')
    // Clean up spaces around newlines
    .replace(/ \n/g, '\n')
    .replace(/\n /g, '\n');
}

/**
 * Add line breaks before common thinking patterns in LLM responses.
 * DISABLED: Backend sends appropriate spacing already.
 */
function addThinkingLineBreaks(text: string): string {
  // Return text as-is - backend handles spacing
  return text;
}

interface ThinkingStepData {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  startTime?: number;
  endTime?: number;
  progress?: number;
  subTasks?: Array<{
    id: string;
    description: string;
    status: "pending" | "in_progress" | "completed" | "failed";
    value?: string | number;
  }>;
  metadata?: Record<string, unknown>;
  /** Call details for tool execution (U3) */
  callDetails?: {
    toolName: string;
    parameters?: Record<string, unknown>;
    response?: unknown;
    responseIsTruncated?: boolean;
    error?: string;
  };
}

/**
 * Thinking indicator state for real-time feedback.
 * This is ephemeral and NOT persisted to conversation history.
 */
export interface ThinkingIndicatorState {
  /** Current state: idle, thinking, or completed */
  state: "idle" | "thinking" | "completed";
  /** When thinking started (epoch ms) */
  startTime?: number;
  /** Duration in seconds (when completed) */
  durationSeconds?: number;
  /** Title/name of current step (e.g., "Generating Analysis") */
  stepTitle?: string;
}

interface MessageState {
  // Messages by conversation ID
  messagesByConversation: Record<string, Message[]>;

  // Currently streaming message ID (if any)
  streamingMessageId: string | null;

  // Thinking indicator state per message (ephemeral, not persisted)
  thinkingByMessage: Record<string, ThinkingIndicatorState>;

  // Actions
  setMessages: (conversationId: string, messages: Message[]) => void;
  addMessage: (conversationId: string, message: Message) => void;
  updateMessage: (
    conversationId: string,
    messageId: string,
    updates: Partial<Message>
  ) => void;
  appendToMessage: (
    conversationId: string,
    messageId: string,
    content: string
  ) => void;
  setStreamingMessage: (messageId: string | null) => void;
  getMessages: (conversationId: string) => Message[];
  clearMessages: (conversationId: string) => void;
  retryMessage: (conversationId: string, messageId: string) => Message | null;
  moveMessages: (fromConversationId: string, toConversationId: string) => void;
  updateThinkingStep: (
    conversationId: string,
    messageId: string,
    step: ThinkingStepData
  ) => void;
  setThinkingIndicator: (
    messageId: string,
    state: "idle" | "thinking" | "completed",
    durationSeconds?: number,
    stepTitle?: string
  ) => void;
  getThinkingIndicator: (messageId: string) => ThinkingIndicatorState;
  reset: () => void;
}

const initialState = {
  messagesByConversation: {},
  streamingMessageId: null,
  thinkingByMessage: {},
};

/**
 * Message store.
 *
 * Manages messages for all conversations with support for streaming updates.
 *
 * @example
 * ```tsx
 * const { getMessages, addMessage, appendToMessage } = useMessageStore();
 *
 * // Get messages for a conversation
 * const messages = getMessages(conversationId);
 *
 * // Add a new message
 * addMessage(conversationId, newMessage);
 *
 * // Append to streaming message
 * appendToMessage(conversationId, messageId, " more text");
 * ```
 */
export const useMessageStore = create<MessageState>((set, get) => ({
  ...initialState,

  setMessages: (conversationId, messages) =>
    set((state) => {
      // Deduplicate incoming messages by ID
      const seen = new Set();
      const uniqueMessages = messages.filter(m => {
        if (!m.message_id) return true;
        if (seen.has(m.message_id)) return false;
        seen.add(m.message_id);
        return true;
      });

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: uniqueMessages.map((msg) => {
            // Promote complete_report from metadata to top level if present
            const complete_report = msg.complete_report || msg.metadata?.complete_report || null;
            
            // Phase 2: Promote tool_positions from metadata to top level
            const tool_positions = msg.tool_positions || msg.metadata?.tool_positions || [];
            
            // B2 fix: Promote thinking_steps from metadata for history reload
            const thinking_steps = msg.thinking_steps || msg.metadata?.thinking_steps || [];
            
            return {
              ...msg,
              // Phase 2: Clean message structure (no marker manipulation)
              tool_calls: msg.tool_calls || [],
              tool_positions: tool_positions,
              complete_report: complete_report,
              // B2 fix: Ensure thinking_steps are available on reload
              thinking_steps: thinking_steps,
            };
          }),
        },
      };
    }),

  addMessage: (conversationId, message) =>
    set((state) => {
      const existingMessages = state.messagesByConversation[conversationId] || [];
      
      // Check if message with this ID already exists
      const existingMessageIndex = existingMessages.findIndex(m => m.message_id === message.message_id);
      
      if (existingMessageIndex >= 0) {
        // Don't add duplicate messages
        // console.warn(`[messageStore] Duplicate message ${message.message_id} ignored`);
        return state;
      }

      logger.debug(`[messageStore] Adding message ${message.message_id} to ${conversationId}`);
      
      // Append new message
      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: [...existingMessages, message],
        },
      };
    }),

  updateMessage: (conversationId, messageId, updates) =>
    set((state) => {
      const timestamp = new Date().toISOString().substring(11, 23); // HH:MM:SS.mmm

      // Log when tool_calls or tool_positions are updated
      if (updates.tool_calls || updates.tool_positions) {
        logger.debug(`[${timestamp}] [updateMessage] Updating tools for ${messageId}:`, {
          toolCallsCount: updates.tool_calls?.length,
          toolPositionsCount: updates.tool_positions?.length,
          toolNames: updates.tool_calls?.map(tc => tc.tool_name),
        });
      }
      
      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: (
            state.messagesByConversation[conversationId] || []
          ).map((msg) => {
            if (msg.message_id === messageId) {
              // Phase 2: Simple update without marker manipulation
              return { ...msg, ...updates };
            }
            return msg;
          }),
        },
      };
    }),

  appendToMessage: (conversationId, messageId, content) =>
    set((state) => {
      const timestamp = new Date().toISOString().substring(11, 23); // HH:MM:SS.mmm
      logger.debug(`[${timestamp}] [appendToMessage] Adding content to ${messageId}:`, {
        contentLength: content?.length,
        contentPreview: content?.substring(0, 50),
      });
      
      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: (
            state.messagesByConversation[conversationId] || []
          ).map((msg) => {
            if (msg.message_id !== messageId) {
              return msg;
            }
            
            // Add intelligent spacing between thinking chunks
            // Keep it simple: add space after sentence-ending punctuation
            let separator = '';
            
            if (msg.content && content) {
              const lastChar = msg.content.slice(-1);
              const firstChar = content.charAt(0);
              
              // Add space after sentence-ending punctuation if next starts with capital
              if (
                (lastChar === '.' || lastChar === '!' || lastChar === '?') &&
                firstChar.match(/[A-Z]/)
              ) {
                separator = ' ';
              }
              // Add space after colon if followed by capital
              else if (lastChar === ':' && firstChar.match(/[A-Z]/)) {
                separator = ' ';
              }
              // Don't add space if content already has whitespace at boundaries
              else if (lastChar.match(/\s/) || firstChar.match(/\s/)) {
                separator = '';
              }
              // Don't add space for punctuation
              else if (firstChar.match(/[.!?,;:'")\]]/)) {
                separator = '';
              }
            }
            
            const contentToAppend = content;
            const newContent = cleanMessageContent(msg.content + separator + contentToAppend);
            
            logger.debug(`[${timestamp}] [appendToMessage] Content updated:`, {
              oldLength: msg.content?.length || 0,
              newLength: newContent?.length || 0,
              toolCallsCount: msg.tool_calls?.length || 0,
              toolPositionsCount: msg.tool_positions?.length || 0,
            });
            
            return { 
              ...msg, 
              content: newContent,
            };
          }),
        },
      };
    }),

  setStreamingMessage: (messageId) => set({ streamingMessageId: messageId }),

  getMessages: (conversationId) => {
    return get().messagesByConversation[conversationId] || [];
  },

  clearMessages: (conversationId) =>
    set((state) => {
      const newMessages = { ...state.messagesByConversation };
      delete newMessages[conversationId];
      return { messagesByConversation: newMessages };
    }),

  retryMessage: (conversationId, messageId) => {
    const state = get();
    const messages = state.messagesByConversation[conversationId] || [];
    const message = messages.find((m) => m.message_id === messageId);

    if (!message) {
      console.warn("Message not found for retry:", messageId);
      return null;
    }

    // Check retry limit (max 3 attempts)
    const retryCount = message.retry_count || 0;
    if (retryCount >= 3) {
      console.warn("Max retry attempts (3) reached for message:", messageId);
      return null;
    }

    // Update message to processing state with incremented retry count
    set((state) => ({
      messagesByConversation: {
        ...state.messagesByConversation,
        [conversationId]: messages.map((msg) =>
          msg.message_id === messageId
            ? {
                ...msg,
                status: MessageStatus.PROCESSING,
                retry_count: retryCount + 1,
              }
            : msg
        ),
      },
    }));

    // Return the updated message for the caller to re-send
    return {
      ...message,
      status: MessageStatus.PROCESSING,
      retry_count: retryCount + 1,
    };
  },

  moveMessages: (fromConversationId, toConversationId) =>
    set((state) => {
      const messages = state.messagesByConversation[fromConversationId] || [];
      
      if (messages.length === 0) {
        logger.debug(`[messageStore] No messages to move from ${fromConversationId}`);
        return state;  // Nothing to move
      }

      logger.debug(`[messageStore] Moving ${messages.length} messages from ${fromConversationId} to ${toConversationId}`);
      
      // Update conversation_id in all messages
      const movedMessages = messages.map(msg => ({
        ...msg,
        conversation_id: toConversationId,
      }));
      
      // Remove from old ID, add to new ID
      const newState = { ...state.messagesByConversation };
      delete newState[fromConversationId];
      newState[toConversationId] = [
        ...(newState[toConversationId] || []),
        ...movedMessages,
      ];
      
      return {
        messagesByConversation: newState,
      };
    }),

  updateThinkingStep: (conversationId, messageId, step) =>
    set((state) => {
      const messages = state.messagesByConversation[conversationId] || [];
      
      // Find the message (or use "current" to target streaming message)
      const targetMessageId = messageId === "current" 
        ? state.streamingMessageId 
        : messageId;
      
      if (!targetMessageId) {
        console.warn("[messageStore] No target message for thinking step");
        return state;
      }

      // Find the target message
      const targetMessage = messages.find(m => m.message_id === targetMessageId);
      if (!targetMessage) {
        return state; // Message not found, no change
      }

      // Get existing thinking steps
      const existingSteps = targetMessage.thinking_steps || [];
      const existingIndex = existingSteps.findIndex(s => s.id === step.id);

      // Check if this is actually a change - prevents infinite update loops
      if (existingIndex >= 0) {
        const existingStep = existingSteps[existingIndex];
        // Check if status is the same (most common update trigger)
        if (
          existingStep.status === step.status &&
          existingStep.title === step.title &&
          existingStep.progress === step.progress &&
          // Only compare callDetails if provided in the update
          (!step.callDetails || existingStep.callDetails === step.callDetails)
        ) {
          return state; // No meaningful change, don't trigger re-render
        }
      }
      
      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: messages.map((msg) => {
            if (msg.message_id !== targetMessageId) return msg;
            
            let updatedSteps;
            if (existingIndex >= 0) {
              // Update existing step
              updatedSteps = [...existingSteps];
              updatedSteps[existingIndex] = {
                ...existingSteps[existingIndex],
                ...step,
                // Merge sub-tasks if both exist
                subTasks: step.subTasks || existingSteps[existingIndex].subTasks,
                // Merge call details if provided (U3 - 3-level thinking steps)
                callDetails: step.callDetails || existingSteps[existingIndex].callDetails,
              };
            } else {
              // Add new step
              updatedSteps = [...existingSteps, step];
            }
            
            return {
              ...msg,
              thinking_steps: updatedSteps,
            };
          }),
        },
      };
    }),

  setThinkingIndicator: (messageId, state, durationSeconds, stepTitle) =>
    set((prevState) => {
      const current = prevState.thinkingByMessage[messageId] || {
        state: "idle",
      };

      // Calculate new values
      const newStartTime = state === "thinking" 
        ? (current.state === "thinking" ? current.startTime : Date.now())
        : current.startTime;
      const newDurationSeconds = state === "completed" ? durationSeconds : undefined;
      const newStepTitle = stepTitle ?? (state === "idle" ? undefined : current.stepTitle);

      // Early return if no actual change - prevents infinite update loops
      if (
        current.state === state &&
        current.startTime === newStartTime &&
        current.durationSeconds === newDurationSeconds &&
        current.stepTitle === newStepTitle
      ) {
        return prevState; // No change, don't trigger re-render
      }

      return {
        thinkingByMessage: {
          ...prevState.thinkingByMessage,
          [messageId]: {
            state,
            startTime: newStartTime,
            durationSeconds: newDurationSeconds,
            stepTitle: newStepTitle,
          },
        },
      };
    }),

  getThinkingIndicator: (messageId) => {
    return get().thinkingByMessage[messageId] || { state: "idle" };
  },

  reset: () => set(initialState),
}));
