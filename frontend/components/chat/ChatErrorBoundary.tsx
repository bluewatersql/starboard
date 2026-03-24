/**
 * ChatErrorBoundary component.
 *
 * Specialized error boundary for chat interface with chat-specific
 * error handling and recovery options.
 */

"use client";

import React, { Component, ReactNode } from "react";
import { Box, Typography, Button, Stack, Paper, Alert } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReplayIcon from "@mui/icons-material/Replay";

interface ChatErrorBoundaryProps {
  /**
   * Child components to render.
   */
  children: ReactNode;

  /**
   * Optional custom fallback UI.
   */
  fallback?: ReactNode;

  /**
   * Callback when error is caught.
   */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;

  /**
   * Callback when user clicks "Try Again" button.
   */
  onReset?: () => void;
}

interface ChatErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Chat-specific error boundary.
 *
 * Catches errors in chat components and displays a fallback UI
 * with chat-specific guidance and recovery options.
 *
 * Features:
 * - Chat-specific error messages
 * - Data safety reassurance
 * - Multiple recovery options (retry, reload)
 * - Error logging integration
 *
 * @example
 * ```tsx
 * <ChatErrorBoundary onReset={handleReset}>
 *   <ChatContainer />
 * </ChatErrorBoundary>
 * ```
 */
export class ChatErrorBoundary extends Component<
  ChatErrorBoundaryProps,
  ChatErrorBoundaryState
> {
  constructor(props: ChatErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ChatErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    // Log error to console
    console.error("[ChatErrorBoundary] Caught error:", {
      error,
      errorInfo,
      componentStack: errorInfo.componentStack,
    });

    // Call custom error handler if provided
    this.props.onError?.(error, errorInfo);

    // TODO(BACKLOG-009): Integrate error tracking service (Sentry, etc.)
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (this.state.hasError) {
      // Render custom fallback if provided
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Render default chat-specific error UI
      return (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "400px",
            p: 3,
          }}
        >
          <Paper
            role="alert"
            elevation={2}
            sx={{
              p: 4,
              maxWidth: 600,
              width: "100%",
            }}
          >
            {/* Error Icon */}
            <Box sx={{ textAlign: "center", mb: 3 }}>
              <ErrorOutlineIcon
                sx={{ fontSize: 64, color: "error.main", mb: 2 }}
              />
              <Typography variant="h5" gutterBottom>
                Something Went Wrong
              </Typography>
              <Typography variant="body2" color="text.secondary">
                The chat interface encountered an error
              </Typography>
            </Box>

            {/* Error Details */}
            <Alert severity="error" sx={{ mb: 3 }}>
              <Typography variant="body2" fontWeight="medium">
                Error: {this.state.error?.message || "Unknown error"}
              </Typography>
            </Alert>

            {/* Reassurance */}
            <Alert severity="info" sx={{ mb: 3 }}>
              <Typography variant="body2" gutterBottom>
                <strong>Your conversation data is safe.</strong>
              </Typography>
              <Typography variant="body2">
                No messages have been lost. You can try again or reload the page.
              </Typography>
            </Alert>

            {/* Recovery Actions */}
            <Stack spacing={2}>
              <Button
                variant="contained"
                startIcon={<ReplayIcon />}
                onClick={this.handleReset}
                fullWidth
              >
                Try Again
              </Button>
              <Button
                variant="outlined"
                startIcon={<RefreshIcon />}
                onClick={this.handleReload}
                fullWidth
              >
                Reload Page
              </Button>
            </Stack>

            {/* Technical Details (for debugging) */}
            {process.env.NODE_ENV === "development" && (
              <Box sx={{ mt: 3, p: 2, bgcolor: "grey.100", borderRadius: 1 }}>
                <Typography variant="caption" component="div" sx={{ fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {this.state.error?.stack}
                </Typography>
              </Box>
            )}
          </Paper>
        </Box>
      );
    }

    return this.props.children;
  }
}

