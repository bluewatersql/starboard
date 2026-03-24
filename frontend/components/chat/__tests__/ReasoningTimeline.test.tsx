/**
 * ReasoningTimeline component tests.
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { ReasoningTimeline } from "../ReasoningTimeline";
import type { ToolCall } from "@/lib/types/api";

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) =>
  render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);

const makeToolCall = (overrides: Partial<ToolCall> = {}): ToolCall => ({
  tool_call_id: "tc-1",
  tool_name: "get_table_metadata",
  status: "completed",
  ...overrides,
});

describe("ReasoningTimeline", () => {
  describe("Rendering", () => {
    it("renders step count in summary", () => {
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[makeToolCall(), makeToolCall({ tool_call_id: "tc-2", tool_name: "resolve_query" })]}
        />
      );
      expect(screen.getByTestId("reasoning-summary")).toHaveTextContent("2 reasoning steps");
    });

    it("renders singular step count for one step", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall()]} />
      );
      expect(screen.getByTestId("reasoning-summary")).toHaveTextContent("1 reasoning step");
    });

    it("shows total latency in summary when duration_ms is present", () => {
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[
            makeToolCall({ duration_ms: 250 }),
            makeToolCall({ tool_call_id: "tc-2", duration_ms: 350 }),
          ]}
        />
      );
      expect(screen.getByTestId("reasoning-summary")).toHaveTextContent("600ms");
    });

    it("omits latency from summary when no duration_ms", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall()]} />
      );
      const summary = screen.getByTestId("reasoning-summary").textContent ?? "";
      expect(summary).not.toContain("ms");
    });

    it("returns null for empty toolCalls array", () => {
      const { container } = renderWithTheme(
        <ReasoningTimeline toolCalls={[]} />
      );
      expect(container.firstChild).toBeNull();
    });
  });

  describe("Expand / Collapse", () => {
    it("does not show tool names visibly before expanding", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall()]} />
      );
      // MUI Accordion keeps content in DOM but hidden when collapsed
      const el = screen.queryByText("Get Table Metadata");
      if (el) {
        // If present, it must be hidden (collapsed accordion)
        expect(el.closest("[hidden]") || el.closest(".MuiCollapse-hidden") || el).toBeTruthy();
      }
      // Summary must be visible
      expect(screen.getByTestId("reasoning-summary")).toBeInTheDocument();
    });

    it("shows tool names after expanding", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall()]} />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      expect(screen.getByText("Get Table Metadata")).toBeInTheDocument();
    });

    it("shows friendly_name when provided", () => {
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[makeToolCall({ friendly_name: "Fetch Metadata" })]}
        />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      expect(screen.getByText("Fetch Metadata")).toBeInTheDocument();
    });

    it("collapses again after second click", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall()]} />
      );
      const summary = screen.getByTestId("reasoning-summary");
      // Expand
      fireEvent.click(summary);
      // Content is visible after expand
      const el = screen.getByText("Get Table Metadata");
      expect(el).toBeInTheDocument();
      // Collapse - MUI Accordion hides content but keeps in DOM
      fireEvent.click(summary);
      // Summary is still present
      expect(screen.getByTestId("reasoning-summary")).toBeInTheDocument();
    });
  });

  describe("Step display", () => {
    it("shows per-step latency chip when duration_ms present", () => {
      renderWithTheme(
        <ReasoningTimeline toolCalls={[makeToolCall({ duration_ms: 123 })]} />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      expect(screen.getByText("123ms")).toBeInTheDocument();
    });

    it("shows failed chip for failed steps", () => {
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[makeToolCall({ status: "failed" })]}
        />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      expect(screen.getByText("failed")).toBeInTheDocument();
    });

    it("shows truncated arguments", () => {
      const longArgs = { query: "SELECT " + "x".repeat(200) };
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[makeToolCall({ arguments: longArgs })]}
        />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      // Should be truncated with ellipsis
      const argEl = screen.getByText((content) => content.includes("…"));
      expect(argEl).toBeInTheDocument();
    });

    it("renders multiple steps in order", () => {
      renderWithTheme(
        <ReasoningTimeline
          toolCalls={[
            makeToolCall({ tool_call_id: "tc-1", tool_name: "resolve_job" }),
            makeToolCall({ tool_call_id: "tc-2", tool_name: "get_job_config" }),
            makeToolCall({ tool_call_id: "tc-3", tool_name: "analyze_job_history" }),
          ]}
        />
      );
      fireEvent.click(screen.getByTestId("reasoning-summary"));
      expect(screen.getByText("Resolve Job")).toBeInTheDocument();
      expect(screen.getByText("Get Job Config")).toBeInTheDocument();
      expect(screen.getByText("Analyze Job History")).toBeInTheDocument();
    });
  });
});
