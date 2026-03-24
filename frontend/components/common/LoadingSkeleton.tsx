/**
 * LoadingSkeleton component.
 *
 * Displays skeleton loaders for different content types.
 */

"use client";

import React from "react";
import { Box, Skeleton } from "@mui/material";

interface LoadingSkeletonProps {
  variant?: "message" | "conversation" | "chat";
  count?: number;
}

/**
 * Loading skeleton component.
 *
 * Shows placeholder skeletons while content is loading.
 *
 * @param props - Component props
 * @returns Loading skeleton component
 *
 * @example
 * ```tsx
 * <LoadingSkeleton variant="message" count={3} />
 * ```
 */
export function LoadingSkeleton({
  variant = "message",
  count = 3,
}: LoadingSkeletonProps) {
  if (variant === "message") {
    return (
      <Box sx={{ px: 2, py: 1 }}>
        {Array.from({ length: count }).map((_, i) => (
          <Box
            key={i}
            sx={{
              display: "flex",
              gap: 1,
              mb: 2,
              flexDirection: i % 2 === 0 ? "row" : "row-reverse",
            }}
          >
            <Skeleton variant="circular" width={32} height={32} />
            <Box sx={{ flex: 1, maxWidth: "70%" }}>
              <Skeleton variant="rounded" height={60} />
              <Skeleton variant="text" width="30%" sx={{ mt: 0.5 }} />
            </Box>
          </Box>
        ))}
      </Box>
    );
  }

  if (variant === "conversation") {
    return (
      <Box sx={{ px: 2 }}>
        {Array.from({ length: count }).map((_, i) => (
          <Box key={i} sx={{ mb: 1 }}>
            <Skeleton variant="rounded" height={56} />
          </Box>
        ))}
      </Box>
    );
  }

  if (variant === "chat") {
    return (
      <Box sx={{ display: "flex", height: "100vh" }}>
        <Box sx={{ width: 280, p: 2 }}>
          <Skeleton variant="rounded" height={40} sx={{ mb: 2 }} />
          <Skeleton variant="rounded" height={48} sx={{ mb: 2 }} />
          <LoadingSkeleton variant="conversation" count={5} />
        </Box>
        <Box sx={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <Skeleton variant="rectangular" height={64} />
          <Box sx={{ flex: 1, p: 2 }}>
            <LoadingSkeleton variant="message" count={4} />
          </Box>
          <Skeleton variant="rectangular" height={80} />
        </Box>
      </Box>
    );
  }

  return null;
}

