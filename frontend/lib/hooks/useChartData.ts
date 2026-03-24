/**
 * React Query hook for chart data fetching.
 *
 * Encapsulates chart rendering logic with proper loading, error, and success states.
 * Handles cache expiration gracefully and provides automatic retry on failure.
 */

import { useQuery, UseQueryResult } from "@tanstack/react-query";
import { logger } from "@/lib/utils/logger";
import { renderChart } from "@/lib/api/chart";
import type { ChartConfig } from "@/lib/types/chart";

export interface UseChartDataOptions {
  /** Cache key for dataset */
  dataReference: string;
  /** Chart configuration from LLM */
  chartConfig: ChartConfig;
  /** Whether to enable the query */
  enabled?: boolean;
}

export interface ChartDataResult {
  /** Blob URL for the chart image */
  imageUrl: string;
  /** Whether the error is due to expired data */
  isExpired?: boolean;
}

/**
 * Custom error for expired chart data.
 */
export class ChartExpiredError extends Error {
  constructor(message: string = "Chart data has expired") {
    super(message);
    this.name = "ChartExpiredError";
  }
}

/**
 * Fetch chart image and return blob URL.
 * Throws ChartExpiredError if data has expired.
 */
async function fetchChartImage(
  dataReference: string,
  chartConfig: ChartConfig
): Promise<ChartDataResult> {
  try {
    const blob = await renderChart(dataReference, chartConfig);
    logger.debug('[useChartData] Blob received:', {
      size: blob.size,
      type: blob.type,
      dataReference,
    });

    if (blob.size === 0) {
      console.error('[useChartData] Received empty blob!');
      throw new Error('Received empty image from server');
    }

    const imageUrl = URL.createObjectURL(blob);
    logger.debug('[useChartData] Created blob URL:', imageUrl);
    return { imageUrl };
  } catch (err) {
    console.error('[useChartData] Error fetching chart:', err);
    // Handle expired data gracefully
    if (err instanceof Error && err.name === "DataExpiredError") {
      throw new ChartExpiredError(
        "⏱️ Chart data has expired. This visualization is no longer available."
      );
    }
    throw err;
  }
}

/**
 * Check if an error indicates expired cache data.
 */
export function isChartExpiredError(error: unknown): boolean {
  if (error instanceof ChartExpiredError) return true;
  if (error instanceof Error) {
    return (
      error.name === "ChartExpiredError" ||
      error.message.includes("expired") ||
      error.message.includes("no longer available") ||
      error.message.includes("Chart data has expired")
    );
  }
  return false;
}

/**
 * React Query hook for fetching chart images.
 *
 * @param options - Hook options including data reference and chart config
 * @returns Query result with image URL, loading state, and error handling
 *
 * @example
 * ```tsx
 * const { data, isLoading, error, refetch, isExpiredError } = useChartData({
 *   dataReference: "data_ref_abc123",
 *   chartConfig: { title: "Cost Analysis", chartType: "bar" },
 * });
 *
 * if (isLoading) return <CircularProgress />;
 * if (isExpiredError) return <ExpiredMessage />;
 * if (error) return <ErrorMessage error={error} onRetry={refetch} />;
 * return <img src={data.imageUrl} />;
 * ```
 */
export function useChartData({
  dataReference,
  chartConfig,
  enabled = true,
}: UseChartDataOptions): UseQueryResult<ChartDataResult> & {
  isExpiredError: boolean;
} {
  const query = useQuery({
    queryKey: ["chartImage", dataReference, chartConfig],
    queryFn: () => fetchChartImage(dataReference, chartConfig),
    enabled: enabled && !!dataReference,
    staleTime: 5 * 60 * 1000, // 5 minutes
    // Retry is controlled by the QueryClient in tests (disabled)
    // In production, retry up to 3 times except for expired data errors
    retry: (failureCount, error) => {
      // Don't retry expired data errors
      if (isChartExpiredError(error)) return false;
      // Retry other errors up to 3 times
      return failureCount < 3;
    },
    retryDelay: 0, // No delay between retries
    // Clean up blob URLs when data is removed from cache
    gcTime: 10 * 60 * 1000, // 10 minutes before garbage collection
  });

  return {
    ...query,
    isExpiredError: isChartExpiredError(query.error),
  };
}

