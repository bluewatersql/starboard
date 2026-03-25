/**
 * Zustand store for conversation state management.
 *
 * Manages conversation list, active conversation selection,
 * and conversation CRUD operations.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Conversation, ConversationConfig, CreateConversationRequest } from "../types/api";
import { createConversation, AuthenticationError } from "../api/client";
import type { FileAttachment } from "@/components/chat/FileUploadButton";

interface ConversationState {
  // State
  conversations: Conversation[];
  activeConversationId: string | null;
  loading: boolean;
  error: string | null;
  // Track newly created conversations (skip validation for 30 seconds)
  newlyCreatedIds: string[];
  // Message to send after navigation (fixes race condition)
  pendingMessage: string | null;
  // File attachment to send with pending message (BB-02)
  pendingAttachment: FileAttachment | null;

  // Actions
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversation: (id: string, updates: Partial<Conversation>) => void;
  removeConversation: (id: string) => void;
  setActiveConversation: (id: string | null) => void;
  getActiveConversation: () => Conversation | null;
  isNewlyCreated: (id: string) => boolean;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  clearError: () => void;
  reset: () => void;
  setPendingMessage: (message: string | null) => void;
  setPendingAttachment: (attachment: FileAttachment | null) => void;

  // UX vNext Phase 1: Create conversation and prepare for navigation
  createAndNavigate: (params: {
    initialMessage?: string;
    context?: Record<string, unknown>;
    config?: ConversationConfig;
    metadata?: Record<string, unknown>;
  }) => Promise<{ conversation_id: string }>;
}

const initialState = {
  conversations: [],
  activeConversationId: null,
  loading: false,
  error: null,
  newlyCreatedIds: [],
  pendingMessage: null,
  pendingAttachment: null,
};

/**
 * Conversation store.
 *
 * Manages conversation state with persistence to localStorage.
 *
 * @example
 * ```tsx
 * const { conversations, addConversation, setActiveConversation } = useConversationStore();
 *
 * // Add new conversation
 * addConversation(newConversation);
 *
 * // Set active conversation
 * setActiveConversation(conversationId);
 * ```
 */
export const useConversationStore = create<ConversationState>()(
  persist(
    (set, get) => ({
      ...initialState,

      setConversations: (conversations) => set({ conversations }),

      addConversation: (conversation) =>
        set((state) => {
          // Auto-remove from tracking after 30 seconds
          setTimeout(() => {
            set((s) => ({
              newlyCreatedIds: s.newlyCreatedIds.filter(
                (id) => id !== conversation.conversation_id
              ),
            }));
          }, 30000);

          return {
            conversations: [conversation, ...state.conversations],
            newlyCreatedIds: state.newlyCreatedIds.includes(conversation.conversation_id)
              ? state.newlyCreatedIds
              : [...state.newlyCreatedIds, conversation.conversation_id],
          };
        }),

      updateConversation: (id, updates) =>
        set((state) => ({
          conversations: state.conversations.map((conv) =>
            conv.conversation_id === id ? { ...conv, ...updates } : conv
          ),
        })),

      removeConversation: (id) =>
        set((state) => {
          const newConversations = state.conversations.filter(
            (conv) => conv.conversation_id !== id
          );
          
          const newActiveId = state.activeConversationId === id
            ? null
            : state.activeConversationId;
          
          return {
            conversations: newConversations,
            activeConversationId: newActiveId,
          };
        }),

      setActiveConversation: (id) => set({ activeConversationId: id }),

      getActiveConversation: () => {
        const state = get();
        if (!state.activeConversationId) return null;
        return (
          state.conversations.find(
            (conv) => conv.conversation_id === state.activeConversationId
          ) || null
        );
      },

      isNewlyCreated: (id) => {
        const state = get();
        return state.newlyCreatedIds.includes(id);
      },

      setLoading: (loading) => set({ loading }),

      setError: (error) => set({ error }),

      clearError: () => set({ error: null }),

      reset: () => set(initialState),

      setPendingMessage: (message) => set({ pendingMessage: message }),

      setPendingAttachment: (attachment) => set({ pendingAttachment: attachment }),

      /**
       * Create a new conversation and prepare for navigation.
       *
       * UX vNext Phase 1: Single method that creates a conversation,
       * optionally sends an initial message, adds to store, and sets as active.
       *
       * @param params - Conversation creation parameters
       * @returns Promise with conversation_id for navigation
       *
       * @example
       * ```tsx
       * const { createAndNavigate } = useConversationStore();
       * const { conversation_id } = await createAndNavigate({
       *   initialMessage: "Analyze job performance",
       *   context: { job_id: "123" },
       * });
       * router.push(`/chat/${conversation_id}`);
       * ```
       */
      createAndNavigate: async (params) => {
        try {
          set({ loading: true, error: null });

          // Store pending message to send after navigation (fixes race condition)
          if (params.initialMessage) {
            set({ pendingMessage: params.initialMessage });
          }

          // Prepare request WITHOUT initial_message (send it after navigation)
          // Note: metadata is stored client-side, not sent to backend
          const request: CreateConversationRequest = {
            context: params.context,
            config: params.config,
          };

          // Create conversation via API
          const conversation = await createConversation(request);

          // Add to store (ensure user_id is set)
          get().addConversation({
            ...conversation,
            user_id: conversation.user_id || "anonymous",
          });

          // Set as active
          get().setActiveConversation(conversation.conversation_id);

          set({ loading: false });

          return {
            conversation_id: conversation.conversation_id,
          };
        } catch (error) {
          // Preserve specific error messages
          let errorMessage: string;
          
          if (error instanceof AuthenticationError) {
            errorMessage = error.message;
          } else if (error instanceof Error) {
            errorMessage = error.message;
          } else {
            errorMessage = "Failed to create conversation";
          }

          set({ error: errorMessage, loading: false });
          throw error;
        }
      },
    }),
    {
      name: "conversation-storage",
      partialize: (state) => ({
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
        pendingMessage: state.pendingMessage,
        pendingAttachment: state.pendingAttachment,
      }),
      // Handle rehydration - clear stale data if conversation doesn't exist
      onRehydrateStorage: () => (state) => {
        if (state?.activeConversationId && state.activeConversationId !== "new") {
          // Validate conversation still exists by checking if it's in the list
          // If not in list, it was likely from a previous session with stale data
          const conversationExists = state.conversations.some(
            (c) => c.conversation_id === state.activeConversationId
          );
          
          if (!conversationExists) {
            // Clear stale active conversation ID
            console.warn(
              `[ConversationStore] Clearing stale activeConversationId: ${state.activeConversationId}`
            );
            state.activeConversationId = null;
          }
        }
        
        // Clear any persisted conversations that may be stale (backend is in-memory)
        // Keep only recent ones (from current session) - conversations older than 1 hour
        // are likely stale after server restart
        const oneHourAgo = Date.now() - 60 * 60 * 1000;
        if (state?.conversations) {
          const freshConversations = state.conversations.filter((c) => {
            const createdAt = new Date(c.created_at).getTime();
            return createdAt > oneHourAgo;
          });
          
          if (freshConversations.length !== state.conversations.length) {
            console.warn(
              `[ConversationStore] Cleared ${state.conversations.length - freshConversations.length} stale conversations`
            );
            state.conversations = freshConversations;
          }
        }
      },
    }
  )
);

