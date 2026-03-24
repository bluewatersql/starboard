/**
 * Tests for useSSE error handling.
 *
 * Tests various error scenarios and recovery mechanisms.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { useSSE } from "../useSSE";
import { EventSourceClient } from "../../sse/EventSourceClient";
import { useMessageStore } from "../../store/messageStore";
import { useConversationStore } from "../../store/conversationStore";

// Mock EventSourceClient
jest.mock("../../sse/EventSourceClient");

// Mock stores
jest.mock("../../store/messageStore");
jest.mock("../../store/conversationStore");

// Mock debug utility to always log in tests
jest.mock("../../utils/debug", () => ({
  debug: {
    log: (...args: unknown[]) => console.log(...args),
    warn: (...args: unknown[]) => console.warn(...args),
    error: (...args: unknown[]) => console.error(...args),
    info: (...args: unknown[]) => console.info(...args),
    isEnabled: () => true,
  },
}));

// Mock fetch for conversation validation
global.fetch = jest.fn();

describe("useSSE Error Handling", () => {
  let mockEventSourceClient: jest.Mocked<EventSourceClient>;
  let mockAddMessage: jest.Mock;
  let mockUpdateMessage: jest.Mock;
  let mockAppendToMessage: jest.Mock;
  let mockSetStreamingMessage: jest.Mock;

  beforeEach(() => {
    // Reset mocks
    jest.clearAllMocks();

    // Setup message store mocks
    mockAddMessage = jest.fn();
    mockUpdateMessage = jest.fn();
    mockAppendToMessage = jest.fn();
    mockSetStreamingMessage = jest.fn();

    (useMessageStore as unknown as jest.Mock).mockReturnValue({
      addMessage: mockAddMessage,
      updateMessage: mockUpdateMessage,
      appendToMessage: mockAppendToMessage,
      setStreamingMessage: mockSetStreamingMessage,
    });

    (useMessageStore).getState = jest.fn().mockReturnValue({
      messagesByConversation: {},
      addMessage: mockAddMessage,
      updateMessage: mockUpdateMessage,
      appendToMessage: mockAppendToMessage,
      setStreamingMessage: mockSetStreamingMessage,
    });

    // Setup conversation store mock
    (useConversationStore).getState = jest.fn().mockReturnValue({
      updateConversation: jest.fn(),
    });

    // Setup EventSourceClient mock
    mockEventSourceClient = {
      connect: jest.fn(),
      disconnect: jest.fn(),
      isConnected: jest.fn().mockReturnValue(false),
      getState: jest.fn(),
      deactivate: jest.fn(),
      isActive: jest.fn().mockReturnValue(false),
    } as unknown as jest.Mocked<EventSourceClient>;

    (EventSourceClient as jest.Mock).mockImplementation(() => mockEventSourceClient);

    // Mock fetch to succeed by default
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      status: 200,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe("Connection Errors", () => {
    it("calls onError when EventSourceClient reports error", () => {
      const onError = jest.fn();

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
          onError,
        })
      );

      // Simulate error from EventSourceClient
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const errorHandler = clientOptions.onError;

      const testError = new Error("Connection failed");
      errorHandler(testError);

      expect(onError).toHaveBeenCalledWith(testError);
    });

    it("handles conversation not found error gracefully", async () => {
      const onError = jest.fn();

      // Mock fetch to return 404
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 404,
      });

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: true,
          onError,
        })
      );

      await waitFor(() => {
        expect(onError).toHaveBeenCalledWith(
          expect.objectContaining({
            message: "Conversation no longer exists",
            code: "CONVERSATION_NOT_FOUND",
            conversationId: "conv_123",
          })
        );
      });

      // Should not attempt to connect
      expect(mockEventSourceClient.connect).not.toHaveBeenCalled();
    });

    it("connects anyway on validation network error", async () => {
      // Mock fetch to fail with network error
      (global.fetch as jest.Mock).mockRejectedValue(new Error("Network error"));

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: true,
        })
      );

      await waitFor(() => {
        // Should attempt to connect despite validation error
        expect(mockEventSourceClient.connect).toHaveBeenCalled();
      });
    });

    it("skips validation when skipValidation is true", async () => {
      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: true,
          skipValidation: true,
        })
      );

      await waitFor(() => {
        expect(mockEventSourceClient.connect).toHaveBeenCalled();
      });

      // Should not have called fetch
      expect(global.fetch).not.toHaveBeenCalled();
    });

    it("does not notify error twice for same conversation", async () => {
      const onError = jest.fn();

      // Mock fetch to return 404
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 404,
      });

      const { rerender } = renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: true,
          onError,
        })
      );

      await waitFor(() => {
        expect(onError).toHaveBeenCalledTimes(1);
      });

      // Rerender with same props
      rerender();

      // Should not call onError again
      expect(onError).toHaveBeenCalledTimes(1);
    });
  });

  describe("Event Error Handling", () => {
    it("handles ERROR event by updating message status", () => {
      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      // Mock existing message
      (useMessageStore.getState as jest.Mock).mockReturnValue({
        messagesByConversation: {
          conv_123: [
            {
              message_id: "msg_123",
              content: "Processing...",
            },
          ],
        },
        addMessage: mockAddMessage,
        updateMessage: mockUpdateMessage,
        appendToMessage: mockAppendToMessage,
        setStreamingMessage: mockSetStreamingMessage,
      });

      // Get event handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const eventHandler = clientOptions.onEvent;

      // Simulate ERROR event
      eventHandler({
        type: "error",
        data: {
          message_id: "msg_123",
          error: {
            message: "Database connection failed",
          },
        },
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
      });

      // Should update message with error
      expect(mockUpdateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          status: "failed",
          content: expect.stringContaining("Database connection failed"),
        })
      );

      // Should stop streaming
      expect(mockSetStreamingMessage).toHaveBeenCalledWith(null);
    });

    it("handles missing message_id in MESSAGE_START", () => {
      const consoleWarnSpy = jest.spyOn(console, "warn").mockImplementation();

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      // Get event handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const eventHandler = clientOptions.onEvent;

      // Simulate MESSAGE_START without message_id
      eventHandler({
        type: "message.start",
        data: {},
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
      });

      // Should warn
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining("MESSAGE_START received but no message_id")
      );

      // Should not add message
      expect(mockAddMessage).not.toHaveBeenCalled();

      consoleWarnSpy.mockRestore();
    });

    it("handles missing content in MESSAGE_DELTA", () => {
      const consoleWarnSpy = jest.spyOn(console, "warn").mockImplementation();

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      // Get event handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const eventHandler = clientOptions.onEvent;

      // Simulate MESSAGE_DELTA without content
      eventHandler({
        type: "message.delta",
        data: {
          message_id: "msg_123",
          delta: {},
        },
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
      });

      // Should warn about missing message (handled as placeholder creation)
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining("not found")
      );

      consoleWarnSpy.mockRestore();
    });

    it("warns on unhandled event type", () => {
      const consoleWarnSpy = jest.spyOn(console, "warn").mockImplementation();

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      // Get event handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const eventHandler = clientOptions.onEvent;

      // Simulate unknown event type
      eventHandler({
        type: "unknown.event",
        data: {},
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
      });

      // Should warn
      expect(consoleWarnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Unhandled event type: unknown.event")
      );

      consoleWarnSpy.mockRestore();
    });
  });

  describe("Validation Error Integration", () => {
    it("handles validation errors from EventSourceClient", () => {
      const onError = jest.fn();

      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
          onError,
        })
      );

      // Get error handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const errorHandler = clientOptions.onError;

      // Simulate validation error from EventSourceClient
      const validationError = new Error(
        "Event validation failed for type 'tool.call.start' at data.tool_call.tool_call_id"
      );
      errorHandler(validationError);

      expect(onError).toHaveBeenCalledWith(validationError);
    });
  });

  describe("Error Recovery", () => {
    it("clears streaming state on error", () => {
      renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      // Get event handler
      const clientConstructorCall = (EventSourceClient as jest.Mock).mock.calls[0];
      const clientOptions = clientConstructorCall[0];
      const eventHandler = clientOptions.onEvent;

      // Simulate ERROR event
      eventHandler({
        type: "error",
        data: {
          message_id: "msg_123",
          error: "Test error",
        },
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
      });

      // Should clear streaming state
      expect(mockSetStreamingMessage).toHaveBeenCalledWith(null);
    });

    it("resets error notification flag when conversation changes", () => {
      const onError = jest.fn();

      // Mock fetch to return 404
      (global.fetch as jest.Mock).mockResolvedValue({
        ok: false,
        status: 404,
      });

      const { rerender } = renderHook(
        ({ conversationId }) =>
          useSSE({
            conversationId,
            autoConnect: true,
            onError,
          }),
        {
          initialProps: { conversationId: "conv_123" },
        }
      );

      waitFor(() => {
        expect(onError).toHaveBeenCalledTimes(1);
      });

      // Change conversation
      rerender({ conversationId: "conv_456" });

      // Should be able to notify error again for new conversation
      waitFor(() => {
        expect(onError).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe("Cleanup", () => {
    it("disconnects client on unmount", () => {
      const { unmount } = renderHook(() =>
        useSSE({
          conversationId: "conv_123",
          autoConnect: false,
        })
      );

      unmount();

      expect(mockEventSourceClient.disconnect).toHaveBeenCalled();
    });

    it("disconnects and reconnects on conversation change", async () => {
      const { rerender } = renderHook(
        ({ conversationId }) =>
          useSSE({
            conversationId,
            autoConnect: true,
            skipValidation: true,
          }),
        {
          initialProps: { conversationId: "conv_123" },
        }
      );

      await waitFor(() => {
        expect(mockEventSourceClient.connect).toHaveBeenCalledTimes(1);
      });

      // Change conversation
      rerender({ conversationId: "conv_456" });

      await waitFor(() => {
        expect(mockEventSourceClient.disconnect).toHaveBeenCalled();
        expect(mockEventSourceClient.connect).toHaveBeenCalledTimes(2);
      });
    });
  });
});

