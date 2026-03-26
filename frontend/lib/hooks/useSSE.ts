/**
 * React hook for SSE streaming.
 *
 * Manages EventSource connection lifecycle and event handling.
 */

import { useEffect, useRef, useState } from "react";
import { EventSourceClient, ConnectionState } from "../sse/EventSourceClient";
import type { StreamingChatEvent } from "../types/api";
import { EventType } from "../types/api";
import { useMessageStore } from "../store/messageStore";
import { useConversationStore } from "../store/conversationStore";
import { SSEErrors } from "../sse/errors";
import { debug } from "../utils/debug";
import {
  handleMessageStart,
  handleMessageDelta,
  handleMessageComplete,
  handleToolCallStart,
  handleToolCallResult,
  handleFinalOutput,
  handleError,
  handleFriendlyNameUpdate,
  handleStepStart,
  handleNextSteps,
  handleAgentTransition,
  handleUserInputRequest,
} from "../sse/event-handlers";

/**
 * SSE hook options.
 */
export interface UseSSEOptions {
  /**
   * Conversation ID to stream events for.
   */
  conversationId: string;

  /**
   * Whether to auto-connect on mount. Default: true
   */
  autoConnect?: boolean;

  /**
   * Whether this is a newly created conversation (skip existence check).
   * Set to true for conversations just created via API to avoid race conditions.
   * Default: false (will validate conversation exists before connecting)
   */
  skipValidation?: boolean;

  /**
   * Custom event handler (optional, events also go to message store).
   */
  onEvent?: (event: StreamingChatEvent) => void;

  /**
   * Error handler.
   */
  onError?: (error: Error) => void;
}

/**
 * Hook for SSE streaming.
 *
 * Manages EventSource connection and integrates with message store
 * to update UI in real-time as events are received.
 *
 * @param options - Hook options
 * @returns Connection state and control functions
 *
 * @example
 * ```tsx
 * const { state, connect, disconnect } = useSSE({
 *   conversationId: "conv_123",
 *   onEvent: (event) => {
 *     debug.log("Event received:", event);
 *   },
 * });
 *
 * // State: "connecting" | "connected" | "disconnected" | "error"
 * ```
 */
export function useSSE(options: UseSSEOptions) {
  const {
    conversationId,
    autoConnect = true,
    skipValidation = false,
    onEvent,
    onError,
  } = options;

  const [state, setState] = useState<ConnectionState>(
    ConnectionState.DISCONNECTED
  );

  const clientRef = useRef<EventSourceClient | null>(null);
  const errorNotifiedRef = useRef<boolean>(false); // Track if error notification already shown
  const activeClientIdRef = useRef<string | null>(null); // Track active client to ignore stale events

  // Stable refs for callbacks to prevent stale closures in event handlers
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  // Handle SSE events (created in useEffect with clientId closure)
  // NOTE: We use getState() instead of useMessageStore() to avoid subscribing
  // the hook to store changes, which would cause re-renders on every update
  // and potentially trigger infinite update loops during rapid SSE events.
  const createEventHandler = (clientId: string) => (event: StreamingChatEvent) => {
    // CRITICAL: Only process events from the active client
    // This prevents duplicate events when React StrictMode causes rapid unmount/remount
    // The old client may still receive events before server detects disconnect
    if (activeClientIdRef.current !== clientId) {
      debug.log('[useSSE] Ignoring event from stale client', { clientId, activeId: activeClientIdRef.current });
      return;
    }
    
    debug.log('[useSSE] Event received:', event.type, 'data:', event.data);
    
    // Get fresh store actions using getState() - avoids subscription-based re-renders
    const messageStore = useMessageStore.getState();
    
    // Create store adapters for handlers with fresh function references
    const messageStoreAdapter = {
      addMessage: messageStore.addMessage,
      updateMessage: messageStore.updateMessage,
      appendToMessage: messageStore.appendToMessage,
      setStreamingMessage: messageStore.setStreamingMessage,
      updateThinkingStep: messageStore.updateThinkingStep,
      setThinkingIndicator: messageStore.setThinkingIndicator,
      getThinkingIndicator: messageStore.getThinkingIndicator,
      // Get fresh messages from current state
      getMessages: (convId: string) => useMessageStore.getState().messagesByConversation[convId] || [],
    };
    
    const conversationStoreAdapter = {
      updateConversation: useConversationStore.getState().updateConversation,
    };
    
    // Delegate to extracted handlers based on event type
    switch (event.type) {
      case EventType.MESSAGE_START:
        handleMessageStart(event, conversationId, messageStoreAdapter);
        break;

      case EventType.MESSAGE_DELTA:
      case EventType.THINKING:
        handleMessageDelta(event, conversationId, messageStoreAdapter);
        break;

      case EventType.MESSAGE_END:
        // MESSAGE_END signals completion of message processing
        handleMessageComplete(event, conversationId, messageStoreAdapter);
        break;

      case EventType.TOOL_CALL_START:
        handleToolCallStart(event, conversationId, messageStoreAdapter);
        break;

      case EventType.TOOL_CALL_RESULT:
        handleToolCallResult(event, conversationId, messageStoreAdapter);
        break;

      case EventType.FINAL_OUTPUT:
        handleFinalOutput(event, conversationId, messageStoreAdapter);
        break;

      case EventType.ERROR:
        handleError(event, conversationId, messageStoreAdapter);
        break;

      case EventType.FRIENDLY_NAME_UPDATE:
        handleFriendlyNameUpdate(event, conversationId, conversationStoreAdapter);
        break;

      // V2 Multi-Agent events
      case EventType.STEP_START:
        // Enhanced thinking step event with sub-tasks
        handleStepStart(event, conversationId, messageStoreAdapter);
        break;

      case EventType.STEP_COMPLETE:
      case EventType.ROUTING_DECISION:
      case EventType.TOOL_PROGRESS:
        // Informational events, no UI updates needed
        break;

      case EventType.AGENT_TRANSITION:
        // Update message with agent type for visual indicator
        handleAgentTransition(event, conversationId, messageStoreAdapter);
        break;

      case EventType.NEXT_STEPS:
        // Handle next steps event (Phase 1 - Conversation Patterns)
        handleNextSteps(event, conversationId, messageStoreAdapter);
        break;

      case EventType.USER_INPUT_REQUEST:
        // Handle user input requests (Phase 3 - Interruptible Reasoning)
        handleUserInputRequest(event, conversationId, messageStoreAdapter);
        break;

      case EventType.USER_INPUT_RESPONSE:
        // TODO(PHASE-03): Handle user input responses for interruptible reasoning
        break;

      // HEARTBEAT events handled at EventSourceClient level, not typed in EventType

      default:
        debug.warn(`[useSSE] Unhandled event type: ${event.type}`);
        break;
    }

    // Call custom handler if provided (via ref to avoid stale closure)
    onEventRef.current?.(event);
  };

  // Create and setup client
  useEffect(() => {
    // Generate unique client ID for this effect instance
    // This is used to ignore events from stale clients during React StrictMode double-mount
    const clientId = `client_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    activeClientIdRef.current = clientId;
    
    debug.log("[useSSE] Creating new client", { clientId, conversationId, autoConnect, skipValidation });
    
    // Reset error notification flag when conversation changes
    errorNotifiedRef.current = false;
    
    // Create event handler bound to this client's ID
    const handleEvent = createEventHandler(clientId);
    
    const client = new EventSourceClient({
      conversationId,
      onEvent: handleEvent,
      onError: (error) => {
        // Only process errors from active client
        if (activeClientIdRef.current !== clientId) {
          return;
        }
        console.error("SSE error:", error);
        onErrorRef.current?.(error);
      },
      onStateChange: (newState) => {
        // Only update state from active client
        if (activeClientIdRef.current !== clientId) {
          return;
        }
        setState(newState);
      },
    });

    clientRef.current = client;

    // Create AbortController to cancel pending requests on cleanup
    const abortController = new AbortController();

    if (autoConnect) {
      if (skipValidation) {
        // Newly created conversation - trust it exists and connect immediately
        debug.log("[useSSE] Skipping validation, connecting immediately", { conversationId, skipValidation });
        client.connect();
      } else {
        debug.log("[useSSE] Validating conversation exists before connecting", { conversationId, skipValidation });
        // Existing conversation - validate it still exists before connecting
        // This prevents SSE errors after server restarts (conversations are in-memory)
        fetch(`/api/chat/conversations/${conversationId}`, {
          method: "HEAD",
          signal: abortController.signal,
        })
          .then((response) => {
            // Check if this client is still active before proceeding
            if (activeClientIdRef.current !== clientId) {
              debug.log("[useSSE] Validation response received for stale client, ignoring");
              return;
            }
            
            if (response.ok) {
              // Conversation exists, safe to connect
              client.connect();
            } else if (response.status === 404) {
              // Conversation no longer exists (server restarted)
              // Handle gracefully without throwing error to console
              debug.info(
                `Conversation ${conversationId} not found on server (likely server restart)`
              );
              
              // Notify parent component with structured error (only once)
              if (!errorNotifiedRef.current && onErrorRef.current) {
                errorNotifiedRef.current = true;
                onErrorRef.current(SSEErrors.conversationNotFound(conversationId));
              }
              
              setState(ConnectionState.DISCONNECTED);
            } else if (response.status === 500) {
              // 500 error - likely conversation doesn't exist (backend error)
              debug.error(
                `Server error for conversation ${conversationId} (likely deleted or doesn't exist)`
              );
              
              // Treat 500 as "not found" for conversations
              if (!errorNotifiedRef.current && onErrorRef.current) {
                errorNotifiedRef.current = true;
                onErrorRef.current(SSEErrors.conversationNotFound(conversationId));
              }
              
              setState(ConnectionState.DISCONNECTED);
            } else {
              // Other error (503, etc.)
              console.error(
                `Failed to verify conversation: ${response.status}`
              );
              client.connect(); // Try connecting anyway
            }
          })
          .catch((error) => {
            // Ignore abort errors - these are expected on cleanup
            if (error.name === "AbortError") {
              debug.log("[useSSE] Validation request aborted (cleanup)");
              return;
            }
            // Check if this client is still active before proceeding
            if (activeClientIdRef.current !== clientId) {
              return;
            }
            console.error("Failed to check conversation existence:", error);
            client.connect(); // Try connecting anyway on network error
          });
      }
    }

    return () => {
      debug.log("[useSSE] Cleanup: deactivating client", { clientId });
      // Abort any pending validation requests
      abortController.abort();
      // Mark both the ref AND client as inactive to prevent race conditions
      // The client's active flag is checked synchronously in handleMessage
      // This prevents events from being processed during the async disconnect
      if (activeClientIdRef.current === clientId) {
        activeClientIdRef.current = null;
      }
      // Deactivate client immediately (synchronous) - prevents any new events
      client.deactivate();
      // Then disconnect (may be async due to reconnect timeout cleanup)
      client.disconnect();
    };
    // Note: handleEvent, onError intentionally omitted to prevent re-creating client on every render
    // skipValidation IS included because it determines the initial connection path
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, autoConnect, skipValidation]);

  // Control functions
  const connect = () => {
    clientRef.current?.connect();
  };

  const disconnect = () => {
    clientRef.current?.disconnect();
  };

  const isConnected = () => {
    return clientRef.current?.isConnected() ?? false;
  };

  return {
    state,
    connect,
    disconnect,
    isConnected,
  };
}

