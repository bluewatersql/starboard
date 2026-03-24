/**
 * Error fallback components for messages and reports.
 *
 * Provides graceful error handling UI that matches the chat aesthetic.
 * Used with error boundaries to prevent single message errors from
 * crashing the entire conversation.
 */

"use client";

import React from "react";
import { Box, Paper, Typography, Button, Chip } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import RefreshIcon from "@mui/icons-material/Refresh";

interface MessageErrorFallbackProps {
  /** Error that was caught */
  error?: Error;
  /** Callback to attempt recovery */
  onRetry?: () => void;
  /** Message ID for debugging */
  messageId?: string;
}

/**
 * Error fallback for individual message bubbles.
 *
 * Displays a compact error UI in place of a failed message,
 * styled to match the chat aesthetic.
 *
 * @example
 * <ErrorBoundary fallback={<MessageErrorFallback />}>
 *   <MessageBubble message={msg} />
 * </ErrorBoundary>
 */
export function MessageErrorFallback({
  error,
  onRetry,
  messageId,
}: MessageErrorFallbackProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "flex-start",
        mb: 2,
        px: 2,
      }}
    >
      <Box
        sx={{
          display: "flex",
          gap: 1,
          maxWidth: "85%",
        }}
      >
        {/* Error icon as avatar */}
        <Box
          sx={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            bgcolor: "error.main",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <ErrorOutlineIcon sx={{ fontSize: 20, color: "white" }} />
        </Box>

        {/* Error content */}
        <Paper
          elevation={1}
          sx={{
            p: 2,
            borderRadius: 2,
            bgcolor: isDark ? "rgba(211, 47, 47, 0.08)" : "rgba(211, 47, 47, 0.04)",
            borderLeft: `3px solid ${theme.palette.error.main}`,
            minWidth: 200,
          }}
        >
          <Typography
            variant="subtitle2"
            sx={{ color: "error.main", fontWeight: 600, mb: 0.5 }}
          >
            Failed to render message
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {error?.message || "An error occurred while displaying this message."}
          </Typography>

          <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
            {onRetry && (
              <Button
                size="small"
                variant="outlined"
                color="error"
                startIcon={<RefreshIcon />}
                onClick={onRetry}
              >
                Retry
              </Button>
            )}

            {messageId && (
              <Chip
                label={`ID: ${messageId.slice(0, 8)}...`}
                size="small"
                variant="outlined"
                sx={{ opacity: 0.6 }}
              />
            )}
          </Box>
        </Paper>
      </Box>
    </Box>
  );
}

interface ReportErrorFallbackProps {
  /** Error that was caught */
  error?: Error;
  /** Report type for context */
  reportType?: "advisor" | "analytics" | "default";
  /** Callback to attempt recovery */
  onRetry?: () => void;
}

/**
 * Error fallback for report bubbles.
 *
 * Displays a styled error card in place of a failed report,
 * with information about what went wrong.
 *
 * @example
 * <ErrorBoundary fallback={<ReportErrorFallback reportType="advisor" />}>
 *   <AdvisorReportBubble report={report} />
 * </ErrorBoundary>
 */
export function ReportErrorFallback({
  error,
  reportType = "default",
  onRetry,
}: ReportErrorFallbackProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  const borderColor =
    reportType === "analytics"
      ? theme.palette.info.main
      : reportType === "advisor"
        ? theme.palette.success.main
        : theme.palette.grey[500];

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "flex-start",
        mb: 2,
        px: 2,
      }}
    >
      <Box
        sx={{
          display: "flex",
          gap: 1,
          maxWidth: "85%",
          width: "100%",
        }}
      >
        {/* Avatar placeholder */}
        <Box
          sx={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            bgcolor: "error.light",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <ErrorOutlineIcon sx={{ fontSize: 18, color: "error.dark" }} />
        </Box>

        {/* Report error content */}
        <Paper
          elevation={2}
          sx={{
            p: 3,
            borderRadius: 2,
            bgcolor: isDark ? "rgba(211, 47, 47, 0.06)" : "rgba(211, 47, 47, 0.03)",
            borderLeft: `4px solid ${borderColor}`,
            flex: 1,
            maxWidth: 800,
          }}
        >
          <Box sx={{ display: "flex", alignItems: "center", mb: 1.5 }}>
            <ErrorOutlineIcon sx={{ color: "error.main", mr: 1 }} />
            <Typography variant="h6" sx={{ fontWeight: 600 }}>
              Report Failed to Load
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {error?.message ||
              "There was an error rendering this report. The analysis may still be available in the raw data."}
          </Typography>

          <Box
            sx={{
              p: 1.5,
              borderRadius: 1,
              bgcolor: isDark ? "rgba(0,0,0,0.2)" : "rgba(0,0,0,0.04)",
              mb: 2,
            }}
          >
            <Typography
              variant="caption"
              component="pre"
              sx={{
                fontFamily: "monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                color: "text.secondary",
              }}
            >
              {error?.stack?.split("\n").slice(0, 3).join("\n") ||
                "No stack trace available"}
            </Typography>
          </Box>

          {onRetry && (
            <Button
              variant="contained"
              color="primary"
              startIcon={<RefreshIcon />}
              onClick={onRetry}
            >
              Try Again
            </Button>
          )}
        </Paper>
      </Box>
    </Box>
  );
}

export default MessageErrorFallback;

