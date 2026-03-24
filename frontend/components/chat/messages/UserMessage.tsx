/**
 * UserMessage component.
 * Renders user messages with right-aligned styling.
 * Supports file attachment display (BB-05).
 */

"use client";

import React from "react";
import { Box, Paper, Typography, Slide } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type { Message, MessageAttachment } from "@/lib/types/api";
import { MessageAvatar, MessageFooter } from "../message-parts";
import { FileAttachmentChip } from "../FileAttachmentChip";
import type { FileAttachment } from "../FileUploadButton";

export interface UserMessageProps {
  message: Message;
  onRetry?: (messageId: string) => void;
}

/**
 * Convert MessageAttachment to FileAttachment for FileAttachmentChip.
 */
function toFileAttachment(attachment: MessageAttachment): FileAttachment {
  return {
    filename: attachment.filename,
    size: attachment.size || 0,
    content: attachment.content || "",
    contentPreview: attachment.content_preview || attachment.content?.slice(0, 500) || "",
    isLargeFile: attachment.is_large_file || false,
  };
}

export function UserMessage({ message, onRetry }: UserMessageProps) {
  const theme = useTheme();

  // Get attachments from message.attachments or message.metadata?.attachments
  const attachments: MessageAttachment[] = 
    message.attachments || 
    (message.metadata?.attachments as MessageAttachment[] | undefined) || 
    [];

  return (
    <Slide direction="left" in={true} timeout={300} mountOnEnter unmountOnExit>
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-end",
          mb: 2,
          px: 2,
        }}
      >
        <Box
          sx={{
            display: "flex",
            gap: 1,
            maxWidth: "70%",
            flexDirection: "row-reverse",
          }}
        >
          {/* User Avatar */}
          <MessageAvatar isUser={true} />

          {/* Message content */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Paper
              elevation={1}
              sx={{
                p: 1.5,
                // Lighter blue backgrounds for better text readability
                bgcolor:
                  theme.palette.mode === "dark"
                    ? "rgba(66, 165, 245, 0.15)" // Light blue tint in dark mode
                    : "rgba(33, 150, 243, 0.12)", // Very light blue in light mode
                borderRadius: 2,
                borderTopLeftRadius: 2,
                borderTopRightRadius: 0,
                // Subtle border for definition
                border: 1,
                borderColor:
                  theme.palette.mode === "dark"
                    ? "rgba(66, 165, 245, 0.3)"
                    : "rgba(33, 150, 243, 0.25)",
              }}
            >
              {/* File attachment chips (BB-05) */}
              {attachments.length > 0 && (
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mb: 1 }}>
                  {attachments.map((attachment, idx) => (
                    <FileAttachmentChip
                      key={attachment.id || `attachment-${idx}`}
                      attachment={toFileAttachment(attachment)}
                      showDelete={false}
                    />
                  ))}
                </Box>
              )}
              <Typography
                variant="body1"
                component="div"
                sx={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  color: "text.primary",
                }}
              >
                {message.content}
              </Typography>
            </Paper>

            {/* Footer with timestamp and status */}
            <MessageFooter
              timestamp={message.timestamp}
              status={message.status}
              messageId={message.message_id}
              retryCount={message.retry_count}
              isAssistant={false}
              onRetry={onRetry}
            />
          </Box>
        </Box>
      </Box>
    </Slide>
  );
}

