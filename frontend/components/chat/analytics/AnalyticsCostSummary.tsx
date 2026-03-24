/**
 * Analytics cost summary component.
 *
 * Displays aggregated cost statistics with trend indicators.
 */

"use client";

import React from "react";
import { Box, Typography, Paper } from "@mui/material";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import TrendingFlatIcon from "@mui/icons-material/TrendingFlat";
import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import type { CostSummary } from "@/lib/types/api";

interface AnalyticsCostSummaryProps {
  /** Cost summary data */
  costSummary: CostSummary;
}

/**
 * Cost summary card for analytics reports.
 *
 * Shows total cost, trend direction, period, and top contributors with
 * visual indicators for cost trends.
 *
 * @param props - Component props
 * @returns Cost summary component
 *
 * @example
 * ```tsx
 * <AnalyticsCostSummary
 *   costSummary={{
 *     total_cost: 45234.56,
 *     cost_trend: "increasing",
 *     period: "30 days",
 *     top_contributors: ["warehouse_prod", "job_123"]
 *   }}
 * />
 * ```
 */
export function AnalyticsCostSummary({
  costSummary,
}: AnalyticsCostSummaryProps) {
  const { 
    total = 0, 
    cost_trend, 
    period, 
    top_contributors = [],
    primary_metric_unit = "USD" 
  } = costSummary;

  // Trend icon and color
  const getTrendIcon = () => {
    switch (cost_trend) {
      case "increasing":
        return <TrendingUpIcon fontSize="small" sx={{ color: "error.main" }} />;
      case "decreasing":
        return <TrendingDownIcon fontSize="small" sx={{ color: "success.main" }} />;
      case "stable":
        return <TrendingFlatIcon fontSize="small" sx={{ color: "text.secondary" }} />;
      default:
        return null;
    }
  };

  const getTrendColor = () => {
    switch (cost_trend) {
      case "increasing":
        return "error.main";
      case "decreasing":
        return "success.main";
      case "stable":
        return "text.secondary";
      default:
        return "text.primary";
    }
  };

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        mb: 2,
        bgcolor: "rgba(33, 150, 243, 0.05)",
        border: "1px solid",
        borderColor: "divider",
        borderRadius: 2,
      }}
    >
      <Typography
        variant="h6"
        sx={{
          fontSize: "1rem",
          fontWeight: 600,
          mb: 1.5,
          color: "primary.main",
        }}
      >
        Cost Overview
      </Typography>

      {/* Total Cost */}
      <Box sx={{ mb: 1 }}>
        <Typography variant="body2" color="text.secondary" gutterBottom>
          Total Cost
        </Typography>
        <Typography
          variant="h4"
          sx={{
            fontWeight: 700,
            color: "primary.dark",
          }}
        >
          {primary_metric_unit === "USD" ? "$" : ""}{total.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}{primary_metric_unit === "DBU" ? " DBUs" : ""}
        </Typography>
      </Box>

      {/* Period */}
      {period && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Period: <strong>{period}</strong>
        </Typography>
      )}

      {/* Cost Trend */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, mb: 2 }}>
        {getTrendIcon()}
        <Typography
          variant="body2"
          sx={{
            fontWeight: 600,
            color: getTrendColor(),
            textTransform: "capitalize",
          }}
        >
          {cost_trend}
        </Typography>
      </Box>

      {/* Top Contributors */}
      {top_contributors.length > 0 && (
        <>
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ fontWeight: 600, mb: 0.5 }}
          >
            Top Contributors
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 2 }}>
            {top_contributors.slice(0, 5).map((contributor, index) => {
              // Handle both string and object formats
              if (typeof contributor === 'string') {
                return (
                  <Typography
                    key={index}
                    component="li"
                    variant="body2"
                    sx={{ mb: 0.25 }}
                  >
                    {contributor}
                  </Typography>
                );
              }
              
              // Object format with id, name, value, unit
              const name = contributor?.name || contributor?.id || `Contributor ${index + 1}`;
              const value = contributor?.value;
              const unit = contributor?.unit;
              const displayValue = value !== undefined && unit 
                ? ` - ${unit === 'USD' ? '$' : ''}${value.toLocaleString()}${unit === 'DBU' ? ' DBUs' : ''}`
                : '';
              
              return (
                <Typography
                  key={contributor?.id || index}
                  component="li"
                  variant="body2"
                  sx={{ mb: 0.25 }}
                >
                  {name}{displayValue}
                </Typography>
              );
            })}
          </Box>
        </>
      )}
    </Paper>
  );
}

