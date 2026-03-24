/**
 * Budget exhausted alert component.
 *
 * Displays a prominent warning when the agent's token budget was exhausted
 * and the analysis may be incomplete or truncated.
 */

"use client";

import React from "react";
import { Alert, AlertTitle, Box, Typography } from "@mui/material";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";

interface BudgetExhaustedAlertProps {
  /** Custom message to display (optional) */
  message?: string;
  /** Whether to show suggestions for the user */
  showSuggestions?: boolean;
}

/**
 * Alert component shown when the agent's token budget is exhausted.
 *
 * @param props - Component props
 * @returns Budget exhausted alert component
 *
 * @example
 * ```tsx
 * <BudgetExhaustedAlert />
 * <BudgetExhaustedAlert
 *   message="Analysis was limited due to token budget"
 *   showSuggestions={false}
 * />
 * ```
 */
export function BudgetExhaustedAlert({
  message,
  showSuggestions = true,
}: BudgetExhaustedAlertProps) {
  return (
    <Alert
      severity="warning"
      icon={<WarningAmberIcon sx={{ fontSize: 28 }} />}
      sx={{
        mb: 2,
        borderRadius: 2,
        border: "2px solid",
        borderColor: "warning.main",
        bgcolor: (theme) =>
          theme.palette.mode === "dark"
            ? "rgba(255, 167, 38, 0.15)"
            : "rgba(255, 167, 38, 0.12)",
        "& .MuiAlert-icon": {
          alignItems: "flex-start",
          pt: 0.5,
          color: "warning.main",
        },
        "& .MuiAlert-message": {
          width: "100%",
        },
      }}
    >
      <AlertTitle
        sx={{
          fontWeight: 700,
          mb: 0.5,
          color: "warning.dark",
          fontSize: "1rem",
        }}
      >
        ⚠️ Partial Analysis - Token Budget Exhausted
      </AlertTitle>
      <Typography
        variant="body2"
        sx={{
          mb: showSuggestions ? 1.5 : 0,
          color: "text.primary",
        }}
      >
        {message ||
          "The agent ran out of tokens before completing the full analysis. The results below show what was gathered before the limit was reached."}
      </Typography>
      {showSuggestions && (
        <Box
          component="ul"
          sx={{
            m: 0,
            pl: 2.5,
            color: "text.secondary",
            "& li": {
              mb: 0.75,
              "&:last-child": { mb: 0 },
            },
          }}
        >
          <li>
            <Typography variant="body2">
              For large workloads, try increasing the token budget, reducing max steps, or narrowing the scope of your question.
            </Typography>
          </li>
          <li>
            <Typography variant="body2">
              Use the suggested next steps below to continue the analysis from where it left off.
            </Typography>
          </li>
        </Box>
      )}
    </Alert>
  );
}

