/**
 * CodeBlockSkeleton component.
 *
 * Loading placeholder shown while CodeBlockWithActions lazy-loads.
 * Mimics the code block header + line structure.
 */

"use client";

import React from "react";
import { Box, Skeleton, Paper } from "@mui/material";

export interface CodeBlockSkeletonProps {
  /** Number of skeleton lines to render (default: 4) */
  lines?: number;
}

/**
 * Skeleton placeholder for code blocks while the Shiki bundle loads.
 *
 * @example
 * ```tsx
 * <Suspense fallback={<CodeBlockSkeleton lines={6} />}>
 *   <LazyCodeBlock ... />
 * </Suspense>
 * ```
 */
export function CodeBlockSkeleton({ lines = 4 }: CodeBlockSkeletonProps) {
  // Generate varying widths to look like real code lines
  const lineWidths = ["75%", "55%", "90%", "40%", "65%", "80%"];

  return (
    <Paper
      data-testid="code-block-skeleton"
      elevation={0}
      sx={{
        my: 2,
        borderRadius: 2,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
      }}
    >
      {/* Header skeleton */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1,
          borderBottom: 1,
          borderColor: "divider",
          bgcolor: "action.hover",
        }}
      >
        <Skeleton variant="text" width={48} height={18} />
        <Box sx={{ display: "flex", gap: 0.5 }}>
          <Skeleton variant="circular" width={24} height={24} />
          <Skeleton variant="circular" width={24} height={24} />
        </Box>
      </Box>

      {/* Code lines skeleton */}
      <Box sx={{ p: 2 }}>
        {Array.from({ length: lines }, (_, i) => (
          <Skeleton
            key={i}
            variant="text"
            width={lineWidths[i % lineWidths.length]}
            height={20}
            sx={{ mb: 0.5, fontFamily: "monospace" }}
          />
        ))}
      </Box>
    </Paper>
  );
}
