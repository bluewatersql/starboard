/**
 * Lazy-loaded heavy components.
 *
 * Import from this barrel to get the lazily-loaded versions that split
 * Recharts and Shiki into separate async chunks.
 *
 * Each wrapper shows a skeleton fallback while the bundle downloads.
 */

export { LazyVisualizationPanel } from "./LazyVisualizationPanel";
export type { LazyVisualizationPanelProps } from "./LazyVisualizationPanel";

export { LazyCodeBlock } from "./LazyCodeBlock";
export type { LazyCodeBlockProps } from "./LazyCodeBlock";
