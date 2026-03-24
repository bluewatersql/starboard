/**
 * Recommendation card component.
 *
 * Displays a single recommendation with impact/effort badges,
 * expandable details section, and optional SQL code suggestion.
 */

"use client";

import React, { useState } from "react";
import {
  Box,
  Card,
  CardContent,
  Typography,
  Collapse,
  Button,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { useTheme } from "@mui/material/styles";
import { ImpactBadge, ImpactLevel } from "./ImpactBadge";
import { EffortBadge, EffortLevel } from "./EffortBadge";
import { CodeBlockWithActions } from "../CodeBlockWithActions";

export interface RecommendationItem {
  /** Unique identifier */
  id: string;
  /** Short title of the recommendation */
  title: string;
  /** Brief description of the issue/opportunity */
  description: string;
  /** Expected impact level */
  impact: ImpactLevel;
  /** Implementation effort level */
  effort: EffortLevel;
  /** Category (e.g., "Query Optimization", "Schema Design") */
  category?: string;
  /** Suggested SQL changes */
  sql_suggestion?: string;
  /** Detailed explanation of why this matters */
  explanation?: string;
  /** Estimated improvement (e.g., "25% faster") */
  estimated_improvement?: string;
  /** Estimated time to implement */
  estimated_time?: string;
}

interface RecommendationCardProps {
  /** The recommendation item to display */
  item: RecommendationItem;
  /** Display index (1-based) for numbering */
  index: number;
  /** Initial expanded state */
  defaultExpanded?: boolean;
  /** Callback when Apply button is clicked */
  onApply?: (code: string, recommendationId: string) => void;
}

/**
 * Card component for displaying a single recommendation with expandable details.
 *
 * @example
 * ```tsx
 * <RecommendationCard
 *   item={{
 *     id: "1",
 *     title: "Add partition filter",
 *     description: "Query scans entire table without partition pruning",
 *     impact: "high",
 *     effort: "low",
 *     sql_suggestion: "WHERE partition_date = '2024-01-01'"
 *   }}
 *   index={1}
 *   onApply={(code) => console.log("Apply:", code)}
 * />
 * ```
 */
export function RecommendationCard({
  item,
  index,
  defaultExpanded = false,
  onApply,
}: RecommendationCardProps) {
  const theme = useTheme();
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  const hasExpandableContent = Boolean(item.sql_suggestion || item.explanation);

  const handleApply = (code: string) => {
    if (onApply) {
      onApply(code, item.id);
    }
  };

  return (
    <Card
      elevation={1}
      sx={{
        border: 1,
        borderColor: "divider",
        transition: "box-shadow 0.2s, border-color 0.2s",
        "&:hover": {
          boxShadow: 2,
          borderColor: "primary.light",
        },
      }}
    >
      <CardContent sx={{ pb: hasExpandableContent ? 1 : 2 }}>
        {/* Header Row */}
        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 2,
          }}
        >
          {/* Title and Description */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography
              variant="subtitle1"
              sx={{
                fontWeight: 600,
                color: "text.primary",
                mb: 0.5,
              }}
            >
              {index}. {item.title}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                color: "text.secondary",
                lineHeight: 1.5,
              }}
            >
              {item.description}
            </Typography>
          </Box>

          {/* Badges */}
          <Box
            sx={{
              display: "flex",
              flexDirection: "column",
              gap: 0.5,
              flexShrink: 0,
            }}
          >
            <ImpactBadge
              impact={item.impact}
              value={item.estimated_improvement}
            />
            <EffortBadge effort={item.effort} time={item.estimated_time} />
          </Box>
        </Box>

        {/* Expand/Collapse Button */}
        {hasExpandableContent && (
          <Button
            size="small"
            onClick={() => setIsExpanded(!isExpanded)}
            startIcon={isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
            sx={{
              mt: 1.5,
              color: "primary.main",
              textTransform: "none",
              fontWeight: 500,
            }}
          >
            {isExpanded ? "Hide Details" : "View Details"}
          </Button>
        )}
      </CardContent>

      {/* Expandable Content */}
      <Collapse in={isExpanded}>
        <Box
          sx={{
            px: 2,
            pb: 2,
            pt: 1,
            borderTop: 1,
            borderColor: "divider",
            bgcolor:
              theme.palette.mode === "dark"
                ? "rgba(255,255,255,0.02)"
                : "rgba(0,0,0,0.01)",
          }}
        >
          {/* Explanation */}
          {item.explanation && (
            <Box sx={{ mb: 2 }}>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 600, mb: 1, color: "text.primary" }}
              >
                Why this matters:
              </Typography>
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", lineHeight: 1.6 }}
              >
                {item.explanation}
              </Typography>
            </Box>
          )}

          {/* SQL Suggestion - let CodeBlockWithActions auto-detect language */}
          {item.sql_suggestion && (
            <Box>
              <Typography
                variant="subtitle2"
                sx={{ fontWeight: 600, mb: 1, color: "text.primary" }}
              >
                Suggested Changes:
              </Typography>
              <CodeBlockWithActions
                code={item.sql_suggestion}
                language={undefined}  // Auto-detect: SQL for actual queries, text for plain text
                showLineNumbers={item.sql_suggestion.split("\n").length > 5}
                onApply={onApply ? (code) => handleApply(code) : undefined}
              />
            </Box>
          )}
        </Box>
      </Collapse>
    </Card>
  );
}

export default RecommendationCard;

