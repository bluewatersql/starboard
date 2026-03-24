/**
 * LazyVisualizationPanel component.
 *
 * Wraps VisualizationPanel with React.lazy + Suspense so that the
 * Recharts (~150 KB) bundle is only downloaded when a chart message
 * actually appears in the conversation.
 *
 * Drop-in replacement for VisualizationPanel — identical props interface.
 */

"use client";

import React, { Suspense, lazy } from "react";
import { ChartSkeleton } from "@/components/common/skeletons";
import type { ChartConfig } from "@/lib/types/chart";

// Lazy-load the full visualization panel (pulls in Recharts)
const VisualizationPanel = lazy(() =>
  import("@/components/chat/visualization/VisualizationPanel").then((mod) => ({
    default: mod.VisualizationPanel,
  }))
);

export interface LazyVisualizationPanelProps {
  /** Cache key for dataset */
  dataReference: string;
  /** Chart configuration from LLM (null if no chart available) */
  chartConfig: ChartConfig | null;
  /** Optional skeleton height in pixels (default: 300) */
  skeletonHeight?: number;
}

/**
 * Lazy-loading wrapper for VisualizationPanel.
 *
 * Shows a ChartSkeleton while the Recharts bundle downloads, then
 * renders the full interactive chart/table UI.
 *
 * @example
 * ```tsx
 * <LazyVisualizationPanel
 *   dataReference="data_ref_abc123"
 *   chartConfig={chartConfig}
 * />
 * ```
 */
export function LazyVisualizationPanel({
  dataReference,
  chartConfig,
  skeletonHeight = 300,
}: LazyVisualizationPanelProps) {
  return (
    <Suspense fallback={<ChartSkeleton height={skeletonHeight} />}>
      <VisualizationPanel
        dataReference={dataReference}
        chartConfig={chartConfig}
      />
    </Suspense>
  );
}
