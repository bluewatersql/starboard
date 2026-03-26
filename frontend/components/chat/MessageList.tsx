/**
 * MessageList component.
 *
 * Displays a scrollable list of messages with auto-scroll behavior
 * and markdown rendering support.
 *
 * Message structure (for assistant messages):
 * 1. MessageBubble - thinking text with inline tool calls
 * 2. ThinkingStepsBubble - tool call lineage summary (after message complete)
 * 3. ReportBubble - formatted report (if applicable)
 * 4. NextStepsBubble - action options
 *
 * Virtual scrolling: uses @tanstack/react-virtual to render only visible
 * message groups, keeping the DOM lean for long conversations.
 */

"use client";

import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { Box, CircularProgress, Typography, Chip, Divider } from "@mui/material";
import Image from "next/image";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api, sendMessage } from "@/lib/api/client";
import { useMessageStore } from "@/lib/store/messageStore";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useThemeMode } from "@/lib/theme/ThemeProvider";
import { MessageBubble } from "./MessageBubble";
import { ReportBubble } from "./ReportBubble";
import { NextStepsBubble } from "./NextStepsBubble";
import { ThinkingStepsBubble } from "./ThinkingStepsBubble";
import { ConfigErrorAlert } from "../common/ConfigErrorAlert";
import { ErrorBoundary } from "../common/ErrorBoundary";
import { MessageErrorFallback, ReportErrorFallback } from "./MessageErrorFallback";
import type { NextStepOption, FeedbackRating, Message } from "@/lib/types/api";
import { MessageStatus } from "@/lib/types/api";

// Stable empty array to avoid infinite re-render loops in selectors
const EMPTY_MESSAGES: Message[] = [];

interface MessageListProps {
  conversationId: string;
  isNew?: boolean;
}

/**
 * Message list component.
 *
 * Renders the conversation message history with automatic scrolling
 * to the latest message and markdown rendering support.
 *
 * @param props - Component props
 * @returns Message list component
 *
 * @example
 * ```tsx
 * <MessageList conversationId="conv_123" />
 * ```
 */
export function MessageList({ conversationId, isNew = false }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);

  // Use granular selectors to minimize re-renders
  // Functions are stable references in Zustand, so these won't trigger re-renders
  const setMessages = useMessageStore((state) => state.setMessages);
  const retryMessage = useMessageStore((state) => state.retryMessage);
  const getMessages = useMessageStore((state) => state.getMessages);

  // State values - only subscribe to what we need
  const streamingMessageId = useMessageStore((state) => state.streamingMessageId);

  // Subscribe to the raw messages array - this triggers re-renders when messages change
  // (including thinking_steps updates)
  const rawMessages = useMessageStore((state) =>
    state.messagesByConversation[conversationId]
  ) ?? EMPTY_MESSAGES;
  // Memoize the filtered messages to avoid creating new arrays on every render
  const messages = useMemo(() => {
    // Defensive filtering: Ensure we only show messages for the current conversation
    return rawMessages.filter(m => !m.conversation_id || m.conversation_id === conversationId);
  }, [rawMessages, conversationId]);
  const conversations = useConversationStore((s) => s.conversations);
  const { mode } = useThemeMode();
  const [dismissedConfigError, setDismissedConfigError] = useState(false);

  // Get conversation config for welcome message
  const conversation = conversations.find((c) => c.conversation_id === conversationId);
  const config = conversation?.config;

  // Detect configuration errors in messages
  const configError = messages.find(m =>
    m.role === "assistant" &&
    m.content &&
    (
      m.content.includes("⚙️ **Configuration Error**") ||
      m.content.includes("ConfigurationError") ||
      m.content.includes("Invalid model configuration")
    )
  );

  // Fetch conversation history
  // Skip for new conversations to avoid overwriting optimistic messages
  const { data: history, isLoading } = useQuery({
    queryKey: ["conversation-history", conversationId],
    queryFn: () => api.getConversationHistory(conversationId),
    enabled: !!conversationId && conversationId !== "new" && !isNew,
    staleTime: 1000 * 60, // 1 minute
  });

  // Handle message retry - memoized to prevent MessageBubble re-renders
  const handleRetry = useCallback(async (messageId: string) => {
    const message = retryMessage(conversationId, messageId);
    if (!message) {
      console.error("Failed to retry message:", messageId);
      return;
    }

    try {
      // Re-send the message content
      await sendMessage(conversationId, {
        content: message.content,
      });
      // The SSE stream will handle updating the message with the new response
    } catch (error) {
      console.error("Retry failed:", error);
      // Error state is already managed by the store
    }
  }, [conversationId, retryMessage]);

  // Handle next step option selection - memoized to prevent child re-renders
  // Phase 1: Conversation Patterns - Pattern 1 (Option Selection)
  const handleSelectOption = useCallback(async (option: NextStepOption) => {
    try {
      // Send enriched message with full option context
      // Format: "[Option N] Title" for clear conversation history
      const enrichedContent = `[Option ${option.number}] ${option.title}`;

      // Include full option details in metadata for backend processing
      await sendMessage(conversationId, {
        content: enrichedContent,
        metadata: {
          is_option_selection: true,
          selected_option: {
            id: option.id,
            number: option.number,
            title: option.title,
            description: option.description,
            action_type: option.action_type,
            target_agent: option.target_agent,
            tool_name: option.tool_name,
            parameters: option.parameters,
          },
        },
      });
      // The SSE stream will handle the agent's response
    } catch (error) {
      console.error("[MessageList] Option selection failed:", error);
      throw error;
    }
  }, [conversationId]);

  // Handle feedback submission - memoized to prevent child re-renders
  // Phase 1: Conversation Patterns - Pattern 4 (Feedback Collection)
  const handleSubmitFeedback = useCallback(async (messageId: string, rating: FeedbackRating) => {
    try {
      await api.submitFeedback(conversationId, {
        message_id: messageId,
        rating,
      });
    } catch (error) {
      console.error("Feedback submission failed:", error);
      throw error; // Re-throw to let FeedbackWidget handle the error
    }
  }, [conversationId]);

  // Get domain models from history
  const domainModels = history?.domain_models || [];

  // Load messages into store when history is fetched
  // IMPORTANT: Only set if store is empty to avoid overwriting optimistic messages
  useEffect(() => {
    if (history?.messages) {
      const existingMessages = getMessages(conversationId);

      // Only load history if store is empty (fresh page load)
      // If there are already messages, they were added optimistically and shouldn't be overwritten
      if (existingMessages.length === 0) {
        setMessages(conversationId, history.messages);
      }
    }
  }, [history, conversationId, setMessages, getMessages]);

  // Messages are already deduplicated by the store (setMessages and addMessage)
  // In development, log a warning if duplicates are detected (indicates a bug)
  const uniqueMessages = React.useMemo(() => {
    if (process.env.NODE_ENV === 'development') {
      const ids = messages.map(m => m.message_id).filter(Boolean);
      const uniqueIds = new Set(ids);
      if (ids.length !== uniqueIds.size) {
        console.warn('[MessageList] Duplicate messages detected - this indicates a bug:', {
          totalMessages: messages.length,
          uniqueIds: uniqueIds.size,
          duplicateIds: ids.filter((id, i) => ids.indexOf(id) !== i),
        });
      }
    }
    // Trust the store - no client-side deduplication needed
    return messages;
  }, [messages]);

  // Build flat filtered list used by the virtualizer
  const filteredMessages = useMemo(() => {
    return uniqueMessages.filter((message) => {
      // Filter out system messages about domain models (shown in welcome screen)
      if (message.role === "system" && message.content.includes("Multi-Agent Configuration")) {
        return false;
      }
      // Filter out configuration error messages from the chat since they're shown in the alert
      if (message.role === "assistant" && message.content) {
        return !(
          message.content.includes("⚙️ **Configuration Error**") ||
          message.content.includes("ConfigurationError") ||
          message.content.includes("Invalid model configuration")
        );
      }
      return true;
    });
  }, [uniqueMessages]);

  // Set up virtualizer - each item is a full message group (bubble + thinking + report + next steps)
  const virtualizer = useVirtualizer({
    count: filteredMessages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 150, // estimated average message group height in px
    overscan: 5,
  });

  // Track user scroll position to determine if we should auto-scroll
  // Only auto-scroll if user is near bottom (hasn't scrolled up to read history)
  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = scrollEl;
      // Consider "at bottom" if within 100px of bottom
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 100;
      userScrolledRef.current = !isAtBottom;
    };

    // Use passive listener for better scroll performance
    scrollEl.addEventListener('scroll', handleScroll, { passive: true });
    return () => scrollEl.removeEventListener('scroll', handleScroll);
  }, []);

  // Auto-scroll to the last message using the virtualizer when new messages arrive
  // or streaming content grows. Respects manual user scrolling.
  //
  // align: "end"   → during active streaming, keep the bottom edge visible so the
  //                  user sees the latest text as it arrives.
  // align: "start" → once streaming ends (or a completed message is added), scroll
  //                  to the *top* of the last message group so the user sees the
  //                  beginning of the response.  Using "end" here causes blank-space
  //                  overscroll because the virtualizer's estimated row height (150px)
  //                  is much smaller than a real report, so the scroll position ends up
  //                  well past the rendered content.
  useEffect(() => {
    if (userScrolledRef.current) return;
    if (filteredMessages.length === 0) return;
    const isStreaming = !!streamingMessageId;
    virtualizer.scrollToIndex(filteredMessages.length - 1, {
      align: isStreaming ? "end" : "start",
    });
  }, [filteredMessages.length, streamingMessageId, virtualizer]);

  if (isLoading) {
    return (
      <Box
        aria-live="polite"
        aria-label="Loading messages"
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  // Only show welcome screen if there are no messages
  const shouldShowWelcome = uniqueMessages.length === 0;

  if (shouldShowWelcome) {
    return (
      <Box
        aria-live="polite"
        aria-label="Welcome screen"
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          textAlign: "center",
          color: "text.secondary",
          px: 3,
        }}
      >
        <Box sx={{ maxWidth: 600 }}>
          <Box sx={{ mb: 2, display: "flex", justifyContent: "center" }}>
            <Image
              src={mode === "dark" ? "/logo_wheel_dark_small.png" : "/logo_wheel_light_small.png"}
              alt="Starboard Logo"
              width={128}
              height={128}
              style={{ objectFit: "contain" }}
            />
          </Box>

          <Typography variant="h6" gutterBottom>
            Welcome to Starboard AI Chat
          </Typography>

          <Typography variant="body2" paragraph>
            <b><em>Navigating deep Databricks insights for efficiency at scale.</em></b>
            <br />
            <br />
            AI-powered assistant for Databricks workload analysis and optimization.
          </Typography>

          {config && (
            <Box sx={{ display: "flex", gap: 1, justifyContent: "center", flexWrap: "wrap", mt: 2 }}>
              <Chip
                label={`Model: ${config.model || "databricks-claude-sonnet-4-5"}`}
                size="small"
                variant="outlined"
              />
              <Chip
                label={`Max Tokens: ${(config.max_tokens || 2048).toLocaleString()}`}
                size="small"
                variant="outlined"
              />
              {config.budget_enforced && (
                <Chip
                  label="Budget Enforced"
                  size="small"
                  color="primary"
                  variant="outlined"
                />
              )}
            </Box>
          )}

          {/* Show domain-specific models if multi-agent is configured */}
          {domainModels && domainModels.length > 0 && (
            <Box sx={{ mt: 3 }}>
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 1 }}>
                Multi-Agent Configuration
              </Typography>
              <Box sx={{ display: "flex", gap: 1, justifyContent: "center", flexWrap: "wrap" }}>
                {domainModels.map((item, idx) => (
                  <Chip
                    key={idx}
                    label={`${item.domain}: ${item.model}`}
                    size="small"
                    variant="outlined"
                    color="secondary"
                  />
                ))}
              </Box>
            </Box>
          )}

          <Typography variant="body2" sx={{ mt: 3 }}>
            Start a conversation by sending a message below
          </Typography>
        </Box>
      </Box>
    );
  }

  /**
   * Check if a message has visible thinking steps.
   * Returns true if message has steps that are not hidden internal tools.
   */
  const hasVisibleThinkingSteps = (message: Message): boolean => {
    if (!message.thinking_steps || message.thinking_steps.length === 0) return false;
    const hiddenTools = new Set([
      "complete",
    ]);
    return message.thinking_steps.some(step => !hiddenTools.has(step.id));
  };

  /**
   * Check if message is completed (either status enum or string).
   */
  const isMessageCompleted = (message: Message): boolean => {
    return message.status === MessageStatus.COMPLETED || String(message.status) === "completed";
  };

  return (
    <Box
      ref={scrollRef}
      sx={{
        flex: 1,
        minHeight: 0, // Critical for proper flex shrinking in nested flex containers
        overflowY: "auto",
        overflowX: "hidden",
        p: 2,
      }}
    >
      {/* Configuration Error Alert - outside the virtual list so it stays pinned at top */}
      {configError && !dismissedConfigError && (
        <Box sx={{ px: 2, pb: 2 }}>
          <ConfigErrorAlert
            errorMessage={configError.content}
            onDismiss={() => setDismissedConfigError(true)}
          />
        </Box>
      )}

      {/* Virtual scroll container: height drives the scrollbar */}
      <div role="log" aria-label="Conversation messages" aria-live="polite" style={{ height: virtualizer.getTotalSize(), width: "100%", position: "relative" }}>
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const message = filteredMessages[virtualRow.index];
          if (!message) return null;
          return (
            <div
              key={message.message_id || `msg-${virtualRow.index}`}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
                // Replicate the gap: 2 spacing from the previous flex layout
                paddingBottom: "16px",
              }}
            >
              {/* Wrap each message in error boundary to prevent single message crash */}
              <ErrorBoundary
                fallbackRender={({ error }) => (
                  <MessageErrorFallback
                    error={error}
                    messageId={message.message_id}
                  />
                )}
              >
                <MessageBubble
                  message={message}
                  onRetry={handleRetry}
                  onSelectOption={handleSelectOption}
                  onSubmitFeedback={handleSubmitFeedback}
                />
              </ErrorBoundary>

              {/* ThinkingStepsBubble - rendered after message content, only when complete */}
              {message.role === "assistant" &&
               isMessageCompleted(message) &&
               hasVisibleThinkingSteps(message) && (
                <ThinkingStepsBubble message={message} />
              )}

              {/* Render report bubble if message has a complete_report */}
              {!!message.metadata?.complete_report && (
                <ErrorBoundary
                  fallbackRender={({ error: errorVal }) => (
                    <ReportErrorFallback
                      error={errorVal}
                      reportType={
                        typeof message.metadata?.complete_report === "object" &&
                        message.metadata.complete_report !== null &&
                        "report_type" in message.metadata.complete_report &&
                        (message.metadata.complete_report as Record<string, unknown>).report_type === "analytics"
                          ? "analytics"
                          : "advisor"
                      }
                    />
                  )}
                >
                  <ReportBubble
                    message={message}
                    onSelectOption={handleSelectOption}
                    onSubmitFeedback={handleSubmitFeedback}
                  />
                </ErrorBoundary>
              )}
              {/* Visual divider between report and next steps for better separation */}
              {!!message.metadata?.complete_report && message.next_steps && message.next_steps.length > 0 && (
                <Box
                  sx={{
                    display: "flex",
                    alignItems: "center",
                    my: 2,
                    px: 4,
                    opacity: 0.7,
                  }}
                >
                  <Divider sx={{ flex: 1 }} />
                  <Typography
                    variant="caption"
                    sx={{
                      mx: 2,
                      color: "text.secondary",
                      fontWeight: 600,
                      letterSpacing: "0.05em",
                      textTransform: "uppercase",
                      fontSize: "0.7rem",
                    }}
                  >
                    Next Steps
                  </Typography>
                  <Divider sx={{ flex: 1 }} />
                </Box>
              )}
              {/* Render next steps separately for better visibility (Phase 2) */}
              {message.next_steps && message.next_steps.length > 0 && (
                <NextStepsBubble
                  options={message.next_steps as NextStepOption[]}
                  onSelectOption={handleSelectOption}
                  disabled={message.status === "processing"}
                />
              )}
            </div>
          );
        })}
      </div>
    </Box>
  );
}
