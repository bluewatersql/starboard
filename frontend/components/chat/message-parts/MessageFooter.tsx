/**
 * Footer component for message bubbles.
 * Shows timestamp, status chips, retry button, feedback widget, and token/cost display.
 */

"use client";

import React from "react";
import { Box, Typography, Chip, IconButton } from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import { MessageStatus, FeedbackRating } from "@/lib/types/api";
import { FeedbackWidget } from "../FeedbackWidget";
import { TokenDisplay } from "../TokenDisplay";

export interface MessageFooterProps {
  timestamp?: string;
  status?: MessageStatus | string;
  messageId?: string;
  conversationId?: string;
  retryCount?: number;
  isAssistant: boolean;
  hasReport?: boolean;
  hasNextSteps?: boolean;
  /** Token usage metadata — populated from message.metadata after FINAL_OUTPUT */
  tokensUsed?: number;
  /** Estimated cost in USD — populated from message.metadata after FINAL_OUTPUT */
  costUsd?: number;
  /** Model that generated this message */
  model?: string;
  onRetry?: (messageId: string) => void;
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

export function MessageFooter({
  timestamp,
  status,
  messageId,
  conversationId,
  retryCount,
  isAssistant,
  hasReport,
  hasNextSteps,
  tokensUsed,
  costUsd,
  model,
  onRetry,
  onSubmitFeedback,
}: MessageFooterProps) {
  const showFeedback =
    isAssistant &&
    status === MessageStatus.COMPLETED &&
    onSubmitFeedback &&
    messageId &&
    !hasReport &&
    !hasNextSteps;

  return (
    <Box
      sx={{
        display: "flex",
        gap: 1,
        mt: 0.5,
        px: 1,
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <Box sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}>
        {timestamp && (
          <Typography variant="caption" color="text.secondary">
            {new Date(timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </Typography>
        )}
        {status === "processing" && (
          <Chip label="Processing" size="small" sx={{ height: 16 }} />
        )}
        {status === "failed" && (
          <>
            <Chip
              label="Failed"
              size="small"
              color="error"
              sx={{ height: 16 }}
            />
            {onRetry && messageId && (retryCount || 0) < 3 && (
              <IconButton
                size="small"
                color="error"
                onClick={() => onRetry(messageId)}
                aria-label="retry message"
                sx={{ ml: 0.5, p: 0.25 }}
              >
                <RefreshIcon sx={{ fontSize: 16 }} />
              </IconButton>
            )}
            {retryCount !== undefined && retryCount > 0 && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ ml: 0.5 }}
              >
                (Attempt {retryCount + 1}/3)
              </Typography>
            )}
          </>
        )}
        {/* Token/cost display — only for completed assistant messages */}
        {isAssistant && status === MessageStatus.COMPLETED && (
          <TokenDisplay
            totalTokens={tokensUsed}
            estimatedCostUsd={costUsd}
            model={model}
          />
        )}
      </Box>

      {/* Feedback Widget - Only for completed assistant messages without reports */}
      {showFeedback && messageId && conversationId && (
        <FeedbackWidget
          messageId={messageId}
          conversationId={conversationId}
          onSubmitFeedback={onSubmitFeedback}
          disabled={false}
        />
      )}
    </Box>
  );
}
