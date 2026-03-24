/**
 * TokenDisplay component.
 *
 * Displays token usage and estimated cost as a compact MUI Chip.
 * Shows a tooltip with full breakdown: model, input tokens, output tokens.
 *
 * Returns null when no token or cost data is available.
 */

"use client";

import React from "react";
import { Chip, Tooltip, Box, Typography } from "@mui/material";

export interface TokenDisplayProps {
  /** Input (prompt) tokens consumed */
  inputTokens?: number;
  /** Output (completion) tokens consumed */
  outputTokens?: number;
  /** Total tokens (if explicitly provided by the backend) */
  totalTokens?: number;
  /** Estimated cost in USD */
  estimatedCostUsd?: number;
  /** Model name (e.g. "claude-sonnet-4-5") */
  model?: string;
}

/**
 * Compute the effective total to display.
 * Prefers explicit totalTokens; falls back to input+output sum.
 */
function computeDisplayTotal(
  totalTokens?: number,
  inputTokens?: number,
  outputTokens?: number
): number | undefined {
  if (typeof totalTokens === "number" && totalTokens > 0) {
    return totalTokens;
  }
  const input = inputTokens ?? 0;
  const output = outputTokens ?? 0;
  const sum = input + output;
  return sum > 0 ? sum : undefined;
}

/**
 * Build the chip label text.
 * Format: "{N,NNN tokens}" or "${cost}" or "{N,NNN tokens · $cost}".
 */
function buildLabel(displayTotal?: number, estimatedCostUsd?: number): string {
  const tokenPart =
    typeof displayTotal === "number"
      ? `${displayTotal.toLocaleString()} tokens`
      : undefined;
  const costPart =
    typeof estimatedCostUsd === "number"
      ? `$${estimatedCostUsd.toFixed(4)}`
      : undefined;

  if (tokenPart && costPart) {
    return `${tokenPart} · ${costPart}`;
  }
  return tokenPart ?? costPart ?? "";
}

/**
 * Tooltip content showing the full token breakdown.
 */
function TooltipContent({
  model,
  inputTokens,
  outputTokens,
  displayTotal,
  estimatedCostUsd,
}: {
  model?: string;
  inputTokens?: number;
  outputTokens?: number;
  displayTotal?: number;
  estimatedCostUsd?: number;
}) {
  return (
    <Box sx={{ p: 0.5 }}>
      {model && (
        <Typography variant="caption" display="block" sx={{ fontWeight: 600 }}>
          {model}
        </Typography>
      )}
      {typeof inputTokens === "number" && (
        <Typography variant="caption" display="block">
          Input: {inputTokens.toLocaleString()} tokens
        </Typography>
      )}
      {typeof outputTokens === "number" && (
        <Typography variant="caption" display="block">
          Output: {outputTokens.toLocaleString()} tokens
        </Typography>
      )}
      {typeof displayTotal === "number" && (
        <Typography variant="caption" display="block">
          Total: {displayTotal.toLocaleString()} tokens
        </Typography>
      )}
      {typeof estimatedCostUsd === "number" && (
        <Typography variant="caption" display="block">
          Cost: ${estimatedCostUsd.toFixed(4)}
        </Typography>
      )}
    </Box>
  );
}

/**
 * TokenDisplay component.
 *
 * @param props - Token usage and cost data
 * @returns A compact chip showing token/cost summary, or null if no data
 *
 * @example
 * ```tsx
 * <TokenDisplay
 *   inputTokens={800}
 *   outputTokens={200}
 *   totalTokens={1000}
 *   estimatedCostUsd={0.002}
 *   model="claude-sonnet-4-5"
 * />
 * ```
 */
export function TokenDisplay({
  inputTokens,
  outputTokens,
  totalTokens,
  estimatedCostUsd,
  model,
}: TokenDisplayProps) {
  const displayTotal = computeDisplayTotal(totalTokens, inputTokens, outputTokens);
  const hasCost = typeof estimatedCostUsd === "number";

  // Render nothing if there is no data to show
  if (!displayTotal && !hasCost) {
    return null;
  }

  const label = buildLabel(displayTotal, estimatedCostUsd);

  return (
    <Tooltip
      title={
        <TooltipContent
          model={model}
          inputTokens={inputTokens}
          outputTokens={outputTokens}
          displayTotal={displayTotal}
          estimatedCostUsd={estimatedCostUsd}
        />
      }
      arrow
      placement="top"
    >
      <Chip
        label={label}
        size="small"
        variant="outlined"
        sx={{
          height: 20,
          fontSize: "0.7rem",
          color: "text.secondary",
          borderColor: "divider",
          cursor: "default",
          "& .MuiChip-label": {
            px: 1,
          },
        }}
      />
    </Tooltip>
  );
}
