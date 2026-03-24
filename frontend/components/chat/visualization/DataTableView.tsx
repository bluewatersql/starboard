/**
 * DataTableView component.
 *
 * Displays raw query results in a table format with CSV export functionality.
 * Uses React Query for data fetching with proper loading, error, and success states.
 *
 * Features:
 * - Fetches data using React Query with automatic retry
 * - Shows loading spinner while fetching
 * - Handles errors with retry option
 * - Gracefully handles expired cache data
 * - Displays data in responsive table
 * - Handles null values gracefully (shows "—")
 * - CSV export with proper formatting
 * - Horizontal scroll for wide tables
 */

"use client";

import React from "react";
import {
  Box,
  CircularProgress,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import RefreshIcon from "@mui/icons-material/Refresh";
import { useTheme } from "@mui/material/styles";
import { useTableData } from "@/lib/hooks";
import { downloadCsv, generateFilename } from "@/lib/utils/file-download";

interface DataTableViewProps {
  /** Cache key for dataset */
  dataReference: string;
}

/**
 * Format cell value for display.
 * Shows "—" for null/undefined values.
 */
function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }

  // Format numbers with reasonable precision
  if (typeof value === "number") {
    // If it's a float with many decimals, round to 2 decimal places
    if (!Number.isInteger(value) && Math.abs(value) < 1000000) {
      return value.toFixed(2);
    }
    // For large numbers, use locale string
    if (Math.abs(value) >= 1000) {
      return value.toLocaleString();
    }
  }

  return String(value);
}

/**
 * DataTableView component.
 *
 * Fetches and displays raw query results in a table format.
 * Uses React Query for data management with automatic retry and caching.
 *
 * @param props - Component props
 * @returns DataTableView component
 *
 * @example
 * ```tsx
 * <DataTableView dataReference="data_ref_abc123" />
 * ```
 */
export function DataTableView({ dataReference }: DataTableViewProps) {
  const theme = useTheme();

  // Use React Query hook for data fetching
  const { data, isLoading, error, refetch, isExpiredError } = useTableData({
    dataReference,
  });

  /**
   * Export data as CSV.
   * Handles commas in values by wrapping in quotes.
   * Converts null/undefined values to empty strings.
   */
  const handleExportCSV = () => {
    if (!data) return;

    // Extract rows and columns from the new format
    const rows = data.orientation === "records" 
      ? (data.data as Array<Record<string, unknown>>)
      : []; // TODO(BACKLOG-006): Handle "columns" orientation if needed
    
    const columns = data.schema ? Object.keys(data.schema) : [];
    
    if (rows.length === 0 || columns.length === 0) return;

    // Generate CSV header
    const csvHeader = columns.join(",");

    // Generate CSV rows
    const csvRows = rows.map((row) =>
      columns
        .map((col) => {
          const value = row[col];

          // Handle null/undefined
          if (value === null || value === undefined) {
            return "";
          }

          // Convert to string
          const stringValue = String(value);

          // Wrap in quotes if contains comma, quote, or newline
          if (
            stringValue.includes(",") ||
            stringValue.includes('"') ||
            stringValue.includes("\n")
          ) {
            // Escape quotes by doubling them
            const escapedValue = stringValue.replace(/"/g, '""');
            return `"${escapedValue}"`;
          }

          return stringValue;
        })
        .join(",")
    );

    // Combine header and rows
    const csvContent = [csvHeader, ...csvRows].join("\n");

    // Download using utility
    downloadCsv(csvContent, generateFilename("data", "csv"));
  };

  /**
   * Loading state: Show spinner and text.
   */
  if (isLoading) {
    return (
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 300,
          gap: 2,
        }}
      >
        <CircularProgress size={40} />
        <Typography variant="body2" color="text.secondary">
          Loading data...
        </Typography>
      </Box>
    );
  }

  /**
   * Expired data state: Show friendly message without retry.
   */
  if (isExpiredError) {
    return (
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 200,
          gap: 2,
          p: 3,
          textAlign: "center",
          bgcolor: "background.paper",
          border: "1px solid",
          borderColor: "divider",
          borderRadius: 2,
        }}
      >
        <Typography variant="body1" color="text.secondary" sx={{ mb: 0.5 }}>
          📊 Table data expired
        </Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ maxWidth: 500 }}
        >
          Data is cached for 60 minutes after the query runs. This conversation
          was loaded from history, so the data is no longer available.
        </Typography>
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ mt: 1, fontStyle: "italic" }}
        >
          Tip: Send a new query to regenerate the data
        </Typography>
      </Box>
    );
  }

  /**
   * Error state: Show error message and retry button.
   */
  if (error) {
    const errorMessage =
      error instanceof Error ? error.message : "Unknown error occurred";

    return (
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 300,
          gap: 2,
          p: 3,
          textAlign: "center",
        }}
      >
        <Typography variant="body1" color="error" sx={{ mb: 1 }}>
          Failed to load data
        </Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ maxWidth: 400 }}
        >
          {errorMessage}
        </Typography>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RefreshIcon />}
          onClick={() => refetch()}
          sx={{ mt: 1 }}
        >
          Try Again
        </Button>
      </Box>
    );
  }

  /**
   * Empty state: Show message when no data available.
   */
  // No data yet (shouldn't reach here due to loading guard, but satisfy TS)
  if (!data) return null;

  // Extract rows for display (handle both orientations)
  const rows = data.orientation === "records" 
    ? (data.data as Array<Record<string, unknown>>)
    : []; // TODO: Handle "columns" orientation if needed
  
  const columns = data.schema ? Object.keys(data.schema) : [];
  
  if (rows.length === 0) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          minHeight: 300,
          p: 3,
        }}
      >
        <Typography variant="body2" color="text.secondary">
          No data available
        </Typography>
      </Box>
    );
  }

  /**
   * Success state: Display table with data.
   */
  return (
    <Box sx={{ width: "100%" }}>
      {/* Export Button */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-end",
          mb: 2,
        }}
      >
        <Button
          variant="outlined"
          size="small"
          startIcon={<DownloadIcon />}
          onClick={handleExportCSV}
          sx={{
            textTransform: "none",
          }}
        >
          Export CSV
        </Button>
      </Box>

      {/* Data Table */}
      <TableContainer
        component={Paper}
        sx={{
          maxHeight: 600,
          overflowX: "auto",
          overflowY: "auto",
          border: `1px solid ${theme.palette.divider}`,
          position: "relative",
        }}
      >
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableCell
                  key={column}
                  sx={{
                    bgcolor:
                      theme.palette.mode === "dark" ? "grey.900" : "grey.100",
                    fontWeight: 600,
                    fontSize: "0.75rem",
                    textTransform: "uppercase",
                    letterSpacing: 0.5,
                    color:
                      theme.palette.mode === "dark" ? "grey.400" : "grey.700",
                    whiteSpace: "nowrap",
                    // Ensure sticky header stays above body content
                    zIndex: 2,
                    position: "sticky",
                    top: 0,
                  }}
                >
                  {column}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, rowIndex) => (
              <TableRow
                key={rowIndex}
                sx={{
                  "&:hover": {
                    bgcolor:
                      theme.palette.mode === "dark"
                        ? "rgba(255, 255, 255, 0.05)"
                        : "rgba(0, 0, 0, 0.02)",
                  },
                }}
              >
                {columns.map((column) => (
                  <TableCell
                    key={`${rowIndex}-${column}`}
                    sx={{
                      fontSize: "0.875rem",
                      whiteSpace: "nowrap",
                      color: "text.primary",
                    }}
                  >
                    {formatCellValue(row[column])}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Row count */}
      <Box sx={{ mt: 1, px: 1 }}>
        <Typography variant="caption" color="text.secondary">
          {rows.length} row{rows.length !== 1 ? "s" : ""}
        </Typography>
      </Box>
    </Box>
  );
}
