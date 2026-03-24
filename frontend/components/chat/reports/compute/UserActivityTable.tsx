/**
 * User activity table component for compute reports.
 * 
 * Displays top users with activity breakdown for chargeback reporting.
 */

"use client";

import React from "react";
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  LinearProgress,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type { UserActivitySummary, UserActivity } from "@/lib/types/api";

interface UserActivityTableProps {
  activity: UserActivitySummary;
}

function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let unitIndex = 0;
  let value = bytes;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }

  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function UserRow({ user, maxQueries }: { user: UserActivity; maxQueries: number }) {
  const theme = useTheme();
  const queryPct = (user.query_count / maxQueries) * 100;

  return (
    <TableRow hover>
      <TableCell>
        <Typography variant="body2" fontWeight={500}>
          {user.user_email}
        </Typography>
      </TableCell>
      <TableCell align="right">
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Box sx={{ flex: 1, minWidth: 60 }}>
            <LinearProgress
              variant="determinate"
              value={queryPct}
              sx={{
                height: 6,
                borderRadius: 1,
                bgcolor: "rgba(0, 0, 0, 0.1)",
                "& .MuiLinearProgress-bar": {
                  bgcolor: theme.palette.primary.main,
                },
              }}
            />
          </Box>
          <Typography variant="body2">
            {user.query_count.toLocaleString()}
          </Typography>
        </Box>
      </TableCell>
      <TableCell align="right">
        <Typography variant="body2">
          {formatDuration(user.total_runtime_seconds)}
        </Typography>
      </TableCell>
      <TableCell align="right">
        <Typography variant="body2">
          {formatBytes(user.bytes_scanned)}
        </Typography>
      </TableCell>
      {user.cost_attribution_pct !== undefined && (
        <TableCell align="right">
          <Chip
            label={`${user.cost_attribution_pct.toFixed(1)}%`}
            size="small"
            color={user.cost_attribution_pct > 25 ? "warning" : "default"}
            sx={{ fontWeight: 600 }}
          />
        </TableCell>
      )}
    </TableRow>
  );
}

export function UserActivityTable({ activity }: UserActivityTableProps) {
  const theme = useTheme();
  const maxQueries = Math.max(...(activity.top_users?.map((u) => u.query_count) || [1]));
  const showCostColumn = activity.top_users?.some((u) => u.cost_attribution_pct !== undefined);

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Typography variant="subtitle1" fontWeight={600}>
          👥 User Activity
        </Typography>
        {activity.period && (
          <Chip label={activity.period} size="small" variant="outlined" />
        )}
      </Box>

      {activity.allocation_method && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1.5 }}>
          Allocation method: {activity.allocation_method}
        </Typography>
      )}

      {activity.top_users && activity.top_users.length > 0 ? (
        <TableContainer
          component={Paper}
          variant="outlined"
          sx={{
            bgcolor: theme.palette.mode === "dark"
              ? "rgba(255, 255, 255, 0.02)"
              : "rgba(0, 0, 0, 0.02)",
          }}
        >
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>User</TableCell>
                <TableCell align="right">Queries</TableCell>
                <TableCell align="right">Runtime</TableCell>
                <TableCell align="right">Bytes Scanned</TableCell>
                {showCostColumn && <TableCell align="right">Cost %</TableCell>}
              </TableRow>
            </TableHead>
            <TableBody>
              {activity.top_users.slice(0, 10).map((user) => (
                <UserRow key={user.user_email} user={user} maxQueries={maxQueries} />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No user activity data available.
        </Typography>
      )}
    </Box>
  );
}

