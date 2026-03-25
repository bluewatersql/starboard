/**
 * ChatContainer component.
 *
 * Main container for the chat interface, managing layout and
 * coordinating between message list and input components.
 */

"use client";

import React from "react";
import { Box, Paper } from "@mui/material";
import { useRouter } from "next/navigation";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useMessageStore } from "@/lib/store/messageStore";
import { useUIStore } from "@/lib/store/uiStore";
import { useConfigStore } from "@/lib/store/configStore";
import { useSSE } from "@/lib/hooks/useSSE";
import { useClarification } from "@/lib/hooks/useClarification";
import { SSEError } from "@/lib/sse/errors";
import { EventType, type ClarificationRequest } from "@/lib/types/api";
import type { FileAttachment as ApiFileAttachment } from "@/lib/types/generated-api";
import type { FileAttachment } from "./FileUploadButton";
import { api, createConversation } from "@/lib/api/client";
import { logger } from "@/lib/utils/logger";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import ClarificationDialog from "./ClarificationDialog";
import { OfflineModeToggle } from "./OfflineModeToggle";
import { ExportMenu } from "./ExportMenu";

interface ChatContainerProps {
  conversationId: string;
  /**
   * Skip SSE validation for newly created conversations (from HeroPrompt).
   * This prevents race conditions where validation fails before conversation is persisted.
   */
  skipSSEValidation?: boolean;
}

/**
 * Chat container component.
 *
 * Manages the chat UI layout with message list and input areas.
 * Handles SSE connection for real-time updates.
 *
 * @param props - Component props
 * @returns Chat container component
 *
 * @example
 * ```tsx
 * <ChatContainer conversationId="conv_123" />
 * ```
 */
export function ChatContainer({ conversationId, skipSSEValidation = false }: ChatContainerProps) {
  const router = useRouter();
  const addConversation = useConversationStore((s) => s.addConversation);
  const removeConversation = useConversationStore((s) => s.removeConversation);
  const setActiveConversation = useConversationStore((s) => s.setActiveConversation);
  const pendingMessage = useConversationStore((s) => s.pendingMessage);
  const setPendingMessage = useConversationStore((s) => s.setPendingMessage);
  const pendingAttachment = useConversationStore((s) => s.pendingAttachment);
  const setPendingAttachment = useConversationStore((s) => s.setPendingAttachment);
  const isNewlyCreated = useConversationStore((s) => s.isNewlyCreated);
  const getMessages = useMessageStore((s) => s.getMessages);
  const addMessage = useMessageStore((s) => s.addMessage);
  const clearMessages = useMessageStore((s) => s.clearMessages);
  const toConversationConfig = useConfigStore((s) => s.toConversationConfig);
  const addNotification = useUIStore((s) => s.addNotification);
  const errorHandledRef = React.useRef<Set<string>>(new Set());

  // Clarification pattern hook (Phase 7)
  const {
    activeClarification,
    isSubmitting: isClarificationSubmitting,
    error: clarificationError,
    setActiveClarification,
    respondWithOption,
    respondWithCustomText,
    clear: clearClarification,
  } = useClarification();

  // Check if this conversation was just created (to skip SSE validation)
  // Priority: 1. URL param (most reliable), 2. Store check, 3. pendingMessage
  const wasJustCreated = skipSSEValidation || isNewlyCreated(conversationId) || !!pendingMessage;
  
  // Track state for handleNewConversationMessage flow
  const [localWasJustCreated, setLocalWasJustCreated] = React.useState(false);
  
  // Debug logging for SSE connection issues
  React.useEffect(() => {
    logger.debug("[ChatContainer] SSE validation check:", {
      conversationId,
      skipSSEValidation,
      isNewlyCreatedFromStore: isNewlyCreated(conversationId),
      hasPendingMessage: !!pendingMessage,
      wasJustCreated,
      localWasJustCreated,
    });
  }, [conversationId, skipSSEValidation, isNewlyCreated, pendingMessage, wasJustCreated, localWasJustCreated]);

  // Clean up "new" conversation messages when leaving the "new" state
  React.useEffect(() => {
    return () => {
      if (conversationId === "new") {
        // Clear messages from the "new" placeholder to ensure a fresh state next time
        clearMessages("new");
      }
    };
  }, [conversationId, clearMessages]);
  
  // Connect to SSE stream (skip for "new" placeholder - no conversation exists yet)
  const shouldConnectSSE = conversationId !== "new";
  const { state: sseState } = useSSE({
    conversationId,
    autoConnect: shouldConnectSSE,
    skipValidation: wasJustCreated || localWasJustCreated, // Skip validation for conversations we just created
    onEvent: (event) => {
      // Handle clarification request events (Phase 7)
      if (event.type === EventType.CLARIFICATION_REQUEST) {
        setActiveClarification(event.data as ClarificationRequest);
      }
    },
    onError: (error: SSEError | Error) => {
      // Prevent duplicate error notifications for the same conversation
      if (errorHandledRef.current.has(conversationId)) {
        return;
      }
      
      // Handle conversation not found gracefully
      if (('code' in error && error.code === "CONVERSATION_NOT_FOUND") || error.message?.includes("no longer exists")) {
        // Mark as handled before showing notification
        errorHandledRef.current.add(conversationId);
        
        // Show user-friendly notification
        addNotification({
          message: "This conversation no longer exists. It may have been deleted or the server restarted.",
          type: "warning",
          duration: 5000,
        });
        
        // Clean up UI state
        removeConversation(conversationId);
        setActiveConversation(null);
        
        // Navigate to home page
        router.push("/");
      } else {
        // Other SSE errors - log but don't throw
        console.error("SSE connection error:", error);
        
        // Mark as handled
        errorHandledRef.current.add(conversationId);
        
        addNotification({
          message: "Connection error. Please refresh the page.",
          type: "error",
          duration: 5000,
        });
      }
    },
  });

  // Handle sending message for NEW conversations
  // This creates the conversation first, then navigates to the real conversation page
  const handleNewConversationMessage = React.useCallback(async (content: string, attachments?: FileAttachment[]): Promise<void> => {
    if (conversationId !== "new") {
      // Not a new conversation - use normal send
      await api.sendMessage(conversationId, { content, attachments: attachments as unknown as ApiFileAttachment[] });
      return;
    }
    
    try {
      // 1. Create conversation first
      const config = toConversationConfig();
      const conversation = await createConversation({ 
        config,
        context: { source: "web-ui" }
      });
      
      const realConversationId = conversation.conversation_id;
      
      // 2. Add to conversation store (cast to Conversation type)
      addConversation({
        ...conversation,
        user_id: conversation.user_id || "unknown",
      });
      setActiveConversation(realConversationId);
      
      // 3. Copy messages from "new" to the real conversation ID
      // We copy instead of move to prevent the UI from flickering empty/welcome screen
      // before the navigation completes. The "new" messages are cleared in the cleanup effect.
      const newMessages = getMessages("new");
      newMessages.forEach(msg => {
        addMessage(realConversationId, {
          ...msg,
          conversation_id: realConversationId
        });
      });
      
      // 4. Mark as just created to skip SSE validation on next page
      setLocalWasJustCreated(true);
      
      // 5. Send the message to the real conversation (with attachments if any)
      await api.sendMessage(realConversationId, { content, attachments: attachments as unknown as ApiFileAttachment[] });
      
      // 6. Navigate to the real conversation page (use replace to avoid flashing)
      // Using query params for static export compatibility
      router.replace(`/chat?id=${realConversationId}`);
    } catch (error) {
      console.error("[ChatContainer] Failed to create conversation:", error);
      throw error;
    }
  }, [conversationId, toConversationConfig, addConversation, setActiveConversation, getMessages, addMessage, router]);

  // Determine if this is a new (unsaved) conversation
  const isNewConversation = conversationId === "new";

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Header */}
      <Paper
        elevation={1}
        sx={{
          p: 2,
          borderRadius: 0,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            {/* Connection indicator */}
            <Box
              role="status"
              aria-label={
                isNewConversation
                  ? "Connection status: new conversation"
                  : sseState === "connected"
                    ? "Connection status: connected"
                    : sseState === "connecting"
                      ? "Connection status: connecting"
                      : "Connection status: disconnected"
              }
              sx={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                bgcolor:
                  isNewConversation
                    ? "info.main" // Blue for new conversations (not connected yet)
                    : sseState === "connected"
                      ? "success.main"
                      : sseState === "connecting"
                        ? "warning.main"
                        : "error.main",
              }}
            />
          </Box>
          
          {/* Export & Offline Mode */}
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            {!isNewConversation && (
              <ExportMenu conversationId={conversationId} />
            )}
            <OfflineModeToggle compact />
          </Box>
        </Box>
      </Paper>

      {/* Message list area */}
      <Box
        sx={{
          flex: 1,
          minHeight: 0, // Critical for flex shrinking - allows content to scroll properly
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <MessageList 
          key={conversationId} 
          conversationId={conversationId}
          isNew={isNewConversation}
        />

        {/* Clarification Dialog (Phase 7) */}
        {activeClarification && (
          <Box sx={{ p: 2, pb: 0 }}>
            <ClarificationDialog
              clarification={activeClarification}
              onRespondWithOption={respondWithOption}
              onRespondWithCustomText={respondWithCustomText}
              onDismiss={
                !activeClarification.is_required ? clearClarification : undefined
              }
              isSubmitting={isClarificationSubmitting}
              error={clarificationError}
            />
          </Box>
        )}
      </Box>

      {/* Input area */}
      <Paper
        elevation={3}
        sx={{
          p: 2,
          borderRadius: 0,
          borderTop: 1,
          borderColor: "divider",
        }}
      >
        <MessageInput 
          conversationId={conversationId}
          pendingMessage={sseState === "connected" || isNewConversation ? pendingMessage : null}
          pendingAttachment={sseState === "connected" || isNewConversation ? pendingAttachment : null}
          onPendingMessageSent={() => {
            setPendingMessage(null);
            setPendingAttachment(null);
          }}
          onSendMessage={isNewConversation ? handleNewConversationMessage : undefined}
        />
      </Paper>
    </Box>
  );
}
