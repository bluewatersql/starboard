/**
 * File download utilities.
 *
 * Consolidates file download logic used across multiple components.
 * Handles both text content and blobs, with proper cleanup.
 *
 * @module lib/utils/file-download
 */

export interface DownloadOptions {
  /** File content (string) or Blob */
  content: string | Blob;
  /** Filename for download */
  filename: string;
  /** MIME type (required for string content, ignored for Blob) */
  mimeType?: string;
}

/**
 * Download content as a file.
 *
 * Handles both text content and blobs. Creates a temporary download link,
 * triggers the download, and cleans up immediately.
 *
 * @param options - Download options
 *
 * @example
 * // Download text content
 * downloadFile({
 *   content: 'Hello, world!',
 *   filename: 'hello.txt',
 *   mimeType: 'text/plain'
 * });
 *
 * @example
 * // Download CSV
 * downloadFile({
 *   content: 'col1,col2\nval1,val2',
 *   filename: 'data.csv',
 *   mimeType: 'text/csv;charset=utf-8;'
 * });
 *
 * @example
 * // Download existing blob
 * downloadFile({
 *   content: imageBlob,
 *   filename: 'chart.png'
 * });
 */
export function downloadFile({ content, filename, mimeType }: DownloadOptions): void {
  // Create blob from content if it's a string
  const blob =
    content instanceof Blob
      ? content
      : new Blob([content], { type: mimeType || "text/plain" });

  // Create object URL for download
  const url = URL.createObjectURL(blob);

  // Create and configure download link
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;

  // Trigger download
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  // Clean up immediately
  URL.revokeObjectURL(url);
}

/**
 * Download from an existing object URL.
 *
 * Use this when you already have an object URL (e.g., from fetched image).
 * Note: This does NOT revoke the URL after download - caller is responsible
 * for URL lifecycle management.
 *
 * @param url - Object URL to download from
 * @param filename - Filename for download
 *
 * @example
 * const imageUrl = URL.createObjectURL(blob);
 * downloadFromUrl(imageUrl, 'chart.png');
 * // Don't forget to revoke when done with the URL
 */
export function downloadFromUrl(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/**
 * Generate a timestamped filename.
 *
 * Creates a filename with format: {base}-{YYYY-MM-DD}.{extension}
 * Sanitizes the base name to remove special characters.
 *
 * @param base - Base name for the file (will be sanitized)
 * @param extension - File extension (without dot)
 * @returns Sanitized filename with timestamp
 *
 * @example
 * generateFilename('My Report!', 'pdf')
 * // Returns: 'my-report-2024-01-15.pdf'
 *
 * @example
 * generateFilename('Sales Data Q4', 'csv')
 * // Returns: 'sales-data-q4-2024-01-15.csv'
 */
export function generateFilename(base: string, extension: string): string {
  const timestamp = new Date().toISOString().split("T")[0];
  const sanitized = base
    .replace(/[^a-z0-9]/gi, "-")
    .toLowerCase()
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return `${sanitized}-${timestamp}.${extension}`;
}

/**
 * Download content as JSON file.
 *
 * Convenience wrapper for downloading JSON data.
 *
 * @param data - Data to serialize as JSON
 * @param filename - Filename (will have .json appended if not present)
 * @param pretty - Whether to pretty-print the JSON (default: true)
 *
 * @example
 * downloadJson({ name: 'Report', data: [1, 2, 3] }, 'report.json');
 */
export function downloadJson(
  data: unknown,
  filename: string,
  pretty: boolean = true
): void {
  const content = pretty ? JSON.stringify(data, null, 2) : JSON.stringify(data);
  const finalFilename = filename.endsWith(".json") ? filename : `${filename}.json`;

  downloadFile({
    content,
    filename: finalFilename,
    mimeType: "application/json",
  });
}

/**
 * Download content as CSV file.
 *
 * Convenience wrapper for downloading CSV data.
 *
 * @param content - CSV content string
 * @param filename - Filename (will have .csv appended if not present)
 *
 * @example
 * const csv = 'name,value\nfoo,1\nbar,2';
 * downloadCsv(csv, 'data.csv');
 */
export function downloadCsv(content: string, filename: string): void {
  const finalFilename = filename.endsWith(".csv") ? filename : `${filename}.csv`;

  downloadFile({
    content,
    filename: finalFilename,
    mimeType: "text/csv;charset=utf-8;",
  });
}

/**
 * Download content as Markdown file.
 *
 * Convenience wrapper for downloading Markdown data.
 *
 * @param content - Markdown content string
 * @param filename - Filename (will have .md appended if not present)
 *
 * @example
 * downloadMarkdown('# Report\n\nSome content', 'report.md');
 */
export function downloadMarkdown(content: string, filename: string): void {
  const finalFilename = filename.endsWith(".md") ? filename : `${filename}.md`;

  downloadFile({
    content,
    filename: finalFilename,
    mimeType: "text/markdown",
  });
}

