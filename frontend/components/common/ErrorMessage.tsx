/**
 * ErrorMessage component.
 *
 * Displays error messages with optional retry action.
 */

"use client";

import React from "react";
import { Box, Paper, Typography, Button } from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import RefreshIcon from "@mui/icons-material/Refresh";

interface ErrorMessageProps {
  message: string;
  onRetry?: () => void;
  fullPage?: boolean;
}

/**
 * Error message component.
 *
 * Displays an error message with optional retry button.
 *
 * @param props - Component props
 * @returns Error message component
 *
 * @example
 * ```tsx
 * <ErrorMessage
 *   message="Failed to load data"
 *   onRetry={() => refetch()}
 * />
 * ```
 */
export function ErrorMessage({
  message,
  onRetry,
  fullPage = false,
}: ErrorMessageProps) {
  const content = (
    <Paper
      elevation={2}
      sx={{
        p: 3,
        textAlign: "center",
        maxWidth: 400,
        mx: "auto",
      }}
    >
      <ErrorOutlineIcon sx={{ fontSize: 48, color: "error.main", mb: 2 }} />
      <Typography variant="h6" gutterBottom>
        Something went wrong
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {message}
      </Typography>
      {onRetry && (
        <Button
          variant="contained"
          startIcon={<RefreshIcon />}
          onClick={onRetry}
        >
          Try Again
        </Button>
      )}
    </Paper>
  );

  if (fullPage) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "100vh",
          p: 3,
        }}
      >
        {content}
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 3,
      }}
    >
      {content}
    </Box>
  );
}

