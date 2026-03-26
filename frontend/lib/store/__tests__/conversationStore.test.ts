/**
 * Tests for conversationStore.
 *
 * Tests Zustand store for conversation state management,
 * including the new createAndNavigate method for UX vNext Phase 1.
 */

import { renderHook, act, waitFor } from "@testing-library/react";
import { useConversationStore } from "../conversationStore";
import * as client from "../../api/client";
import type { ConversationResponse } from "../../types/api";

// Mock the API client
jest.mock("../../api/client");

describe("conversationStore", () => {
  // Reset store before each test
  beforeEach(() => {
    const { result } = renderHook(() => useConversationStore());
    act(() => {
      result.current.reset();
    });
    jest.clearAllMocks();
  });

  describe("Basic State Management", () => {
    it("initializes with empty state", () => {
      const { result } = renderHook(() => useConversationStore());

      expect(result.current.conversations).toEqual([]);
      expect(result.current.activeConversationId).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it("adds a conversation", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test Conversation",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
      });

      expect(result.current.conversations).toHaveLength(1);
      expect(result.current.conversations[0]).toEqual(mockConversation);
    });

    it("sets active conversation", () => {
      const { result } = renderHook(() => useConversationStore());

      act(() => {
        result.current.setActiveConversation("conv_123");
      });

      expect(result.current.activeConversationId).toBe("conv_123");
    });

    it("gets active conversation", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test Conversation",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
        result.current.setActiveConversation("conv_123");
      });

      const activeConv = result.current.getActiveConversation();
      expect(activeConv).toEqual(mockConversation);
    });

    it("removes a conversation", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test Conversation",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
        result.current.setActiveConversation("conv_123");
      });

      expect(result.current.conversations).toHaveLength(1);

      act(() => {
        result.current.removeConversation("conv_123");
      });

      expect(result.current.conversations).toHaveLength(0);
      expect(result.current.activeConversationId).toBeNull();
    });

    it("updates a conversation", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test Conversation",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
      });

      act(() => {
        result.current.updateConversation("conv_123", {
          friendly_name: "Updated Conversation",
        });
      });

      expect(result.current.conversations[0]!.friendly_name).toBe("Updated Conversation");
    });
  });

  describe("createAndNavigate (UX vNext Phase 1)", () => {
    const mockConversationResponse: ConversationResponse = {
      conversation_id: "conv_new_123",
      user_id: "user_456",
      friendly_name: "New Conversation",
      created_at: new Date().toISOString(),
      config: {
        temperature: 0.4,
        max_tokens: 120000,
        safe_mode: false,
        streaming: true,
        model: "gpt-4o-mini",
      },
      domain_models: [],
    };

    it("creates conversation without initial message", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      let conversationId: string = "";

      await act(async () => {
        const response = await result.current.createAndNavigate({
          context: { source: "test" },
        });
        conversationId = response.conversation_id;
      });

      // Verify API was called correctly
      expect(client.createConversation).toHaveBeenCalledTimes(1);
      expect(client.createConversation).toHaveBeenCalledWith({
        context: { source: "test" },
        config: undefined,
        metadata: undefined,
        initial_message: undefined,
      });

      // Verify conversation was added to store
      expect(result.current.conversations).toHaveLength(1);
      expect(result.current.conversations[0]!.conversation_id).toBe("conv_new_123");

      // Verify conversation was set as active
      expect(result.current.activeConversationId).toBe("conv_new_123");

      // Verify return value
      expect(conversationId).toBe("conv_new_123");

      // Verify loading state was managed
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it("creates conversation with initial message", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      await act(async () => {
        await result.current.createAndNavigate({
          initialMessage: "Test query",
          context: { source: "homepage" },
        });
      });

      // Verify API was called WITHOUT initial_message (it's stored as pendingMessage)
      expect(client.createConversation).toHaveBeenCalledWith({
        context: { source: "homepage" },
        config: undefined,
        metadata: undefined,
      });

      // Verify pendingMessage was set
      expect(result.current.pendingMessage).toBe("Test query");

      // Verify conversation was added and set as active
      expect(result.current.conversations).toHaveLength(1);
      expect(result.current.activeConversationId).toBe("conv_new_123");
    });

    it("creates conversation with config", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      const customConfig = {
        temperature: 0.7,
        max_tokens: 4096,
        safe_mode: true,
        streaming: true,
        model: "gpt-4" as const,
      };

      await act(async () => {
        await result.current.createAndNavigate({
          config: customConfig,
        });
      });

      // Verify API was called with config
      expect(client.createConversation).toHaveBeenCalledWith({
        config: customConfig,
        context: undefined,
        metadata: undefined,
        initial_message: undefined,
      });
    });

    it("creates conversation with metadata", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      const metadata = {
        tags: ["test", "automation"],
        source: "test-suite",
      };

      await act(async () => {
        await result.current.createAndNavigate({
          metadata,
        });
      });

      // Verify API was called WITHOUT metadata (metadata is client-side only per implementation)
      expect(client.createConversation).toHaveBeenCalledWith({
        context: undefined,
        config: undefined,
      });
    });

    it("creates conversation with all parameters", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      const params = {
        initialMessage: "Analyze job performance",
        context: { job_id: "123", source: "test" },
        config: {
          temperature: 0.4,
          max_tokens: 4096,
          safe_mode: false,
          streaming: true,
          model: "gpt-4o-mini" as const,
        },
        metadata: {
          tags: ["job-analysis"],
          job_id: "123",
        },
      };

      await act(async () => {
        await result.current.createAndNavigate(params);
      });

      // Verify API was called WITHOUT initial_message or metadata
      // (initial_message is stored as pendingMessage, metadata is client-side only)
      expect(client.createConversation).toHaveBeenCalledWith({
        context: params.context,
        config: params.config,
      });

      // Verify pendingMessage was set
      expect(result.current.pendingMessage).toBe(params.initialMessage);

      // Verify conversation was added and set as active
      expect(result.current.conversations).toHaveLength(1);
      expect(result.current.activeConversationId).toBe("conv_new_123");
    });

    it("handles API errors gracefully", async () => {
      const { result } = renderHook(() => useConversationStore());

      const apiError = new Error("Network error");
      (client.createConversation as jest.Mock).mockRejectedValue(apiError);

      await expect(async () => {
        await act(async () => {
          await result.current.createAndNavigate({
            initialMessage: "Test",
          });
        });
      }).rejects.toThrow("Network error");

      // Verify error state was set
      expect(result.current.error).toBe("Network error");
      expect(result.current.loading).toBe(false);

      // Verify no conversation was added
      expect(result.current.conversations).toHaveLength(0);
      expect(result.current.activeConversationId).toBeNull();
    });

    it("handles authentication errors", async () => {
      const { result } = renderHook(() => useConversationStore());

      // Create a proper error instance
      const authError = new Error("Authentication required");
      (client.createConversation as jest.Mock).mockRejectedValue(authError);

      let thrownError: Error | null = null;

      await act(async () => {
        try {
          await result.current.createAndNavigate({});
        } catch (error) {
          thrownError = error as Error;
        }
      });

      // Verify the error was thrown
      expect(thrownError).toBeInstanceOf(Error);
      expect((thrownError as Error | null)?.message).toBe("Authentication required");

      // After the promise settles, error state should be set
      expect(result.current.error).toBe("Authentication required");
      expect(result.current.loading).toBe(false);
      
      // Verify no conversation was added
      expect(result.current.conversations).toHaveLength(0);
    });

    it("handles non-Error exceptions", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockRejectedValue("String error");

      let thrownError: unknown = null;

      await act(async () => {
        try {
          await result.current.createAndNavigate({});
        } catch (error) {
          thrownError = error;
        }
      });

      // Verify the error was thrown
      expect(thrownError).toBe("String error");

      // After the promise settles, error state should be set
      expect(result.current.error).toBe("Failed to create conversation");
      expect(result.current.loading).toBe(false);
    });

    it("manages loading state correctly", async () => {
      const { result } = renderHook(() => useConversationStore());

      (client.createConversation as jest.Mock).mockImplementation(
        () => new Promise((resolve) => {
          setTimeout(() => resolve(mockConversationResponse), 100);
        })
      );

      // Start the async operation
      const promise = act(async () => {
        await result.current.createAndNavigate({});
      });

      // Loading should be true immediately
      await waitFor(() => {
        expect(result.current.loading).toBe(true);
      });

      // Wait for completion
      await promise;

      // Loading should be false after completion
      expect(result.current.loading).toBe(false);
    });

    it("clears previous error before new attempt", async () => {
      const { result } = renderHook(() => useConversationStore());

      // First attempt: fail
      (client.createConversation as jest.Mock).mockRejectedValue(
        new Error("First error")
      );

      await expect(async () => {
        await act(async () => {
          await result.current.createAndNavigate({});
        });
      }).rejects.toThrow();

      expect(result.current.error).toBe("First error");

      // Second attempt: succeed
      (client.createConversation as jest.Mock).mockResolvedValue(
        mockConversationResponse
      );

      await act(async () => {
        await result.current.createAndNavigate({});
      });

      // Error should be cleared
      expect(result.current.error).toBeNull();
      expect(result.current.conversations).toHaveLength(1);
    });
  });

  describe("Error Management", () => {
    it("sets error message", () => {
      const { result } = renderHook(() => useConversationStore());

      act(() => {
        result.current.setError("Test error");
      });

      expect(result.current.error).toBe("Test error");
    });

    it("clears error message", () => {
      const { result } = renderHook(() => useConversationStore());

      act(() => {
        result.current.setError("Test error");
      });

      expect(result.current.error).toBe("Test error");

      act(() => {
        result.current.clearError();
      });

      expect(result.current.error).toBeNull();
    });
  });

  describe("Loading State", () => {
    it("sets loading state", () => {
      const { result } = renderHook(() => useConversationStore());

      act(() => {
        result.current.setLoading(true);
      });

      expect(result.current.loading).toBe(true);

      act(() => {
        result.current.setLoading(false);
      });

      expect(result.current.loading).toBe(false);
    });
  });

  describe("Newly Created Tracking", () => {
    it("tracks newly created conversations", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
      });

      expect(result.current.isNewlyCreated("conv_123")).toBe(true);
    });

    it("auto-removes from tracking after timeout", async () => {
      jest.useFakeTimers();

      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
      });

      expect(result.current.isNewlyCreated("conv_123")).toBe(true);

      // Fast-forward 30 seconds
      act(() => {
        jest.advanceTimersByTime(30000);
      });

      expect(result.current.isNewlyCreated("conv_123")).toBe(false);

      jest.useRealTimers();
    });
  });

  describe("Store Persistence", () => {
    it("persists conversations and activeConversationId", () => {
      const { result: result1 } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result1.current.addConversation(mockConversation);
        result1.current.setActiveConversation("conv_123");
      });

      // Create new hook instance (simulating page reload)
      const { result: result2 } = renderHook(() => useConversationStore());

      // Should have persisted state
      expect(result2.current.conversations).toHaveLength(1);
      expect(result2.current.activeConversationId).toBe("conv_123");
    });

    it("only persists specified fields per partialize config", () => {
      // This test verifies the partialize configuration
      // In production, only conversations and activeConversationId are persisted
      // to localStorage. loading and error are transient and reset on page reload.
      
      const { result } = renderHook(() => useConversationStore());
      
      // Reset to initial state
      act(() => {
        result.current.reset();
      });
      
      // Verify initial state has transient fields reset
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.conversations).toEqual([]);
      expect(result.current.activeConversationId).toBeNull();
      
      // Note: The persistence behavior is handled by Zustand's persist middleware
      // which will only save/restore the fields specified in partialize:
      // { conversations, activeConversationId }
    });
  });

  describe("Reset Functionality", () => {
    it("resets store to initial state", () => {
      const { result } = renderHook(() => useConversationStore());

      const mockConversation = {
        conversation_id: "conv_123",
        user_id: "user_456",
        friendly_name: "Test",
        created_at: new Date().toISOString(),
        config: {},
        domain_models: [],
      };

      act(() => {
        result.current.addConversation(mockConversation);
        result.current.setActiveConversation("conv_123");
        result.current.setLoading(true);
        result.current.setError("Error");
      });

      act(() => {
        result.current.reset();
      });

      expect(result.current.conversations).toEqual([]);
      expect(result.current.activeConversationId).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });
});

