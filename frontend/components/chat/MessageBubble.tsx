/**
 * MessageBubble component.
 *
 * Entry point for rendering chat messages. Delegates to role-specific
 * components (SystemMessage, UserMessage, AssistantMessage) for actual rendering.
 */

"use client";

import React, { memo } from "react";
import type { Message, NextStepOption } from "@/lib/types/api";
import { FeedbackRating } from "@/lib/types/api";
import { SystemMessage } from "./messages/SystemMessage";
import { UserMessage } from "./messages/UserMessage";
import { AssistantMessage } from "./messages/AssistantMessage";

export interface MessageBubbleProps {
  message: Message;
  onRetry?: (messageId: string) => void;
  onSelectOption?: (option: NextStepOption) => void;
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

/**
 * Message bubble component.
 *
 * Renders a chat message with appropriate styling for user vs assistant.
 * Delegates to role-specific components for actual rendering.
 * 
 * Wrapped with React.memo to prevent unnecessary re-renders when parent
 * (MessageList) re-renders but this message's props haven't changed.
 *
 * @param props - Component props
 * @returns Message bubble component
 *
 * @example
 * ```tsx
 * <MessageBubble message={message} onRetry={handleRetry} />
 * ```
 */
export const MessageBubble = memo(function MessageBubble({
  message,
  onRetry,
  onSelectOption: _onSelectOption, // eslint-disable-line @typescript-eslint/no-unused-vars
  onSubmitFeedback,
}: MessageBubbleProps) {
  // System messages - centered, informational
  if (message.role === "system") {
    return <SystemMessage content={message.content} />;
  }

  // User messages - right-aligned
  if (message.role === "user") {
    return <UserMessage message={message} onRetry={onRetry} />;
  }

  // Assistant messages - left-aligned with thinking steps
  return (
    <AssistantMessage
      message={message}
      onRetry={onRetry}
      onSubmitFeedback={onSubmitFeedback}
    />
  );
})
