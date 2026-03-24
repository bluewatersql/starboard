/**
 * ReasoningTimeline component.
 *
 * Displays the agent's reasoning steps (tool calls) as a collapsible
 * vertical timeline. Shows after message completion.
 */

"use client";

import React, { useState } from "react";
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  Box,
  Chip,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import BuildIcon from "@mui/icons-material/Build";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import HourglassEmptyIcon from "@mui/icons-material/HourglassEmpty";
import type { ToolCall } from "@/lib/types/api";

export interface ReasoningTimelineProps {
  /** Tool calls to render as reasoning steps */
  toolCalls: ToolCall[];
}

/**
 * Format a tool name from snake_case to Title Case.
 */
function formatToolName(name: string): string {
  return name
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Get a short string representation of tool arguments.
 */
function formatArgs(args: unknown): string {
  if (!args) return "";
  try {
    const str = typeof args === "string" ? args : JSON.stringify(args);
    return str.length > 120 ? str.slice(0, 120) + "…" : str;
  } catch {
    return "";
  }
}

/**
 * Get step colour based on tool call status.
 */
function getStepColor(status?: string): string {
  switch (status) {
    case "completed":
      return "success.main";
    case "failed":
      return "error.main";
    case "running":
      return "warning.main";
    default:
      return "primary.main";
  }
}

/**
 * Step icon based on tool call status.
 */
function StepIcon({ status }: { status?: string }) {
  const sx = { fontSize: 16 };
  switch (status) {
    case "completed":
      return <CheckCircleOutlineIcon sx={{ ...sx, color: "success.main" }} />;
    case "failed":
      return <ErrorOutlineIcon sx={{ ...sx, color: "error.main" }} />;
    case "running":
      return <HourglassEmptyIcon sx={{ ...sx, color: "warning.main" }} />;
    default:
      return <BuildIcon sx={{ ...sx, color: "primary.main" }} />;
  }
}

/**
 * Calculate total latency across all tool calls that have duration_ms.
 */
function totalLatencyMs(toolCalls: ToolCall[]): number | null {
  const latencies = toolCalls
    .map((tc) => tc.duration_ms)
    .filter((v): v is number => typeof v === "number");
  return latencies.length > 0 ? latencies.reduce((a, b) => a + b, 0) : null;
}

/**
 * Collapsible reasoning timeline for completed assistant messages.
 *
 * @example
 * ```tsx
 * {message.status === "completed" && message.tool_calls && message.tool_calls.length > 0 && (
 *   <ReasoningTimeline toolCalls={message.tool_calls} />
 * )}
 * ```
 */
export function ReasoningTimeline({ toolCalls }: ReasoningTimelineProps) {
  const [expanded, setExpanded] = useState(false);

  if (!toolCalls || toolCalls.length === 0) return null;

  const totalMs = totalLatencyMs(toolCalls);
  const stepCount = toolCalls.length;

  const summaryText =
    totalMs != null
      ? `${stepCount} reasoning step${stepCount !== 1 ? "s" : ""} · ${totalMs.toLocaleString()}ms`
      : `${stepCount} reasoning step${stepCount !== 1 ? "s" : ""}`;

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, isExpanded) => setExpanded(isExpanded)}
      disableGutters
      elevation={0}
      sx={{
        mt: 1,
        border: 1,
        borderColor: "divider",
        borderRadius: 1,
        "&:before": { display: "none" },
        bgcolor: "transparent",
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
        sx={{ minHeight: 36, "& .MuiAccordionSummary-content": { my: 0.5 } }}
      >
        <Typography
          variant="caption"
          sx={{ color: "text.secondary", fontStyle: "italic" }}
          data-testid="reasoning-summary"
        >
          {summaryText}
        </Typography>
      </AccordionSummary>

      <AccordionDetails sx={{ pt: 0, pb: 1.5, px: 1.5 }}>
        {/* Vertical timeline list */}
        <Box
          component="ol"
          sx={{ listStyle: "none", m: 0, p: 0 }}
          aria-label="Reasoning steps"
        >
          {toolCalls.map((tc, idx) => {
            const name =
              tc.friendly_name ||
              (tc.tool_name ? formatToolName(tc.tool_name) : `Step ${idx + 1}`);
            const argStr = formatArgs(tc.arguments);
            const stepLatency = tc.duration_ms;
            const isLast = idx === toolCalls.length - 1;

            return (
              <Box
                component="li"
                key={tc.tool_call_id ?? idx}
                sx={{ display: "flex", gap: 1, position: "relative" }}
              >
                {/* Timeline track */}
                <Box
                  sx={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    pt: 0.5,
                  }}
                >
                  <StepIcon status={tc.status} />
                  {!isLast && (
                    <Box
                      sx={{
                        flex: 1,
                        width: 2,
                        bgcolor: "divider",
                        mt: 0.5,
                        minHeight: 16,
                      }}
                    />
                  )}
                </Box>

                {/* Step content */}
                <Box sx={{ flex: 1, pb: isLast ? 0 : 1 }}>
                  <Box
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 0.5,
                      flexWrap: "wrap",
                    }}
                  >
                    <Typography
                      variant="caption"
                      sx={{ fontWeight: 600, color: getStepColor(tc.status) }}
                    >
                      {name}
                    </Typography>
                    {stepLatency != null && (
                      <Chip
                        label={`${stepLatency.toLocaleString()}ms`}
                        size="small"
                        sx={{ height: 16, fontSize: "0.625rem" }}
                      />
                    )}
                    {tc.status === "failed" && (
                      <Chip
                        label="failed"
                        size="small"
                        color="error"
                        sx={{ height: 16, fontSize: "0.625rem" }}
                      />
                    )}
                  </Box>

                  {argStr && (
                    <Typography
                      variant="caption"
                      sx={{
                        display: "block",
                        color: "text.secondary",
                        fontFamily: "monospace",
                        fontSize: "0.6875rem",
                        mt: 0.25,
                        wordBreak: "break-all",
                      }}
                    >
                      {argStr}
                    </Typography>
                  )}
                </Box>
              </Box>
            );
          })}
        </Box>
      </AccordionDetails>
    </Accordion>
  );
}

export default ReasoningTimeline;
