/**
 * Effort badge component.
 *
 * Visual indicator showing the implementation effort required
 * for a recommendation (low/medium/high effort).
 */

"use client";

import React from "react";
import { Chip, Tooltip } from "@mui/material";
import BuildIcon from "@mui/icons-material/Build";

export type EffortLevel = "low" | "medium" | "high";

interface EffortBadgeProps {
  /** Effort level (low, medium, high) */
  effort: EffortLevel;
  /** Optional estimated time (e.g., "5-10 min") */
  time?: string;
  /** Show tooltip with explanation */
  showTooltip?: boolean;
}

const EFFORT_CONFIG = {
  low: {
    label: "Low Effort",
    color: "success" as const,
    tooltip: "Quick win - can be implemented in 5-10 minutes",
    wrenches: 1,
  },
  medium: {
    label: "Medium Effort",
    color: "warning" as const,
    tooltip: "Moderate effort - typically 15-30 minutes",
    wrenches: 2,
  },
  high: {
    label: "High Effort",
    color: "error" as const,
    tooltip: "Significant effort - may take 1-2 hours or more",
    wrenches: 3,
  },
};

/**
 * Effort badge showing implementation difficulty level.
 *
 * @example
 * ```tsx
 * <EffortBadge effort="low" time="5-10 min" />
 * ```
 */
export function EffortBadge({
  effort,
  time,
  showTooltip = true,
}: EffortBadgeProps) {
  const config = EFFORT_CONFIG[effort];

  const badge = (
    <Chip
      size="small"
      color={config.color}
      variant="outlined"
      icon={
        <span style={{ display: "flex", alignItems: "center", marginLeft: 4 }}>
          {Array.from({ length: config.wrenches }).map((_, i) => (
            <BuildIcon
              key={i}
              sx={{ fontSize: 12, marginLeft: i > 0 ? "-4px" : 0 }}
            />
          ))}
        </span>
      }
      label={time ? `${config.label} • ${time}` : config.label}
      sx={{
        fontWeight: 500,
        fontSize: "0.75rem",
        "& .MuiChip-icon": {
          marginRight: 0,
        },
      }}
    />
  );

  if (showTooltip) {
    return <Tooltip title={config.tooltip}>{badge}</Tooltip>;
  }

  return badge;
}

export default EffortBadge;

