/**
 * ChartView component.
 *
 * Displays server-rendered chart images from the FinOps Analytics Agent.
 * Uses React Query for data fetching with proper loading, error, and success states.
 *
 * Features:
 * - Fetches chart image using React Query with automatic retry
 * - Shows loading spinner while fetching
 * - Handles errors with retry option
 * - Gracefully handles expired cache data
 * - Download button for saving chart as PNG
 */

"use client";

import React, { useRef, useEffect } from "react";
import { Box, CircularProgress, Typography, Button } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import RefreshIcon from "@mui/icons-material/Refresh";
import { useTheme } from "@mui/material/styles";
import { useChartData } from "@/lib/hooks";
import type { ChartConfig } from "@/lib/types/chart";
import { downloadFromUrl, generateFilename } from "@/lib/utils/file-download";
import { logger } from "@/lib/utils/logger";

interface ChartViewProps {
  /** Cache key for dataset */
  dataReference: string;
  /** Chart configuration from LLM */
  chartConfig: ChartConfig;
}

/**
 * ChartView component.
 *
 * Fetches and displays a server-rendered chart image as PNG.
 * Uses React Query for data management with automatic retry and caching.
 *
 * @param props - Component props
 * @returns ChartView component
 *
 * @example
 * ```tsx
 * <ChartView
 *   dataReference="data_ref_abc123"
 *   chartConfig={chartConfig}
 * />
 * ```
 */
export function ChartView({ dataReference, chartConfig }: ChartViewProps) {
  const theme = useTheme();
  const imageUrlRef = useRef<string | null>(null);

  // Use React Query hook for chart data fetching
  const { data, isLoading, error, refetch, isExpiredError } = useChartData({
    dataReference,
    chartConfig,
  });

  // Keep ref updated for cleanup and download
  useEffect(() => {
    if (data?.imageUrl) {
      imageUrlRef.current = data.imageUrl;
    }
    // Cleanup blob URL when component unmounts or data changes
    return () => {
      if (imageUrlRef.current && imageUrlRef.current !== data?.imageUrl) {
        URL.revokeObjectURL(imageUrlRef.current);
        imageUrlRef.current = null;
      }
    };
  }, [data?.imageUrl]);

  /**
   * Handle chart download.
   * Creates a download link with the chart image and triggers download.
   */
  const handleDownloadChart = () => {
    const url = data?.imageUrl || imageUrlRef.current;
    if (!url) return;

    // Generate filename using title from config
    const filename = generateFilename(`chart-${chartConfig.title}`, "png");
    downloadFromUrl(url, filename);
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
          Rendering chart...
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
          📊 Chart data expired
        </Typography>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ maxWidth: 500 }}
        >
          Chart data is cached for 10 minutes after the query runs. This
          conversation was loaded from history, so the chart data is no longer
          available.
        </Typography>
        <Typography
          variant="caption"
          color="text.disabled"
          sx={{ mt: 1, fontStyle: "italic" }}
        >
          Tip: Send a new query to regenerate the chart
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
          Failed to load chart
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
   * Success state: Display chart image with download button.
   */
  logger.debug('[ChartView] Rendering success state:', {
    hasData: !!data,
    hasImageUrl: !!data?.imageUrl,
    imageUrl: data?.imageUrl,
    chartTitle: chartConfig.title,
  });
  
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 2,
      }}
    >
      {/* Chart Image */}
      <Box
        sx={{
          width: "100%",
          display: "flex",
          justifyContent: "center",
          bgcolor:
            theme.palette.mode === "dark"
              ? "rgba(255, 255, 255, 0.02)"
              : "rgba(0, 0, 0, 0.01)",
          borderRadius: 1,
          p: 2,
        }}
      >
        {data?.imageUrl ? (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={data.imageUrl}
            alt={`${chartConfig.title}${chartConfig.description ? ` - ${chartConfig.description}` : ""}`}
            style={{
              maxWidth: "100%",
              height: "auto",
              display: "block",
            }}
            onError={(e) => console.error('[ChartView] Image failed to load:', e)}
          />
        ) : (
          <Typography color="text.secondary">No image URL available</Typography>
        )}
      </Box>

      {/* Download Button */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-end",
          width: "100%",
        }}
      >
        <Button
          variant="outlined"
          size="small"
          startIcon={<DownloadIcon />}
          onClick={handleDownloadChart}
          sx={{
            textTransform: "none",
          }}
        >
          Save Chart
        </Button>
      </Box>
    </Box>
  );
}
