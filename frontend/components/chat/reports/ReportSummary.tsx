/**
 * Report summary component.
 *
 * Displays overview summary with quick stats about recommendations,
 * estimated improvements, and quick wins count.
 */

"use client";

import React from "react";
import { Box, Paper, Typography, Grid } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import BoltIcon from "@mui/icons-material/Bolt";
import TargetIcon from "@mui/icons-material/GpsFixed";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import SavingsIcon from "@mui/icons-material/Savings";

export interface ReportSummaryMetadata {
  /** Total number of recommendations */
  total_recommendations: number;
  /** Estimated performance improvement */
  estimated_improvement?: string;
  /** Estimated cost reduction */
  cost_reduction?: string;
  /** Number of quick wins (high impact, low effort) */
  quick_wins_count?: number;
}

interface ReportSummaryProps {
  /** Summary text overview */
  summary: string;
  /** Optional metadata with stats */
  metadata?: ReportSummaryMetadata;
}

/**
 * Report summary card with overview and key metrics.
 *
 * @example
 * ```tsx
 * <ReportSummary
 *   summary="This query has 4 optimization opportunities..."
 *   metadata={{
 *     total_recommendations: 4,
 *     estimated_improvement: "25% faster",
 *     quick_wins_count: 2
 *   }}
 * />
 * ```
 */
export function ReportSummary({ summary, metadata }: ReportSummaryProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2.5,
        bgcolor: isDark
          ? "rgba(33, 150, 243, 0.08)"
          : "rgba(33, 150, 243, 0.04)",
        border: 1,
        borderColor: isDark
          ? "rgba(33, 150, 243, 0.2)"
          : "rgba(33, 150, 243, 0.15)",
        borderRadius: 2,
        mb: 3,
      }}
    >
      {/* Summary Header */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1.5 }}>
        <Typography component="span" sx={{ fontSize: "1.25rem" }}>
          📋
        </Typography>
        <Typography
          variant="subtitle1"
          sx={{
            fontWeight: 600,
            color: isDark ? "primary.light" : "primary.dark",
          }}
        >
          Summary
        </Typography>
      </Box>

      {/* Summary Text */}
      <Typography
        variant="body1"
        sx={{
          color: "text.primary",
          lineHeight: 1.6,
          mb: metadata ? 2.5 : 0,
        }}
      >
        {summary}
      </Typography>

      {/* Stats Grid */}
      {metadata && (
        <Grid container spacing={2}>
          {/* Quick Wins */}
          {metadata.quick_wins_count !== undefined && metadata.quick_wins_count > 0 && (
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatCard
                icon={<BoltIcon sx={{ color: "warning.main" }} />}
                label="Quick Wins"
                value={`${metadata.quick_wins_count}`}
                sublabel="recommendations"
                isDark={isDark}
              />
            </Grid>
          )}

          {/* Total Recommendations */}
          <Grid size={{ xs: 6, sm: 3 }}>
            <StatCard
              icon={<TargetIcon sx={{ color: "primary.main" }} />}
              label="Total"
              value={`${metadata.total_recommendations}`}
              sublabel="recommendations"
              isDark={isDark}
            />
          </Grid>

          {/* Estimated Improvement */}
          {metadata.estimated_improvement && (
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatCard
                icon={<TrendingUpIcon sx={{ color: "success.main" }} />}
                label="Est. Impact"
                value={metadata.estimated_improvement}
                sublabel="faster"
                isDark={isDark}
              />
            </Grid>
          )}

          {/* Cost Reduction */}
          {metadata.cost_reduction && (
            <Grid size={{ xs: 6, sm: 3 }}>
              <StatCard
                icon={<SavingsIcon sx={{ color: "success.main" }} />}
                label="Cost Savings"
                value={metadata.cost_reduction}
                sublabel="reduction"
                isDark={isDark}
              />
            </Grid>
          )}
        </Grid>
      )}
    </Paper>
  );
}

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  sublabel: string;
  isDark: boolean;
}

function StatCard({ icon, label, value, sublabel, isDark }: StatCardProps) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "flex-start",
        gap: 1.5,
        p: 1.5,
        bgcolor: isDark ? "rgba(255,255,255,0.05)" : "background.paper",
        borderRadius: 1.5,
        border: 1,
        borderColor: "divider",
      }}
    >
      <Box sx={{ mt: 0.25 }}>{icon}</Box>
      <Box>
        <Typography
          variant="caption"
          sx={{ color: "text.secondary", fontWeight: 500 }}
        >
          {label}
        </Typography>
        <Typography
          variant="h6"
          sx={{
            fontWeight: 700,
            color: "text.primary",
            lineHeight: 1.2,
          }}
        >
          {value}
        </Typography>
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {sublabel}
        </Typography>
      </Box>
    </Box>
  );
}

export default ReportSummary;

