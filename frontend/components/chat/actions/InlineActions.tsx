/**
 * Inline actions component.
 *
 * Contextual action buttons for recommendations enabling users
 * to mark as applied, copy SQL, request explanations, or skip.
 * Uses React Query mutations for consistent error handling and feedback.
 */

"use client";

import React, { useState } from "react";
import {
  Box,
  Button,
  IconButton,
  Tooltip,
  CircularProgress,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import CloseIcon from "@mui/icons-material/Close";
import { useSimpleActionMutation } from "@/lib/hooks";
import { useUIStore } from "@/lib/store/uiStore";
import { useConfirmation } from "@/lib/hooks/useConfirmation";
import { ConfirmationDialog } from "@/components/common/ConfirmationDialog";

export interface ActionConfig {
  /** Unique action identifier */
  id: string;
  /** Display label */
  label: string;
  /** Material UI icon component */
  icon: React.ComponentType<{
    fontSize?: "small" | "inherit" | "medium" | "large";
  }>;
  /** Button variant styling */
  variant?: "primary" | "secondary" | "success" | "danger";
  /** Whether to show confirmation dialog */
  confirmRequired?: boolean;
  /** Custom confirmation message */
  confirmMessage?: string;
}

interface InlineActionsProps {
  /** ID of the recommendation these actions apply to */
  recommendationId: string;
  /** Custom actions (defaults to standard set if not provided) */
  actions?: ActionConfig[];
  /** Callback when action is performed */
  onAction: (actionId: string, recommendationId: string) => void | Promise<void>;
  /** Compact mode for smaller displays */
  compact?: boolean;
  /** SQL code for copy action (optional) */
  sqlCode?: string;
}

const DEFAULT_ACTIONS: ActionConfig[] = [
  {
    id: "mark_applied",
    label: "Mark as Applied",
    icon: CheckCircleOutlineIcon,
    variant: "success",
  },
  {
    id: "copy_sql",
    label: "Copy SQL",
    icon: ContentCopyIcon,
    variant: "secondary",
  },
  {
    id: "explain_more",
    label: "Explain More",
    icon: HelpOutlineIcon,
    variant: "secondary",
  },
  {
    id: "skip",
    label: "Skip",
    icon: CloseIcon,
    variant: "secondary",
  },
];

/**
 * Get button color based on variant and applied state.
 */
function getVariantProps(
  variant: string = "secondary",
  isApplied: boolean
): {
  color: "success" | "primary" | "error" | "inherit";
  variant: "contained" | "outlined" | "text";
} {
  if (isApplied) {
    return { color: "success", variant: "contained" };
  }

  const variants: Record<
    string,
    {
      color: "success" | "primary" | "error" | "inherit";
      variant: "contained" | "outlined" | "text";
    }
  > = {
    primary: { color: "primary", variant: "contained" },
    secondary: { color: "inherit", variant: "outlined" },
    success: { color: "success", variant: "outlined" },
    danger: { color: "error", variant: "outlined" },
  };

  const defaultVariant = { color: "inherit" as const, variant: "outlined" as const };
  return variants[variant] ?? defaultVariant;
}

/**
 * Inline action buttons for recommendations.
 *
 * Uses React Query mutations for consistent error handling
 * and notification feedback on success/failure.
 *
 * @example
 * ```tsx
 * <InlineActions
 *   recommendationId="rec-123"
 *   onAction={(actionId, recId) => console.log(actionId, recId)}
 *   sqlCode="SELECT * FROM table"
 * />
 * ```
 */
export function InlineActions({
  recommendationId,
  actions = DEFAULT_ACTIONS,
  onAction,
  compact = false,
  sqlCode,
}: InlineActionsProps) {
  const addNotification = useUIStore((s) => s.addNotification);
  const [appliedActions, setAppliedActions] = useState<Set<string>>(new Set());
  const [copiedSql, setCopiedSql] = useState(false);

  // Use React Query mutation for action execution
  const mutation = useSimpleActionMutation(onAction);
  const { confirm, dialogProps } = useConfirmation();

  /**
   * Handle action execution with proper error feedback.
   */
  const handleAction = async (actionId: string) => {
    const action = actions.find((a) => a.id === actionId);

    // Handle confirmation
    if (action?.confirmRequired) {
      const confirmed = await confirm({
        title: action.label,
        message: action.confirmMessage || `Are you sure you want to ${action.label}?`,
        severity: "warning",
      });
      if (!confirmed) return;
    }

    // Special handling for copy_sql (client-side only)
    if (actionId === "copy_sql" && sqlCode) {
      try {
        await navigator.clipboard.writeText(sqlCode);
        setCopiedSql(true);
        setTimeout(() => setCopiedSql(false), 2000);
        addNotification({
          message: "SQL copied to clipboard",
          type: "success",
          duration: 2000,
        });
      } catch {
        addNotification({
          message: "Failed to copy SQL",
          type: "error",
          duration: 3000,
        });
      }
      return;
    }

    // Execute action via mutation
    mutation.mutate(
      { actionId, recommendationId },
      {
        onSuccess: () => {
          setAppliedActions((prev) => new Set(prev).add(actionId));
          addNotification({
            message: `${action?.label || "Action"} completed`,
            type: "success",
            duration: 3000,
          });
        },
        onError: (error) => {
          addNotification({
            message: error.message || "Action failed. Please try again.",
            type: "error",
            duration: 5000,
          });
        },
      }
    );
  };

  // Filter out copy_sql if no SQL code provided
  const visibleActions = actions.filter(
    (action) => action.id !== "copy_sql" || sqlCode
  );

  // Track which action is currently loading
  const loadingActionId =
    mutation.isPending && mutation.variables?.actionId
      ? mutation.variables.actionId
      : null;

  return (
    <Box
      sx={{
        display: "flex",
        flexWrap: "wrap",
        gap: compact ? 0.5 : 1,
        mt: 1.5,
      }}
    >
      {visibleActions.map((action) => {
        const Icon = action.icon;
        const isApplied = appliedActions.has(action.id);
        const isLoading = loadingActionId === action.id;
        const isCopyAction = action.id === "copy_sql";
        const { color, variant } = getVariantProps(action.variant, isApplied);

        // For copy action, show copied state
        const showCopied = isCopyAction && copiedSql;

        if (compact) {
          return (
            <Tooltip key={action.id} title={action.label}>
              <span>
                <IconButton
                  size="small"
                  onClick={() => handleAction(action.id)}
                  disabled={isLoading || (isApplied && !isCopyAction)}
                  color={
                    showCopied ? "success" : isApplied ? "success" : "default"
                  }
                  sx={{
                    border: 1,
                    borderColor: "divider",
                    "&:hover": {
                      borderColor: "primary.main",
                    },
                  }}
                >
                  {isLoading ? (
                    <CircularProgress size={16} />
                  ) : isApplied && action.id === "mark_applied" ? (
                    <CheckCircleIcon fontSize="small" />
                  ) : (
                    <Icon fontSize="small" />
                  )}
                </IconButton>
              </span>
            </Tooltip>
          );
        }

        return (
          <Tooltip key={action.id} title={action.label}>
            <span>
              <Button
                size="small"
                onClick={() => handleAction(action.id)}
                disabled={isLoading || (isApplied && !isCopyAction)}
                color={showCopied ? "success" : color}
                variant={showCopied ? "contained" : variant}
                startIcon={
                  isLoading ? (
                    <CircularProgress size={16} color="inherit" />
                  ) : isApplied && action.id === "mark_applied" ? (
                    <CheckCircleIcon />
                  ) : (
                    <Icon />
                  )
                }
                sx={{
                  textTransform: "none",
                  fontWeight: 500,
                  fontSize: "0.8125rem",
                }}
              >
                {isLoading
                  ? "..."
                  : showCopied
                    ? "Copied!"
                    : isApplied
                      ? "Applied"
                      : action.label}
              </Button>
            </span>
          </Tooltip>
        );
      })}
      <ConfirmationDialog {...dialogProps} />
    </Box>
  );
}

export default InlineActions;
