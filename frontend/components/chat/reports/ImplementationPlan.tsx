/**
 * Implementation plan component.
 *
 * Shows a prioritized list of recommendations sorted by impact/effort ratio,
 * with time estimates and bulk action buttons.
 */

"use client";

import React, { useState, useMemo } from "react";
import {
  Box,
  Paper,
  Typography,
  Button,
  Tooltip,
  Snackbar,
  Alert,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import DownloadIcon from "@mui/icons-material/Download";
import { useTheme } from "@mui/material/styles";
import { RecommendationItem } from "./RecommendationCard";
import { ImpactLevel } from "./ImpactBadge";
import { EffortLevel } from "./EffortBadge";
import { downloadMarkdown, generateFilename } from "@/lib/utils/file-download";

interface ImplementationPlanProps {
  /** All recommendations from the report */
  recommendations: RecommendationItem[];
  /** Callback when export is clicked */
  onExport?: (recommendations: RecommendationItem[]) => void;
}

// Score mappings for prioritization
const IMPACT_SCORE: Record<ImpactLevel, number> = {
  high: 3,
  medium: 2,
  low: 1,
};

const EFFORT_SCORE: Record<EffortLevel, number> = {
  low: 3, // Low effort = high score (prioritize)
  medium: 2,
  high: 1, // High effort = low score
};

// Time estimates
const EFFORT_TIME: Record<EffortLevel, string> = {
  low: "5-10 min",
  medium: "15-30 min",
  high: "1-2 hours",
};

/**
 * Sort recommendations by impact/effort ratio (best first).
 */
function sortByPriority(items: RecommendationItem[]): RecommendationItem[] {
  return [...items].sort((a, b) => {
    const scoreA = IMPACT_SCORE[a.impact] * EFFORT_SCORE[a.effort];
    const scoreB = IMPACT_SCORE[b.impact] * EFFORT_SCORE[b.effort];
    return scoreB - scoreA; // Descending (highest score first)
  });
}

/**
 * Implementation plan showing prioritized recommendations.
 *
 * @example
 * ```tsx
 * <ImplementationPlan
 *   recommendations={report.sections.flatMap(s => s.items)}
 *   onExport={(items) => downloadPlan(items)}
 * />
 * ```
 */
export function ImplementationPlan({
  recommendations,
  onExport,
}: ImplementationPlanProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";

  const [copied, setCopied] = useState(false);
  const [snackbarOpen, setSnackbarOpen] = useState(false);

  // Sort recommendations by priority
  const sortedItems = useMemo(
    () => sortByPriority(recommendations),
    [recommendations]
  );

  // Collect all SQL suggestions
  const allSql = useMemo(() => {
    return sortedItems
      .filter((item) => item.sql_suggestion)
      .map(
        (item, index) =>
          `-- ${index + 1}. ${item.title}\n${item.sql_suggestion}`
      )
      .join("\n\n");
  }, [sortedItems]);

  const handleCopyAllSql = async () => {
    if (!allSql) return;

    try {
      await navigator.clipboard.writeText(allSql);
      setCopied(true);
      setSnackbarOpen(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy SQL:", err);
    }
  };

  const handleExport = () => {
    if (onExport) {
      onExport(sortedItems);
    } else {
      // Default export: download as markdown
      const markdown = generateMarkdown(sortedItems);
      downloadMarkdown(markdown, generateFilename("implementation-plan", "md"));
    }
  };

  if (sortedItems.length === 0) {
    return null;
  }

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2.5,
        background: isDark
          ? "linear-gradient(135deg, rgba(33, 150, 243, 0.08) 0%, rgba(103, 58, 183, 0.08) 100%)"
          : "linear-gradient(135deg, rgba(33, 150, 243, 0.05) 0%, rgba(103, 58, 183, 0.05) 100%)",
        border: 1,
        borderColor: isDark
          ? "rgba(33, 150, 243, 0.2)"
          : "rgba(33, 150, 243, 0.15)",
        borderRadius: 2,
        mt: 2,
      }}
    >
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
        <Typography component="span" sx={{ fontSize: "1.25rem" }}>
          🎯
        </Typography>
        <Typography
          variant="subtitle1"
          sx={{
            fontWeight: 600,
            color: "text.primary",
          }}
        >
          Suggested Implementation Order
        </Typography>
      </Box>

      {/* Ordered List */}
      <Box
        component="ol"
        sx={{
          listStyle: "none",
          p: 0,
          m: 0,
          mb: 2,
        }}
      >
        {sortedItems.map((item, index) => (
          <Box
            component="li"
            key={item.id}
            sx={{
              display: "flex",
              alignItems: "flex-start",
              gap: 1.5,
              py: 1,
              borderBottom: index < sortedItems.length - 1 ? 1 : 0,
              borderColor: "divider",
            }}
          >
            {/* Number Badge */}
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                width: 24,
                height: 24,
                borderRadius: "50%",
                bgcolor: "primary.main",
                color: "primary.contrastText",
                fontSize: "0.75rem",
                fontWeight: 700,
                flexShrink: 0,
                mt: 0.25,
              }}
            >
              {index + 1}
            </Box>

            {/* Title */}
            <Typography
              variant="body2"
              sx={{
                flex: 1,
                color: "text.primary",
                fontWeight: 500,
              }}
            >
              {item.title}
            </Typography>

            {/* Time Estimate */}
            <Typography
              variant="caption"
              sx={{
                color: "text.secondary",
                flexShrink: 0,
                whiteSpace: "nowrap",
              }}
            >
              ~{item.estimated_time || EFFORT_TIME[item.effort]}
            </Typography>
          </Box>
        ))}
      </Box>

      {/* Action Buttons */}
      <Box
        sx={{
          display: "flex",
          gap: 1.5,
          pt: 2,
          borderTop: 1,
          borderColor: "divider",
        }}
      >
        {/* Copy All SQL Button */}
        {allSql && (
          <Tooltip title={copied ? "Copied!" : "Copy all SQL suggestions"}>
            <Button
              variant="contained"
              size="small"
              onClick={handleCopyAllSql}
              startIcon={copied ? <CheckIcon /> : <ContentCopyIcon />}
              color={copied ? "success" : "primary"}
              sx={{ flex: 1 }}
            >
              {copied ? "Copied!" : "Copy All SQL"}
            </Button>
          </Tooltip>
        )}

        {/* Export Plan Button */}
        <Tooltip title="Download implementation plan as markdown">
          <Button
            variant="outlined"
            size="small"
            onClick={handleExport}
            startIcon={<DownloadIcon />}
            sx={{ minWidth: 120 }}
          >
            Export Plan
          </Button>
        </Tooltip>
      </Box>

      {/* Success Snackbar */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={2000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert
          severity="success"
          variant="filled"
          onClose={() => setSnackbarOpen(false)}
        >
          SQL copied to clipboard!
        </Alert>
      </Snackbar>
    </Paper>
  );
}

/**
 * Generate markdown from sorted recommendations.
 */
function generateMarkdown(items: RecommendationItem[]): string {
  const lines = [
    "# Implementation Plan",
    "",
    `Generated: ${new Date().toLocaleString()}`,
    "",
    "## Prioritized Recommendations",
    "",
  ];

  items.forEach((item, index) => {
    lines.push(`### ${index + 1}. ${item.title}`);
    lines.push("");
    lines.push(`**Impact:** ${item.impact} | **Effort:** ${item.effort}`);
    if (item.estimated_improvement) {
      lines.push(`**Expected Improvement:** ${item.estimated_improvement}`);
    }
    lines.push("");
    lines.push(item.description);
    lines.push("");

    if (item.explanation) {
      lines.push("**Why this matters:**");
      lines.push(item.explanation);
      lines.push("");
    }

    if (item.sql_suggestion) {
      lines.push("**Suggested SQL:**");
      lines.push("```sql");
      lines.push(item.sql_suggestion);
      lines.push("```");
      lines.push("");
    }

    lines.push("---");
    lines.push("");
  });

  return lines.join("\n");
}

export default ImplementationPlan;

