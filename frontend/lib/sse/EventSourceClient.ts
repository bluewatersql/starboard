/**
 * Server-Sent Events (SSE) client for streaming chat events.
 *
 * Provides a wrapper around EventSource with reconnection logic,
 * event parsing, and error handling.
 */

import { logger } from "../utils/logger";
import { EventType } from "../types/api";
import type { StreamingChatEvent } from "../types/api";
import {
  validateStreamingEvent,
  formatValidationError,
  getValidationErrorPath,
} from "../validation/event-schemas";
import { debug } from "../utils/debug";

/**
 * Event handler type.
 */
export type EventHandler = (event: StreamingChatEvent) => void;

/**
 * Error handler type.
 */
export type ErrorHandler = (error: Error) => void;

/**
 * Connection state.
 */
export enum ConnectionState {
  CONNECTING = "connecting",
  CONNECTED = "connected",
  DISCONNECTED = "disconnected",
  ERROR = "error",
}

/**
 * SSE client options.
 */
export interface EventSourceClientOptions {
  /**
   * Conversation ID to stream events for.
   */
  conversationId: string;

  /**
   * Event handler callback.
   */
  onEvent?: EventHandler;

  /**
   * Error handler callback.
   */
  onError?: ErrorHandler;

  /**
   * Connection state change callback.
   */
  onStateChange?: (state: ConnectionState) => void;

  /**
   * Maximum reconnection attempts. Default: 5
   */
  maxReconnectAttempts?: number;

  /**
   * Initial reconnection delay in ms. Default: 1000
   */
  initialReconnectDelay?: number;

  /**
   * Maximum reconnection delay in ms. Default: 30000
   */
  maxReconnectDelay?: number;
}

/**
 * EventSource client for SSE streaming.
 *
 * Handles connection, reconnection, event parsing, and error handling
 * for Server-Sent Events from the chat API.
 *
 * @example
 * ```tsx
 * const client = new EventSourceClient({
 *   conversationId: "conv_123",
 *   onEvent: (event) => {
 *     debug.log("Received event:", event);
 *   },
 *   onError: (error) => {
 *     console.error("SSE error:", error);
 *   },
 * });
 *
 * client.connect();
 *
 * // Later...
 * client.disconnect();
 * ```
 */
export class EventSourceClient {
  private conversationId: string;
  private eventSource: EventSource | null = null;
  private onEvent?: EventHandler;
  private onError?: ErrorHandler;
  private onStateChange?: (state: ConnectionState) => void;
  private reconnectAttempts = 0;
  private maxReconnectAttempts: number;
  private initialReconnectDelay: number;
  private maxReconnectDelay: number;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private state: ConnectionState = ConnectionState.DISCONNECTED;
  private manualDisconnect = false;
  
  /**
   * Whether this client is active and should process events.
   * Set to false when deactivated to prevent race conditions during
   * React StrictMode double-mount/unmount cycles.
   */
  private active = true;
  
  /**
   * Whether we've ever successfully connected (received handleOpen).
   * Used to distinguish initial connection failure (likely 404) from
   * mid-session reconnection attempts.
   */
  private hasConnectedOnce = false;

  constructor(options: EventSourceClientOptions) {
    this.conversationId = options.conversationId;
    this.onEvent = options.onEvent;
    this.onError = options.onError;
    this.onStateChange = options.onStateChange;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.initialReconnectDelay = options.initialReconnectDelay ?? 1000;
    this.maxReconnectDelay = options.maxReconnectDelay ?? 30000;
  }

  /**
   * Get SSE endpoint URL.
   */
  private getUrl(): string {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const basePath = process.env.NEXT_PUBLIC_API_BASE_PATH || "/api";
    return `${apiUrl}${basePath}/chat/conversations/${this.conversationId}/stream`;
  }

  /**
   * Update connection state.
   */
  private setState(state: ConnectionState): void {
    this.state = state;
    this.onStateChange?.(state);
  }

  /**
   * Parse SSE event data with runtime validation.
   */
  private parseEvent(data: string): StreamingChatEvent | null {
    // Note: Returns validated event from Zod schemas, which may not have all
    // ExtendedStreamingChatEvent fields (e.g., conversation_id may be optional)
    // Skip empty or undefined data
    if (!data || data === "undefined" || data.trim() === "") {
      return null;
    }
    
    try {
      // Parse JSON
      const parsed = JSON.parse(data);
      
      // Validate schema
      const validationResult = validateStreamingEvent(parsed);
      
      if (!validationResult.success) {
        // Log detailed validation error
        const errorPath = getValidationErrorPath(validationResult.error);
        
        // Extra debugging for final_output events
        if (parsed?.type === "final_output") {
          console.error("[EventSourceClient] final_output validation failed.");
          console.error("  status:", parsed?.data?.output?.status, typeof parsed?.data?.output?.status);
          console.error("  complete_report:", parsed?.data?.output?.complete_report, typeof parsed?.data?.output?.complete_report);
          console.error("  formatted_report:", parsed?.data?.output?.formatted_report, typeof parsed?.data?.output?.formatted_report);
        }
        
        console.error("[EventSourceClient] Schema validation failed:", {
          eventType: parsed?.type || "unknown",
          errorPath: errorPath.join("."),
          formattedError: formatValidationError(validationResult.error),
          rawData: parsed,
        });
        
        // Report validation error to error handler
        const error = new Error(
          `Event validation failed for type '${parsed?.type || "unknown"}' at ${errorPath.join(".")}`
        );
        this.onError?.(error);
        
        return null;
      }
      
      // Return validated, type-safe event
      // Cast to StreamingChatEvent - validation ensures it's safe
      return validationResult.data as unknown as StreamingChatEvent;
    } catch (error) {
      console.error("[EventSourceClient] Failed to parse SSE event:", error, "Data:", data);
      return null;
    }
  }

  /**
   * Handle SSE message event.
   * Ignores events if client has been deactivated.
   */
  private handleMessage = (event: MessageEvent): void => {
    // Skip processing if client has been deactivated
    if (!this.active) {
      return;
    }
    
    if (!event.data || event.data === "undefined") {
      return;
    }
    
    const parsedEvent = this.parseEvent(event.data);
    if (parsedEvent && this.onEvent) {
      this.onEvent(parsedEvent);
    }
  };

  /**
   * Handle SSE open event.
   */
  private handleOpen = (): void => {
    logger.debug("[EventSourceClient] handleOpen - SSE connection established", { conversationId: this.conversationId });
    this.reconnectAttempts = 0;
    this.hasConnectedOnce = true; // Mark that we've successfully connected
    this.setState(ConnectionState.CONNECTED);
  };

  /**
   * Handle SSE error event.
   */
  private handleError = (error: Event): void => {
    // EventSource errors are often sparse - provide better diagnostics
    const readyState = this.eventSource?.readyState;
    const readyStateStr = readyState === EventSource.CONNECTING ? "CONNECTING" 
      : readyState === EventSource.OPEN ? "OPEN" 
      : readyState === EventSource.CLOSED ? "CLOSED" 
      : `UNKNOWN(${readyState})`;
    
    console.warn("SSE connection error:", {
      type: error.type || "unknown",
      readyState: readyStateStr,
      url: this.eventSource?.url || "no-url",
      state: this.state,
      reconnectAttempts: this.reconnectAttempts,
    });

    // Check if this is a 404 (conversation not found)
    // EventSource doesn't expose HTTP status, but if the connection fails immediately
    // and stays in CONNECTING state, it's likely a 404 or other HTTP error
    // IMPORTANT: Only treat CONNECTING as 404 if we've NEVER connected before.
    // If we have connected before, CONNECTING means auto-reconnect after error event.
    if (this.eventSource?.readyState === EventSource.CONNECTING && !this.hasConnectedOnce) {
      // Initial connection failed to establish - likely 404 or other HTTP error
      // Note: Don't call onError here - the useSSE validation hook already handles
      // 404s before connection attempt, so this would be a duplicate notification
      debug.info("SSE initial connection failed (likely conversation not found)");
      this.setState(ConnectionState.ERROR);
      this.disconnect(); // Don't retry on 404
      return;
    }
    
    // If we were previously connected and now in CONNECTING, it's a reconnect attempt
    if (this.eventSource?.readyState === EventSource.CONNECTING && this.hasConnectedOnce) {
      debug.log("SSE reconnecting after error, allowing auto-reconnect");
      // Don't disconnect - let EventSource auto-reconnect
      return;
    }

    // Connection failed or closed
    if (this.eventSource?.readyState === EventSource.CLOSED) {
      this.setState(ConnectionState.ERROR);

      // Attempt reconnection if not manually disconnected
      if (!this.manualDisconnect) {
        this.reconnect();
      }
    }
  };

  /**
   * Calculate reconnection delay with exponential backoff.
   */
  private getReconnectDelay(): number {
    const delay = Math.min(
      this.initialReconnectDelay * Math.pow(2, this.reconnectAttempts),
      this.maxReconnectDelay
    );
    // Add jitter
    return delay + Math.random() * 1000;
  }

  /**
   * Attempt to reconnect.
   */
  private reconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      const error = new Error(
        `Max reconnection attempts (${this.maxReconnectAttempts}) exceeded`
      );
      this.onError?.(error);
      return;
    }

    this.reconnectAttempts++;
    const delay = this.getReconnectDelay();

    debug.log(
      `Reconnecting in ${Math.round(delay / 1000)}s (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  /**
   * Connect to SSE stream.
   */
  public connect(): void {
    logger.debug("[EventSourceClient] connect() called", { conversationId: this.conversationId });
    
    if (this.eventSource) {
      debug.warn("EventSource already connected");
      return;
    }

    // Re-activate when connecting (in case this client was reused)
    this.active = true;
    this.manualDisconnect = false;
    this.setState(ConnectionState.CONNECTING);
    logger.debug("[EventSourceClient] State set to CONNECTING");

    try {
      const url = this.getUrl();
      logger.debug("[EventSourceClient] Creating EventSource with URL:", url);
      this.eventSource = new EventSource(url);

      // Setup event listeners
      this.eventSource.addEventListener("open", this.handleOpen);
      this.eventSource.addEventListener("error", this.handleError);
      
      // NOTE: We do NOT add a generic "message" event listener here.
      // SSE events from the backend are sent with specific event types (e.g., "message_delta").
      // The generic "message" event would only fire for events without an explicit type,
      // but our backend always sends typed events. Adding both listeners would cause
      // duplicate event processing and potential infinite loops in state updates.

      // Listen for all event types (must match backend exactly)
      const eventTypes = [
        EventType.MESSAGE_START,
        EventType.MESSAGE_DELTA,
        EventType.MESSAGE_END,
        EventType.TOOL_CALL_START,
        EventType.TOOL_PROGRESS,
        EventType.TOOL_CALL_RESULT,
        EventType.FINAL_OUTPUT,
        EventType.ERROR,
        // HEARTBEAT removed - not in EventType enum
        EventType.THINKING,
        EventType.STEP_START,
        EventType.STEP_COMPLETE,
        EventType.ROUTING_DECISION,
        EventType.AGENT_TRANSITION,
        EventType.USER_INPUT_REQUEST,
        EventType.USER_INPUT_RESPONSE,
        EventType.FRIENDLY_NAME_UPDATE,
        EventType.NEXT_STEPS,  // Phase 1: Next steps pattern
        EventType.CLARIFICATION_REQUEST,  // Phase 7: Clarification pattern
      ];

      eventTypes.forEach((eventType) => {
        this.eventSource?.addEventListener(eventType, this.handleMessage);
      });
    } catch (error) {
      const err =
        error instanceof Error ? error : new Error("Failed to connect");
      this.onError?.(err);
      this.setState(ConnectionState.ERROR);
    }
  }

  /**
   * Deactivate this client immediately.
   * 
   * Call this before disconnect() to prevent race conditions where events
   * arrive between starting disconnect and the connection actually closing.
   * This is especially important for React StrictMode double-mount/unmount.
   */
  public deactivate(): void {
    logger.debug("[EventSourceClient] deactivate() called", { conversationId: this.conversationId });
    this.active = false;
  }

  /**
   * Check if client is active.
   */
  public isActive(): boolean {
    return this.active;
  }

  /**
   * Disconnect from SSE stream.
   */
  public disconnect(): void {
    logger.debug("[EventSourceClient] disconnect() called", { conversationId: this.conversationId });
    // Deactivate first to prevent any new events from being processed
    this.active = false;
    this.manualDisconnect = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.setState(ConnectionState.DISCONNECTED);
  }

  /**
   * Get current connection state.
   */
  public getState(): ConnectionState {
    return this.state;
  }

  /**
   * Check if connected.
   */
  public isConnected(): boolean {
    return this.state === ConnectionState.CONNECTED;
  }
}

