/**
 * Tests for SSE error types and utilities.
 */

import {
  SSEError,
  ConversationNotFoundError,
  EventValidationError,
  ConnectionError,
  MissingDataError,
  SSEErrors,
} from "../errors";

describe("SSE Error Types", () => {
  describe("SSEError", () => {
    it("creates base SSE error", () => {
      const error = new SSEError("Test error", "TEST_ERROR", "Try again");

      expect(error.message).toBe("Test error");
      expect(error.code).toBe("TEST_ERROR");
      expect(error.recoveryAction).toBe("Try again");
      expect(error.name).toBe("SSEError");
      expect(error instanceof Error).toBe(true);
    });

    it("creates SSE error without recovery action", () => {
      const error = new SSEError("Test error", "TEST_ERROR");

      expect(error.recoveryAction).toBeUndefined();
    });
  });

  describe("ConversationNotFoundError", () => {
    it("creates conversation not found error", () => {
      const error = new ConversationNotFoundError("conv_123");

      expect(error.message).toBe("Conversation no longer exists");
      expect(error.code).toBe("CONVERSATION_NOT_FOUND");
      expect(error.conversationId).toBe("conv_123");
      expect(error.recoveryAction).toContain("Start a new conversation");
      expect(error.name).toBe("ConversationNotFoundError");
    });
  });

  describe("EventValidationError", () => {
    it("creates event validation error", () => {
      const error = new EventValidationError(
        "tool.call.start",
        "data.tool_call.tool_call_id",
        "Expected string, received undefined"
      );

      expect(error.message).toContain("tool.call.start");
      expect(error.message).toContain("data.tool_call.tool_call_id");
      expect(error.code).toBe("EVENT_VALIDATION_ERROR");
      expect(error.eventType).toBe("tool.call.start");
      expect(error.errorPath).toBe("data.tool_call.tool_call_id");
      expect(error.details).toBe("Expected string, received undefined");
      expect(error.recoveryAction).toContain("backend issue");
    });

    it("creates validation error without details", () => {
      const error = new EventValidationError("message.start", "data.message_id");

      expect(error.details).toBeUndefined();
    });
  });

  describe("ConnectionError", () => {
    it("creates connection error", () => {
      const error = new ConnectionError("Failed to connect", 1, 5);

      expect(error.message).toBe("Failed to connect");
      expect(error.code).toBe("CONNECTION_ERROR");
      expect(error.attempt).toBe(1);
      expect(error.maxAttempts).toBe(5);
      expect(error.recoveryAction).toContain("reconnect");
    });

    it("shows max attempts message when exceeded", () => {
      const error = new ConnectionError("Failed to connect", 5, 5);

      expect(error.recoveryAction).toContain("Maximum reconnection attempts exceeded");
      expect(error.recoveryAction).toContain("Reload the page");
    });

    it("creates connection error without attempts", () => {
      const error = new ConnectionError("Failed to connect");

      expect(error.attempt).toBeUndefined();
      expect(error.maxAttempts).toBeUndefined();
    });
  });

  describe("MissingDataError", () => {
    it("creates missing data error", () => {
      const error = new MissingDataError("message.start", "message_id");

      expect(error.message).toContain("message.start");
      expect(error.message).toContain("message_id");
      expect(error.code).toBe("MISSING_DATA_ERROR");
      expect(error.eventType).toBe("message.start");
      expect(error.missingField).toBe("message_id");
      expect(error.recoveryAction).toContain("skipped");
    });
  });
});

describe("SSEErrors Utilities", () => {
  describe("Factory Methods", () => {
    it("creates conversationNotFound error", () => {
      const error = SSEErrors.conversationNotFound("conv_123");

      expect(error).toBeInstanceOf(ConversationNotFoundError);
      expect(error.conversationId).toBe("conv_123");
    });

    it("creates eventValidation error", () => {
      const error = SSEErrors.eventValidation("tool.call.start", "data.tool_call");

      expect(error).toBeInstanceOf(EventValidationError);
      expect(error.eventType).toBe("tool.call.start");
      expect(error.errorPath).toBe("data.tool_call");
    });

    it("creates connection error", () => {
      const error = SSEErrors.connection("Connection lost", 2, 5);

      expect(error).toBeInstanceOf(ConnectionError);
      expect(error.attempt).toBe(2);
      expect(error.maxAttempts).toBe(5);
    });

    it("creates missingData error", () => {
      const error = SSEErrors.missingData("message.delta", "content");

      expect(error).toBeInstanceOf(MissingDataError);
      expect(error.eventType).toBe("message.delta");
      expect(error.missingField).toBe("content");
    });
  });

  describe("Type Guards", () => {
    it("identifies SSEError", () => {
      const sseError = new SSEError("Test", "TEST");
      const normalError = new Error("Test");

      expect(SSEErrors.isSSEError(sseError)).toBe(true);
      expect(SSEErrors.isSSEError(normalError)).toBe(false);
    });

    it("identifies ConversationNotFoundError", () => {
      const notFoundError = new ConversationNotFoundError("conv_123");
      const otherError = new EventValidationError("test", "test");

      expect(SSEErrors.isConversationNotFound(notFoundError)).toBe(true);
      expect(SSEErrors.isConversationNotFound(otherError)).toBe(false);
    });

    it("identifies EventValidationError", () => {
      const validationError = new EventValidationError("test", "test");
      const otherError = new ConnectionError("test");

      expect(SSEErrors.isEventValidation(validationError)).toBe(true);
      expect(SSEErrors.isEventValidation(otherError)).toBe(false);
    });

    it("identifies ConnectionError", () => {
      const connError = new ConnectionError("test");
      const otherError = new MissingDataError("test", "test");

      expect(SSEErrors.isConnection(connError)).toBe(true);
      expect(SSEErrors.isConnection(otherError)).toBe(false);
    });

    it("identifies MissingDataError", () => {
      const missingError = new MissingDataError("test", "test");
      const otherError = new SSEError("test", "TEST");

      expect(SSEErrors.isMissingData(missingError)).toBe(true);
      expect(SSEErrors.isMissingData(otherError)).toBe(false);
    });
  });

  describe("getUserMessage", () => {
    it("returns message with recovery action for SSEError", () => {
      const error = new SSEError("Connection failed", "ERROR", "Try reloading");

      const message = SSEErrors.getUserMessage(error);

      expect(message).toBe("Connection failed. Try reloading");
    });

    it("returns message without recovery action", () => {
      const error = new SSEError("Connection failed", "ERROR");

      const message = SSEErrors.getUserMessage(error);

      expect(message).toBe("Connection failed");
    });

    it("returns message for regular Error", () => {
      const error = new Error("Regular error");

      const message = SSEErrors.getUserMessage(error);

      expect(message).toBe("Regular error");
    });

    it("returns default message for unknown error", () => {
      const message = SSEErrors.getUserMessage("string error");

      expect(message).toBe("An unexpected error occurred");
    });
  });

  describe("getErrorCode", () => {
    it("returns code for SSEError", () => {
      const error = new SSEError("Test", "TEST_ERROR");

      expect(SSEErrors.getErrorCode(error)).toBe("TEST_ERROR");
    });

    it("returns UNKNOWN_ERROR for regular Error", () => {
      const error = new Error("Test");

      expect(SSEErrors.getErrorCode(error)).toBe("UNKNOWN_ERROR");
    });

    it("returns UNKNOWN for non-error", () => {
      expect(SSEErrors.getErrorCode("test")).toBe("UNKNOWN");
    });
  });
});

