/**
 * Tests for SSE event handlers.
 *
 * Tests individual event handlers extracted from useSSE.
 */

import {
  handleMessageStart,
  handleMessageDelta,
  handleMessageComplete,
  handleFinalOutput,
  handleError,
  handleFriendlyNameUpdate,
} from "../event-handlers";
import type { StreamingChatEvent } from "../../types/api";
import { MessageRole, MessageStatus, EventType } from "../../types/api";

import type { MessageStoreOperations, ConversationStoreOperations } from "../event-handlers";

// Mock message store operations
const mockMessageStore = {
  addMessage: jest.fn(),
  updateMessage: jest.fn(),
  appendToMessage: jest.fn(),
  setStreamingMessage: jest.fn(),
  getMessages: jest.fn().mockReturnValue([]),
} as jest.Mocked<MessageStoreOperations>;

// Mock conversation store operations
const mockConversationStore: ConversationStoreOperations = {
  updateConversation: jest.fn(),
};

describe("Event Handlers", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("handleMessageStart", () => {
    it("creates new assistant message", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_START,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
        },
      };

      handleMessageStart(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.addMessage).toHaveBeenCalledWith("conv_123", {
        id: "msg_123",
        message_id: "msg_123",
        conversation_id: "conv_123",
        trace_id: "trace_msg_123",
        timestamp: expect.any(String),
        role: MessageRole.ASSISTANT,
        content: "",
        status: MessageStatus.PROCESSING,
        tool_calls: [],
      });

      expect(mockMessageStore.setStreamingMessage).toHaveBeenCalledWith("msg_123");
    });

    it("handles initial tool_calls if provided", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_START,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          tool_calls: [
            {
              tool_name: "test_tool",
              arguments: {},
              status: "pending",
            },
          ],
        },
      };

      handleMessageStart(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.addMessage).toHaveBeenCalledWith(
        "conv_123",
        expect.objectContaining({
          tool_calls: expect.arrayContaining([
            expect.objectContaining({
              tool_name: "test_tool",
            }),
          ]),
        })
      );
    });

    it("returns null if message_id is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_START,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {},
      };

      const result = handleMessageStart(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.addMessage).not.toHaveBeenCalled();
    });
  });

  describe("handleMessageDelta", () => {
    it("appends content to message", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_DELTA,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          delta: {
            content: "Hello world",
          },
        },
      };

      handleMessageDelta(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.appendToMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        "Hello world"
      );
    });

    it("returns null if message_id is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_DELTA,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          delta: { content: "test" },
        },
      };

      const result = handleMessageDelta(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.appendToMessage).not.toHaveBeenCalled();
    });

    it("does not append if content is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_DELTA,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          delta: {},
        },
      };

      handleMessageDelta(event, "conv_123", mockMessageStore);

      // Should not append when content is missing
      expect(mockMessageStore.appendToMessage).not.toHaveBeenCalled();
    });
  });

  describe("handleMessageComplete", () => {
    it("marks message as completed", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_END,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
        },
      };

      handleMessageComplete(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        {
          status: MessageStatus.COMPLETED,
        }
      );

      expect(mockMessageStore.setStreamingMessage).toHaveBeenCalledWith(null);
    });

    it("includes next_steps if provided", () => {
      const nextSteps = [
        {
          id: "step_1",
          number: 1,
          title: "Next step",
          description: null,
          action_type: "continue",
          target_agent: null,
          tool_name: null,
          parameters: null,
        },
      ];

      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_END,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          next_steps: nextSteps,
        },
      };

      handleMessageComplete(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          next_steps: nextSteps,
        })
      );
    });

    it("returns null if message_id is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.MESSAGE_END,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {},
      };

      const result = handleMessageComplete(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.updateMessage).not.toHaveBeenCalled();
    });
  });

  describe("handleError", () => {
    it("marks message as failed with error message", () => {
      mockMessageStore.getMessages.mockReturnValue([
        {
          id: "msg_123",
          message_id: "msg_123",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Processing...",
        },
      ]);

      const event: StreamingChatEvent = {
        type: EventType.ERROR,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          error: {
            message: "Database connection failed",
          },
        },
      };

      handleError(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          status: MessageStatus.FAILED,
          content: expect.stringContaining("Database connection failed"),
        })
      );

      expect(mockMessageStore.setStreamingMessage).toHaveBeenCalledWith(null);
    });

    it("uses default error message if not provided", () => {
      mockMessageStore.getMessages.mockReturnValue([
        {
          id: "msg_123",
          message_id: "msg_123",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Processing...",
        },
      ]);

      const event: StreamingChatEvent = {
        type: EventType.ERROR,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          error: {},
        },
      };

      handleError(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          content: expect.stringContaining("An error occurred"),
        })
      );
    });

    it("returns null if message_id is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.ERROR,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          error: { message: "Error" },
        },
      };

      const result = handleError(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.updateMessage).not.toHaveBeenCalled();
    });
  });

  describe("handleFriendlyNameUpdate", () => {
    it("updates conversation friendly name", () => {
      const event: StreamingChatEvent = {
        type: EventType.FRIENDLY_NAME_UPDATE,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          conversation_id: "conv_123",
          friendly_name: "My Conversation",
        },
      };

      handleFriendlyNameUpdate(event, "conv_123", mockConversationStore);

      expect(mockConversationStore.updateConversation).toHaveBeenCalledWith("conv_123", {
        friendly_name: "My Conversation",
      });
    });

    it("returns null if friendly_name is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.FRIENDLY_NAME_UPDATE,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          conversation_id: "conv_123",
        },
      };

      const result = handleFriendlyNameUpdate(event, "conv_123", mockConversationStore);

      expect(result).toBeNull();
      expect(mockConversationStore.updateConversation).not.toHaveBeenCalled();
    });
  });

  describe("handleFinalOutput", () => {
    it("updates message with complete report and metadata", () => {
      const event: StreamingChatEvent = {
        type: EventType.FINAL_OUTPUT,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          formatted_markdown: "# Report\n\nResults...",
          output: {
            status: "success",
            complete_report: { findings: [] },
            tokens_used: 1500,
            cost_usd: 0.05,
            duration_seconds: 12.5,
            steps_taken: 3,
          },
        },
      };

      handleFinalOutput(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          status: MessageStatus.COMPLETED,
          metadata: expect.objectContaining({
            complete_report: { findings: [] },
            tokens_used: 1500,
            cost_usd: 0.05,
            duration_seconds: 12.5,
            steps_taken: 3,
            formatted_markdown: "# Report\n\nResults...",
          }),
        })
      );

      expect(mockMessageStore.setStreamingMessage).toHaveBeenCalledWith(null);
    });

    it("handles output without complete_report", () => {
      const event: StreamingChatEvent = {
        type: EventType.FINAL_OUTPUT,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
          output: {
            status: "success",
            tokens_used: 1500,
          },
        },
      };

      handleFinalOutput(event, "conv_123", mockMessageStore);

      expect(mockMessageStore.updateMessage).toHaveBeenCalledWith(
        "conv_123",
        "msg_123",
        expect.objectContaining({
          status: MessageStatus.COMPLETED,
          metadata: expect.objectContaining({
            tokens_used: 1500,
          }),
        })
      );
    });

    it("returns null if message_id is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.FINAL_OUTPUT,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          output: { status: "success" },
        },
      };

      const result = handleFinalOutput(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.updateMessage).not.toHaveBeenCalled();
    });

    it("returns null if output is missing", () => {
      const event: StreamingChatEvent = {
        type: EventType.FINAL_OUTPUT,
        event_id: "evt_1",
        timestamp: new Date().toISOString(),
        data: {
          message_id: "msg_123",
        },
      };

      const result = handleFinalOutput(event, "conv_123", mockMessageStore);

      expect(result).toBeNull();
      expect(mockMessageStore.updateMessage).not.toHaveBeenCalled();
    });
  });
});

