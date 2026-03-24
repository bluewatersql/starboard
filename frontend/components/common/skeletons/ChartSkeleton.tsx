/**
 * ChartSkeleton component.
 *
 * Loading placeholder shown while VisualizationPanel lazy-loads.
 * Matches the approximate dimensions of the chart/table toggle UI.
 */

"use client";

import React from "react";
import { Box, Skeleton } from "@mui/material";

export interface ChartSkeletonProps {
  /** Height of the chart area in pixels (default: 300) */
  height?: number;
}

/**
 * Skeleton placeholder for charts while the visualization bundle loads.
 *
 * @example
 * ```tsx
 * <Suspense fallback={<ChartSkeleton height={300} />}>
 *   <LazyVisualizationPanel ... />
 * </Suspense>
 * ```
 */
export function ChartSkeleton({ height = 300 }: ChartSkeletonProps) {
  return (
    <Box
      data-testid="chart-skeleton"
      sx={{
        border: 1,
        borderColor: "divider",
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      {/* Header bar skeleton */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1.5,
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Skeleton variant="text" width={120} height={20} />
        <Box sx={{ display: "flex", gap: 1 }}>
          <Skeleton variant="rounded" width={60} height={28} />
          <Skeleton variant="rounded" width={60} height={28} />
        </Box>
      </Box>

      {/* Chart area skeleton */}
      <Box sx={{ p: 2 }}>
        <Skeleton
          variant="rectangular"
          width="100%"
          height={height}
          sx={{ borderRadius: 1 }}
        />
      </Box>
    </Box>
  );
}
