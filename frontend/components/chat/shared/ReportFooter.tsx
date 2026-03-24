/**
 * Shared report footer component.
 *
 * Displays report metadata (tokens, cost, duration, steps).
 */

"use client";

import React from "react";
import { Box, Typography, Divider } from "@mui/material";

interface ReportMetadata {
  tokens_used?: number;
  cost_usd?: number;
  duration_seconds?: number;
  steps_taken?: number;
}

interface ReportFooterProps {
  /** Report metadata */
  metadata?: ReportMetadata | null;
}

/**
 * Footer component for all report types.
 *
 * Shows execution metadata consistently across all report types.
 *
 * @param props - Component props
 * @returns Report footer component or null if no metadata
 *
 * @example
 * ```tsx
 * <ReportFooter metadata={{
 *   tokens_used: 12500,
 *   cost_usd: 0.0125,
 *   duration_seconds: 4.2,
 *   steps_taken: 3
 * }} />
 * ```
 */
export function ReportFooter({ metadata }: ReportFooterProps) {
  if (!metadata) {
    return null;
  }

  const hasAnyMetadata =
    typeof metadata.tokens_used === "number" ||
    typeof metadata.cost_usd === "number" ||
    typeof metadata.duration_seconds === "number" ||
    typeof metadata.steps_taken === "number";

  if (!hasAnyMetadata) {
    return null;
  }

  return (
    <>
      <Divider sx={{ my: 2 }} />
      <Box
        sx={{
          display: "flex",
          gap: 2,
          flexWrap: "wrap",
          fontSize: "0.85rem",
          color: "text.secondary",
        }}
      >
        {typeof metadata.tokens_used === "number" && (
          <Typography variant="caption">
            <strong>Tokens:</strong> {metadata.tokens_used.toLocaleString()}
          </Typography>
        )}
        {typeof metadata.cost_usd === "number" && (
          <Typography variant="caption">
            <strong>Cost:</strong> ${metadata.cost_usd.toFixed(4)}
          </Typography>
        )}
        {typeof metadata.duration_seconds === "number" && (
          <Typography variant="caption">
            <strong>Duration:</strong> {metadata.duration_seconds.toFixed(1)}s
          </Typography>
        )}
        {typeof metadata.steps_taken === "number" && (
          <Typography variant="caption">
            <strong>Steps:</strong> {metadata.steps_taken}
          </Typography>
        )}
      </Box>
    </>
  );
}

