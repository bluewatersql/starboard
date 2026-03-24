/**
 * React Query hook for table data fetching.
 *
 * Encapsulates cached data fetching logic with proper loading, error, and success states.
 * Provides automatic retry on failure and consistent error handling.
 */

import { useQuery, UseQueryResult } from "@tanstack/react-query";
import { fetchCachedData } from "@/lib/api/chart";
import type { CachedDataResponse } from "@/lib/types/chart";

export interface UseTableDataOptions {
  /** Cache key for dataset */
  dataReference: string;
  /** Whether to enable the query */
  enabled?: boolean;
}

/**
 * Custom error for expired table data.
 */
export class TableDataExpiredError extends Error {
  constructor(message: string = "Table data has expired") {
    super(message);
    this.name = "TableDataExpiredError";
  }
}

/**
 * Fetch table data from cache.
 * Returns the full CachedDataResponse with new format.
 */
async function fetchTableData(dataReference: string): Promise<CachedDataResponse> {
  try {
    return await fetchCachedData(dataReference);
  } catch (err) {
    // Handle expired data gracefully
    if (err instanceof Error && err.name === "DataExpiredError") {
      throw new TableDataExpiredError(
        "Table data has expired. This data is no longer available."
      );
    }
    throw err;
  }
}

/**
 * Check if an error indicates expired table data.
 */
export function isTableDataExpiredError(error: unknown): boolean {
  if (error instanceof TableDataExpiredError) return true;
  if (error instanceof Error) {
    return (
      error.name === "TableDataExpiredError" ||
      error.name === "DataExpiredError" ||
      error.message.includes("expired") ||
      error.message.includes("no longer available")
    );
  }
  return false;
}

/**
 * React Query hook for fetching cached table data.
 *
 * Returns the full CachedDataResponse with new format containing:
 * - version: Schema version
 * - orientation: "records" or "columns"
 * - schema: Column metadata
 * - data: Array of records or column arrays
 * - row_count: Total row count
 *
 * @param options - Hook options including data reference
 * @returns Query result with table data, loading state, and error handling
 *
 * @example
 * ```tsx
 * const { data, isLoading, error, refetch, isExpiredError } = useTableData({
 *   dataReference: "data_ref_abc123",
 * });
 *
 * if (isLoading) return <CircularProgress />;
 * if (isExpiredError) return <ExpiredMessage />;
 * if (error) return <ErrorMessage error={error} onRetry={refetch} />;
 * 
 * // Extract rows from new format
 * const rows = data.orientation === "records" 
 *   ? (data.data as Array<Record<string, unknown>>)
 *   : [];
 * const columns = Object.keys(data.schema);
 * return <DataTable rows={rows} columns={columns} />;
 * ```
 */
export function useTableData({
  dataReference,
  enabled = true,
}: UseTableDataOptions): UseQueryResult<CachedDataResponse> & {
  isExpiredError: boolean;
} {
  const query = useQuery({
    queryKey: ["tableData", dataReference],
    queryFn: () => fetchTableData(dataReference),
    enabled: enabled && !!dataReference,
    staleTime: 5 * 60 * 1000, // 5 minutes
    // Retry is controlled by the QueryClient in tests (disabled)
    // In production, retry up to 3 times except for expired data errors
    retry: (failureCount, error) => {
      // Don't retry expired data errors
      if (isTableDataExpiredError(error)) return false;
      // Retry other errors up to 3 times
      return failureCount < 3;
    },
    retryDelay: 0, // No delay between retries
  });

  return {
    ...query,
    isExpiredError: isTableDataExpiredError(query.error),
  };
}

