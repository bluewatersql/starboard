/**
 * Unit tests for VisualizationPanel component.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VisualizationPanel } from "../VisualizationPanel";
import * as chartApi from "@/lib/api/chart";
import type { ChartConfig } from "@/lib/types/chart";

// Mock the API
jest.mock("@/lib/api/chart");
const mockRenderChart = chartApi.renderChart as jest.MockedFunction<
  typeof chartApi.renderChart
>;
const mockFetchCachedData = chartApi.fetchCachedData as jest.MockedFunction<
  typeof chartApi.fetchCachedData
>;

// Mock chart config
const mockChartConfig: ChartConfig = {
  chart_type: "bar",
  title: "Test Chart",
  encodings: {
    x: { field: "category", type: "nominal" },
    y: { field: "value", type: "quantitative" },
  },
};

// Mock data — matches CachedDataResponse interface
const mockData = {
  version: 1,
  orientation: "records" as const,
  schema: {
    category: { dtype: "Utf8", encoding: "native" },
    value: { dtype: "Float64", encoding: "float_finite_only" },
  },
  data: [
    { category: "A", value: 100 },
    { category: "B", value: 200 },
  ],
  row_count: 2,
};

// Mock URL methods
global.URL.createObjectURL = jest.fn(() => "blob:mock-url");
global.URL.revokeObjectURL = jest.fn();

/**
 * Create a wrapper with QueryClientProvider for tests.
 */
function createTestWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return function TestWrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("VisualizationPanel", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRenderChart.mockResolvedValue(new Blob(["mock"], { type: "image/png" }));
    mockFetchCachedData.mockResolvedValue(mockData);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("renders with toggle buttons when chart is available", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Verify header with toggle buttons
    expect(screen.getByText(/data visualization/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show chart view/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show data table/i })
    ).toBeInTheDocument();

    // Wait for chart to load (default view)
    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });
  });

  it('hides toggle buttons when chart type is "table"', async () => {
    const tableConfig: ChartConfig = {
      ...mockChartConfig,
      chart_type: "table",
    };

    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={tableConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Toggle buttons should not be present
    expect(screen.queryByText(/data visualization/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show chart view/i })
    ).not.toBeInTheDocument();

    // Should show table directly
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });
  });

  it("hides toggle buttons when chartConfig is null", async () => {
    render(
      <VisualizationPanel dataReference="data_ref_test" chartConfig={null} />,
      { wrapper: createTestWrapper() }
    );

    // Toggle buttons should not be present
    expect(screen.queryByText(/data visualization/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show chart view/i })
    ).not.toBeInTheDocument();

    // Should show table directly
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });
  });

  it("defaults to chart view when chart is available", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Wait for chart to load
    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    // Chart button should be active
    const chartButton = screen.getByRole("button", { name: /show chart view/i });
    expect(chartButton).toHaveAttribute("aria-pressed", "true");

    // Table should not be present
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("defaults to table view when chart is not available", async () => {
    render(
      <VisualizationPanel dataReference="data_ref_test" chartConfig={null} />,
      { wrapper: createTestWrapper() }
    );

    // Wait for table to load
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });

    // Chart should not be present
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("toggles from chart to table view", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Wait for chart to load
    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    // Click table button
    const tableButton = screen.getByRole("button", { name: /show data table/i });
    fireEvent.click(tableButton);

    // Wait for table to appear
    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });

    // Chart should not be present
    expect(screen.queryByRole("img")).not.toBeInTheDocument();

    // Table button should be active
    expect(tableButton).toHaveAttribute("aria-pressed", "true");
  });

  it("toggles from table to chart view", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Wait for initial chart load
    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    // Switch to table
    const tableButton = screen.getByRole("button", { name: /show data table/i });
    fireEvent.click(tableButton);

    await waitFor(() => {
      expect(screen.getByRole("table")).toBeInTheDocument();
    });

    // Switch back to chart
    const chartButton = screen.getByRole("button", { name: /show chart view/i });
    fireEvent.click(chartButton);

    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    // Table should not be present
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    // Chart button should be active
    expect(chartButton).toHaveAttribute("aria-pressed", "true");
  });

  it("highlights active button correctly", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    const chartButton = screen.getByRole("button", { name: /show chart view/i });
    const tableButton = screen.getByRole("button", { name: /show data table/i });

    // Initially chart button is active
    expect(chartButton).toHaveAttribute("aria-pressed", "true");
    expect(tableButton).toHaveAttribute("aria-pressed", "false");

    // Click table button
    fireEvent.click(tableButton);

    // Now table button is active
    expect(chartButton).toHaveAttribute("aria-pressed", "false");
    expect(tableButton).toHaveAttribute("aria-pressed", "true");
  });

  it("passes correct props to ChartView", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    await waitFor(() => {
      expect(mockRenderChart).toHaveBeenCalledWith(
        "data_ref_test",
        mockChartConfig
      );
    });
  });

  it("passes correct props to DataTableView", async () => {
    render(
      <VisualizationPanel dataReference="data_ref_test" chartConfig={null} />,
      { wrapper: createTestWrapper() }
    );

    await waitFor(() => {
      expect(mockFetchCachedData).toHaveBeenCalledWith("data_ref_test");
    });
  });

  it("does not fetch table data until switched to table view", async () => {
    render(
      <VisualizationPanel
        dataReference="data_ref_test"
        chartConfig={mockChartConfig}
      />,
      { wrapper: createTestWrapper() }
    );

    // Wait for chart to load
    await waitFor(() => {
      expect(screen.getByRole("img")).toBeInTheDocument();
    });

    // Table data should not be fetched yet
    expect(mockFetchCachedData).not.toHaveBeenCalled();

    // Switch to table view
    const tableButton = screen.getByRole("button", { name: /show data table/i });
    fireEvent.click(tableButton);

    // Now table data should be fetched
    await waitFor(() => {
      expect(mockFetchCachedData).toHaveBeenCalledWith("data_ref_test");
    });
  });
});
