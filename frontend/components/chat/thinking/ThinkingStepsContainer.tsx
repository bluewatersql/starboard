/**
 * Thinking steps container component.
 *
 * Displays tool call lineage and summary AFTER message completion.
 * Uses subtle, de-emphasized styling to avoid distracting from main content.
 * 
 * Features:
 * - 3-level detail hierarchy (steps → sub-tasks → call details)
 * - Defaults to expanded at first level
 * - Subtle visual styling that adapts to theme
 */

"use client";

import React, { useState, useCallback } from "react";
import { Box, Paper, Typography, IconButton } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import { useTheme } from "@mui/material/styles";
import { ThinkingStepEnhanced, ThinkingStep } from "./ThinkingStepEnhanced";

interface ThinkingStepsContainerProps {
  /** Array of thinking steps to display */
  steps: ThinkingStep[];
  /** Whether to show the container in collapsed state initially */
  defaultCollapsed?: boolean;
  /** Maximum height before scrolling */
  maxHeight?: string | number;
  /** Title for the thinking section */
  title?: string;
}

/**
 * Container for displaying multiple thinking steps.
 * 
 * This component is rendered as a separate bubble AFTER the message
 * content is complete. It preserves lineage and summarizes tool calls
 * for the conversation context.
 *
 * @example
 * ```tsx
 * <ThinkingStepsContainer
 *   steps={[
 *     { id: "1", title: "Resolving Query", status: "completed", ... },
 *     { id: "2", title: "Analyzing Plan", status: "completed", ... },
 *   ]}
 * />
 * ```
 */
export function ThinkingStepsContainer({
  steps,
  defaultCollapsed = false,
  maxHeight = 400,
  title = "Tool Calls",
}: ThinkingStepsContainerProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  
  // Count completed steps
  const completedCount = steps.filter((s) => s.status === "completed").length;
  const totalCount = steps.length;

  // Handle step expand toggle
  const handleToggleStep = useCallback((stepId: string, expanded: boolean) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (expanded) {
        next.add(stepId);
      } else {
        next.delete(stepId);
      }
      return next;
    });
  }, []);

  // Calculate total duration
  const totalDuration = React.useMemo(() => {
    const completedSteps = steps.filter(
      (s) => s.status === "completed" && s.startTime && s.endTime
    );
    if (completedSteps.length === 0) return null;

    const totalMs = completedSteps.reduce(
      (sum, s) => sum + (s.endTime! - s.startTime!),
      0
    );
    return (totalMs / 1000).toFixed(2);
  }, [steps]);

  if (steps.length === 0) {
    return null;
  }
  
  return (
    <Paper
      elevation={0}
      sx={{
        width: "100%",
        // Subtle border - de-emphasized
        border: 1,
        borderColor: isDark 
          ? "rgba(255, 255, 255, 0.08)" 
          : "rgba(0, 0, 0, 0.08)",
        borderRadius: 2,
        overflow: "hidden",
        // De-emphasized background
        bgcolor: isDark
          ? "rgba(255, 255, 255, 0.02)"
          : "rgba(0, 0, 0, 0.01)",
      }}
    >
      {/* Header - subtle styling */}
      <Box
        onClick={() => setCollapsed(!collapsed)}
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 1.5,
          py: 1,
          cursor: "pointer",
          transition: "background-color 0.2s ease",
          "&:hover": {
            bgcolor: isDark
              ? "rgba(255, 255, 255, 0.04)"
              : "rgba(0, 0, 0, 0.02)",
          },
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <AccountTreeOutlinedIcon
            sx={{
              fontSize: 16,
              color: isDark 
                ? "rgba(255, 255, 255, 0.4)" 
                : "rgba(0, 0, 0, 0.35)",
            }}
          />
          <Typography
            variant="caption"
            sx={{
              fontWeight: 500,
              color: isDark 
                ? "rgba(255, 255, 255, 0.5)" 
                : "rgba(0, 0, 0, 0.45)",
              letterSpacing: "0.02em",
            }}
          >
            {title}
          </Typography>

          {/* Count indicator */}
          <Typography
            variant="caption"
            sx={{
              color: isDark 
                ? "rgba(255, 255, 255, 0.35)" 
                : "rgba(0, 0, 0, 0.3)",
              fontFamily: "monospace",
              fontSize: "0.7rem",
            }}
          >
            ({completedCount}/{totalCount})
          </Typography>

          {/* Total duration */}
          {totalDuration && (
            <Typography
              variant="caption"
              sx={{
                color: isDark 
                  ? "rgba(255, 255, 255, 0.3)" 
                  : "rgba(0, 0, 0, 0.25)",
                fontFamily: "monospace",
                fontSize: "0.7rem",
              }}
            >
              • {totalDuration}s
            </Typography>
          )}
        </Box>

        <IconButton
          size="small"
          aria-label={collapsed ? "Expand tool calls" : "Collapse tool calls"}
          sx={{ 
            p: 0.25,
            color: isDark 
              ? "rgba(255, 255, 255, 0.3)" 
              : "rgba(0, 0, 0, 0.25)",
          }}
        >
          {collapsed ? (
            <ExpandMoreIcon sx={{ fontSize: 18 }} />
          ) : (
            <ExpandLessIcon sx={{ fontSize: 18 }} />
          )}
        </IconButton>
      </Box>

      {/* Steps content */}
      {!collapsed && (
        <Box
          sx={{
            px: 1.5,
            py: 1,
            maxHeight,
            overflowY: "auto",
            borderTop: 1,
            borderColor: isDark 
              ? "rgba(255, 255, 255, 0.06)" 
              : "rgba(0, 0, 0, 0.05)",
            // Subtle fade-in
            animation: "fadeIn 0.15s ease-out",
            "@keyframes fadeIn": {
              from: { opacity: 0 },
              to: { opacity: 1 },
            },
          }}
          role="list"
          aria-label="Tool call history"
        >
          {steps.map((step) => (
            <ThinkingStepEnhanced
              key={step.id}
              step={step}
              defaultExpanded={expandedSteps.has(step.id)}
              onToggleExpand={handleToggleStep}
            />
          ))}
        </Box>
      )}
    </Paper>
  );
}

export default ThinkingStepsContainer;
