/**
 * InlineToolSummary component.
 *
 * Displays inline tool call summaries within thinking text.
 * Uses de-emphasized styling to avoid distracting from main content.
 *
 * Example rendered output:
 *   --> Explored 1 Tool
 *       • Execute SQL
 *
 * @module components/chat/InlineToolSummary
 */

"use client";

import React from "react";
import { Box, CircularProgress } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ArrowForwardIcon from "@mui/icons-material/ArrowForward";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";

export interface InlineToolInfo {
  /** Tool name identifier */
  name: string;
  /** User-friendly display name */
  friendly_name?: string;
  /** Tool completion status */
  status?: "in_progress" | "completed" | "failed";
}

interface InlineToolSummaryProps {
  /** Tools that were explored */
  tools: InlineToolInfo[];
}

/**
 * Inline tool summary displayed within thinking text.
 *
 * Renders tool exploration summaries with de-emphasized styling
 * to maintain focus on the agent's reasoning while showing what
 * tools were used.
 *
 * @param props - Component props
 * @returns InlineToolSummary component
 *
 * @example
 * ```tsx
 * <InlineToolSummary
 *   tools={[
 *     { name: "execute_sql", friendly_name: "Execute SQL", status: "completed" },
 *     { name: "get_job_config", friendly_name: "Get Job Config", status: "completed" },
 *   ]}
 * />
 * ```
 */
export function InlineToolSummary({ tools }: InlineToolSummaryProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  if (!tools || tools.length === 0) {
    return null;
  }

  // Separate running and completed tools
  const runningTools = tools.filter(t => t.status === "in_progress" || !t.status);
  const completedTools = tools.filter(t => t.status === "completed" || t.status === "failed");
  
  const hasRunning = runningTools.length > 0;
  const hasCompleted = completedTools.length > 0;
  const count = tools.length;
  const label = count === 1 ? "Tool" : "Tools";

  // Get display name: prefer friendly_name, otherwise format tool name
  const getDisplayName = (tool: InlineToolInfo): string => {
    if (tool.friendly_name) {
      return tool.friendly_name;
    }
    return formatToolName(tool.name);
  };

  return (
    <Box
      component="div"
      sx={{
        display: "block",
        mt: 0.5,
        mb: 0.5,
        // De-emphasized styling - lighter contrast based on theme
        color: isDark
          ? "rgba(255, 255, 255, 0.5)" // Muted in dark mode
          : "rgba(0, 0, 0, 0.45)", // Muted in light mode
        fontFamily: '"SF Mono", "Monaco", "Consolas", monospace',
        fontSize: "0.8rem",
        lineHeight: 1.4,
        userSelect: "none",
      }}
    >
      {/* Arrow and header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 0.5,
        }}
      >
        <ArrowForwardIcon
          sx={{
            fontSize: 12,
            opacity: 0.7,
          }}
        />
        <span style={{ fontWeight: 500 }}>
          {hasRunning && !hasCompleted ? "Running" : "Explored"} {count} {label}:
        </span>
      </Box>

      {/* Tool list - compact inline */}
      <Box sx={{ ml: 2.5 }}>
        {tools.map((tool, idx) => {
          const isRunning = tool.status === "in_progress" || !tool.status;
          const isFailed = tool.status === "failed";
          const isCompleted = tool.status === "completed";
          
          return (
            <Box
              key={`${tool.name}-${idx}`}
              component="span"
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 0.5,
                lineHeight: 1.3,
              }}
            >
              {/* Status indicator */}
              {isRunning ? (
                <CircularProgress
                  size={10}
                  thickness={4}
                  sx={{ 
                    color: isDark ? "rgba(255, 255, 255, 0.6)" : "rgba(0, 0, 0, 0.5)",
                  }}
                />
              ) : isCompleted ? (
                <CheckCircleOutlineIcon
                  sx={{
                    fontSize: 12,
                    opacity: 0.6,
                    color: theme.palette.success.main,
                  }}
                />
              ) : (
                <span style={{ opacity: 0.6 }}>•</span>
              )}
              <span style={{ opacity: isRunning ? 0.8 : 1 }}>
                {getDisplayName(tool)}
                {isRunning && <span style={{ marginLeft: 4, opacity: 0.7 }}>...</span>}
              </span>
              {isFailed && (
                <span style={{ color: theme.palette.error.main, fontSize: "0.7rem" }}>
                  (failed)
                </span>
              )}
            </Box>
          );
        })}
      </Box>
    </Box>
  );
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

export default InlineToolSummary;

