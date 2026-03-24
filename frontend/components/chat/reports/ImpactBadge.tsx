/**
 * Impact badge component.
 *
 * Visual indicator showing the expected performance improvement
 * of a recommendation (high/medium/low impact).
 */

"use client";

import React from "react";
import { Chip, Tooltip } from "@mui/material";
import BoltIcon from "@mui/icons-material/Bolt";

export type ImpactLevel = "high" | "medium" | "low";

interface ImpactBadgeProps {
  /** Impact level (high, medium, low) */
  impact: ImpactLevel;
  /** Optional specific improvement value (e.g., "25% faster") */
  value?: string;
  /** Show tooltip with explanation */
  showTooltip?: boolean;
}

const IMPACT_CONFIG = {
  high: {
    label: "High Impact",
    color: "success" as const,
    tooltip: "Significant performance improvement expected (>20%)",
    bolts: 3,
  },
  medium: {
    label: "Medium Impact",
    color: "warning" as const,
    tooltip: "Moderate performance improvement expected (10-20%)",
    bolts: 2,
  },
  low: {
    label: "Low Impact",
    color: "default" as const,
    tooltip: "Minor performance improvement expected (<10%)",
    bolts: 1,
  },
};

/**
 * Impact badge showing expected performance improvement level.
 *
 * @example
 * ```tsx
 * <ImpactBadge impact="high" value="25% faster" />
 * ```
 */
export function ImpactBadge({
  impact,
  value,
  showTooltip = true,
}: ImpactBadgeProps) {
  const config = IMPACT_CONFIG[impact];

  const badge = (
    <Chip
      size="small"
      color={config.color}
      icon={
        <span style={{ display: "flex", alignItems: "center", marginLeft: 4 }}>
          {Array.from({ length: config.bolts }).map((_, i) => (
            <BoltIcon
              key={i}
              sx={{ fontSize: 12, marginLeft: i > 0 ? "-4px" : 0 }}
            />
          ))}
        </span>
      }
      label={value ? `${config.label} • ${value}` : config.label}
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

export default ImpactBadge;

