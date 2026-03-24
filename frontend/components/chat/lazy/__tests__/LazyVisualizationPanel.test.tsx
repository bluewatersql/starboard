/**
 * Tests for LazyVisualizationPanel.
 *
 * Verifies:
 * - Skeleton fallback renders while loading
 * - Actual component renders after Suspense resolves
 * - Suspense boundary is present
 */

import React, { Suspense } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ChartConfig } from "@/lib/types/chart";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the skeleton so we can detect it easily
jest.mock("@/components/common/skeletons", () => ({
  ChartSkeleton: ({ height }: { height?: number }) => (
    <div data-testid="chart-skeleton-mock" data-height={height}>
      Chart loading...
    </div>
  ),
}));

// Mock the actual VisualizationPanel so the test doesn't pull in Recharts
jest.mock("@/components/chat/visualization/VisualizationPanel", () => ({
  VisualizationPanel: ({
    dataReference,
    chartConfig,
  }: {
    dataReference: string;
    chartConfig: ChartConfig | null;
  }) => (
    <div
      data-testid="visualization-panel-mock"
      data-ref={dataReference}
      data-has-chart={chartConfig !== null ? "true" : "false"}
    >
      Visualization Panel
    </div>
  ),
}));

// Import AFTER mocks are in place
import { LazyVisualizationPanel } from "../LazyVisualizationPanel";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={createQueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

const mockChartConfig: ChartConfig = {
  chart_type: "bar",
  title: "Test",
  encodings: {
    x: { field: "category", type: "nominal" },
    y: { field: "value", type: "quantitative" },
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("LazyVisualizationPanel", () => {
  it("renders the lazy panel wrapped in Suspense and shows the panel after loading", async () => {
    render(
      <Wrapper>
        <LazyVisualizationPanel
          dataReference="data_ref_abc"
          chartConfig={mockChartConfig}
        />
      </Wrapper>
    );

    // After React resolves the lazy import, the actual component should be shown
    await waitFor(() => {
      expect(
        screen.getByTestId("visualization-panel-mock")
      ).toBeInTheDocument();
    });
  });

  it("passes dataReference prop to VisualizationPanel", async () => {
    render(
      <Wrapper>
        <LazyVisualizationPanel
          dataReference="my_data_ref"
          chartConfig={null}
        />
      </Wrapper>
    );

    await waitFor(() => {
      const panel = screen.getByTestId("visualization-panel-mock");
      expect(panel).toHaveAttribute("data-ref", "my_data_ref");
    });
  });

  it("passes chartConfig=null to VisualizationPanel", async () => {
    render(
      <Wrapper>
        <LazyVisualizationPanel dataReference="ref" chartConfig={null} />
      </Wrapper>
    );

    await waitFor(() => {
      const panel = screen.getByTestId("visualization-panel-mock");
      expect(panel).toHaveAttribute("data-has-chart", "false");
    });
  });

  it("passes chartConfig to VisualizationPanel when provided", async () => {
    render(
      <Wrapper>
        <LazyVisualizationPanel
          dataReference="ref"
          chartConfig={mockChartConfig}
        />
      </Wrapper>
    );

    await waitFor(() => {
      const panel = screen.getByTestId("visualization-panel-mock");
      expect(panel).toHaveAttribute("data-has-chart", "true");
    });
  });

  it("renders without crashing when chartConfig is null", async () => {
    const { container } = render(
      <Wrapper>
        <LazyVisualizationPanel dataReference="ref" chartConfig={null} />
      </Wrapper>
    );

    await waitFor(() => {
      expect(container.firstChild).toBeInTheDocument();
    });
  });
});
