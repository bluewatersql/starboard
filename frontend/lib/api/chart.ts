/**
 * API client methods for chart rendering and data fetching.
 * 
 * These functions interact with the backend FinOps Analytics Agent endpoints
 * to render charts server-side and fetch cached query results.
 * 
 * Backend endpoints:
 * - POST /api/visualization/render - Renders chart as PNG image
 * - GET /api/data/{data_reference} - Fetches cached query results
 * 
 * @module api/chart
 */

import type { ChartConfig, CachedDataResponse } from '@/lib/types/chart';
import { logger } from '@/lib/utils/logger';

/**
 * Render chart image from cached data.
 * 
 * Sends chart configuration to backend, which:
 * 1. Loads cached data by data_reference
 * 2. Converts ChartConfig to Vega-Lite spec
 * 3. Renders Vega-Lite to PNG image
 * 4. Returns image bytes
 * 
 * The resulting Blob can be converted to an object URL for display:
 * ```typescript
 * const blob = await renderChart(dataRef, chartConfig);
 * const imageUrl = URL.createObjectURL(blob);
 * // Use imageUrl in <img src={imageUrl} />
 * // Remember to revoke: URL.revokeObjectURL(imageUrl)
 * ```
 * 
 * @param dataRef - Cache key for dataset (e.g., "data_ref_abc123")
 * @param chartConfig - Chart configuration from LLM
 * @returns Promise resolving to Blob containing PNG image
 * @throws Error if rendering fails (network error, invalid config, data not found)
 * 
 * @example
 * ```typescript
 * try {
 *   const imageBlob = await renderChart("data_ref_abc123", chartConfig);
 *   const imageUrl = URL.createObjectURL(imageBlob);
 *   setImageUrl(imageUrl);
 * } catch (error) {
 *   console.error("Failed to render chart:", error);
 *   setError(error.message);
 * }
 * ```
 */
export async function renderChart(
  dataRef: string,
  chartConfig: ChartConfig
): Promise<Blob> {
  try {
    logger.debug('[renderChart] Starting chart render:', {
      dataRef,
      chartType: chartConfig.chart_type,
      title: chartConfig.title,
    });
    
    // BUGFIX: LLM sometimes generates encodings with null values (e.g., {"color": null})
    // Backend validator rejects null encoding values - filter them out
    const cleanChartConfig = { ...chartConfig };
    if (cleanChartConfig.encodings && typeof cleanChartConfig.encodings === 'object') {
      const filteredEncodings: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(cleanChartConfig.encodings)) {
        if (value !== null && value !== undefined) {
          filteredEncodings[key] = value;
        }
      }
      cleanChartConfig.encodings = filteredEncodings as Record<string, import("@/lib/types/chart").Encoding>;
    }
    
    const requestBody = {
      chart_config: cleanChartConfig,
      data_reference: dataRef,
      format: 'png',
    };
    
    logger.debug('[renderChart] Request body:', requestBody);
    
    const response = await fetch('/api/visualization/render', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody),
    });

    logger.debug('[renderChart] Response received:', {
      status: response.status,
      ok: response.ok,
      contentType: response.headers.get('content-type'),
      contentLength: response.headers.get('content-length'),
    });

    if (!response.ok) {
      // Try to extract error message from response
      let errorMessage = `Chart rendering failed with status ${response.status}`;
      
      try {
        const errorText = await response.text();
        if (errorText) {
          errorMessage = errorText;
        }
      } catch {
        // If we can't read error text, use default message
      }
      
      throw new Error(errorMessage);
    }

    // Return blob directly
    const blob = await response.blob();
    
    logger.debug('[renderChart] Blob created:', {
      size: blob.size,
      type: blob.type,
    });
    
    // Verify we got a valid image
    if (blob.size === 0) {
      throw new Error('Received empty image from server');
    }
    
    return blob;
  } catch (error) {
    // Check if this is an expired data error (expected for old conversations)
    if (error instanceof Error) {
      const errorMessage = error.message.toLowerCase();
      if (errorMessage.includes('expired') || 
          errorMessage.includes('not found') ||
          errorMessage.includes('no longer available')) {
        // Create custom error for expired data
        const expiredError = new Error('Chart data has expired');
        expiredError.name = 'DataExpiredError';
        throw expiredError;
      }
      // Re-throw with more context for other errors
      throw new Error(`Failed to render chart: ${error.message}`);
    }
    throw new Error('Failed to render chart: Unknown error');
  }
}

/**
 * Fetch cached data for table view.
 * 
 * Retrieves the raw query results that were cached when the SQL query executed.
 * The data is cached with a TTL (typically 10 minutes) and will be automatically
 * cleaned up after expiration.
 * 
 * @param dataRef - Cache key for dataset (e.g., "data_ref_abc123")
 * @returns Promise resolving to cached data with rows, columns, and row count
 * @throws Error if data not found (expired or invalid key) or network error
 * 
 * @example
 * ```typescript
 * try {
 *   const data = await fetchCachedData("data_ref_abc123");
 *   console.log(`Loaded ${data.row_count} rows with columns:`, data.columns);
 *   setTableData(data.rows);
 * } catch (error) {
 *   console.error("Failed to fetch data:", error);
 *   setError(error.message);
 * }
 * ```
 */
export async function fetchCachedData(
  dataRef: string
): Promise<CachedDataResponse> {
  try {
    const response = await fetch(`/api/data/${encodeURIComponent(dataRef)}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      // Handle specific error cases
      if (response.status === 404) {
        throw new Error('Data not found. The cached data may have expired. Please re-run your query.');
      }
      
      // Try to extract error message from response
      let errorMessage = `Failed to fetch data with status ${response.status}`;
      
      try {
        const errorText = await response.text();
        if (errorText) {
          errorMessage = errorText;
        }
      } catch {
        // If we can't read error text, use default message
      }
      
      throw new Error(errorMessage);
    }

    const data = await response.json();
    
    // Validate response structure (new format from polars_df_to_dict)
    if (!data || typeof data !== 'object') {
      throw new Error('Invalid response format from server');
    }
    
    if (typeof data.version !== 'number') {
      throw new Error('Response missing version field');
    }
    
    if (!data.orientation || !['records', 'columns'].includes(data.orientation)) {
      throw new Error('Response missing or invalid orientation field');
    }
    
    if (!data.data) {
      throw new Error('Response missing data field');
    }
    
    if (typeof data.row_count !== 'number') {
      throw new Error('Response missing row_count');
    }
    
    return data as CachedDataResponse;
  } catch (error) {
    // Re-throw with more context
    if (error instanceof Error) {
      // Don't wrap error messages that already have context
      if (error.message.startsWith('Failed to fetch') || error.message.startsWith('Data not found')) {
        throw error;
      }
      throw new Error(`Failed to fetch data: ${error.message}`);
    }
    throw new Error('Failed to fetch data: Unknown error');
  }
}

