/**
 * FindingCard component.
 *
 * Displays an individual optimization finding with impact/effort badges,
 * recommendation details, SQL fixes, and inline action buttons.
 * 
 * Phase 2: Part of the Inline Actions integration.
 */

"use client";

import React, { useState } from "react";
import {
  Box,
  Paper,
  Typography,
  Chip,
  Collapse,
  IconButton,
  Divider,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import type { Finding, Fix } from "@/lib/types/api";
import { InlineActions } from "../actions/InlineActions";
import { CodeBlockWithActions } from "../CodeBlockWithActions";

interface FindingCardProps {
  /** The finding to display */
  finding: Finding;
  /** Index for display ordering */
  index: number;
  /** Callback when an action is performed */
  onAction?: (actionId: string, findingId: string) => void | Promise<void>;
  /** Whether the card starts expanded */
  defaultExpanded?: boolean;
}

/**
 * Get severity icon and color based on impact estimate.
 * Derives severity from query_time_pct: >50% is high, >20% is medium, else low.
 */
function getSeverityStyle(impact: Finding["impact_estimate"]) {
  // Derive severity from query_time_pct (or fallback to medium)
  const pct = impact?.query_time_pct || 0;
  const severity = pct > 50 ? "high" : pct > 20 ? "medium" : "low";
  
  switch (severity) {
    case "high":
      return {
        icon: ErrorOutlineIcon,
        color: "error.main",
        bgColor: "rgba(211, 47, 47, 0.08)",
        borderColor: "error.main",
        label: "High Impact",
      };
    case "medium":
      return {
        icon: WarningAmberIcon,
        color: "warning.main",
        bgColor: "rgba(237, 108, 2, 0.08)",
        borderColor: "warning.main",
        label: "Medium Impact",
      };
    case "low":
    default:
      return {
        icon: InfoOutlinedIcon,
        color: "info.main",
        bgColor: "rgba(2, 136, 209, 0.08)",
        borderColor: "info.main",
        label: "Low Impact",
      };
  }
}

/**
 * Get effort level style.
 */
function getEffortStyle(effort: Finding["effort"]) {
  const level = effort?.level?.toLowerCase() || "medium";
  
  switch (level) {
    case "low":
      return { color: "success", label: "Low Effort" };
    case "medium":
      return { color: "warning", label: "Medium Effort" };
    case "high":
      return { color: "error", label: "High Effort" };
    default:
      return { color: "default", label: level };
  }
}

/**
 * Finding card component.
 *
 * @example
 * ```tsx
 * <FindingCard
 *   finding={finding}
 *   index={0}
 *   onAction={(actionId, findingId) => console.log(actionId, findingId)}
 * />
 * ```
 */
export function FindingCard({
  finding,
  index,
  onAction,
  defaultExpanded = false,
}: FindingCardProps) {
  const theme = useTheme();
  const [expanded, setExpanded] = useState(defaultExpanded);
  
  const severityStyle = getSeverityStyle(finding.impact_estimate);
  const effortStyle = getEffortStyle(finding.effort);
  const SeverityIcon = severityStyle.icon;
  
  // Extract SQL from fixes if available (using snippet field)
  const sqlFix = finding.fixes?.find((fix: Fix) => fix.snippet);
  const sqlCode = sqlFix?.snippet || "";

  const handleAction = async (actionId: string, recId: string) => {
    if (onAction) {
      await onAction(actionId, recId);
    }
  };

  return (
    <Paper
      elevation={1}
      sx={{
        mb: 2,
        overflow: "hidden",
        borderLeft: `4px solid`,
        borderLeftColor: severityStyle.borderColor,
        bgcolor: theme.palette.mode === "dark"
          ? "rgba(255, 255, 255, 0.02)"
          : "rgba(0, 0, 0, 0.01)",
        transition: "all 0.2s ease",
        "&:hover": {
          boxShadow: 2,
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "flex-start",
          gap: 1.5,
          p: 2,
          cursor: "pointer",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Rank badge */}
        <Box
          sx={{
            width: 28,
            height: 28,
            borderRadius: "50%",
            bgcolor: severityStyle.color,
            color: "white",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 600,
            fontSize: "0.875rem",
            flexShrink: 0,
          }}
        >
          {finding.rank || index + 1}
        </Box>

        {/* Content */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* Title row */}
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
            <Typography
              variant="subtitle1"
              sx={{
                fontWeight: 600,
                color: "text.primary",
                flex: 1,
              }}
            >
              {finding.title}
            </Typography>
            
            {/* Badges */}
            <Box sx={{ display: "flex", gap: 0.5, flexShrink: 0 }}>
              <Chip
                icon={<SeverityIcon sx={{ fontSize: "1rem !important" }} />}
                label={severityStyle.label}
                size="small"
                sx={{
                  bgcolor: severityStyle.bgColor,
                  color: severityStyle.color,
                  fontWeight: 500,
                  fontSize: "0.75rem",
                  "& .MuiChip-icon": {
                    color: "inherit",
                  },
                }}
              />
              <Chip
                label={effortStyle.label}
                size="small"
                color={effortStyle.color as "success" | "warning" | "error" | "default"}
                variant="outlined"
                sx={{
                  fontWeight: 500,
                  fontSize: "0.75rem",
                }}
              />
            </Box>
          </Box>

          {/* Category */}
          {finding.category && (
            <Typography
              variant="caption"
              sx={{
                color: "text.secondary",
                textTransform: "uppercase",
                letterSpacing: "0.5px",
              }}
            >
              {finding.category}
            </Typography>
          )}
        </Box>

        {/* Expand icon */}
        <IconButton size="small" sx={{ ml: 1 }}>
          {expanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </IconButton>
      </Box>

      {/* Expandable content */}
      <Collapse in={expanded}>
        <Box sx={{ px: 2, pb: 2 }}>
          <Divider sx={{ mb: 2 }} />

          {/* Recommendation */}
          <Typography
            variant="body2"
            sx={{
              color: "text.primary",
              lineHeight: 1.6,
              mb: 2,
            }}
          >
            {finding.recommendation}
          </Typography>

          {/* Code Fix (auto-detect language) */}
          {sqlCode && (
            <Box sx={{ mb: 2 }}>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  fontWeight: 600,
                  display: "block",
                  mb: 1,
                }}
              >
                Suggested Code:
              </Typography>
              <CodeBlockWithActions
                code={sqlCode}
                showLineNumbers={false}
                maxHeight="200px"
              />
            </Box>
          )}

          {/* Impact details */}
          {finding.impact_estimate?.query_time_pct && (
            <Box sx={{ mb: 2 }}>
              <Typography
                variant="caption"
                sx={{
                  color: "text.secondary",
                  fontWeight: 600,
                  display: "block",
                  mb: 0.5,
                }}
              >
                Expected Impact:
              </Typography>
              <Typography variant="body2" sx={{ color: "text.secondary" }}>
                {`Query time reduction: ${finding.impact_estimate.query_time_pct}%`}
                {finding.impact_estimate.data_read_pct && ` | Data read: ${finding.impact_estimate.data_read_pct}%`}
                {finding.impact_estimate.cost_pct && ` | Cost: ${finding.impact_estimate.cost_pct}%`}
              </Typography>
            </Box>
          )}

          {/* Risks */}
          {finding.risks && finding.risks.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography
                variant="caption"
                sx={{
                  color: "warning.main",
                  fontWeight: 600,
                  display: "block",
                  mb: 0.5,
                }}
              >
                ⚠️ Risks:
              </Typography>
              <Box component="ul" sx={{ m: 0, pl: 2 }}>
                {finding.risks.map((risk, i) => (
                  <Typography
                    key={i}
                    component="li"
                    variant="body2"
                    sx={{ color: "text.secondary" }}
                  >
                    {risk}
                  </Typography>
                ))}
              </Box>
            </Box>
          )}

          {/* Inline Actions */}
          {onAction && (
            <InlineActions
              recommendationId={finding.id}
              onAction={handleAction}
              sqlCode={sqlCode}
              compact={false}
            />
          )}
        </Box>
      </Collapse>
    </Paper>
  );
}

export default FindingCard;

