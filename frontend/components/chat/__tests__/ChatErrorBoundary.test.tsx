/**
 * Tests for ChatErrorBoundary component.
 *
 * Tests error catching, fallback UI, and recovery actions.
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChatErrorBoundary } from "../ChatErrorBoundary";

// Component that throws an error for testing
const ThrowError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) {
    throw new Error("Test error");
  }
  return <div>No error</div>;
};

describe("ChatErrorBoundary", () => {
  // Suppress console.error for cleaner test output
  const originalError = console.error;
  beforeAll(() => {
    console.error = jest.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  describe("Error Catching", () => {
    it("catches errors from child components", () => {
      render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      // Should display error UI instead of crashing
      expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
    });

    it("renders children when no error", () => {
      render(
        <ChatErrorBoundary>
          <div data-testid="child">Child content</div>
        </ChatErrorBoundary>
      );

      expect(screen.getByTestId("child")).toBeInTheDocument();
      expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
    });

    it("displays error message", () => {
      const { container } = render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      // Error message should be displayed somewhere in the component
      const text = container.textContent || "";
      expect(text).toContain("Test error");
    });
  });

  describe("Recovery Actions", () => {
    it("shows retry button", () => {
      render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    });

    it("calls onReset when retry button is clicked", () => {
      const onReset = jest.fn();

      render(
        <ChatErrorBoundary onReset={onReset}>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      const retryButton = screen.getByRole("button", { name: /try again/i });
      fireEvent.click(retryButton);

      expect(onReset).toHaveBeenCalledTimes(1);
    });

    it("shows reload page button", () => {
      render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      expect(screen.getByRole("button", { name: /reload page/i })).toBeInTheDocument();
    });

    it("reload button is functional", () => {
      render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      const reloadButton = screen.getByRole("button", { name: /reload page/i });
      
      // Verify button exists and is clickable
      expect(reloadButton).toBeInTheDocument();
      expect(reloadButton).toBeEnabled();
      
      // Note: Actually testing window.location.reload is difficult in jest/jsdom
      // Integration tests should cover the actual reload behavior
    });
  });

  describe("Custom Fallback", () => {
    it("renders custom fallback when provided", () => {
      const customFallback = <div data-testid="custom-fallback">Custom error UI</div>;

      render(
        <ChatErrorBoundary fallback={customFallback}>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      expect(screen.getByTestId("custom-fallback")).toBeInTheDocument();
      expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument();
    });
  });

  describe("Error Logging", () => {
    it("calls onError callback when error is caught", () => {
      const onError = jest.fn();

      render(
        <ChatErrorBoundary onError={onError}>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      expect(onError).toHaveBeenCalledTimes(1);
      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({
          message: "Test error",
        }),
        expect.any(Object)
      );
    });
  });

  describe("Error Context", () => {
    it("displays chat-specific error guidance", () => {
      const { container } = render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      // Should show chat-specific guidance
      const text = container.textContent || "";
      expect(text.toLowerCase()).toContain("your conversation data is safe");
    });

    it("maintains conversation state hint", () => {
      const { container } = render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      // Should reassure user about data safety
      const text = container.textContent || "";
      expect(text.toLowerCase()).toContain("no messages have been lost");
    });
  });

  describe("Accessibility", () => {
    it("has appropriate ARIA attributes", () => {
      render(
        <ChatErrorBoundary>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      const alerts = screen.getAllByRole("alert");
      expect(alerts.length).toBeGreaterThan(0);
    });

    it("retry button is keyboard accessible", () => {
      const onReset = jest.fn();

      render(
        <ChatErrorBoundary onReset={onReset}>
          <ThrowError shouldThrow={true} />
        </ChatErrorBoundary>
      );

      const retryButton = screen.getByRole("button", { name: /try again/i });
      retryButton.focus();
      expect(retryButton).toHaveFocus();
    });
  });
});

