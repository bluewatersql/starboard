/**
 * ToolCallCard component.
 *
 * Displays tool call information in an expandable card with formatted parameters and results.
 */

"use client";

import React, { useState } from "react";
import {
  Card,
  CardContent,
  Collapse,
  IconButton,
  Typography,
  Box,
  Chip,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import BuildIcon from "@mui/icons-material/Build";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import { useTheme } from "@mui/material/styles";
import type { ToolCall, ToolCallStatus } from "@/lib/types/api";

interface ToolCallCardProps {
  toolCall: ToolCall;
}

/**
 * Format JSON for display.
 */
function formatJSON(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

/**
 * Format duration from milliseconds to human-readable string.
 */
function formatDuration(ms: number): string {
  if (ms < 1000) {
    return "< 1 second";
  }
  
  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  
  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`;
  }
  
  return `${seconds}s`;
}

/**
 * Get icon based on tool status.
 */
function getStatusIcon(status: ToolCallStatus | undefined) {
  if (!status) return <BuildIcon fontSize="small" />;
  
  switch (status) {
    case "completed":
      return <CheckCircleIcon fontSize="small" />;
    case "failed":
      return <ErrorIcon fontSize="small" />;
    default:
      return <BuildIcon fontSize="small" />;
  }
}

/**
 * Get color based on tool status.
 */
function getStatusColor(
  status: ToolCallStatus | undefined
): "success" | "error" | "primary" | "default" {
  if (!status) return "default";
  
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "running":
      return "primary";
    default:
      return "default";
  }
}

/**
 * Tool call card component.
 *
 * Shows tool execution details with expandable sections for parameters and results.
 *
 * @param props - Component props
 * @returns Tool call card component
 *
 * @example
 * ```tsx
 * <ToolCallCard toolCall={toolCall} />
 * ```
 */
export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(false);

  const handleExpandClick = () => {
    setExpanded(!expanded);
  };

  return (
    <Card
      variant="outlined"
      sx={{
        my: 1,
        borderRadius: 2,
        borderColor: `${getStatusColor(toolCall.status)}.main`,
        borderWidth: 1,
        maxWidth: "100%",
      }}
    >
      <CardContent sx={{ p: 1.5, "&:last-child": { pb: 1.5 } }}>
        {/* Header */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              color: `${getStatusColor(toolCall.status)}.main`,
            }}
          >
            {getStatusIcon(toolCall.status)}
          </Box>

          <Typography variant="body2" sx={{ flex: 1, fontWeight: 600 }}>
            {toolCall.friendly_name || toolCall.tool_name}
          </Typography>

          <Chip
            label={toolCall.status}
            size="small"
            color={getStatusColor(toolCall.status)}
            sx={{ height: 20, fontSize: "0.7rem" }}
          />

          {typeof toolCall.duration_ms === 'number' && (
            <Typography variant="caption" color="text.secondary">
              {formatDuration(toolCall.duration_ms)}
            </Typography>
          )}

          <IconButton
            onClick={handleExpandClick}
            size="small"
            sx={{
              transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
              transition: theme.transitions.create("transform", {
                duration: theme.transitions.duration.shortest,
              }),
            }}
          >
            <ExpandMoreIcon fontSize="small" />
          </IconButton>
        </Box>

        {/* Expandable Content */}
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <Box sx={{ mt: 2 }}>
            {/* Parameters */}
            {toolCall.arguments &&
              Object.keys(toolCall.arguments).length > 0 && (
                <Box sx={{ mb: 2 }}>
                  <Typography
                    variant="caption"
                    sx={{ fontWeight: 600, color: "text.secondary" }}
                  >
                    Parameters:
                  </Typography>
                  <Box
                    sx={{
                      mt: 0.5,
                      p: 1,
                      bgcolor: "background.default",
                      borderRadius: 1,
                      border: 1,
                      borderColor: "divider",
                      maxHeight: 200,
                      overflow: "auto",
                    }}
                  >
                    <Typography
                      variant="caption"
                      component="pre"
                      sx={{
                        fontFamily: "monospace",
                        fontSize: "0.75rem",
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        m: 0,
                      }}
                    >
                      {formatJSON(toolCall.arguments)}
                    </Typography>
                  </Box>
                </Box>
              )}

            {/* Result */}
            {toolCall.result !== undefined && (
              <Box>
                <Typography
                  variant="caption"
                  sx={{ fontWeight: 600, color: "text.secondary" }}
                >
                  Result:
                </Typography>
                <Box
                  sx={{
                    mt: 0.5,
                    p: 1,
                    bgcolor: "background.default",
                    borderRadius: 1,
                    border: 1,
                    borderColor: "divider",
                    maxHeight: 200,
                    overflow: "auto",
                  }}
                >
                  <Typography
                    variant="caption"
                    component="pre"
                    sx={{
                      fontFamily: "monospace",
                      fontSize: "0.75rem",
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      m: 0,
                    }}
                  >
                    {typeof toolCall.result === "string"
                      ? toolCall.result
                      : formatJSON(toolCall.result)}
                  </Typography>
                </Box>
              </Box>
            )}

            {/* Error */}
            {toolCall.error && (
              <Box sx={{ mt: 2 }}>
                <Typography
                  variant="caption"
                  sx={{ fontWeight: 600, color: "error.main" }}
                >
                  Error:
                </Typography>
                <Typography
                  variant="caption"
                  sx={{ display: "block", mt: 0.5, color: "error.main" }}
                >
                  {toolCall.error}
                </Typography>
              </Box>
            )}
          </Box>
        </Collapse>
      </CardContent>
    </Card>
  );
}

