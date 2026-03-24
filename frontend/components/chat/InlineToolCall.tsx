/**
 * InlineToolCall component.
 *
 * Displays a single tool call inline within thinking text.
 * Uses de-emphasized styling similar to Cursor's thinking indicators.
 *
 * Format: -> Tool Name
 *
 * @module components/chat/InlineToolCall
 */

"use client";

import React from "react";
import { Box } from "@mui/material";
import { useTheme } from "@mui/material/styles";

export interface InlineToolCallProps {
  /** Tool name identifier */
  toolName: string;
  /** User-friendly display name (optional) */
  friendlyName?: string;
  /** Tool call status */
  status?: "in_progress" | "completed" | "failed";
}

/**
 * Format tool name for display.
 * Converts snake_case to Title Case.
 */
function formatToolName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Inline tool call indicator displayed within thinking text.
 *
 * Renders a single tool call with de-emphasized styling to maintain
 * focus on the agent's reasoning while showing what tools are being called.
 *
 * @param props - Component props
 * @returns InlineToolCall component
 *
 * @example
 * ```tsx
 * <InlineToolCall
 *   toolName="execute_sql"
 *   friendlyName="Execute SQL"
 *   status="in_progress"
 * />
 * ```
 */
export function InlineToolCall({ 
  toolName, 
  friendlyName,
  status = "in_progress" 
}: InlineToolCallProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  // Get display name: prefer friendly_name, otherwise format tool name
  const displayName = friendlyName || formatToolName(toolName);

  return (
    <Box
      component="span"
      sx={{
        display: "block",
        // De-emphasized styling - similar to Cursor's thinking text
        color: isDark
          ? "rgba(255, 255, 255, 0.45)"
          : "rgba(0, 0, 0, 0.4)",
        fontSize: "0.85rem",
        fontStyle: "italic",
        lineHeight: 1.4,
        userSelect: "none",
      }}
    >
      → {displayName}
      {status === "failed" && (
        <Box
          component="span"
          sx={{
            color: theme.palette.error.main,
            ml: 0.5,
            fontSize: "0.8em",
          }}
        >
          (failed)
        </Box>
      )}
    </Box>
  );
}

export default InlineToolCall;
