/**
 * Tests for skeleton loading components.
 *
 * Verifies that ChartSkeleton and CodeBlockSkeleton render correctly
 * with default and custom props.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ChartSkeleton } from "../ChartSkeleton";
import { CodeBlockSkeleton } from "../CodeBlockSkeleton";

// ---------------------------------------------------------------------------
// ChartSkeleton
// ---------------------------------------------------------------------------
describe("ChartSkeleton", () => {
  it("renders with data-testid", () => {
    render(<ChartSkeleton />);
    expect(screen.getByTestId("chart-skeleton")).toBeInTheDocument();
  });

  it("renders with default height without crashing", () => {
    const { container } = render(<ChartSkeleton />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders with custom height prop without crashing", () => {
    const { container } = render(<ChartSkeleton height={400} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders skeleton elements for header and chart area", () => {
    const { container } = render(<ChartSkeleton />);
    // MUI Skeleton renders a span with a wave animation class
    const skeletons = container.querySelectorAll(".MuiSkeleton-root");
    // Expect at least the header title + two toggle buttons + chart rect = 4
    expect(skeletons.length).toBeGreaterThanOrEqual(4);
  });
});

// ---------------------------------------------------------------------------
// CodeBlockSkeleton
// ---------------------------------------------------------------------------
describe("CodeBlockSkeleton", () => {
  it("renders with data-testid", () => {
    render(<CodeBlockSkeleton />);
    expect(screen.getByTestId("code-block-skeleton")).toBeInTheDocument();
  });

  it("renders with default 4 line skeletons", () => {
    const { container } = render(<CodeBlockSkeleton />);
    const skeletons = container.querySelectorAll(".MuiSkeleton-root");
    // Header: 1 text + 2 circular icon buttons = 3
    // Body: 4 text lines
    // Total = 7
    expect(skeletons.length).toBeGreaterThanOrEqual(7);
  });

  it("renders with custom lines prop", () => {
    const { container } = render(<CodeBlockSkeleton lines={6} />);
    const skeletons = container.querySelectorAll(".MuiSkeleton-root");
    // Header: 3, body: 6 → total 9
    expect(skeletons.length).toBeGreaterThanOrEqual(9);
  });

  it("renders without crashing when lines=1", () => {
    const { container } = render(<CodeBlockSkeleton lines={1} />);
    expect(container.firstChild).toBeInTheDocument();
  });
});
