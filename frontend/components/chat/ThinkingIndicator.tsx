/**
 * ThinkingIndicator component.
 *
 * Shows inline visual feedback when the agent is thinking/working.
 * Displays "Thinking ..." with animated ellipsis during processing,
 * then transitions to "Thought for Xs" when complete.
 *
 * @module components/chat/ThinkingIndicator
 */

"use client";

import React, { useState, useEffect, useRef } from "react";
import { Box, Typography } from "@mui/material";
import { useTheme } from "@mui/material/styles";

export type ThinkingState = "idle" | "thinking" | "completed";

export interface ThinkingIndicatorProps {
  /** Current state: idle, thinking, or completed */
  state: ThinkingState;
  /** Duration in seconds (shown when completed) */
  durationSeconds?: number;
  /** When thinking started (for live duration counter) */
  startTime?: number;
  /** Title/name of current step (e.g., "Generating Analysis") */
  stepTitle?: string;
}

/**
 * Inline thinking indicator with animated ellipsis.
 *
 * Shows:
 * - "Thinking ..." with animated dots when thinking
 * - "Thought for Xs" when completed
 * - Nothing when idle
 *
 * Uses de-emphasized styling to avoid distracting from content.
 *
 * @param props - Component props
 * @returns ThinkingIndicator component
 *
 * @example
 * ```tsx
 * // While thinking
 * <ThinkingIndicator state="thinking" startTime={Date.now()} />
 *
 * // After thought complete
 * <ThinkingIndicator state="completed" durationSeconds={5} />
 * ```
 */
export function ThinkingIndicator({
  state,
  durationSeconds,
  startTime,
  stepTitle,
}: ThinkingIndicatorProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const [elapsed, setElapsed] = useState(0);
  const startTimeRef = useRef(startTime);

  // Update ref when startTime changes
  useEffect(() => {
    startTimeRef.current = startTime;
  }, [startTime]);

  // Update elapsed time every second while thinking
  useEffect(() => {
    if (state !== "thinking" || !startTimeRef.current) {
      return;
    }

    // Use callback form of setElapsed with captured ref
    const updateElapsed = () => {
      if (startTimeRef.current) {
        const now = Date.now();
        setElapsed(Math.floor((now - startTimeRef.current) / 1000));
      }
    };

    // Initial update
    updateElapsed();

    const interval = setInterval(updateElapsed, 1000);

    return () => clearInterval(interval);
  }, [state]);

  if (state === "idle") {
    return null;
  }

  const baseColor = isDark
    ? "rgba(255, 255, 255, 0.45)"
    : "rgba(0, 0, 0, 0.4)";

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 0.75,
        my: 1.5,
        color: baseColor,
        fontSize: "0.85rem",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {state === "thinking" && (
        <>
          <EllipsisSpinner />
          <Typography
            variant="body2"
            component="span"
            sx={{
              color: "inherit",
              fontSize: "inherit",
              fontStyle: "italic",
            }}
          >
            {stepTitle || "Thinking"}{elapsed > 0 ? ` (${elapsed}s)` : ""}
          </Typography>
        </>
      )}

      {state === "completed" && durationSeconds !== undefined && (
        <Typography
          variant="body2"
          component="span"
          sx={{
            color: "inherit",
            fontSize: "inherit",
            fontStyle: "italic",
          }}
        >
          Thought for {durationSeconds}s
        </Typography>
      )}
    </Box>
  );
}

/**
 * Animated ellipsis spinner (three dots).
 * Each dot fades in and out in sequence.
 */
function EllipsisSpinner() {
  return (
    <Box
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: "3px",
        "& span": {
          width: 4,
          height: 4,
          borderRadius: "50%",
          bgcolor: "currentColor",
          animation: "ellipsisAnim 1.4s infinite ease-in-out",
        },
        "& span:nth-of-type(1)": { animationDelay: "0s" },
        "& span:nth-of-type(2)": { animationDelay: "0.2s" },
        "& span:nth-of-type(3)": { animationDelay: "0.4s" },
        "@keyframes ellipsisAnim": {
          "0%, 80%, 100%": { opacity: 0.2 },
          "40%": { opacity: 1 },
        },
      }}
    >
      <span />
      <span />
      <span />
    </Box>
  );
}

export default ThinkingIndicator;

