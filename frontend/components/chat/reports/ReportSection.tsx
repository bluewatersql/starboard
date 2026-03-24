/**
 * Report section component.
 *
 * Collapsible section container for grouping recommendations
 * by severity (critical, warning, info).
 */

"use client";

import React from "react";
import { Box, Typography, IconButton, Collapse, Paper } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { useTheme } from "@mui/material/styles";
import { RecommendationCard, RecommendationItem } from "./RecommendationCard";

export type SeverityLevel = "critical" | "warning" | "info";

export interface ReportSectionData {
  /** Unique section identifier */
  id: string;
  /** Section title */
  title: string;
  /** Severity level for styling */
  severity: SeverityLevel;
  /** Recommendation items in this section */
  items: RecommendationItem[];
}

interface ReportSectionProps {
  /** Section data */
  section: ReportSectionData;
  /** Whether section is collapsed */
  isCollapsed: boolean;
  /** Toggle callback */
  onToggle: () => void;
  /** Callback when Apply is clicked on a recommendation */
  onApplyRecommendation?: (code: string, recommendationId: string) => void;
}

const SEVERITY_CONFIG = {
  critical: {
    icon: "🔴",
    bgColor: {
      light: "rgba(211, 47, 47, 0.08)",
      dark: "rgba(244, 67, 54, 0.12)",
    },
    borderColor: {
      light: "rgba(211, 47, 47, 0.3)",
      dark: "rgba(244, 67, 54, 0.3)",
    },
    textColor: {
      light: "#c62828",
      dark: "#ef5350",
    },
  },
  warning: {
    icon: "🟡",
    bgColor: {
      light: "rgba(237, 108, 2, 0.08)",
      dark: "rgba(255, 152, 0, 0.12)",
    },
    borderColor: {
      light: "rgba(237, 108, 2, 0.3)",
      dark: "rgba(255, 152, 0, 0.3)",
    },
    textColor: {
      light: "#e65100",
      dark: "#ffb74d",
    },
  },
  info: {
    icon: "🔵",
    bgColor: {
      light: "rgba(2, 136, 209, 0.08)",
      dark: "rgba(33, 150, 243, 0.12)",
    },
    borderColor: {
      light: "rgba(2, 136, 209, 0.3)",
      dark: "rgba(33, 150, 243, 0.3)",
    },
    textColor: {
      light: "#0277bd",
      dark: "#64b5f6",
    },
  },
};

/**
 * Collapsible report section for grouping recommendations.
 *
 * @example
 * ```tsx
 * <ReportSection
 *   section={{
 *     id: "critical",
 *     title: "Critical Issues",
 *     severity: "critical",
 *     items: [...]
 *   }}
 *   isCollapsed={false}
 *   onToggle={() => setCollapsed(!collapsed)}
 * />
 * ```
 */
export function ReportSection({
  section,
  isCollapsed,
  onToggle,
  onApplyRecommendation,
}: ReportSectionProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const config = SEVERITY_CONFIG[section.severity];

  return (
    <Box sx={{ mb: 2 }}>
      {/* Section Header */}
      <Paper
        elevation={0}
        onClick={onToggle}
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1.5,
          bgcolor: isDark ? config.bgColor.dark : config.bgColor.light,
          border: 1,
          borderColor: isDark ? config.borderColor.dark : config.borderColor.light,
          borderRadius: isCollapsed ? 2 : "8px 8px 0 0",
          cursor: "pointer",
          transition: "all 0.2s",
          "&:hover": {
            boxShadow: 1,
          },
        }}
        aria-expanded={!isCollapsed}
        aria-controls={`section-content-${section.id}`}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggle();
          }
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
          <Typography component="span" sx={{ fontSize: "1.25rem" }}>
            {config.icon}
          </Typography>
          <Typography
            variant="subtitle1"
            sx={{
              fontWeight: 600,
              color: isDark ? config.textColor.dark : config.textColor.light,
            }}
          >
            {section.title}
          </Typography>
          <Typography
            variant="body2"
            sx={{
              color: isDark ? config.textColor.dark : config.textColor.light,
              opacity: 0.8,
            }}
          >
            ({section.items.length})
          </Typography>
        </Box>

        <IconButton
          size="small"
          sx={{
            color: isDark ? config.textColor.dark : config.textColor.light,
          }}
          aria-label={isCollapsed ? "Expand section" : "Collapse section"}
        >
          {isCollapsed ? <ExpandMoreIcon /> : <ExpandLessIcon />}
        </IconButton>
      </Paper>

      {/* Section Content */}
      <Collapse in={!isCollapsed}>
        <Box
          id={`section-content-${section.id}`}
          sx={{
            pt: 2,
            pb: 1,
            px: 2,
            bgcolor: isDark
              ? "rgba(255,255,255,0.02)"
              : "rgba(0,0,0,0.01)",
            borderLeft: 1,
            borderRight: 1,
            borderBottom: 1,
            borderColor: "divider",
            borderRadius: "0 0 8px 8px",
          }}
        >
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {section.items.map((item, index) => (
              <RecommendationCard
                key={item.id}
                item={item}
                index={index + 1}
                onApply={onApplyRecommendation}
              />
            ))}
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
}

export default ReportSection;

