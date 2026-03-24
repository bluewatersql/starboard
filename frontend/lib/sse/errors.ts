/**
 * Structured error types for SSE and useSSE.
 *
 * Provides clear error types with codes and recovery actions.
 */

/**
 * Base error class for SSE-related errors.
 */
export class SSEError extends Error {
  constructor(
    message: string,
    public code: string,
    public recoveryAction?: string
  ) {
    super(message);
    this.name = "SSEError";
  }
}

/**
 * Error when conversation is not found (404).
 */
export class ConversationNotFoundError extends SSEError {
  constructor(public conversationId: string) {
    super(
      "Conversation no longer exists",
      "CONVERSATION_NOT_FOUND",
      "Start a new conversation or reload the page"
    );
    this.name = "ConversationNotFoundError";
  }
}

/**
 * Error when event validation fails.
 */
export class EventValidationError extends SSEError {
  constructor(
    public eventType: string,
    public errorPath: string,
    public details?: string
  ) {
    super(
      `Event validation failed for type '${eventType}' at ${errorPath}`,
      "EVENT_VALIDATION_ERROR",
      "This is likely a backend issue. Try refreshing the page."
    );
    this.name = "EventValidationError";
  }
}

/**
 * Error when connection to SSE stream fails.
 */
export class ConnectionError extends SSEError {
  constructor(
    message: string,
    public attempt?: number,
    public maxAttempts?: number
  ) {
    const recoveryMsg =
      attempt && maxAttempts && attempt >= maxAttempts
        ? "Maximum reconnection attempts exceeded. Reload the page to reconnect."
        : "Attempting to reconnect...";

    super(message, "CONNECTION_ERROR", recoveryMsg);
    this.name = "ConnectionError";
  }
}

/**
 * Error when required data is missing from event.
 */
export class MissingDataError extends SSEError {
  constructor(
    public eventType: string,
    public missingField: string
  ) {
    super(
      `Missing required field '${missingField}' in ${eventType} event`,
      "MISSING_DATA_ERROR",
      "This event will be skipped. If the issue persists, reload the page."
    );
    this.name = "MissingDataError";
  }
}

/**
 * Error utilities.
 */
export const SSEErrors = {
  /**
   * Create ConversationNotFoundError.
   */
  conversationNotFound: (conversationId: string) =>
    new ConversationNotFoundError(conversationId),

  /**
   * Create EventValidationError.
   */
  eventValidation: (eventType: string, errorPath: string, details?: string) =>
    new EventValidationError(eventType, errorPath, details),

  /**
   * Create ConnectionError.
   */
  connection: (message: string, attempt?: number, maxAttempts?: number) =>
    new ConnectionError(message, attempt, maxAttempts),

  /**
   * Create MissingDataError.
   */
  missingData: (eventType: string, missingField: string) =>
    new MissingDataError(eventType, missingField),

  /**
   * Check if error is an SSEError.
   */
  isSSEError: (error: unknown): error is SSEError => {
    return error instanceof SSEError;
  },

  /**
   * Check if error is ConversationNotFoundError.
   */
  isConversationNotFound: (error: unknown): error is ConversationNotFoundError => {
    return error instanceof ConversationNotFoundError;
  },

  /**
   * Check if error is EventValidationError.
   */
  isEventValidation: (error: unknown): error is EventValidationError => {
    return error instanceof EventValidationError;
  },

  /**
   * Check if error is ConnectionError.
   */
  isConnection: (error: unknown): error is ConnectionError => {
    return error instanceof ConnectionError;
  },

  /**
   * Check if error is MissingDataError.
   */
  isMissingData: (error: unknown): error is MissingDataError => {
    return error instanceof MissingDataError;
  },

  /**
   * Get user-friendly error message with recovery action.
   */
  getUserMessage: (error: unknown): string => {
    if (SSEErrors.isSSEError(error)) {
      const message = error.message;
      const recovery = error.recoveryAction;
      return recovery ? `${message}. ${recovery}` : message;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return "An unexpected error occurred";
  },

  /**
   * Get error code for tracking/logging.
   */
  getErrorCode: (error: unknown): string => {
    if (SSEErrors.isSSEError(error)) {
      return error.code;
    }

    if (error instanceof Error) {
      return "UNKNOWN_ERROR";
    }

    return "UNKNOWN";
  },
};

