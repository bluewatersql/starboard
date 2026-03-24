/**
 * Warehouse table component for compute reports.
 *
 * Displays all warehouses in a sortable table format when the user
 * requests a data listing (e.g., "show me all our SQL warehouses").
 *
 * The agent decides when to include this based on user intent.
 */

"use client";

import React, { useState, useMemo } from "react";
import {
  Box,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Paper,
  Chip,
  Button,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import { useTheme } from "@mui/material/styles";
import { downloadCsv, generateFilename } from "@/lib/utils/file-download";

/**
 * Warehouse data structure from the portfolio tool.
 */
export interface WarehouseData {
  warehouse_id: string;
  warehouse_name: string;
  warehouse_type: string;
  state: string;
  total_queries: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  p99_duration_ms: number;
  avg_queue_time_ms: number;
  queued_query_pct: number;
  unique_users: number;
  error_rate_pct: number;
  health_score: number;
  health_status: "healthy" | "warning" | "critical" | "inactive";
}

interface WarehouseTableProps {
  warehouses: WarehouseData[];
  title?: string;
}

type SortField = keyof WarehouseData;
type SortDirection = "asc" | "desc";

const healthColors = {
  healthy: "#4caf50",
  warning: "#ff9800",
  critical: "#f44336",
  inactive: "#9e9e9e",
} as const;

function formatNumber(value: number, decimals: number = 0): string {
  if (value >= 1000000) {
    return `${(value / 1000000).toFixed(1)}M`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}K`;
  }
  return value.toFixed(decimals);
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

export function WarehouseTable({ warehouses, title = "SQL Warehouses" }: WarehouseTableProps) {
  const theme = useTheme();
  const [sortField, setSortField] = useState<SortField>("total_queries");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const sortedWarehouses = useMemo(() => {
    return [...warehouses].sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];

      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDirection === "asc" ? aVal - bVal : bVal - aVal;
      }
      if (typeof aVal === "string" && typeof bVal === "string") {
        return sortDirection === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }
      return 0;
    });
  }, [warehouses, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  };

  const handleExportCSV = () => {
    const headers = [
      "Name",
      "Type",
      "State",
      "Health Score",
      "Health Status",
      "Total Queries",
      "Unique Users",
      "Avg Duration (ms)",
      "P95 Duration (ms)",
      "Avg Queue Time (ms)",
      "Queued %",
      "Error Rate %",
    ];

    const rows = warehouses.map((w) => [
      w.warehouse_name,
      w.warehouse_type,
      w.state,
      w.health_score,
      w.health_status,
      w.total_queries,
      w.unique_users,
      w.avg_duration_ms,
      w.p95_duration_ms,
      w.avg_queue_time_ms,
      w.queued_query_pct,
      w.error_rate_pct,
    ]);

    const csvContent = [
      headers.join(","),
      ...rows.map((row) => row.map((val) => `"${val}"`).join(",")),
    ].join("\n");

    downloadCsv(csvContent, generateFilename("warehouses", "csv"));
  };

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", mb: 2 }}>
        <Box>
          <Typography variant="subtitle1" fontWeight={600}>
            🏭 {title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Showing {warehouses.length} warehouse{warehouses.length !== 1 ? "s" : ""}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          size="small"
          startIcon={<DownloadIcon />}
          onClick={handleExportCSV}
          sx={{ textTransform: "none" }}
        >
          Export CSV
        </Button>
      </Box>

      <TableContainer
        component={Paper}
        variant="outlined"
        sx={{
          maxHeight: 500,
          bgcolor:
            theme.palette.mode === "dark"
              ? "rgba(255, 255, 255, 0.02)"
              : "rgba(0, 0, 0, 0.02)",
        }}
      >
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>
                <TableSortLabel
                  active={sortField === "warehouse_name"}
                  direction={sortField === "warehouse_name" ? sortDirection : "asc"}
                  onClick={() => handleSort("warehouse_name")}
                >
                  Name
                </TableSortLabel>
              </TableCell>
              <TableCell>Type</TableCell>
              <TableCell>State</TableCell>
              <TableCell align="center">
                <TableSortLabel
                  active={sortField === "health_score"}
                  direction={sortField === "health_score" ? sortDirection : "asc"}
                  onClick={() => handleSort("health_score")}
                >
                  Health
                </TableSortLabel>
              </TableCell>
              <TableCell align="right">
                <TableSortLabel
                  active={sortField === "total_queries"}
                  direction={sortField === "total_queries" ? sortDirection : "asc"}
                  onClick={() => handleSort("total_queries")}
                >
                  Queries
                </TableSortLabel>
              </TableCell>
              <TableCell align="right">
                <TableSortLabel
                  active={sortField === "unique_users"}
                  direction={sortField === "unique_users" ? sortDirection : "asc"}
                  onClick={() => handleSort("unique_users")}
                >
                  Users
                </TableSortLabel>
              </TableCell>
              <TableCell align="right">
                <TableSortLabel
                  active={sortField === "avg_duration_ms"}
                  direction={sortField === "avg_duration_ms" ? sortDirection : "asc"}
                  onClick={() => handleSort("avg_duration_ms")}
                >
                  Avg Duration
                </TableSortLabel>
              </TableCell>
              <TableCell align="right">
                <TableSortLabel
                  active={sortField === "error_rate_pct"}
                  direction={sortField === "error_rate_pct" ? sortDirection : "asc"}
                  onClick={() => handleSort("error_rate_pct")}
                >
                  Error %
                </TableSortLabel>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedWarehouses.map((warehouse) => (
              <TableRow
                key={warehouse.warehouse_id}
                hover
                sx={{
                  "&:hover": {
                    bgcolor:
                      theme.palette.mode === "dark"
                        ? "rgba(255, 255, 255, 0.05)"
                        : "rgba(0, 0, 0, 0.02)",
                  },
                }}
              >
                <TableCell>
                  <Typography variant="body2" fontWeight={500} noWrap sx={{ maxWidth: 200 }}>
                    {warehouse.warehouse_name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace" }}>
                    {warehouse.warehouse_id.slice(0, 8)}...
                  </Typography>
                </TableCell>
                <TableCell>
                  <Chip
                    label={warehouse.warehouse_type}
                    size="small"
                    variant="outlined"
                    sx={{ fontSize: "0.7rem" }}
                  />
                </TableCell>
                <TableCell>
                  <Chip
                    label={warehouse.state}
                    size="small"
                    color={warehouse.state === "RUNNING" ? "success" : "default"}
                    sx={{ fontSize: "0.7rem" }}
                  />
                </TableCell>
                <TableCell align="center">
                  <Chip
                    label={warehouse.health_score}
                    size="small"
                    sx={{
                      bgcolor: healthColors[warehouse.health_status],
                      color: "white",
                      fontWeight: 600,
                      minWidth: 45,
                    }}
                  />
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {formatNumber(warehouse.total_queries)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {warehouse.unique_users}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography variant="body2">
                    {formatDuration(warehouse.avg_duration_ms)}
                  </Typography>
                </TableCell>
                <TableCell align="right">
                  <Typography
                    variant="body2"
                    color={warehouse.error_rate_pct > 10 ? "error" : "text.primary"}
                  >
                    {warehouse.error_rate_pct.toFixed(1)}%
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

