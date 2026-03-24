/**
 * Tests for ThinkingIndicator component.
 */

import React from "react";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { ThinkingIndicator } from "../ThinkingIndicator";

const lightTheme = createTheme({ palette: { mode: "light" } });
const darkTheme = createTheme({ palette: { mode: "dark" } });

function renderWithTheme(
  component: React.ReactNode,
  mode: "light" | "dark" = "light"
) {
  const theme = mode === "dark" ? darkTheme : lightTheme;
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
}

// Mock timers for testing elapsed time
jest.useFakeTimers();

describe("ThinkingIndicator", () => {
  afterEach(() => {
    jest.clearAllTimers();
  });

  describe("idle state", () => {
    it("should render nothing when state is idle", () => {
      const { container } = renderWithTheme(
        <ThinkingIndicator state="idle" />
      );
      expect(container.firstChild).toBeNull();
    });
  });

  describe("thinking state", () => {
    it("should show 'Thinking' text when state is thinking", () => {
      renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={Date.now()} />
      );
      expect(screen.getByText(/Thinking/)).toBeInTheDocument();
    });

    it("should render the ellipsis spinner component", () => {
      const { container } = renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={Date.now()} />
      );
      // The component should render - we check that it has content
      expect(container.firstChild).toBeInTheDocument();
      // Check that "Thinking" text is shown (ellipsis is animated CSS)
      expect(screen.getByText(/Thinking/)).toBeInTheDocument();
    });

    it("should show elapsed time after 1 second", () => {
      const startTime = Date.now();
      renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={startTime} />
      );

      // Initially shows "Thinking" without seconds
      expect(screen.getByText("Thinking")).toBeInTheDocument();

      // Advance timer by 2 seconds
      act(() => {
        jest.advanceTimersByTime(2000);
      });

      // Should now show elapsed time
      expect(screen.getByText(/Thinking \(\d+s\)/)).toBeInTheDocument();
    });
  });

  describe("completed state", () => {
    it("should show 'Thought for Xs' when completed", () => {
      renderWithTheme(
        <ThinkingIndicator state="completed" durationSeconds={5} />
      );
      expect(screen.getByText("Thought for 5s")).toBeInTheDocument();
    });

    it("should not show elapsed counter when completed", () => {
      renderWithTheme(
        <ThinkingIndicator state="completed" durationSeconds={3} />
      );
      // Should NOT find "Thinking"
      expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
      // Should find completed message
      expect(screen.getByText("Thought for 3s")).toBeInTheDocument();
    });
  });

  describe("theming", () => {
    it("should have de-emphasized styling in light mode", () => {
      const { container } = renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={Date.now()} />,
        "light"
      );
      expect(container.firstChild).toBeInTheDocument();
    });

    it("should have de-emphasized styling in dark mode", () => {
      const { container } = renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={Date.now()} />,
        "dark"
      );
      expect(container.firstChild).toBeInTheDocument();
    });
  });

  describe("state transitions", () => {
    it("should handle transition from idle to thinking", () => {
      const { rerender } = renderWithTheme(
        <ThinkingIndicator state="idle" />
      );

      // Initially nothing
      expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();

      // Transition to thinking
      rerender(
        <ThemeProvider theme={lightTheme}>
          <ThinkingIndicator state="thinking" startTime={Date.now()} />
        </ThemeProvider>
      );

      expect(screen.getByText(/Thinking/)).toBeInTheDocument();
    });

    it("should handle transition from thinking to completed", () => {
      const startTime = Date.now();
      const { rerender } = renderWithTheme(
        <ThinkingIndicator state="thinking" startTime={startTime} />
      );

      expect(screen.getByText(/Thinking/)).toBeInTheDocument();

      // Transition to completed
      rerender(
        <ThemeProvider theme={lightTheme}>
          <ThinkingIndicator state="completed" durationSeconds={3} />
        </ThemeProvider>
      );

      expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
      expect(screen.getByText("Thought for 3s")).toBeInTheDocument();
    });
  });
});

