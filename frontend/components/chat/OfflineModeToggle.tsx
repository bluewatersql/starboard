/**
 * OfflineModeToggle component.
 *
 * Switch to force the conversation to OFFLINE mode (no Databricks API calls).
 * Useful for analyzing artifacts without needing Databricks credentials.
 */

"use client";

import React from "react";
import {
  Box,
  Switch,
  FormControlLabel,
  Tooltip,
  Typography,
  Chip,
} from "@mui/material";
import CloudOffIcon from "@mui/icons-material/CloudOff";
import CloudIcon from "@mui/icons-material/Cloud";
import { useConfigStore } from "@/lib/store/configStore";

interface OfflineModeToggleProps {
  /** Compact mode - just the switch, no label */
  compact?: boolean;
}

/**
 * Offline mode toggle component.
 *
 * When enabled, the diagnostic agent will:
 * - Skip all Databricks API calls
 * - Analyze artifacts using only the provided content
 * - Provide guidance instead of tool-enriched responses
 *
 * @example
 * ```tsx
 * <OfflineModeToggle />
 * <OfflineModeToggle compact />
 * ```
 */
export function OfflineModeToggle({ compact = false }: OfflineModeToggleProps) {
  const offlineMode = useConfigStore((s) => s.offlineMode);
  const setOfflineMode = useConfigStore((s) => s.setOfflineMode);

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setOfflineMode(event.target.checked);
  };

  if (compact) {
    return (
      <Tooltip
        title={
          offlineMode
            ? "Offline Mode: No Databricks API calls"
            : "Online Mode: Can use Databricks APIs"
        }
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          {offlineMode ? (
            <CloudOffIcon fontSize="small" color="warning" />
          ) : (
            <CloudIcon fontSize="small" color="primary" />
          )}
          <Switch
            checked={offlineMode}
            onChange={handleChange}
            size="small"
            color={offlineMode ? "warning" : "primary"}
          />
        </Box>
      </Tooltip>
    );
  }

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <FormControlLabel
        control={
          <Switch
            checked={offlineMode}
            onChange={handleChange}
            color={offlineMode ? "warning" : "primary"}
          />
        }
        label={
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            {offlineMode ? (
              <CloudOffIcon fontSize="small" color="warning" />
            ) : (
              <CloudIcon fontSize="small" color="primary" />
            )}
            <Typography variant="body2">
              {offlineMode ? "Offline Mode" : "Online Mode"}
            </Typography>
          </Box>
        }
      />
      {offlineMode && (
        <Chip
          label="No API calls"
          size="small"
          color="warning"
          variant="outlined"
          sx={{ height: 20, fontSize: "0.7rem" }}
        />
      )}
    </Box>
  );
}

