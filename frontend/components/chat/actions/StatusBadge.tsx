/**
 * Status badge component.
 *
 * Visual indicator for recommendation implementation status.
 */

"use client";

import React from "react";
import { Chip, Tooltip } from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import CancelIcon from "@mui/icons-material/Cancel";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";

export type ImplementationStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "skipped";

interface StatusBadgeProps {
  /** Current implementation status */
  status: ImplementationStatus;
  /** Compact mode for smaller displays */
  compact?: boolean;
  /** Whether to show badge for not_started status */
  showNotStarted?: boolean;
}

const STATUS_CONFIG: Record<
  ImplementationStatus,
  {
    icon: React.ComponentType<{ fontSize?: "small" | "inherit" }>;
    label: string;
    shortLabel: string;
    color: "default" | "primary" | "success" | "error" | "warning" | "info";
    tooltip: string;
  }
> = {
  not_started: {
    icon: RadioButtonUncheckedIcon,
    label: "Not Started",
    shortLabel: "New",
    color: "default",
    tooltip: "This recommendation has not been started yet",
  },
  in_progress: {
    icon: AccessTimeIcon,
    label: "In Progress",
    shortLabel: "WIP",
    color: "info",
    tooltip: "This recommendation is currently being implemented",
  },
  completed: {
    icon: CheckCircleIcon,
    label: "Completed",
    shortLabel: "Done",
    color: "success",
    tooltip: "This recommendation has been implemented",
  },
  skipped: {
    icon: CancelIcon,
    label: "Skipped",
    shortLabel: "Skip",
    color: "default",
    tooltip: "This recommendation was skipped",
  },
};

/**
 * Status badge for recommendation implementation tracking.
 *
 * @example
 * ```tsx
 * <StatusBadge status="completed" />
 * <StatusBadge status="in_progress" compact />
 * ```
 */
export function StatusBadge({
  status,
  compact = false,
  showNotStarted = false,
}: StatusBadgeProps) {
  const config = STATUS_CONFIG[status];

  // Don't show badge for not_started unless explicitly requested
  if (status === "not_started" && !showNotStarted) {
    return null;
  }

  const Icon = config.icon;

  const badge = (
    <Chip
      size="small"
      icon={<Icon fontSize="small" />}
      label={compact ? config.shortLabel : config.label}
      color={config.color}
      variant={status === "skipped" ? "outlined" : "filled"}
      sx={{
        fontWeight: 500,
        fontSize: compact ? "0.6875rem" : "0.75rem",
        height: compact ? 20 : 24,
        "& .MuiChip-icon": {
          fontSize: compact ? 14 : 16,
        },
        ...(status === "skipped" && {
          opacity: 0.7,
          textDecoration: "line-through",
        }),
      }}
    />
  );

  return <Tooltip title={config.tooltip}>{badge}</Tooltip>;
}

export default StatusBadge;

