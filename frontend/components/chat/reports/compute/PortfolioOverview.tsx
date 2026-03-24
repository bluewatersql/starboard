/**
 * Portfolio overview component for compute reports.
 * 
 * Displays fleet-level summary with health distribution and top resources.
 */

"use client";

import React from "react";
import { Box, Typography, Chip, Paper, Grid, useTheme } from "@mui/material";
import type { PortfolioSummary, ResourceSummary } from "@/lib/types/api";

interface PortfolioOverviewProps {
  portfolio: PortfolioSummary;
}

const healthColors = {
  healthy: "#4caf50",
  warning: "#ff9800",
  critical: "#f44336",
  inactive: "#9e9e9e",
} as const;

const healthIcons = {
  healthy: "🟢",
  warning: "🟡",
  critical: "🔴",
  inactive: "⚪",
} as const;

function ResourceCard({ resource }: { resource: ResourceSummary }) {
  const theme = useTheme();
  const statusColor = healthColors[resource.health_status];

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderLeft: `3px solid ${statusColor}`,
        bgcolor: theme.palette.mode === "dark" 
          ? "rgba(255, 255, 255, 0.02)" 
          : "rgba(0, 0, 0, 0.02)",
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="subtitle2" fontWeight={600}>
          {resource.name}
        </Typography>
        <Chip
          label={`${resource.health_score}/100`}
          size="small"
          sx={{
            bgcolor: statusColor,
            color: "white",
            fontWeight: 600,
            fontSize: "0.75rem",
          }}
        />
      </Box>
      <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
        <Typography variant="caption" color="text.secondary">
          {resource.resource_type}
        </Typography>
        <Typography variant="caption">
          {healthIcons[resource.health_status]} {resource.health_status}
        </Typography>
      </Box>
      {resource.metrics && (
        <Box sx={{ mt: 1 }}>
          {resource.metrics.p95_latency_ms && (
            <Typography variant="caption" color="text.secondary" display="block">
              P95 Latency: {resource.metrics.p95_latency_ms.toFixed(0)}ms
            </Typography>
          )}
          {resource.metrics.query_count && (
            <Typography variant="caption" color="text.secondary" display="block">
              Queries: {resource.metrics.query_count.toLocaleString()}
            </Typography>
          )}
        </Box>
      )}
    </Paper>
  );
}

export function PortfolioOverview({ portfolio }: PortfolioOverviewProps) {
  const { health_distribution, total_count, top_resources } = portfolio;

  // Calculate percentages for progress bar
  const total = total_count || 1;
  const healthyPct = ((health_distribution.healthy || 0) / total) * 100;
  const warningPct = ((health_distribution.warning || 0) / total) * 100;
  const criticalPct = ((health_distribution.critical || 0) / total) * 100;
  const inactivePct = ((health_distribution.inactive || 0) / total) * 100;

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
        📊 Portfolio Overview
      </Typography>

      {/* Total count */}
      <Typography variant="h4" fontWeight={700} sx={{ mb: 1 }}>
        {total_count}
        <Typography component="span" variant="body1" color="text.secondary" sx={{ ml: 1 }}>
          resources
        </Typography>
      </Typography>

      {/* Health distribution bar */}
      <Box sx={{ mb: 2 }}>
        <Box sx={{ display: "flex", height: 8, borderRadius: 1, overflow: "hidden" }}>
          {healthyPct > 0 && (
            <Box sx={{ width: `${healthyPct}%`, bgcolor: healthColors.healthy }} />
          )}
          {warningPct > 0 && (
            <Box sx={{ width: `${warningPct}%`, bgcolor: healthColors.warning }} />
          )}
          {criticalPct > 0 && (
            <Box sx={{ width: `${criticalPct}%`, bgcolor: healthColors.critical }} />
          )}
          {inactivePct > 0 && (
            <Box sx={{ width: `${inactivePct}%`, bgcolor: healthColors.inactive }} />
          )}
        </Box>
      </Box>

      {/* Health distribution legend */}
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, mb: 2 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: healthColors.healthy }} />
          <Typography variant="caption">
            Healthy: {health_distribution.healthy || 0}
          </Typography>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: healthColors.warning }} />
          <Typography variant="caption">
            Warning: {health_distribution.warning || 0}
          </Typography>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: healthColors.critical }} />
          <Typography variant="caption">
            Critical: {health_distribution.critical || 0}
          </Typography>
        </Box>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ width: 12, height: 12, borderRadius: "50%", bgcolor: healthColors.inactive }} />
          <Typography variant="caption">
            Inactive: {health_distribution.inactive || 0}
          </Typography>
        </Box>
      </Box>

      {/* Top resources grid */}
      {top_resources && top_resources.length > 0 && (
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Top Resources
          </Typography>
          <Grid container spacing={1}>
            {top_resources.slice(0, 5).map((resource) => (
              <Grid key={resource.id} size={{ xs: 12, sm: 6 }}>
                <ResourceCard resource={resource} />
              </Grid>
            ))}
          </Grid>
        </Box>
      )}
    </Box>
  );
}

