/**
 * Health gauge component for compute reports.
 * 
 * Displays overall health score with metric breakdown and SLO compliance.
 */

"use client";

import React from "react";
import { Box, Typography, LinearProgress, Paper, Chip } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type { HealthMetrics } from "@/lib/types/api";

interface HealthGaugeProps {
  health: HealthMetrics;
}

function getScoreColor(score: number): string {
  if (score >= 80) return "#4caf50"; // green
  if (score >= 60) return "#ff9800"; // orange
  return "#f44336"; // red
}

function getScoreLabel(score: number): string {
  if (score >= 80) return "Healthy";
  if (score >= 60) return "Warning";
  return "Critical";
}

function MetricBar({ label, score }: { label: string; score: number }) {
  const color = getScoreColor(score);

  return (
    <Box sx={{ mb: 1.5 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
        <Typography variant="caption" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="caption" fontWeight={600} sx={{ color }}>
          {score}/100
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={score}
        sx={{
          height: 6,
          borderRadius: 1,
          bgcolor: "rgba(0, 0, 0, 0.1)",
          "& .MuiLinearProgress-bar": {
            bgcolor: color,
            borderRadius: 1,
          },
        }}
      />
    </Box>
  );
}

export function HealthGauge({ health }: HealthGaugeProps) {
  const theme = useTheme();
  const scoreColor = getScoreColor(health.overall_score);
  const scoreLabel = getScoreLabel(health.overall_score);

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
        💚 Health Analysis
      </Typography>

      {/* Main health score */}
      <Paper
        variant="outlined"
        sx={{
          p: 2,
          mb: 2,
          bgcolor: theme.palette.mode === "dark"
            ? "rgba(255, 255, 255, 0.02)"
            : "rgba(0, 0, 0, 0.02)",
          display: "flex",
          alignItems: "center",
          gap: 3,
        }}
      >
        {/* Score circle */}
        <Box
          sx={{
            width: 80,
            height: 80,
            borderRadius: "50%",
            border: `4px solid ${scoreColor}`,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography variant="h4" fontWeight={700} sx={{ color: scoreColor }}>
            {health.overall_score}
          </Typography>
        </Box>

        {/* Score label and status */}
        <Box>
          <Chip
            label={scoreLabel}
            size="small"
            sx={{
              bgcolor: scoreColor,
              color: "white",
              fontWeight: 600,
              mb: 1,
            }}
          />
          <Typography variant="body2" color="text.secondary">
            Overall Health Score
          </Typography>
        </Box>
      </Paper>

      {/* Metric breakdown - supports warehouse and cluster metrics */}
      {health.metric_scores && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1.5 }}>
            Metric Breakdown
          </Typography>
          {/* Warehouse metrics */}
          {health.metric_scores.latency !== undefined && (
            <MetricBar label="Latency" score={health.metric_scores.latency} />
          )}
          {health.metric_scores.availability !== undefined && (
            <MetricBar label="Availability" score={health.metric_scores.availability} />
          )}
          {health.metric_scores.queue_time !== undefined && (
            <MetricBar label="Queue Time" score={health.metric_scores.queue_time} />
          )}
          {health.metric_scores.error_rate !== undefined && (
            <MetricBar label="Error Rate" score={health.metric_scores.error_rate} />
          )}
          {/* Cluster metrics */}
          {health.metric_scores.cpu_utilization !== undefined && (
            <MetricBar label="CPU Utilization" score={health.metric_scores.cpu_utilization} />
          )}
          {health.metric_scores.memory_utilization !== undefined && (
            <MetricBar label="Memory Utilization" score={health.metric_scores.memory_utilization} />
          )}
          {health.metric_scores.disk_io !== undefined && (
            <MetricBar label="Disk I/O" score={health.metric_scores.disk_io} />
          )}
          {health.metric_scores.network_io !== undefined && (
            <MetricBar label="Network I/O" score={health.metric_scores.network_io} />
          )}
        </Box>
      )}

      {/* SLO Compliance */}
      {health.slo_compliance && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            SLO Compliance
          </Typography>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <Typography variant="h6" fontWeight={600}>
              {health.slo_compliance.targets_met}/{health.slo_compliance.targets_total}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              targets met
            </Typography>
            {health.slo_compliance.targets_met === health.slo_compliance.targets_total ? (
              <Chip label="✓ All Met" size="small" color="success" />
            ) : (
              <Chip label="⚠ Violations" size="small" color="warning" />
            )}
          </Box>
          {health.slo_compliance.details && health.slo_compliance.details.length > 0 && (
            <Box sx={{ mt: 1 }}>
              {health.slo_compliance.details.map((detail, idx) => (
                <Typography key={idx} variant="caption" display="block" color="text.secondary">
                  {detail.met ? "✓" : "✗"} {detail.metric}: {detail.actual.toFixed(0)} 
                  (target: {detail.target.toFixed(0)})
                </Typography>
              ))}
            </Box>
          )}
        </Box>
      )}

      {/* Risk Factors */}
      {health.risk_factors && health.risk_factors.length > 0 && (
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            ⚠️ Risk Factors
          </Typography>
          {health.risk_factors.map((risk, idx) => (
            <Paper
              key={idx}
              variant="outlined"
              sx={{
                p: 1,
                mb: 0.5,
                bgcolor: theme.palette.mode === "dark"
                  ? "rgba(244, 67, 54, 0.08)"
                  : "rgba(244, 67, 54, 0.04)",
                borderColor: "warning.main",
              }}
            >
              <Typography variant="body2">
                {risk}
              </Typography>
            </Paper>
          ))}
        </Box>
      )}
    </Box>
  );
}

