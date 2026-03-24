/**
 * Analytics findings card component.
 *
 * Displays cost optimization opportunities with savings estimates.
 */

"use client";

import React from "react";
import { Box, Typography, Paper, Chip, Divider } from "@mui/material";
import type { AnalyticsFinding } from "@/lib/types/api";

interface AnalyticsFindingsCardProps {
  /** List of cost/usage findings ranked by savings potential */
  findings: AnalyticsFinding[];
}

/**
 * Findings card for analytics reports.
 *
 * Shows cost optimization opportunities ranked by savings potential with
 * estimated impact and implementation effort.
 *
 * @param props - Component props
 * @returns Findings card component
 *
 * @example
 * ```tsx
 * <AnalyticsFindingsCard
 *   findings={[
 *     {
 *       id: "finops_001",
 *       rank: 1,
 *       category: "WASTE_DETECTION",
 *       title: "Idle warehouse consuming $2,400/month",
 *       recommendation: "Enable auto-stop after 10 minutes",
 *       cost_impact: { ... },
 *       effort: { level: "low", estimate_hours: 0.5 }
 *     }
 *   ]}
 * />
 * ```
 */
export function AnalyticsFindingsCard({
  findings,
}: AnalyticsFindingsCardProps) {
  if (!findings || findings.length === 0) {
    return null;
  }

  return (
    <Box sx={{ mb: 2 }}>
      <Typography
        variant="h6"
        sx={{
          fontSize: "1rem",
          fontWeight: 600,
          mb: 1.5,
          color: "primary.main",
        }}
      >
        💡 Cost Optimization Opportunities
      </Typography>

      {findings.map((finding) => (
        <Paper
          key={finding.id}
          elevation={0}
          sx={{
            p: 2,
            mb: 2,
            bgcolor: "background.paper",
            border: "1px solid",
            borderColor: "divider",
            borderRadius: 2,
            "&:last-child": {
              mb: 0,
            },
          }}
        >
          {/* Finding Header */}
          <Box
            sx={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              mb: 1,
            }}
          >
            <Box sx={{ flex: 1 }}>
              <Typography
                variant="subtitle1"
                sx={{
                  fontWeight: 600,
                  color: "text.primary",
                  mb: 0.5,
                }}
              >
                {finding.rank}. {finding.title}
              </Typography>

              {/* Category Badge */}
              <Chip
                label={finding.category.replace(/_/g, " ")}
                size="small"
                sx={{
                  height: 20,
                  fontSize: "0.75rem",
                  textTransform: "capitalize",
                }}
              />
            </Box>
          </Box>

          {/* Recommendation */}
          <Typography
            variant="body2"
            sx={{
              mb: 1.5,
              color: "text.secondary",
              lineHeight: 1.6,
            }}
          >
            {finding.recommendation}
          </Typography>

          <Divider sx={{ my: 1.5 }} />

          {/* Cost Impact */}
          <Box sx={{ mb: 1.5 }}>
            <Typography
              variant="caption"
              sx={{
                fontWeight: 600,
                color: "text.secondary",
                display: "block",
                mb: 0.5,
              }}
            >
              Cost Impact
            </Typography>

            <Box
              sx={{
                display: "flex",
                flexWrap: "wrap",
                gap: 2,
                alignItems: "baseline",
              }}
            >
              <Typography variant="body2">
                <strong>Current:</strong> $
                {(finding.cost_impact?.current_monthly_cost ?? 0).toLocaleString(
                  undefined,
                  {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  }
                )}
                /month
              </Typography>

              <Typography
                variant="body2"
                sx={{
                  color: "success.main",
                  fontWeight: 600,
                }}
              >
                <strong>Save:</strong> $
                {(finding.cost_impact?.projected_savings_monthly ?? 0).toLocaleString(
                  undefined,
                  {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  }
                )}
                /month ({(finding.cost_impact?.savings_pct ?? 0).toFixed(0)}%)
              </Typography>

              <Chip
                label={`${finding.cost_impact?.confidence ?? 'unknown'} confidence`}
                size="small"
                variant="outlined"
                sx={{
                  height: 20,
                  fontSize: "0.7rem",
                  textTransform: "capitalize",
                }}
              />
            </Box>
          </Box>

          {/* Effort */}
          <Box>
            <Typography
              variant="caption"
              sx={{
                fontWeight: 600,
                color: "text.secondary",
                display: "block",
                mb: 0.5,
              }}
            >
              Implementation Effort
            </Typography>

            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Chip
                label={finding.effort.level}
                size="small"
                color={
                  finding.effort.level === "low"
                    ? "success"
                    : finding.effort.level === "medium"
                    ? "warning"
                    : "default"
                }
                sx={{
                  height: 20,
                  fontSize: "0.75rem",
                  textTransform: "capitalize",
                }}
              />

              {typeof finding.effort.estimate_hours === "number" && (
                <Typography variant="body2" color="text.secondary">
                  ~{finding.effort.estimate_hours}h
                </Typography>
              )}
            </Box>
          </Box>
        </Paper>
      ))}
    </Box>
  );
}

