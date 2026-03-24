/**
 * ThinkingStepsBubble component.
 *
 * Renders the ThinkingStepsContainer as a separate bubble in the message list.
 * Only shown AFTER the message is complete, providing tool call lineage summary.
 * 
 * Features:
 * - Subtle, de-emphasized visual styling
 * - Renders between thinking content and report
 * - Only shows when message has thinking_steps and is completed
 */

"use client";

import React, { useMemo } from "react";
import { Box, Slide } from "@mui/material";
import { ThinkingStepsContainer, type ThinkingStep } from "./thinking";
import type { Message } from "@/lib/types/api";
import { MessageStatus } from "@/lib/types/api";

/**
 * List of tool names that should be hidden from the UI.
 * These are internal helper tools that don't provide meaningful user-facing info.
 */
const HIDDEN_TOOLS = new Set([
  "complete",
  "request_user_input",
]);

export interface ThinkingStepsBubbleProps {
  /** The message containing thinking steps */
  message: Message;
}

/**
 * Thinking steps bubble displayed after message content.
 *
 * This component renders tool call lineage/summary as a separate,
 * de-emphasized bubble. It only appears after the message is complete.
 *
 * @param props - Component props
 * @returns ThinkingStepsBubble component or null if no steps to show
 *
 * @example
 * ```tsx
 * <ThinkingStepsBubble message={completedMessage} />
 * ```
 */
export function ThinkingStepsBubble({ message }: ThinkingStepsBubbleProps) {
  // Filter visible steps (excludes internal tools)
  // useMemo must be called unconditionally (React Hooks rule)
  const visibleSteps = useMemo(() => {
    if (!message.thinking_steps) return [];
    return message.thinking_steps.filter(
      (step) => !HIDDEN_TOOLS.has(step.id)
    ) as ThinkingStep[];
  }, [message.thinking_steps]);

  // Only show for completed messages with visible steps
  if (message.status !== MessageStatus.COMPLETED) {
    return null;
  }

  // Don't render if no visible steps
  if (visibleSteps.length === 0) {
    return null;
  }

  return (
    <Slide direction="right" in={true} timeout={200} mountOnEnter unmountOnExit>
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-start",
          mb: 2,
          px: 2,
          // Indent to align with assistant message content (after avatar)
          ml: 6.5, // ~52px to align with message content after 40px avatar + 12px gap
        }}
      >
        <Box
          sx={{
            maxWidth: "65%",
          }}
        >
          <ThinkingStepsContainer
            steps={visibleSteps}
            defaultCollapsed={false}
            title="Tool Calls"
          />
        </Box>
      </Box>
    </Slide>
  );
}

export default ThinkingStepsBubble;
