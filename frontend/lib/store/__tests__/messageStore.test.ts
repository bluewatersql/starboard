/**
 * Tests for messageStore.
 *
 * Tests Zustand store for message state management,
 * including streaming updates, retries, and message operations.
 */

import { renderHook, act } from "@testing-library/react";
import { useMessageStore } from "../messageStore";
import { MessageStatus, MessageRole } from "../../types/api";
import type { Message } from "../../types/api";

describe("messageStore", () => {
  // Reset store before each test
  beforeEach(() => {
    const { result } = renderHook(() => useMessageStore());
    act(() => {
      result.current.reset();
    });
  });

  describe("Initial State", () => {
    it("initializes with empty state", () => {
      const { result } = renderHook(() => useMessageStore());

      expect(result.current.messagesByConversation).toEqual({});
      expect(result.current.streamingMessageId).toBeNull();
    });
  });

  describe("setMessages", () => {
    it("sets messages for a conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
        {
          id: "msg_2",
          message_id: "msg_2",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Hi there!",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
      });

      expect(result.current.messagesByConversation["conv_123"]).toHaveLength(2);
      expect(result.current.messagesByConversation["conv_123"]![0]!.content).toBe(
        "Hello"
      );
    });

    it("deduplicates messages by ID", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
        {
          id: "msg_1",
          message_id: "msg_1", // Duplicate
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello duplicate",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
      });

      expect(result.current.messagesByConversation["conv_123"]).toHaveLength(1);
      expect(result.current.messagesByConversation["conv_123"]![0]!.content).toBe(
        "Hello"
      );
    });

    it("promotes complete_report from metadata", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Analysis complete",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
          metadata: {
            complete_report: { findings: ["test"] },
          },
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.complete_report
      ).toEqual({ findings: ["test"] });
    });

    it("promotes tool_positions from metadata", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Running analysis...",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
          metadata: {
            tool_positions: [{ index: 0, tool_call_id: "call_1" }],
          },
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.tool_positions
      ).toEqual([{ index: 0, tool_call_id: "call_1" }]);
    });
  });

  describe("addMessage", () => {
    it("adds a message to a conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.USER,
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: MessageStatus.COMPLETED,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
      });

      expect(result.current.messagesByConversation["conv_123"]).toHaveLength(1);
      expect(result.current.messagesByConversation["conv_123"]![0]).toEqual(
        message
      );
    });

    it("does not add duplicate messages", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.USER,
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: MessageStatus.COMPLETED,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.addMessage("conv_123", message); // Duplicate
      });

      expect(result.current.messagesByConversation["conv_123"]).toHaveLength(1);
    });

    it("appends to existing messages", () => {
      const { result } = renderHook(() => useMessageStore());

      const message1: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.USER,
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: MessageStatus.COMPLETED,
      };

      const message2: Message = {
        id: "msg_2",
        message_id: "msg_2",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Hi!",
        timestamp: new Date().toISOString(),
        status: MessageStatus.COMPLETED,
      };

      act(() => {
        result.current.addMessage("conv_123", message1);
        result.current.addMessage("conv_123", message2);
      });

      expect(result.current.messagesByConversation["conv_123"]).toHaveLength(2);
    });
  });

  describe("updateMessage", () => {
    it("updates a specific message", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Thinking...",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.updateMessage("conv_123", "msg_1", {
          content: "Done!",
          status: MessageStatus.COMPLETED,
        });
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.content
      ).toBe("Done!");
      expect(result.current.messagesByConversation["conv_123"]![0]!.status).toBe(
        MessageStatus.COMPLETED
      );
    });

    it("does not affect other messages", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
        {
          id: "msg_2",
          message_id: "msg_2",
          conversation_id: "conv_123",
          role: MessageRole.ASSISTANT,
          content: "Thinking...",
          timestamp: new Date().toISOString(),
          status: MessageStatus.PROCESSING,
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
        result.current.updateMessage("conv_123", "msg_2", {
          content: "Updated",
        });
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.content
      ).toBe("Hello");
      expect(
        result.current.messagesByConversation["conv_123"]![1]!.content
      ).toBe("Updated");
    });
  });

  describe("appendToMessage", () => {
    it("appends content to a message", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Hello",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.appendToMessage("conv_123", "msg_1", " world!");
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.content
      ).toBe("Hello world!");
    });

    it("adds space after sentence-ending punctuation", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "First sentence.",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.appendToMessage("conv_123", "msg_1", "Second sentence.");
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.content
      ).toBe("First sentence. Second sentence.");
    });

    it("handles empty content gracefully", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.appendToMessage("conv_123", "msg_1", "Content");
      });

      expect(
        result.current.messagesByConversation["conv_123"]![0]!.content
      ).toBe("Content");
    });
  });

  describe("setStreamingMessage", () => {
    it("sets the streaming message ID", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.setStreamingMessage("msg_123");
      });

      expect(result.current.streamingMessageId).toBe("msg_123");
    });

    it("clears the streaming message ID", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.setStreamingMessage("msg_123");
        result.current.setStreamingMessage(null);
      });

      expect(result.current.streamingMessageId).toBeNull();
    });
  });

  describe("getMessages", () => {
    it("returns messages for a conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
      });

      const retrievedMessages = result.current.getMessages("conv_123");
      expect(retrievedMessages).toHaveLength(1);
      expect(retrievedMessages[0]!.content).toBe("Hello");
    });

    it("returns empty array for unknown conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages = result.current.getMessages("unknown_conv");
      expect(messages).toEqual([]);
    });
  });

  describe("clearMessages", () => {
    it("clears messages for a conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "conv_123",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
      ];

      act(() => {
        result.current.setMessages("conv_123", messages);
        result.current.clearMessages("conv_123");
      });

      expect(result.current.getMessages("conv_123")).toEqual([]);
    });

    it("does not affect other conversations", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.setMessages("conv_1", [
          {
            id: "msg_1",
            message_id: "msg_1",
            conversation_id: "conv_1",
            role: MessageRole.USER,
            content: "Hello 1",
            timestamp: new Date().toISOString(),
            status: MessageStatus.COMPLETED,
          },
        ]);
        result.current.setMessages("conv_2", [
          {
            id: "msg_2",
            message_id: "msg_2",
            conversation_id: "conv_2",
            role: MessageRole.USER,
            content: "Hello 2",
            timestamp: new Date().toISOString(),
            status: MessageStatus.COMPLETED,
          },
        ]);
        result.current.clearMessages("conv_1");
      });

      expect(result.current.getMessages("conv_1")).toEqual([]);
      expect(result.current.getMessages("conv_2")).toHaveLength(1);
    });
  });

  describe("retryMessage", () => {
    it("returns null for non-existent message", () => {
      const { result } = renderHook(() => useMessageStore());

      let retryResult: Message | null = null;
      act(() => {
        retryResult = result.current.retryMessage("conv_123", "unknown_msg");
      });

      expect(retryResult).toBeNull();
    });

    it("updates message status to processing", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Error occurred",
        timestamp: new Date().toISOString(),
        status: MessageStatus.FAILED,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
      });

      let retryResult: Message | null = null;
      act(() => {
        retryResult = result.current.retryMessage("conv_123", "msg_1");
      });

      expect((retryResult as Message | null)?.status).toBe(MessageStatus.PROCESSING);
      expect((retryResult as Message | null)?.retry_count).toBe(1);
    });

    it("increments retry count", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Error",
        timestamp: new Date().toISOString(),
        status: MessageStatus.FAILED,
        retry_count: 1,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
      });

      let retryResult: Message | null = null;
      act(() => {
        retryResult = result.current.retryMessage("conv_123", "msg_1");
      });

      expect((retryResult as Message | null)?.retry_count).toBe(2);
    });

    it("returns null when max retries reached", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Error",
        timestamp: new Date().toISOString(),
        status: MessageStatus.FAILED,
        retry_count: 3, // Max retries
      };

      act(() => {
        result.current.addMessage("conv_123", message);
      });

      let retryResult: Message | null = null;
      act(() => {
        retryResult = result.current.retryMessage("conv_123", "msg_1");
      });

      expect(retryResult).toBeNull();
    });
  });

  describe("moveMessages", () => {
    it("moves messages from one conversation to another", () => {
      const { result } = renderHook(() => useMessageStore());

      const messages: Message[] = [
        {
          id: "msg_1",
          message_id: "msg_1",
          conversation_id: "temp_conv",
          role: MessageRole.USER,
          content: "Hello",
          timestamp: new Date().toISOString(),
          status: MessageStatus.COMPLETED,
        },
      ];

      act(() => {
        result.current.setMessages("temp_conv", messages);
        result.current.moveMessages("temp_conv", "real_conv");
      });

      expect(result.current.getMessages("temp_conv")).toEqual([]);
      expect(result.current.getMessages("real_conv")).toHaveLength(1);
      expect(result.current.getMessages("real_conv")[0]!.conversation_id).toBe(
        "real_conv"
      );
    });

    it("handles empty source conversation", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.moveMessages("empty_conv", "real_conv");
      });

      expect(result.current.getMessages("real_conv")).toEqual([]);
    });

    it("appends to existing messages in target", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.setMessages("source_conv", [
          {
            id: "msg_1",
            message_id: "msg_1",
            conversation_id: "source_conv",
            role: MessageRole.USER,
            content: "Source message",
            timestamp: new Date().toISOString(),
            status: MessageStatus.COMPLETED,
          },
        ]);
        result.current.setMessages("target_conv", [
          {
            id: "msg_existing",
            message_id: "msg_existing",
            conversation_id: "target_conv",
            role: MessageRole.USER,
            content: "Existing message",
            timestamp: new Date().toISOString(),
            status: MessageStatus.COMPLETED,
          },
        ]);
        result.current.moveMessages("source_conv", "target_conv");
      });

      expect(result.current.getMessages("target_conv")).toHaveLength(2);
    });
  });

  describe("updateThinkingStep", () => {
    it("adds a new thinking step", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Processing...",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.updateThinkingStep("conv_123", "msg_1", {
          id: "step_1",
          title: "Analyzing query",
          status: "in_progress",
          startTime: Date.now(),
        });
      });

      const thinkingSteps =
        result.current.messagesByConversation["conv_123"]![0]!.thinking_steps;
      expect(thinkingSteps).toHaveLength(1);
      expect(thinkingSteps?.[0]!.title).toBe("Analyzing query");
    });

    it("updates existing thinking step", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_1",
        message_id: "msg_1",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Processing...",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
        thinking_steps: [
          {
            id: "step_1",
            title: "Analyzing query",
            status: "in_progress",
          },
        ],
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.updateThinkingStep("conv_123", "msg_1", {
          id: "step_1",
          title: "Analyzing query",
          status: "completed",
          endTime: Date.now(),
        });
      });

      const thinkingSteps =
        result.current.messagesByConversation["conv_123"]![0]!.thinking_steps;
      expect(thinkingSteps).toHaveLength(1);
      expect(thinkingSteps?.[0]!.status).toBe("completed");
    });

    it("uses streaming message when messageId is 'current'", () => {
      const { result } = renderHook(() => useMessageStore());

      const message: Message = {
        id: "msg_streaming",
        message_id: "msg_streaming",
        conversation_id: "conv_123",
        role: MessageRole.ASSISTANT,
        content: "Processing...",
        timestamp: new Date().toISOString(),
        status: MessageStatus.PROCESSING,
      };

      act(() => {
        result.current.addMessage("conv_123", message);
        result.current.setStreamingMessage("msg_streaming");
        result.current.updateThinkingStep("conv_123", "current", {
          id: "step_1",
          title: "Analysis step",
          status: "in_progress",
        });
      });

      const thinkingSteps =
        result.current.messagesByConversation["conv_123"]![0]!.thinking_steps;
      expect(thinkingSteps).toHaveLength(1);
      expect(thinkingSteps?.[0]!.title).toBe("Analysis step");
    });
  });

  describe("reset", () => {
    it("resets to initial state", () => {
      const { result } = renderHook(() => useMessageStore());

      act(() => {
        result.current.setMessages("conv_123", [
          {
            id: "msg_1",
            message_id: "msg_1",
            conversation_id: "conv_123",
            role: MessageRole.USER,
            content: "Hello",
            timestamp: new Date().toISOString(),
            status: MessageStatus.COMPLETED,
          },
        ]);
        result.current.setStreamingMessage("msg_streaming");
        result.current.reset();
      });

      expect(result.current.messagesByConversation).toEqual({});
      expect(result.current.streamingMessageId).toBeNull();
    });
  });
});

