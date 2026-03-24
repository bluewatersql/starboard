/**
 * ConversationListSkeleton component.
 *
 * Loading skeleton for conversation list.
 * Shows placeholder UI while conversations are being fetched.
 */

"use client";

import React from "react";
import { Box, Skeleton } from "@mui/material";

/**
 * Skeleton loading state for conversation list.
 *
 * Displays animated placeholders that match the size/shape
 * of actual conversation items for a smooth loading experience.
 *
 * @returns Skeleton component
 *
 * @example
 * ```tsx
 * {isLoading && !cachedData && <ConversationListSkeleton />}
 * ```
 */
export function ConversationListSkeleton() {
  return (
    <Box sx={{ px: 2, py: 1 }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <Box
          key={i}
          sx={{
            mb: 1,
            p: 1.5,
            borderRadius: 1,
          }}
        >
          {/* Conversation title */}
          <Skeleton
            variant="text"
            width="80%"
            height={20}
            sx={{ mb: 0.5 }}
          />
          {/* Timestamp */}
          <Skeleton
            variant="text"
            width="40%"
            height={16}
          />
        </Box>
      ))}
    </Box>
  );
}

