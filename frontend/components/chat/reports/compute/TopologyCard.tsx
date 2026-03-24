/**
 * Topology analysis card for compute reports.
 * 
 * Displays workload clusters and consolidation opportunities.
 */

"use client";

import React from "react";
import { Box, Typography, Paper, Chip, Divider, useTheme } from "@mui/material";
import type { TopologyAnalysis, WorkloadCluster, ConsolidationOpportunity } from "@/lib/types/api";

interface TopologyCardProps {
  topology: TopologyAnalysis;
}

const confidenceColors = {
  high: "#4caf50",
  medium: "#ff9800",
  low: "#9e9e9e",
} as const;

function ClusterCard({ cluster }: { cluster: WorkloadCluster }) {
  const theme = useTheme();
  const similarityPct = Math.round(cluster.similarity_score * 100);

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        mb: 1,
        bgcolor: theme.palette.mode === "dark"
          ? "rgba(255, 255, 255, 0.02)"
          : "rgba(0, 0, 0, 0.02)",
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="subtitle2" fontWeight={600}>
          {cluster.name}
        </Typography>
        <Chip
          label={`${similarityPct}% similar`}
          size="small"
          sx={{
            bgcolor: similarityPct >= 80 ? "#4caf50" : similarityPct >= 60 ? "#ff9800" : "#9e9e9e",
            color: "white",
            fontSize: "0.7rem",
          }}
        />
      </Box>
      <Typography variant="caption" color="text.secondary">
        {cluster.resources.length} resources: {cluster.resources.slice(0, 3).join(", ")}
        {cluster.resources.length > 3 && ` +${cluster.resources.length - 3} more`}
      </Typography>
    </Paper>
  );
}

function OpportunityCard({ opportunity }: { opportunity: ConsolidationOpportunity }) {
  const theme = useTheme();

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        mb: 1,
        borderLeft: `3px solid ${confidenceColors[opportunity.confidence]}`,
        bgcolor: theme.palette.mode === "dark"
          ? "rgba(76, 175, 80, 0.05)"
          : "rgba(76, 175, 80, 0.02)",
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", mb: 1 }}>
        <Typography variant="body2" fontWeight={500}>
          {opportunity.recommendation}
        </Typography>
        <Chip
          label={`${opportunity.estimated_savings_pct.toFixed(0)}% savings`}
          size="small"
          color="success"
          sx={{ ml: 1, fontWeight: 600 }}
        />
      </Box>
      <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
        <Typography variant="caption" color="text.secondary">
          Sources: {opportunity.source_resources.join(", ")}
        </Typography>
        {opportunity.target_resource && (
          <>
            <Typography variant="caption" color="text.secondary">→</Typography>
            <Typography variant="caption" color="text.secondary">
              Target: {opportunity.target_resource}
            </Typography>
          </>
        )}
      </Box>
      <Box sx={{ mt: 0.5 }}>
        <Chip
          label={opportunity.confidence}
          size="small"
          variant="outlined"
          sx={{
            fontSize: "0.65rem",
            height: 18,
            color: confidenceColors[opportunity.confidence],
            borderColor: confidenceColors[opportunity.confidence],
          }}
        />
      </Box>
    </Paper>
  );
}

export function TopologyCard({ topology }: TopologyCardProps) {
  const hasClusters = topology.clusters && topology.clusters.length > 0;
  const hasOpportunities = topology.consolidation_opportunities && topology.consolidation_opportunities.length > 0;

  if (!hasClusters && !hasOpportunities) {
    return (
      <Box sx={{ mb: 3 }}>
        <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
          🔗 Topology Analysis
        </Typography>
        <Typography variant="body2" color="text.secondary">
          No workload clusters or consolidation opportunities identified.
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
        🔗 Topology Analysis
      </Typography>

      {/* Workload clusters */}
      {hasClusters && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Workload Clusters ({topology.clusters!.length})
          </Typography>
          {topology.clusters!.map((cluster) => (
            <ClusterCard key={cluster.id} cluster={cluster} />
          ))}
        </Box>
      )}

      {hasClusters && hasOpportunities && <Divider sx={{ my: 2 }} />}

      {/* Consolidation opportunities */}
      {hasOpportunities && (
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            💡 Consolidation Opportunities ({topology.consolidation_opportunities!.length})
          </Typography>
          {topology.consolidation_opportunities!.map((opp, idx) => (
            <OpportunityCard key={idx} opportunity={opp} />
          ))}
        </Box>
      )}
    </Box>
  );
}

