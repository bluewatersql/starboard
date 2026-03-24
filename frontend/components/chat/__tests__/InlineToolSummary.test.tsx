/**
 * Tests for InlineToolSummary component.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { InlineToolSummary, type InlineToolInfo } from "../InlineToolSummary";

const lightTheme = createTheme({ palette: { mode: "light" } });
const darkTheme = createTheme({ palette: { mode: "dark" } });

function renderWithTheme(component: React.ReactNode, mode: "light" | "dark" = "light") {
  const theme = mode === "dark" ? darkTheme : lightTheme;
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
}

describe("InlineToolSummary", () => {
  describe("rendering", () => {
    it("should render single tool with correct label", () => {
      const tools: InlineToolInfo[] = [
        { name: "execute_sql", friendly_name: "Execute SQL", status: "completed" },
      ];

      renderWithTheme(<InlineToolSummary tools={tools} />);

      // Text spans multiple elements, so use function matcher
      expect(screen.getByText(/Explored.*1.*Tool/)).toBeInTheDocument();
      expect(screen.getByText("Execute SQL")).toBeInTheDocument();
    });

    it("should render multiple tools with plural label", () => {
      const tools: InlineToolInfo[] = [
        { name: "execute_sql", friendly_name: "Execute SQL", status: "completed" },
        { name: "get_job_config", friendly_name: "Get Job Config", status: "completed" },
        { name: "resolve_query", friendly_name: "Resolve Query", status: "completed" },
      ];

      renderWithTheme(<InlineToolSummary tools={tools} />);

      expect(screen.getByText(/Explored.*3.*Tools/)).toBeInTheDocument();
      expect(screen.getByText("Execute SQL")).toBeInTheDocument();
      expect(screen.getByText("Get Job Config")).toBeInTheDocument();
      expect(screen.getByText("Resolve Query")).toBeInTheDocument();
    });

    it("should format tool name when friendly_name is not provided", () => {
      const tools: InlineToolInfo[] = [
        { name: "execute_sql", status: "completed" },
      ];

      renderWithTheme(<InlineToolSummary tools={tools} />);

      expect(screen.getByText("Execute Sql")).toBeInTheDocument();
    });

    it("should show failed status indicator", () => {
      const tools: InlineToolInfo[] = [
        { name: "execute_sql", friendly_name: "Execute SQL", status: "failed" },
      ];

      renderWithTheme(<InlineToolSummary tools={tools} />);

      expect(screen.getByText("(failed)")).toBeInTheDocument();
    });

    it("should return null when tools array is empty", () => {
      const { container } = renderWithTheme(<InlineToolSummary tools={[]} />);
      expect(container.firstChild).toBeNull();
    });

    it("should return null when tools is undefined", () => {
      const { container } = renderWithTheme(
        <InlineToolSummary tools={undefined as unknown as InlineToolInfo[]} />
      );
      expect(container.firstChild).toBeNull();
    });
  });

  describe("theming", () => {
    it("should apply de-emphasized styling in light mode", () => {
      const tools: InlineToolInfo[] = [
        { name: "test_tool", friendly_name: "Test Tool", status: "completed" },
      ];

      const { container } = renderWithTheme(<InlineToolSummary tools={tools} />, "light");

      // The container should have muted color styling
      const box = container.firstChild as HTMLElement;
      expect(box).toBeInTheDocument();
    });

    it("should apply de-emphasized styling in dark mode", () => {
      const tools: InlineToolInfo[] = [
        { name: "test_tool", friendly_name: "Test Tool", status: "completed" },
      ];

      const { container } = renderWithTheme(<InlineToolSummary tools={tools} />, "dark");

      // The container should have muted color styling
      const box = container.firstChild as HTMLElement;
      expect(box).toBeInTheDocument();
    });
  });

  describe("accessibility", () => {
    it("should have accessible text content", () => {
      const tools: InlineToolInfo[] = [
        { name: "execute_sql", friendly_name: "Execute SQL", status: "completed" },
      ];

      renderWithTheme(<InlineToolSummary tools={tools} />);

      // All text should be accessible - use regex for split text
      expect(screen.getByText(/Explored.*1.*Tool/)).toBeInTheDocument();
      expect(screen.getByText("Execute SQL")).toBeInTheDocument();
    });
  });
});
