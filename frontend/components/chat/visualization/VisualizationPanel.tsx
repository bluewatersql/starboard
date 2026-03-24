/**
 * VisualizationPanel component.
 * 
 * Container component that provides interactive toggle between chart and table views.
 * Manages view state and renders ChartView or DataTableView based on user selection.
 * 
 * Features:
 * - Toggle buttons for switching between chart and table views
 * - Defaults to chart view if available, otherwise table view
 * - Hides toggle buttons if no chart available (chart_type === "table")
 * - Active button highlighted with theme colors
 * - Smooth transitions between views
 */

"use client";

import React, { useState, useMemo } from 'react';
import { Box, Typography, Button } from '@mui/material';
import BarChartIcon from '@mui/icons-material/BarChart';
import TableChartIcon from '@mui/icons-material/TableChart';
import { useTheme } from '@mui/material/styles';
import { ChartView } from './ChartView';
import { DataTableView } from './DataTableView';
import type { ChartConfig } from '@/lib/types/chart';

interface VisualizationPanelProps {
  /** Cache key for dataset */
  dataReference: string;
  /** Chart configuration from LLM (null if no chart available) */
  chartConfig: ChartConfig | null;
}

/**
 * View mode type for toggle buttons.
 */
type ViewMode = 'chart' | 'table';

/**
 * VisualizationPanel component.
 * 
 * Provides interactive visualization with chart/table toggle.
 * Defaults to chart view if available, otherwise shows table view only.
 * 
 * @param props - Component props
 * @returns VisualizationPanel component
 * 
 * @example
 * ```tsx
 * <VisualizationPanel
 *   dataReference="data_ref_abc123"
 *   chartConfig={chartConfig}
 * />
 * ```
 */
export function VisualizationPanel({
  dataReference,
  chartConfig,
}: VisualizationPanelProps) {
  const theme = useTheme();

  /**
   * Check if chart is available.
   * Chart is available if chartConfig exists AND chart_type is not "table".
   */
  const hasChart = useMemo(() => {
    return chartConfig !== null && chartConfig.chart_type !== 'table';
  }, [chartConfig]);

  /**
   * Determine default view mode.
   * Default to chart if available, otherwise table.
   */
  const defaultViewMode: ViewMode = hasChart ? 'chart' : 'table';

  /**
   * View mode state.
   */
  const [viewMode, setViewMode] = useState<ViewMode>(defaultViewMode);

  /**
   * Get button styles based on active state.
   */
  const getButtonStyles = (isActive: boolean) => ({
    px: 2,
    py: 0.75,
    borderRadius: 1,
    textTransform: 'none' as const,
    fontWeight: isActive ? 600 : 400,
    fontSize: '0.875rem',
    bgcolor: isActive
      ? theme.palette.mode === 'dark'
        ? 'primary.dark'
        : 'primary.light'
      : 'transparent',
    color: isActive
      ? theme.palette.mode === 'dark'
        ? 'primary.light'
        : 'primary.dark'
      : 'text.secondary',
    '&:hover': {
      bgcolor: isActive
        ? theme.palette.mode === 'dark'
          ? 'primary.dark'
          : 'primary.light'
        : theme.palette.mode === 'dark'
        ? 'rgba(255, 255, 255, 0.05)'
        : 'rgba(0, 0, 0, 0.04)',
    },
    transition: 'all 0.2s ease-in-out',
  });

  return (
    <Box
      sx={{
        border: `1px solid ${theme.palette.divider}`,
        borderRadius: 2,
        overflow: 'hidden',
        bgcolor: 'background.paper',
      }}
    >
      {/* Header with toggle buttons (only shown if chart available) */}
      {hasChart && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            px: 2,
            py: 1.5,
            borderBottom: `1px solid ${theme.palette.divider}`,
            bgcolor: theme.palette.mode === 'dark' ? 'rgba(0, 0, 0, 0.2)' : 'rgba(0, 0, 0, 0.02)',
          }}
        >
          {/* Title */}
          <Typography
            variant="subtitle2"
            sx={{
              fontWeight: 600,
              color: 'text.primary',
            }}
          >
            Data Visualization
          </Typography>

          {/* Toggle Buttons */}
          <Box
            sx={{
              display: 'flex',
              gap: 0.5,
              bgcolor: theme.palette.mode === 'dark' ? 'rgba(0, 0, 0, 0.3)' : 'rgba(0, 0, 0, 0.04)',
              borderRadius: 1,
              p: 0.5,
            }}
          >
            {/* Chart Button */}
            <Button
              size="small"
              onClick={() => setViewMode('chart')}
              aria-label="Show chart view"
              aria-pressed={viewMode === 'chart'}
              sx={getButtonStyles(viewMode === 'chart')}
              startIcon={<BarChartIcon sx={{ fontSize: 18 }} />}
            >
              Chart
            </Button>

            {/* Table Button */}
            <Button
              size="small"
              onClick={() => setViewMode('table')}
              aria-label="Show data table"
              aria-pressed={viewMode === 'table'}
              sx={getButtonStyles(viewMode === 'table')}
              startIcon={<TableChartIcon sx={{ fontSize: 18 }} />}
            >
              Data
            </Button>
          </Box>
        </Box>
      )}

      {/* Content Area */}
      <Box sx={{ p: 2 }}>
        {viewMode === 'chart' && hasChart && chartConfig ? (
          <ChartView dataReference={dataReference} chartConfig={chartConfig} />
        ) : (
          <DataTableView dataReference={dataReference} />
        )}
      </Box>
    </Box>
  );
}

