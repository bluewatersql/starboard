/**
 * Generic data table component for report outputs.
 *
 * Renders tabular data from agent responses (chargeback, user activity, etc.)
 * with sorting, export, and responsive display.
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
  Button,
  Chip,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import DownloadIcon from "@mui/icons-material/Download";
import { downloadCsv, generateFilename } from "@/lib/utils/file-download";
import type { DataTable } from "@/lib/types/api";

interface DataTableViewProps {
  table: DataTable;
}

type SortDirection = "asc" | "desc";

/**
 * Format a cell value for display.
 */
function formatCellValue(value: string | number | null): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") {
    // Format currency-like values
    if (Math.abs(value) >= 100 || value === 0) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    // Format percentages and small numbers
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(value);
}

/**
 * Generic data table component for report outputs.
 *
 * Used for chargeback reports, user activity, cost breakdowns, etc.
 * Features:
 * - Sortable columns
 * - CSV export
 * - Summary row with totals
 *
 * @example
 * ```tsx
 * <DataTableView
 *   table={{
 *     title: "Chargeback Report",
 *     columns: ["User", "Queries", "Cost ($)"],
 *     rows: [["alice@example.com", 500, 540.82]],
 *     summary: { total_cost_usd: 1523.45 }
 *   }}
 * />
 * ```
 */
export function DataTableView({ table }: DataTableViewProps) {
  const theme = useTheme();
  const [sortColumn, setSortColumn] = useState<number | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  // Sort rows
  const sortedRows = useMemo(() => {
    if (sortColumn === null) return table.rows;

    return [...table.rows].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];

      // Handle nulls
      if (aVal === null && bVal === null) return 0;
      if (aVal === null) return sortDirection === "asc" ? -1 : 1;
      if (bVal === null) return sortDirection === "asc" ? 1 : -1;

      // Numeric comparison
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDirection === "asc" ? aVal - bVal : bVal - aVal;
      }

      // String comparison
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      return sortDirection === "asc"
        ? aStr.localeCompare(bStr)
        : bStr.localeCompare(aStr);
    });
  }, [table.rows, sortColumn, sortDirection]);

  // Handle sort click
  const handleSort = (columnIndex: number) => {
    if (sortColumn === columnIndex) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortColumn(columnIndex);
      setSortDirection("desc");
    }
  };

  // Export to CSV
  const handleExportCSV = () => {
    const csvRows = [
      table.columns.join(","),
      ...table.rows.map((row) =>
        row.map((cell) => {
          const val = cell === null ? "" : String(cell);
          // Escape quotes and wrap in quotes if contains comma
          if (val.includes(",") || val.includes('"')) {
            return `"${val.replace(/"/g, '""')}"`;
          }
          return val;
        }).join(",")
      ),
    ];
    const csvContent = csvRows.join("\n");
    const filename = generateFilename(
      table.title.toLowerCase().replace(/\s+/g, "-"),
      "csv"
    );
    downloadCsv(csvContent, filename);
  };

  return (
    <Box sx={{ mb: 3 }}>
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          mb: 2,
        }}
      >
        <Box>
          <Typography variant="subtitle1" fontWeight={600}>
            {table.title}
          </Typography>
          {table.description && (
            <Typography variant="body2" color="text.secondary">
              {table.description}
            </Typography>
          )}
          {table.total_rows && (
            <Chip
              label={`${table.total_rows} rows`}
              size="small"
              variant="outlined"
              sx={{ mt: 0.5 }}
            />
          )}
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

      {/* Summary chips */}
      {table.summary && Object.keys(table.summary).length > 0 && (
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
          {Object.entries(table.summary).map(([key, value]) => (
            <Chip
              key={key}
              label={`${key.replace(/_/g, " ")}: ${formatCellValue(value)}`}
              size="small"
              color="primary"
              variant="outlined"
            />
          ))}
        </Box>
      )}

      {/* Table */}
      <TableContainer
        component={Paper}
        variant="outlined"
        sx={{
          maxHeight: 500,
          overflowX: "auto",
          overflowY: "auto",
          position: "relative",
          bgcolor:
            theme.palette.mode === "dark"
              ? "rgba(255, 255, 255, 0.02)"
              : "rgba(0, 0, 0, 0.02)",
        }}
      >
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              {table.columns.map((column, index) => (
                <TableCell
                  key={index}
                  sortDirection={sortColumn === index ? sortDirection : false}
                  sx={{
                    fontWeight: 600,
                    // Use solid background color to prevent content showing through
                    bgcolor:
                      theme.palette.mode === "dark"
                        ? theme.palette.grey[900]
                        : theme.palette.grey[100],
                    // Ensure sticky header stays above body content
                    zIndex: 2,
                    position: "sticky",
                    top: 0,
                  }}
                >
                  <TableSortLabel
                    active={sortColumn === index}
                    direction={sortColumn === index ? sortDirection : "asc"}
                    onClick={() => handleSort(index)}
                  >
                    {column}
                  </TableSortLabel>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedRows.map((row, rowIndex) => (
              <TableRow key={rowIndex} hover>
                {row.map((cell, cellIndex) => (
                  <TableCell key={cellIndex}>
                    {formatCellValue(cell)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Row count */}
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ mt: 1, display: "block" }}
      >
        Showing {sortedRows.length} of {table.total_rows || sortedRows.length} rows
      </Typography>
    </Box>
  );
}

