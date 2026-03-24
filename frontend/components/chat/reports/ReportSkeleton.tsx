/**
 * Report skeleton loading component.
 *
 * Provides a better perceived loading experience by showing skeleton
 * UI elements that match the shape of the actual report content.
 * Uses Material-UI Skeleton components for smooth animations.
 */

"use client";

import React from "react";
import { Box, Paper, Skeleton, useTheme } from "@mui/material";

interface ReportSkeletonProps {
  /** Report type to customize skeleton shape */
  variant?: "advisor" | "analytics" | "default";
}

/**
 * Skeleton for advisor/performance optimization reports.
 * Shows placeholders for summary, findings, and recommendations.
 */
function AdvisorReportSkeleton() {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Paper
      elevation={2}
      sx={{
        p: 2,
        bgcolor: isDark ? "rgba(76, 175, 80, 0.08)" : "rgba(76, 175, 80, 0.04)",
        borderRadius: 2,
        borderLeft: `4px solid ${theme.palette.success.main}`,
        width: "100%",
        maxWidth: 800,
      }}
    >
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
        <Skeleton variant="circular" width={40} height={40} sx={{ mr: 1.5 }} />
        <Box sx={{ flex: 1 }}>
          <Skeleton variant="text" width="60%" height={28} />
          <Skeleton variant="text" width="40%" height={20} />
        </Box>
      </Box>

      {/* Summary section */}
      <Skeleton variant="text" width="100%" height={20} />
      <Skeleton variant="text" width="95%" height={20} />
      <Skeleton variant="text" width="80%" height={20} sx={{ mb: 2 }} />

      {/* Findings cards */}
      {[1, 2, 3].map((i) => (
        <Box
          key={i}
          sx={{
            mb: 1.5,
            p: 1.5,
            borderRadius: 1,
            bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
          }}
        >
          <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
            <Skeleton variant="rounded" width={60} height={24} sx={{ mr: 1 }} />
            <Skeleton variant="text" width="50%" height={24} />
          </Box>
          <Skeleton variant="text" width="90%" height={18} />
          <Skeleton variant="text" width="70%" height={18} />
        </Box>
      ))}

      {/* Footer with buttons */}
      <Box sx={{ display: "flex", gap: 1, mt: 2 }}>
        <Skeleton variant="rounded" width={100} height={36} />
        <Skeleton variant="rounded" width={100} height={36} />
      </Box>
    </Paper>
  );
}

/**
 * Skeleton for analytics/FinOps reports.
 * Shows placeholders for cost summary, trends, and optimization opportunities.
 */
function AnalyticsReportSkeleton() {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Paper
      elevation={2}
      sx={{
        p: 2,
        bgcolor: isDark ? "rgba(33, 150, 243, 0.08)" : "rgba(33, 150, 243, 0.04)",
        borderRadius: 2,
        borderLeft: `4px solid ${theme.palette.info.main}`,
        width: "100%",
        maxWidth: 800,
      }}
    >
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
        <Skeleton variant="circular" width={40} height={40} sx={{ mr: 1.5 }} />
        <Box sx={{ flex: 1 }}>
          <Skeleton variant="text" width="50%" height={28} />
          <Skeleton variant="text" width="35%" height={20} />
        </Box>
      </Box>

      {/* Cost summary cards */}
      <Box sx={{ display: "flex", gap: 2, mb: 3 }}>
        {[1, 2, 3].map((i) => (
          <Box
            key={i}
            sx={{
              flex: 1,
              p: 1.5,
              borderRadius: 1,
              bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
            }}
          >
            <Skeleton variant="text" width="60%" height={16} />
            <Skeleton variant="text" width="80%" height={32} />
            <Skeleton variant="text" width="40%" height={14} />
          </Box>
        ))}
      </Box>

      {/* Chart placeholder */}
      <Skeleton
        variant="rounded"
        width="100%"
        height={200}
        sx={{ mb: 2, borderRadius: 1 }}
      />

      {/* Findings list */}
      <Skeleton variant="text" width="30%" height={24} sx={{ mb: 1 }} />
      {[1, 2].map((i) => (
        <Box
          key={i}
          sx={{
            mb: 1,
            p: 1.5,
            borderRadius: 1,
            bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
          }}
        >
          <Skeleton variant="text" width="60%" height={20} />
          <Skeleton variant="text" width="85%" height={16} />
        </Box>
      ))}

      {/* Footer */}
      <Box sx={{ display: "flex", gap: 1, mt: 2 }}>
        <Skeleton variant="rounded" width={100} height={36} />
        <Skeleton variant="rounded" width={100} height={36} />
      </Box>
    </Paper>
  );
}

/**
 * Default skeleton for generic reports.
 * Simple structure with header, content, and footer.
 */
function DefaultReportSkeleton() {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Paper
      elevation={2}
      sx={{
        p: 2,
        bgcolor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.02)",
        borderRadius: 2,
        width: "100%",
        maxWidth: 800,
      }}
    >
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center", mb: 2 }}>
        <Skeleton variant="circular" width={32} height={32} sx={{ mr: 1.5 }} />
        <Skeleton variant="text" width="50%" height={24} />
      </Box>

      {/* Content lines */}
      <Skeleton variant="text" width="100%" height={20} />
      <Skeleton variant="text" width="95%" height={20} />
      <Skeleton variant="text" width="90%" height={20} />
      <Skeleton variant="text" width="85%" height={20} />
      <Skeleton variant="text" width="60%" height={20} sx={{ mb: 2 }} />

      {/* Code block placeholder */}
      <Skeleton
        variant="rounded"
        width="100%"
        height={80}
        sx={{ mb: 2, borderRadius: 1 }}
      />

      {/* More content */}
      <Skeleton variant="text" width="100%" height={20} />
      <Skeleton variant="text" width="75%" height={20} sx={{ mb: 2 }} />

      {/* Footer */}
      <Box sx={{ display: "flex", gap: 1 }}>
        <Skeleton variant="rounded" width={80} height={32} />
        <Skeleton variant="rounded" width={80} height={32} />
      </Box>
    </Paper>
  );
}

/**
 * Report skeleton component.
 *
 * Displays a loading skeleton that matches the shape of the expected
 * report content. Provides better perceived performance than a spinner.
 *
 * @param props - Component props
 * @returns Skeleton loading UI
 *
 * @example
 * // Advisor report skeleton
 * <ReportSkeleton variant="advisor" />
 *
 * @example
 * // Analytics report skeleton
 * <ReportSkeleton variant="analytics" />
 *
 * @example
 * // Default skeleton
 * <ReportSkeleton />
 */
export function ReportSkeleton({ variant = "default" }: ReportSkeletonProps) {
  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "flex-start",
        mb: 2,
        px: 2,
      }}
    >
      <Box
        sx={{
          display: "flex",
          gap: 1,
          maxWidth: "85%",
          flexDirection: "row",
          width: "100%",
        }}
      >
        {/* Avatar skeleton */}
        <Skeleton
          variant="circular"
          width={32}
          height={32}
          sx={{ flexShrink: 0 }}
        />

        {/* Report content skeleton */}
        {variant === "advisor" && <AdvisorReportSkeleton />}
        {variant === "analytics" && <AnalyticsReportSkeleton />}
        {variant === "default" && <DefaultReportSkeleton />}
      </Box>
    </Box>
  );
}

export default ReportSkeleton;

